// CV84X6 offline LLM engine -- pure bmrt/bmlib, no sail.
//
// This is a port of the vendor's verified Python demo (sophon-demo
// sample/Qwen3_5/python/qwen3_5.py, origin/developer 2026-10-23), using the C
// idioms of LLM-TPU models/Qwen3_5/cpp_demo/chat.cpp. When the two disagree,
// the Python demo wins: it is the one verified on CV84X6, text and VLM, with
// the 35B-A3B bmodels. Do not "improve" the dataflow without re-checking it
// against that file -- every previous divergence produced silently wrong
// tokens.
//
// Model shape (hybrid attention):
//   * every 4th block is full attention (FA). Prefill block_<i>: (hidden, pos
//     [3,L] [, mask]) -> (hidden, k, v). Decode block_cache_<i>: (hidden, pos
//     [3,1], mask [1,1,1,SEQ+1], k_past, v_past) -> (hidden, k_new, v_new).
//   * the other blocks are linear attention. Prefill: (hidden, rec_state)
//     -> (hidden, conv_state), rec_state updated in place. Decode: (hidden,
//     conv_state, rec_state) -> (hidden, conv_state'[, rec_state']), rec_state
//     updated in place in input[2].
//
// Decode graphs update their state IN PLACE at the graph's own internal input
// memory (addr_mode=1). So that memory is the working state of exactly one
// session -- the "resident" one, as in the single-session vendor demo. Other
// sessions are parked in their own buffers and swapped in when they run.
//
// Vendor rules this file depends on:
//   * buffers the NPU touches come from the NPU heap (heap mask 3, as sail);
//   * every launch is bmrt_launch_tensor_ex(user_mem, user_stmode) with
//     BM_STORE_1N, followed by bm_thread_sync (sail GraphLLM::inference);
//   * dynamic prefill runs only on L % 64 == 0 rows on CV84X6 (see kAlign):
//     prefill the 64-aligned head, replay the tail through the decode graphs,
//     feeding each tail row from the (possibly vit-spliced) embedding matrix;
//   * nothing is allocated or freed while a launch is in flight.

#include "bmruntime_interface.h"
#include "bmlib_runtime.h"
#include "llm_engine.h"

#include <algorithm>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <mutex>
#include <pthread.h>
#include <string>
#include <unistd.h>
#include <vector>

namespace cv84x6 {

namespace {

constexpr int kNpuHeapMask = 3;
constexpr int kFaInterval = 4;
// Dynamic prefill graphs only ever run with a multiple of 64 rows; the rest
// of a chunk (all of a chunk shorter than 64) goes through the decode graphs.
// The demo's rule (16-aligned, only above 64 rows) is not enough on CV84X6
// (MYS-2293, tools/precision/README.md): some short dynamic widths (2 and 5
// rows after a restored 2048-token state) hang the TPU (driver timeout,
// "bdc_reg_read" oops) until the board reboots. 64-row multiples never did,
// over every width tried from 64 to 2048. The decode graphs are static-shaped
// and correct at any position; they are also the only exact path for the
// routed-expert MoE (see Session::set_exact_tail).
constexpr int kAlign = 64;
constexpr int kAlignAbove = 0;
constexpr int kParkGranule = 4096; // parked FA KV grows in steps of this many slots

bm_shape_t make_shape(std::initializer_list<int> dims) {
  bm_shape_t s{};
  s.num_dims = static_cast<int>(dims.size());
  int i = 0;
  for (int d : dims) s.dims[i++] = d;
  return s;
}

bm_tensor_t make_tensor(bm_device_mem_t mem, bm_data_type_t dtype,
                        const bm_shape_t& shape) {
  bm_tensor_t t{};
  bmrt_tensor_with_device(&t, mem, dtype, shape);
  t.st_mode = BM_STORE_1N;
  return t;
}

bm_device_mem_t view(const bm_device_mem_t& base, size_t offset, size_t size) {
  return bm_mem_from_device(base.u.device.device_addr + offset,
                            static_cast<unsigned int>(size));
}

size_t mem_size(const bm_device_mem_t& m) { return bm_mem_get_device_size(m); }
unsigned long long mem_addr(const bm_device_mem_t& m) {
  return bm_mem_get_device_addr(m);
}

// Prefill alignment, overridable for experiments only (LLM_PREFILL_ALIGN /
// LLM_ALIGN_ABOVE); read per call so a test tool can compare paths.
int env_int(const char* name, int dflt) {
  const char* v = std::getenv(name);
  return v && *v ? std::atoi(v) : dflt;
}
int prefill_align() { return env_int("LLM_PREFILL_ALIGN", kAlign); }
int align_above() { return env_int("LLM_ALIGN_ABOVE", kAlignAbove); }

bool trace_on() {
  static const bool on = std::getenv("LLM_TRACE") != nullptr;
  return on;
}

// Command trace (MYS-2703): one line per NPU command, written BEFORE the call
// returns -- and, for launches, before it is submitted at all.
//
// `LLM_TRACE` above cannot answer "which command was stuck": it prints after
// the call, so on a wedged device the one line that matters is the one that is
// never written (MYS-2693 ran into exactly this). `/proc/bmtpu/kernel_fifo`
// does not fill the gap either: `bmdev_kernel_fifo_record()` is called from
// `bm_api.c` keyed on `api_id`, and only LOAD_LIB / GET_FUNC / LAUNCH_FUNC /
// UNLOAD_LIB ever reach it -- `bm_memcpy_d2d_byte` and `bm_memset_device_ext`
// are not recorded there at all. Without the copies in the same ordered stream
// a fifo tail cannot tell "the single-core LAUNCH_FUNC wedged" from "a d2d
// wedged and the launch is merely the first thing to notice".
//
// Off unless LLM_CMD_TRACE names a file. Every line is flushed and is one
// write, so the last line in the file is the last command that started.
//
// Fields: <mono_s> <pid> <tid> see|done <what> ...
// `see` is emitted immediately before the call, `done` immediately after with
// its return code. A `see` with no matching `done` is what was in flight.
struct cmd_trace_t {
  FILE* fp = nullptr;
  bool on = false;
  unsigned long long seq = 0;
  unsigned long long launches = 0;  // launch ordinal, for kernel_fifo alignment

  cmd_trace_t() {
    const char* path = std::getenv("LLM_CMD_TRACE");
    if (!path || !*path) return;
    fp = std::fopen(path, "a");
    if (!fp) return;
    std::setvbuf(fp, nullptr, _IOLBF, 0);
    on = true;
  }

  static double mono_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
  }

  // One line, one flush. Built on the stack: an instrument that allocates on
  // the hot path perturbs the thing it measures.
  //
  // `ord` is the launch ordinal within this process. The driver's `api_seq`
  // (`kernel_fifo`) counts the same launches -- d2d and memset never reach that
  // fifo -- so the two are offset by a constant per process and can be aligned
  // from any point where both are visible. That is how a trace line names the
  // seq the capture reports as stuck.
  void line(const char* phase, const char* fmt, ...) __attribute__((format(printf, 3, 4))) {
    if (!on) return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    const int n = std::vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0) return;
    const unsigned long s = __sync_fetch_and_add(&seq, 1);
    // "see launch ..." and "done launch ... rc=" are one launch between them;
    // only the `see` carries the ordinal, or every launch would take two.
    const bool is_launch = std::strncmp(buf, "launch", 6) == 0 &&
                           std::strstr(buf, " rc=") == nullptr;
    char ord[24] = "";
    if (is_launch) {
      const unsigned long long i = __sync_fetch_and_add(&launches, 1);
      std::snprintf(ord, sizeof(ord), "L%llu ", i);
    }
    std::fprintf(fp, "%.6f %d %d %lu %s%s %s\n", mono_s(),
                 static_cast<int>(::getpid()),
                 static_cast<int>(reinterpret_cast<unsigned long>(::pthread_self())),
                 s, ord, phase, buf);
    std::fflush(fp);
  }
};
cmd_trace_t& cmd_trace() {
  static cmd_trace_t t;
  return t;
}

}  // namespace

// ---------------------------------------------------------------------------
struct Engine::Impl {
  bm_handle_t handle = nullptr;
  void* bmrt = nullptr;
  std::mutex mu;  // one NPU: every graph launch and state swap is serialised
  std::string last_error;
  // Set when a launch or sync fails (the driver gives up after 120 s on a hung
  // TPU). The device is wedged until the board is rebooted, so every later
  // call fails at once instead of blocking for another 120 s.
  bool fault = false;

  const bm_net_info_t* net_embed = nullptr;
  const bm_net_info_t* net_embed_cache = nullptr;
  const bm_net_info_t* net_lm = nullptr;
  const bm_net_info_t* net_greedy = nullptr;
  const bm_net_info_t* net_vit = nullptr;
  std::vector<const bm_net_info_t*> blocks;        // prefill block_<i>
  std::vector<const bm_net_info_t*> blocks_cache;  // decode block_cache_<i>
  // History bmodels only: block_kv_<i> (FA prefill with past KV) per layer,
  // nullptr for linear layers. Empty for plain bmodels.
  std::vector<const bm_net_info_t*> blocks_kv;

  int num_layers = 0;
  int seq_len = 0;
  int max_input = 0;
  int hidden = 0;
  // Embedding table size, set by the caller (Engine::set_vocab_size): the
  // bmodel does not carry it, because lm_head fuses argmax and so never
  // exposes the vocabulary as a shape. 0 = unknown, range checking disabled.
  int vocab = 0;
  size_t hidden_bytes = 0;
  size_t kv_bytes = 0;  // one token of one FA layer's K (or V)
  bool is_dynamic = false;
  bool vit_dynamic = false;
  bool prefill_mask = false;
  bool lm_topk = false;
  uint16_t mask_value = 0;
  int vit_max_patches = 0;
  int vit_dims = 0;

  // Own buffers, mirroring the demo's create_max_* tensors.
  bm_device_mem_t embed_in{}, embed_out{};    // embed_out doubles as the
                                              // vit-spliced prompt matrix
  bm_device_mem_t ec_in{}, ec_out{};          // embedding_cache
  std::vector<bm_device_mem_t> pf_in[2];      // [0] block_0, [1] block_<FA-1>
  std::vector<bm_device_mem_t> pf_out[2];
  bm_device_mem_t dec_pos{}, dec_mask{};      // block_cache_<FA-1> in[1], in[2]
  bm_device_mem_t lm_out{};
  bm_device_mem_t greedy_out{};
  bm_device_mem_t vit_in[4]{};
  bm_device_mem_t vit_out{};
  std::vector<bm_device_mem_t> owned;         // everything above, for teardown

  Session::Impl* resident = nullptr;

  bool is_fa(int i) const { return (i + 1) % kFaInterval == 0; }

  // Decode-graph internal state of layer i (the resident session's state).
  bm_device_mem_t& state_a(int i) {  // FA: k_past   linear: conv_state
    return const_cast<bm_device_mem_t&>(
        blocks_cache[i]->stages[0].input_mems[is_fa(i) ? 3 : 1]);
  }
  bm_device_mem_t& state_b(int i) {  // FA: v_past   linear: rec_state
    return const_cast<bm_device_mem_t&>(
        blocks_cache[i]->stages[0].input_mems[is_fa(i) ? 4 : 2]);
  }

  // First token id outside [0, vocab), or 0 when all are valid (or the
  // vocabulary size is unknown). Ids are int32 per the graph's dtype, so a
  // negative id is as out of bounds as a too-large one.
  int check_tokens(const int* tokens, int n) const {
    if (vocab <= 0) return 0;
    for (int i = 0; i < n; i++) {
      if (tokens[i] < 0 || tokens[i] >= vocab) return tokens[i];
    }
    return 0;
  }

  bool fail(const std::string& msg) {
    last_error = msg;
    std::fprintf(stderr, "[engine] %s\n", msg.c_str());
    return false;
  }

  bool alloc(bm_device_mem_t* m, size_t bytes, const char* what) {
    if (bytes == 0) bytes = 4;
    if (bm_malloc_device_byte_heap_mask(handle, m, kNpuHeapMask,
                                        static_cast<unsigned int>(bytes)) !=
        BM_SUCCESS) {
      return fail(std::string("NPU heap exhausted allocating ") + what);
    }
    owned.push_back(*m);
    zero(*m);
    return true;
  }

  void zero(bm_device_mem_t& m) {
    if (fault) return;  // see d2d: no NPU traffic after the first failure
    int v = 0;
    cmd_trace().line("see", "memset size=%zu", mem_size(m));
    const int rc = bm_memset_device_ext(handle, &v, 1, m);
    cmd_trace().line("done", "memset rc=%d", rc);
    if (rc != BM_SUCCESS) {
      // Was unchecked. A memset that fails leaves the buffer holding whatever
      // the previous session wrote, and the TPU then runs on garbage; the first
      // launch to notice is far from the cause. Record it where it happens.
      fault = true;
      fail("NPU fault: memset failed");
    }
  }

  void d2d(bm_device_mem_t& dst, size_t dst_off, bm_device_mem_t& src,
           size_t src_off, size_t size) {
    if (size == 0 || fault) return;
    cmd_trace().line("see", "d2d size=%zu dst_off=%zu src_off=%zu", size, dst_off,
                     src_off);
    const int rc = bm_memcpy_d2d_byte(handle, dst, dst_off, src, src_off, size);
    cmd_trace().line("done", "d2d size=%zu rc=%d", size, rc);
    if (rc != BM_SUCCESS) {
      // Also was unchecked. d2d moves session state and KV; a silent failure
      // here corrupts one session and shows up much later as a wrong token or a
      // parked-state mismatch, never as the copy that failed.
      fault = true;
      fail("NPU fault: device-to-device copy failed");
    }
  }

  bool s2d(bm_device_mem_t& dst, const void* src, size_t size) {
    if (size > mem_size(dst)) return fail("host->device copy larger than buffer");
    return bm_memcpy_s2d_partial(handle, dst, const_cast<void*>(src),
                                 static_cast<unsigned int>(size)) == BM_SUCCESS;
  }

  // Upload host fp32 as the graph's float dtype (the demo's astype()).
  bool s2d_float(bm_device_mem_t& dst, bm_data_type_t dt, const float* src,
                 size_t count) {
    if (dt == BM_FLOAT32) return s2d(dst, src, count * sizeof(float));
    if (dt != BM_BFLOAT16) return fail("unsupported vit input dtype");
    std::vector<uint16_t> h(count);
    for (size_t i = 0; i < count; i++) {
      uint32_t bits;
      std::memcpy(&bits, &src[i], 4);
      bits += 0x7FFF + ((bits >> 16) & 1);  // round to nearest even
      h[i] = static_cast<uint16_t>(bits >> 16);
    }
    return s2d(dst, h.data(), count * 2);
  }

  // Launch one graph. `wait` = true keeps the historical contract: the call
  // returns once the graph has retired on the TPU, so its outputs and any
  // in-place state are final. `wait` = false only queues the launch
  // (bmrt_launch_tensor_ex is non-blocking, bmruntime_interface.h:476); the
  // caller must establish a boundary with sync_launches() before it reads an
  // output, copies state off the graph's memory, or returns to its own caller.
  //
  // A failed launch is fatal at once whatever `wait` says -- it is the TPU
  // refusing work, not a timing issue -- so `fault` and last_error still
  // describe the first failure even when the sync that would report it is
  // deferred. The deferred sync itself is checked by sync_launches(), which
  // every non-waiting path reaches before it returns.
  bool run(const bm_net_info_t* net, std::vector<bm_tensor_t>& in,
           std::vector<bm_tensor_t>& out, bool wait = true) {
    if (fault) return fail("NPU fault earlier in this process; reboot the board");
    const auto t0 = std::chrono::steady_clock::now();
    // Logged before the submit. On a wedged device the launcher never returns,
    // so this is the only form of the trace that survives the hang.
    cmd_trace().line("see", "launch %s core=%d in=%d out=%d wait=%d",
                     net->name, net->core_num, static_cast<int>(in.size()),
                     static_cast<int>(out.size()), wait ? 1 : 0);
    const int rc = bmrt_launch_tensor_ex(bmrt, net->name, in.data(),
                                         static_cast<int>(in.size()), out.data(),
                                         static_cast<int>(out.size()), true, true);
    cmd_trace().line("done", "launch %s rc=%d", net->name, rc);
    if (!rc) {
      fault = true;
      return fail(std::string("NPU fault: launch failed: ") + net->name + "; reboot the board");
    }
    if (wait && !sync_launches()) return false;
    if (trace_on()) {
      const double ms = std::chrono::duration<double, std::milli>(
                            std::chrono::steady_clock::now() - t0).count();
      static const auto origin = std::chrono::steady_clock::now();
      const double at = std::chrono::duration<double>(std::chrono::steady_clock::now() - origin).count();
      std::fprintf(stderr, "[launch] %s %.1f ms%s @%.3f\n", net->name, ms,
                   wait ? "" : " (queued)", at);
    }
    return true;
  }

  // Boundary: wait until every launch this thread queued has retired. This is
  // the only place a deferred launch's failure can surface, so it keeps the
  // `fault` semantics of the eager path.
  //
  // This -- not the launch -- is where a wedged TPU shows: `bmrt_launch_tensor_ex`
  // only queues, so it returns even when the firmware never answers, and the
  // wait lands here, in `bmdrv_thread_sync_api`. Traced around for that reason:
  // a `see sync` with no `done sync` is the hang itself.
  bool sync_launches() {
    cmd_trace().line("see", "sync");
    const int rc = bm_thread_sync(handle);
    cmd_trace().line("done", "sync rc=%d", rc);
    if (rc != BM_SUCCESS) {
      fault = true;
      return fail("NPU fault: sync timed out; reboot the board");
    }
    return true;
  }

  // Allocate own buffers shaped like a graph's max (stage 0) IO.
  bool alloc_like(const bm_net_info_t* net, bool inputs,
                  std::vector<bm_device_mem_t>* dst) {
    const int n = inputs ? net->input_num : net->output_num;
    dst->assign(n, bm_device_mem_t{});
    for (int i = 0; i < n; i++) {
      const bm_device_mem_t& m = inputs ? net->stages[0].input_mems[i]
                                        : net->stages[0].output_mems[i];
      if (!alloc(&(*dst)[i], mem_size(m), net->name)) return false;
    }
    return true;
  }

  int sample_lm(bm_device_mem_t hidden_row);
  // Debug: copy the lm_head input row to the host (LLM_DEBUG_HIDDEN=1), so
  // tools can compare prefill paths numerically, not just by argmax.
  // Debug (LLM_DEBUG_HIDDEN=2): append `rows` rows of layer `idx`'s output
  // to `out` when idx is LLM_DEBUG_LAYER (default: the last layer).
  std::vector<uint16_t>* dbg_sink = nullptr;  // tail replay target
  void capture_rows(int idx, bm_device_mem_t m, int rows, std::vector<uint16_t>* out) {
    static const bool on = env_int("LLM_DEBUG_HIDDEN", 0) >= 2;
    if (!on || rows <= 0 || !out || idx != env_int("LLM_DEBUG_LAYER", num_layers - 1)) return;
    // The layers are queued without waiting, so this row may not be written
    // yet: debug capture is a consumer and needs its own boundary.
    if (!sync_launches()) return;
    const size_t k = static_cast<size_t>(rows) * hidden_bytes / 2;
    const size_t at = out->size();
    out->resize(at + k);
    bm_memcpy_d2s_partial(handle, out->data() + at, m,
                          static_cast<unsigned int>(k * 2));
  }
  void capture(bm_device_mem_t row, std::vector<uint16_t>* out) {
    static const bool on = std::getenv("LLM_DEBUG_HIDDEN") != nullptr;
    if (!on) return;
    out->assign(hidden_bytes / 2, 0);
    bm_memcpy_d2s_partial(handle, out->data(), row, static_cast<unsigned int>(hidden_bytes));
  }
  bm_device_mem_t decode_layers(bm_device_mem_t in_mem, const int32_t pos3[3],
                                int cur_pos, bool* ok);
  // Decode-graph state, cached at load: does a linear layer's conv_state come
  // back at the very memory it was given as input (addr_mode=1), so writing it
  // back would be a self-copy? Measured per layer from the loaded graph rather
  // than assumed, because a bmodel that hands back a separate output buffer
  // still needs the explicit copy. See measure_state_layout().
  std::vector<uint8_t> conv_inplace;  // per layer, linear layers only
  std::vector<uint8_t> rec_inplace;   // per layer, when output 2 exists
  void measure_state_layout();
};

// ---------------------------------------------------------------------------
struct Session::Impl {
  Engine::Impl* eng = nullptr;
  // The session's whole logical state. decode() reads all four, so a snapshot
  // is only a faithful copy if it carries all four (see Snapshot):
  //   * history  = KV slots actually written, i.e. what the next decode
  //                appends after (its KV slot is also its mask position);
  //   * pos_next = M-RoPE position of the token last_id embeds;
  //   * last_id  = the token the next decode() embeds -- the previous
  //                lm_head argmax, *not* yet in KV;
  //   * pending  = last_id, when the caller has not been handed it yet
  //                (prefill/extend sample a token that the first decode()
  //                returns without touching the NPU).
  int history = 0;
  int pos_next = 0;
  int last_id = -1;
  int pending = -1;
  // Rows at the end of the next prefill/extend call that go through the
  // decode graphs instead of the prefill graphs (Session::set_exact_tail).
  int exact_tail = 0;
  std::vector<uint16_t> dbg_hidden;  // last lm_head input (LLM_DEBUG_HIDDEN)
  std::vector<uint16_t> dbg_rows;    // every prefilled row's last-layer output
  // Parked copy of the per-layer state while another session is resident.
  // FA buffers hold park_cap slots and grow with the session, so a short
  // conversation on a 128k model does not pin 2.5 GB; linear state is fixed.
  std::vector<bm_device_mem_t> park_a, park_b;
  int parked_kv = 0;    // FA slots [0, parked_kv) of park_a/park_b are valid
  int park_cap = 0;     // FA slots allocated in park_a/park_b

  bool alloc_npu(bm_device_mem_t* m, size_t bytes) {
    return bm_malloc_device_byte_heap_mask(eng->handle, m, kNpuHeapMask,
                                           static_cast<unsigned int>(bytes)) == BM_SUCCESS;
  }

  // Make room for `need` FA slots. On failure nothing changes: the caller
  // fails before touching any state, so the call can be retried after the
  // prefix cache gave memory back.
  bool ensure_park(int need) {
    Engine::Impl* e = eng;
    if (park_a.empty()) {
      park_a.assign(e->num_layers, bm_device_mem_t{});
      park_b.assign(e->num_layers, bm_device_mem_t{});
      for (int i = 0; i < e->num_layers; i++) {
        if (e->is_fa(i)) continue;
        if (!alloc_npu(&park_a[i], mem_size(e->state_a(i))) ||
            !alloc_npu(&park_b[i], mem_size(e->state_b(i)))) {
          free_park();
          return e->fail("NPU heap exhausted parking a session");
        }
      }
      parked_kv = 0;
      park_cap = 0;
    }
    if (need <= park_cap) return true;
    int cap = std::max(need, park_cap + park_cap / 2);
    cap = std::min(e->seq_len, (cap + kParkGranule - 1) / kParkGranule * kParkGranule);
    const size_t bytes = static_cast<size_t>(cap) * e->kv_bytes;
    std::vector<bm_device_mem_t> na(e->num_layers, bm_device_mem_t{}),
        nb(e->num_layers, bm_device_mem_t{});
    auto drop = [&]() {
      for (auto* v : {&na, &nb})
        for (auto& m : *v)
          if (m.u.device.device_addr) bm_free_device(e->handle, m);
    };
    for (int i = 0; i < e->num_layers; i++) {
      if (!e->is_fa(i)) continue;
      if (!alloc_npu(&na[i], bytes) || !alloc_npu(&nb[i], bytes)) {
        drop();
        return e->fail("NPU heap exhausted parking a session (" + std::to_string(cap) +
                       " tokens)");
      }
    }
    const size_t keep = static_cast<size_t>(parked_kv) * e->kv_bytes;
    for (int i = 0; i < e->num_layers; i++) {
      if (!e->is_fa(i)) continue;
      if (park_cap > 0) {
        e->d2d(na[i], 0, park_a[i], 0, keep);
        e->d2d(nb[i], 0, park_b[i], 0, keep);
        bm_free_device(e->handle, park_a[i]);
        bm_free_device(e->handle, park_b[i]);
      }
      park_a[i] = na[i];
      park_b[i] = nb[i];
    }
    park_cap = cap;
    return true;
  }

  void free_park() {
    for (auto* v : {&park_a, &park_b}) {
      for (auto& m : *v) {
        if (m.u.device.device_addr) bm_free_device(eng->handle, m);
      }
      v->clear();
    }
    parked_kv = 0;
    park_cap = 0;
  }

  // Copy the resident state out. FA KV is append-only, so only the slots
  // written since the last park are copied; linear state is copied whole.
  bool park() {
    Engine::Impl* e = eng;
    if (!ensure_park(history)) return false;
    for (int i = 0; i < e->num_layers; i++) {
      if (e->is_fa(i)) {
        const size_t off = static_cast<size_t>(parked_kv) * e->kv_bytes;
        const size_t len = static_cast<size_t>(history - parked_kv) * e->kv_bytes;
        e->d2d(park_a[i], off, e->state_a(i), off, len);
        e->d2d(park_b[i], off, e->state_b(i), off, len);
      } else {
        e->d2d(park_a[i], 0, e->state_a(i), 0, mem_size(e->state_a(i)));
        e->d2d(park_b[i], 0, e->state_b(i), 0, mem_size(e->state_b(i)));
      }
    }
    parked_kv = history;
    return true;
  }

  void unpark() {
    Engine::Impl* e = eng;
    for (int i = 0; i < e->num_layers; i++) {
      if (e->is_fa(i)) {
        const size_t len = static_cast<size_t>(history) * e->kv_bytes;
        e->d2d(e->state_a(i), 0, park_a[i], 0, len);
        e->d2d(e->state_b(i), 0, park_b[i], 0, len);
      } else {
        e->d2d(e->state_a(i), 0, park_a[i], 0, mem_size(e->state_a(i)));
        e->d2d(e->state_b(i), 0, park_b[i], 0, mem_size(e->state_b(i)));
      }
    }
  }

  // What has to be reset before this session takes the NPU over. The resident
  // state is one buffer set shared by every session (the decode graphs write
  // in place at their own input memory), so a session becoming resident either
  // restores its parked copy or -- when its old state is dead -- starts clean.
  enum class Reset {
    // A fresh prefill replaces the session. Only the linear conv/rec state is
    // zeroed: the decode graphs read it in place and there is no other reset,
    // and a prompt shorter than the 64-row alignment is replayed entirely
    // through those graphs, so a stale value there would change the answer.
    //
    // The FA K/V buffers are deliberately NOT zeroed. `history` becomes 0
    // right here, so no FA slot belongs to the session, and the graphs never
    // read a slot that is not: the prefill graph writes slots [0, L) through
    // its own output, a decode writes exactly slot `cur_pos`, and the decode
    // mask holds mask_value for every slot in [cur_pos, win). A leftover slot
    // is therefore a finite stale K/V whose contribution is `q.k + mask_value`
    // -- dropped by the softmax, never a NaN. Finite is all that is needed,
    // and the load-time zeroing (Engine::load) is what guarantees it: every
    // later write to these buffers is graph output. This is 2.50 GiB of memset
    // (10 FA layers x 2 x 128 MiB) that the fresh path used to pay on every new
    // session: measured 44 ms, 5.2% of a 67-token first token on the 128k model
    // (docs/research/fresh-prefill-fa-state.md).
    kFreshPrefill,
    // restore() lays a snapshot down over [0, len) and everything past it must
    // not carry a previous, longer session's KV, so the whole per-layer state
    // -- FA included -- is zeroed before the copy, as it always has been.
    kRestore,
    // decode()/extend()/snapshot(): the state is live. Restore the parked copy
    // if another session is resident.
    kKeepState,
  };

  // Make this session resident. See Reset for what each mode clears; the
  // demo's rule is that stale NaN in a masked lane still poisons FA, which is
  // why the buffers are zeroed once at load rather than per session.
  bool activate(Reset what) {
    Engine::Impl* e = eng;
    if (e->resident && e->resident != this) {
      if (!e->resident->park()) return false;
    }
    if (what == Reset::kFreshPrefill || what == Reset::kRestore) {
      for (int i = 0; i < e->num_layers; i++) {
        if (what == Reset::kFreshPrefill && e->is_fa(i)) continue;
        e->zero(e->state_a(i));
        e->zero(e->state_b(i));
      }
      parked_kv = 0;
    } else if (e->resident != this) {
      unpark();
    }
    // A fresh prefill has nothing in KV: the invariant that lets kFreshPrefill
    // skip the FA zeroing, so it is established here and not left to the
    // caller (prefill_impl used to repeat it one line below activate()).
    if (what == Reset::kFreshPrefill) history = 0;
    e->resident = this;
    return true;
  }

  ~Impl() {
    if (eng && eng->resident == this) eng->resident = nullptr;
    if (eng) free_park();
  }
};

// ---------------------------------------------------------------------------
Engine::Engine() : impl_(new Impl()) {}

Engine::~Engine() {
  if (!impl_) return;
  {
    // Wait for a call still running on another thread (a decode in flight
    // when the worker is told to stop) before tearing the runtime down.
    std::lock_guard<std::mutex> g(impl_->mu);
  }
  for (auto& m : impl_->owned) bm_free_device(impl_->handle, m);
  if (impl_->bmrt) bmrt_destroy(impl_->bmrt);
  if (impl_->handle) bm_dev_free(impl_->handle);
  delete impl_;
}

bool Engine::load(const std::string& model_path, int dev_id) {
  Impl* e = impl_;
  if (bm_dev_request(&e->handle, dev_id) != BM_SUCCESS) {
    return e->fail("bm_dev_request failed");
  }
  e->bmrt = bmrt_create(e->handle);
  if (!e->bmrt) return e->fail("bmrt_create failed");
  bmrt_set_flags(e->bmrt, BM_RUNTIME_SHARE_MEM);
  if (!bmrt_load_bmodel(e->bmrt, model_path.c_str())) {
    return e->fail("bmrt_load_bmodel failed (wrong chip or corrupt file?)");
  }
  bm_thread_sync(e->handle);

  // Network discovery. bmrt_get_network_names' array is NOT NULL-terminated.
  const int num_nets = bmrt_get_network_number(e->bmrt);
  const char** names = nullptr;
  bmrt_get_network_names(e->bmrt, &names);
  auto exists = [&](const std::string& n) {
    for (int i = 0; i < num_nets; i++)
      if (n == names[i]) return true;
    return false;
  };
  auto get = [&](const std::string& n) -> const bm_net_info_t* {
    return exists(n) ? bmrt_get_network_info(e->bmrt, n.c_str()) : nullptr;
  };
  e->net_embed = get("embedding");
  e->net_embed_cache = get("embedding_cache");
  e->net_lm = get("lm_head");
  e->net_greedy = get("greedy_head");
  e->net_vit = get("vit");
  const bool history_model = exists("block_kv_" + std::to_string(kFaInterval - 1));
  for (int i = 0;; i++) {
    const auto* b = get("block_" + std::to_string(i));
    const auto* c = get("block_cache_" + std::to_string(i));
    if (!b || !c) break;
    e->blocks.push_back(b);
    e->blocks_cache.push_back(c);
  }
  e->num_layers = static_cast<int>(e->blocks.size());
  if (!e->net_embed || !e->net_embed_cache || !e->net_lm ||
      e->num_layers < kFaInterval) {
    return e->fail("not a Qwen3.5 bmodel: embedding/lm_head/blocks missing");
  }
  if (history_model) {
    for (int i = 0; i < e->num_layers; i++) {
      const bm_net_info_t* kv = e->is_fa(i) ? get("block_kv_" + std::to_string(i)) : nullptr;
      if (e->is_fa(i) && !kv) return e->fail("history bmodel without block_kv_" + std::to_string(i));
      e->blocks_kv.push_back(kv);
    }
  }
  free(names);  // only after the last get(): its array backs exists()

  const bm_net_info_t* fa = e->blocks[kFaInterval - 1];
  const bm_net_info_t* fa_c = e->blocks_cache[kFaInterval - 1];
  e->seq_len = fa_c->stages[0].input_shapes[3].dims[1];
  e->max_input = e->net_embed->stages[0].input_shapes[0].dims[1];
  e->hidden = e->net_lm->stages[0].input_shapes[0].dims[1];
  e->hidden_bytes = static_cast<size_t>(e->hidden) *
                    bmrt_data_type_size(e->net_lm->input_dtypes[0]);
  e->kv_bytes = mem_size(fa_c->stages[0].output_mems[1]);
  e->is_dynamic = e->blocks[0]->is_dynamic;
  e->prefill_mask = fa->input_num == 3;
  e->lm_topk = e->net_lm->stages[0].output_shapes[0].dims[1] == 1;
  const bm_data_type_t emb_dt = e->net_embed_cache->output_dtypes[0];
  if (emb_dt == BM_FLOAT16) e->mask_value = 0xF0E2;
  else if (emb_dt == BM_BFLOAT16) e->mask_value = 0xC61C;
  else return e->fail("unsupported attention dtype");
  if (e->net_vit) {
    e->vit_dynamic = e->net_vit->is_dynamic;
    e->vit_max_patches = e->net_vit->stages[0].input_shapes[0].dims[0];
    e->vit_dims = e->net_vit->stages[0].input_shapes[0].dims[1];
  }
  {
    const auto* c = e->blocks_cache[kFaInterval - 1];
    std::string w;
    for (int k = 0; k < c->stage_num; k++)
      w += (k ? "/" : "") + std::to_string(c->stages[k].input_shapes[3].dims[1]);
    std::fprintf(stderr, "[engine] FA decode windows: %s\n", w.c_str());
  }

  // Own buffers (the demo's create_max_* tensors).
  if (!e->alloc(&e->embed_in, mem_size(e->net_embed->stages[0].input_mems[0]), "embed_in") ||
      !e->alloc(&e->embed_out, mem_size(e->net_embed->stages[0].output_mems[0]), "embed_out") ||
      !e->alloc(&e->ec_in, mem_size(e->net_embed_cache->stages[0].input_mems[0]), "ec_in") ||
      !e->alloc(&e->ec_out, mem_size(e->net_embed_cache->stages[0].output_mems[0]), "ec_out") ||
      !e->alloc_like(e->blocks[0], true, &e->pf_in[0]) ||
      !e->alloc_like(e->blocks[0], false, &e->pf_out[0]) ||
      !e->alloc_like(fa, true, &e->pf_in[1]) ||
      !e->alloc_like(fa, false, &e->pf_out[1]) ||
      !e->alloc(&e->dec_pos, mem_size(fa_c->stages[0].input_mems[1]), "dec_pos") ||
      !e->alloc(&e->dec_mask, mem_size(fa_c->stages[0].input_mems[2]), "dec_mask") ||
      !e->alloc(&e->lm_out, mem_size(e->net_lm->stages[0].output_mems[0]), "lm_out")) {
    return false;
  }
  if (e->net_greedy &&
      !e->alloc(&e->greedy_out, mem_size(e->net_greedy->stages[0].output_mems[0]), "greedy_out")) {
    return false;
  }
  if (e->net_vit) {
    for (int i = 0; i < 4 && i < e->net_vit->input_num; i++) {
      if (!e->alloc(&e->vit_in[i], mem_size(e->net_vit->stages[0].input_mems[i]), "vit_in"))
        return false;
    }
    if (!e->alloc(&e->vit_out, mem_size(e->net_vit->stages[0].output_mems[0]), "vit_out"))
      return false;
  }
  if (!e->blocks_kv.empty()) {
    // The demo zeroes the block_kv past-KV template inputs once: the graph is
    // handed [0, old) of them, but load-time garbage in a masked lane can
    // still poison attention.
    const auto& tst = e->blocks_kv[kFaInterval - 1]->stages[0];
    e->zero(const_cast<bm_device_mem_t&>(tst.input_mems[2]));
    e->zero(const_cast<bm_device_mem_t&>(tst.input_mems[3]));
  }
  if (mem_size(e->embed_out) < static_cast<size_t>(e->max_input) * e->hidden_bytes) {
    return e->fail("embedding output smaller than max_input rows");
  }
  // The prefill buffers are allocated from the template layer only (block_0 for
  // linear, block_<FA-1> for FA) and handed to every layer of that kind. That
  // is only sound if the template is the widest of its kind: a wider layer's
  // graph would read or write past the end of the buffer, which on the device
  // is a silent OOB inside the TPU -- garbage activations at best, an
  // uncatchable abort at worst. Shipped bmodels are uniform, so this is a
  // malformed-bmodel guard, not a supported-layout check.
  for (int i = 0; i < e->num_layers; i++) {
    const int kind = e->is_fa(i) ? 1 : 0;
    const bm_net_info_t* tpl = kind ? fa : e->blocks[0];
    const int n_in = std::min(tpl->input_num, e->blocks[i]->input_num);
    for (int k = 0; k < n_in; k++) {
      if (mem_size(e->blocks[i]->stages[0].input_mems[k]) >
          mem_size(e->pf_in[kind][k])) {
        return e->fail("layer " + std::to_string(i) + " input " + std::to_string(k) +
                       " is larger than the shared prefill buffer");
      }
    }
    const int n_out = std::min(tpl->output_num, e->blocks[i]->output_num);
    for (int k = 1; k < n_out; k++) {  // output 0 is the shared hidden buffer
      if (mem_size(e->blocks[i]->stages[0].output_mems[k]) >
          mem_size(e->pf_out[kind][k])) {
        return e->fail("layer " + std::to_string(i) + " output " + std::to_string(k) +
                       " is larger than the shared prefill buffer");
      }
    }
  }
  for (int i = 0; i < e->num_layers; i++) {
    e->zero(e->state_a(i));
    e->zero(e->state_b(i));
  }
  e->measure_state_layout();

  std::fprintf(stderr,
               "[engine] layers=%d seq=%d max_input=%d hidden=%d kv_bytes=%zu "
               "dynamic=%d prefill_mask=%d lm_topk=%d greedy=%d vit=%d(%d patches) "
               "history=%d\n",
               e->num_layers, e->seq_len, e->max_input, e->hidden, e->kv_bytes,
               e->is_dynamic, e->prefill_mask, e->lm_topk, e->net_greedy != nullptr,
               e->net_vit != nullptr, e->vit_max_patches, !e->blocks_kv.empty());
  return true;
}

int Engine::num_layers() const { return impl_->num_layers; }
int Engine::context_length() const { return impl_->seq_len; }
int Engine::max_input_length() const { return impl_->max_input; }
int Engine::hidden_size() const { return impl_->hidden; }
bool Engine::has_vision() const { return impl_->net_vit != nullptr; }
int Engine::vit_max_patches() const { return impl_->vit_max_patches; }
int Engine::vit_dims() const { return impl_->vit_dims; }
bool Engine::supports_history() const { return !impl_->blocks_kv.empty(); }
bool Engine::fault() const { return impl_->fault; }
void Engine::set_vocab_size(int n) {
  std::lock_guard<std::mutex> g(impl_->mu);
  impl_->vocab = n > 0 ? n : 0;
}
int Engine::vocab_size() const { return impl_->vocab; }
size_t Engine::session_state_bytes() const {
  size_t n = 0;
  for (int i = 0; i < impl_->num_layers; i++)
    n += mem_size(impl_->state_a(i)) + mem_size(impl_->state_b(i));
  return n;
}
size_t Engine::kv_bytes_per_token() const {
  size_t n = 0;
  for (int i = 0; i < impl_->num_layers; i++)
    if (impl_->is_fa(i)) n += 2 * impl_->kv_bytes;
  return n;
}
size_t Engine::linear_state_bytes() const {
  size_t n = 0;
  for (int i = 0; i < impl_->num_layers; i++)
    if (!impl_->is_fa(i)) n += mem_size(impl_->state_a(i)) + mem_size(impl_->state_b(i));
  return n;
}
int Engine::park_granule() const { return kParkGranule; }
std::string Engine::last_error() const { return impl_->last_error; }

std::unique_ptr<Session> Engine::new_session() {
  std::unique_ptr<Session> s(new Session());
  s->impl_ = new Session::Impl();
  s->impl_->eng = impl_;
  return s;
}

// ---------------------------------------------------------------------------
// Does a linear decode graph produce its state in place? The engine's own
// buffers for a linear layer are the graph's template mems (state_a(i) =
// input_mems[1] = conv_state, state_b(i) = input_mems[2] = rec_state), so if
// the graph writes output 1 into that same memory, copying output 1 back onto
// state_a is a buffer copying itself.
//
// This is the property MYS-2377 asked to verify rather than assume, and it
// holds for the Qwen3.5/3.6 bmodels: block_cache_<i> reports output_mems[0]
// == input_mems[0] and output_mems[1] == input_mems[1] (addr_mode=1). Checked
// here with the loaded graph's own addresses, so a bmodel that returns a
// separate buffer keeps the explicit copy.
void Engine::Impl::measure_state_layout() {
  conv_inplace.assign(num_layers, 0);
  rec_inplace.assign(num_layers, 0);
  int conv_n = 0, conv_in = 0, rec_n = 0, rec_in = 0;
  for (int i = 0; i < num_layers; i++) {
    if (is_fa(i)) continue;
    const auto& st = blocks_cache[i]->stages[0];
    conv_n++;
    // Same address and same span: a partial overlap would still need a copy.
    if (mem_addr(st.output_mems[1]) == mem_addr(st.input_mems[1]) &&
        mem_size(st.output_mems[1]) == mem_size(st.input_mems[1])) {
      conv_inplace[i] = 1;
      conv_in++;
    }
    if (blocks_cache[i]->output_num > 2) {
      rec_n++;
      if (mem_addr(st.output_mems[2]) == mem_addr(st.input_mems[2]) &&
          mem_size(st.output_mems[2]) == mem_size(st.input_mems[2])) {
        rec_inplace[i] = 1;
        rec_in++;
      }
    }
  }
  std::fprintf(stderr, "[engine] linear state in place: conv %d/%d, rec %d/%d\n",
               conv_in, conv_n, rec_in, rec_n);
}

// ---------------------------------------------------------------------------
// lm_head on one hidden row, then greedy/argmax. Returns -1 on failure.
int Engine::Impl::sample_lm(bm_device_mem_t hidden_row) {
  std::vector<bm_tensor_t> in{make_tensor(hidden_row, net_lm->input_dtypes[0],
                                          make_shape({1, hidden}))};
  std::vector<bm_tensor_t> out{make_tensor(lm_out, net_lm->output_dtypes[0],
                                           net_lm->stages[0].output_shapes[0])};
  if (!run(net_lm, in, out)) return -1;
  int32_t token = 0;
  if (lm_topk || !net_greedy) {
    bm_memcpy_d2s_partial(handle, &token, lm_out, sizeof(token));
    return token;
  }
  std::vector<bm_tensor_t> gin{make_tensor(lm_out, net_greedy->input_dtypes[0],
                                           net_greedy->stages[0].input_shapes[0])};
  std::vector<bm_tensor_t> gout{make_tensor(greedy_out, net_greedy->output_dtypes[0],
                                            net_greedy->stages[0].output_shapes[0])};
  if (!run(net_greedy, gin, gout)) return -1;
  bm_memcpy_d2s_partial(handle, &token, greedy_out, sizeof(token));
  return token;
}

// All decode-graph layers for one token whose hidden input is `in_mem`, at
// M-RoPE position `pos3` ([3,1]: t/h/w, equal for text) and KV slot
// `cur_pos`. Mirrors the demo's forward_next / forward_first_aligned phase 2.
// Returns the last layer's hidden output.
//
// Two things this does that the straight port does not:
//
//   * The layers are queued back to back. bmrt_launch_tensor_ex does not
//     block (bmruntime_interface.h:476), so layer i+1 is handed to the
//     runtime while layer i is still running -- exactly what the reference
//     cpp demo does in forward_next (chat.cpp:709-750), which syncs only
//     once, after lm_head. Layer i+1 reads layer i's output through the same
//     graph-to-graph ordering the runtime enforces, so no barrier is needed
//     between layers; one sync_launches() at the end covers the batch. That
//     boundary is placed before the *first* consumer of the result -- the
//     caller's state copies, D2S, or lm_head -- never after it.
//   * A linear layer's conv_state (and output-2 rec_state, when present) is
//     only copied back when the graph did not already write it in place.
//     measure_state_layout() decides that from the loaded graph's addresses;
//     on the shipped bmodels output 1 is input 1, so the copy was a buffer
//     copying itself.
//
// Contract: on success every graph this call queued has retired, so this
// token's KV/state is final and the session can be parked, snapshotted or
// decoded again as soon as it returns. On failure `fault` is set and `ok` is
// false, whether the launch or the sync was what failed.
bm_device_mem_t Engine::Impl::decode_layers(bm_device_mem_t in_mem,
                                            const int32_t pos3[3], int cur_pos,
                                            bool* ok) {
  *ok = false;
  // History bmodels compile the FA decode graph at several KV widths (e.g.
  // 8192/4096/2048); attention cost scales with the width, so take the
  // smallest stage whose window still holds slot cur_pos (chat.cpp
  // select_decode_stage). Every stage reads the same [1, len, h, d] layout,
  // so the session's stage-0 KV buffer serves all of them.
  const bm_net_info_t* fa_c = blocks_cache[kFaInterval - 1];
  int fs = 0;
  static const bool force_stage0 = std::getenv("LLM_DECODE_STAGE0") != nullptr;
  if (!force_stage0) {
    for (int k = 0; k < fa_c->stage_num; k++) {
      const int len_k = fa_c->stages[k].input_shapes[3].dims[1];
      if (len_k > cur_pos && len_k < fa_c->stages[fs].input_shapes[3].dims[1]) fs = k;
    }
  }
  const int win = fa_c->stages[fs].input_shapes[3].dims[1];
  std::vector<uint16_t> mask(static_cast<size_t>(win) + 1, 0);
  for (int i = cur_pos; i < win; i++) mask[i] = mask_value;
  if (!s2d(dec_mask, mask.data(), mask.size() * 2) ||
      !s2d(dec_pos, pos3, 3 * sizeof(int32_t))) {
    return in_mem;
  }

  bm_device_mem_t cur = in_mem;
  for (int idx = 0; idx < num_layers; idx++) {
    const bm_net_info_t* net = blocks_cache[idx];
    const auto& st = net->stages[0];
    bm_device_mem_t out0 = st.output_mems[0];
    std::vector<bm_tensor_t> in, out;
    if (is_fa(idx)) {
      const auto& ss = net->stages[fs < net->stage_num ? fs : 0];
      out0 = ss.output_mems[0];
      in = {make_tensor(cur, net->input_dtypes[0], ss.input_shapes[0]),
            make_tensor(dec_pos, net->input_dtypes[1], ss.input_shapes[1]),
            make_tensor(dec_mask, net->input_dtypes[2], ss.input_shapes[2]),
            make_tensor(state_a(idx), net->input_dtypes[3], ss.input_shapes[3]),
            make_tensor(state_b(idx), net->input_dtypes[4], ss.input_shapes[4])};
      const size_t off = static_cast<size_t>(cur_pos) * kv_bytes;
      out = {make_tensor(out0, net->output_dtypes[0], ss.output_shapes[0]),
             make_tensor(view(state_a(idx), off, kv_bytes), net->output_dtypes[1],
                         ss.output_shapes[1]),
             make_tensor(view(state_b(idx), off, kv_bytes), net->output_dtypes[2],
                         ss.output_shapes[2])};
      if (!run(net, in, out, /*wait=*/false)) return cur;
    } else {
      in = {make_tensor(cur, net->input_dtypes[0], st.input_shapes[0]),
            make_tensor(st.input_mems[1], net->input_dtypes[1], st.input_shapes[1]),
            make_tensor(st.input_mems[2], net->input_dtypes[2], st.input_shapes[2])};
      for (int o = 0; o < net->output_num; o++) {
        out.push_back(make_tensor(st.output_mems[o], net->output_dtypes[o],
                                  st.output_shapes[o]));
      }
      if (!run(net, in, out, /*wait=*/false)) return cur;
      // conv_state comes back as output 1; rec_state is in place in input 2
      // unless this bmodel emits it as output 2. Copy only what the graph did
      // not already write where the next layer / the next token will read it.
      if (!conv_inplace[idx]) {
        d2d(state_a(idx), 0, const_cast<bm_device_mem_t&>(st.output_mems[1]), 0,
            std::min(mem_size(state_a(idx)), mem_size(st.output_mems[1])));
      }
      if (net->output_num > 2 && !rec_inplace[idx]) {
        d2d(state_b(idx), 0, const_cast<bm_device_mem_t&>(st.output_mems[2]), 0,
            std::min(mem_size(state_b(idx)), mem_size(st.output_mems[2])));
      }
    }
    cur = out0;
    capture_rows(idx, cur, 1, dbg_sink);
  }
  // One boundary for the whole batch: everything this token queued has to be
  // done before the caller reads `cur`, copies the state out, or asks for a
  // token -- and before this function returns to a caller that may park the
  // session or hand the TPU to another one.
  if (!sync_launches()) return cur;
  *ok = true;
  return cur;
}

// ---------------------------------------------------------------------------
Session::Session() = default;
Session::~Session() {
  if (impl_) {
    std::lock_guard<std::mutex> g(impl_->eng->mu);
    delete impl_;
  }
}

int Session::token_len() const { return impl_->history; }

void Session::set_exact_tail(int rows) { impl_->exact_tail = std::max(0, rows); }

int Session::debug_rows(uint16_t* out, int n) {
  const int k = std::min(n, static_cast<int>(impl_->dbg_rows.size()));
  std::copy(impl_->dbg_rows.begin(), impl_->dbg_rows.begin() + k, out);
  impl_->dbg_rows.clear();
  return k;
}

int Session::last_hidden(uint16_t* out, int n) const {
  const int k = std::min(n, static_cast<int>(impl_->dbg_hidden.size()));
  std::copy(impl_->dbg_hidden.begin(), impl_->dbg_hidden.begin() + k, out);
  return k;
}

bool Session::prefill(const int* tokens, int n, const int* pos3,
                      const VitImage* images, int n_images) {
  return prefill_impl(tokens, n, pos3, images, n_images, false);
}

bool Session::extend(const int* tokens, int n, const int* pos3,
                     const VitImage* images, int n_images) {
  return prefill_impl(tokens, n, pos3, images, n_images, true);
}

// Prefill `n` new tokens. Fresh (append=false) replaces the session; append
// keeps the KV/state already in the session and adds the tokens after it,
// which needs the history graphs (block_kv_<i>). Mirrors the demo's
// forward_first_plain / forward_first_aligned / forward_first_with_kv:
//   * tokens go through in chunks of max_input (the embedding/prefill width);
//   * per chunk, FA layers run block_<i> while no KV exists yet and
//     block_kv_<i> (past KV as input) after that; linear layers start from the
//     session's conv/rec state;
//   * a chunk longer than 64 that is not 16-aligned prefills its aligned head
//     and replays the rest through the decode graphs (CV84X6 dynamic-graph
//     defect), reading those rows from the prompt matrix so image rows survive.
bool Session::prefill_impl(const int* tokens, int n, const int* pos3,
                           const VitImage* images, int n_images, bool append) {
  Impl* s = impl_;
  Engine::Impl* e = s->eng;
  std::lock_guard<std::mutex> guard(e->mu);
  if (append && s->history == 0) append = false;
  const int old0 = append ? s->history : 0;
  if (n <= 0) return e->fail("empty prompt");
  if (append && e->blocks_kv.empty()) {
    return e->fail("this bmodel has no history graphs; it cannot extend a session");
  }
  const int limit = e->blocks_kv.empty() ? std::min(e->max_input, e->seq_len - 1)
                                         : e->seq_len - 1;
  if (old0 + n > limit) {
    return e->fail("prompt of " + std::to_string(old0 + n) + " tokens exceeds the limit of " +
                   std::to_string(limit));
  }
  // Reject out-of-range token ids before anything is submitted. The embedding
  // graphs gather by id, so a bad id is an out-of-bounds device read: the TPU
  // cannot report it as a bad argument, it either reads garbage or faults, and
  // a fault wedges the board until reboot (run() marks it and refuses further
  // work). This is a caller error, so it must not set `fault` -- the session
  // is untouched and the call can be retried with a valid prompt.
  if (const int bad = e->check_tokens(tokens, n)) {
    return e->fail("token id " + std::to_string(bad) + " is outside the vocabulary [0, " +
                   std::to_string(e->vocab) + "); the embedding graph would read out of "
                   "bounds (caller error, not an NPU fault)");
  }
  std::vector<int> lin;
  if (!pos3) {
    const int base = append ? s->pos_next : 0;
    lin.resize(static_cast<size_t>(3) * n);
    for (int r = 0; r < 3; r++)
      for (int i = 0; i < n; i++) lin[static_cast<size_t>(r) * n + i] = base + i;
    pos3 = lin.data();
  }
  for (int k = 0; k < n_images; k++) {
    const VitImage& im = images[k];
    if (!e->net_vit) return e->fail("this bmodel has no vit graph");
    if (im.patches <= 0 || im.patches % 4 != 0 || im.patches > e->vit_max_patches) {
      return e->fail("image patch count " + std::to_string(im.patches) +
                     " out of range (max " + std::to_string(e->vit_max_patches) + ")");
    }
    if (im.offset < 0 || im.offset + im.patches / 4 > n) {
      return e->fail("image rows fall outside the prompt");
    }
  }
  s->pending = -1;
  // A fresh prefill takes the session over (history=0, FA slots untouched --
  // see Reset::kFreshPrefill); an extend keeps the state it has.
  if (!s->activate(append ? Session::Impl::Reset::kKeepState
                          : Session::Impl::Reset::kFreshPrefill)) {
    return false;
  }

  // ---- per chunk: embedding, then each image's vit rows spliced in ----
  // The prompt matrix is one max_input-wide chunk (embed_out): each chunk is
  // embedded right before its layers run, and the vit rows of every image
  // that overlaps it are copied over its <|image_pad|> rows (forward_embed +
  // forward_vit, chunk-wise). An image can straddle two chunks; its vit output
  // stays in vit_out for the second one.
  bm_device_mem_t& pm = e->embed_out;
  int vit_loaded = -1;
  auto embed_chunk = [&](int c0, int cur) -> bool {
    std::vector<int32_t> ids(static_cast<size_t>(e->max_input), 0);
    std::copy(tokens + c0, tokens + c0 + cur, ids.begin());
    if (!e->s2d(e->embed_in, ids.data(), ids.size() * sizeof(int32_t))) return false;
    const auto* g = e->net_embed;
    std::vector<bm_tensor_t> in{make_tensor(e->embed_in, g->input_dtypes[0],
                                            g->stages[0].input_shapes[0])};
    std::vector<bm_tensor_t> out{make_tensor(e->embed_out, g->output_dtypes[0],
                                             g->stages[0].output_shapes[0])};
    return e->run(g, in, out);
  };
  auto run_vit = [&](const VitImage& im) -> bool {
    const auto* g = e->net_vit;
    const size_t P = static_cast<size_t>(im.patches);
    if (!e->vit_dynamic) {
      for (int i = 0; i < 4; i++) e->zero(e->vit_in[i]);
    }
    if (!e->s2d_float(e->vit_in[0], g->input_dtypes[0], im.pixels, P * e->vit_dims) ||
        !e->s2d(e->vit_in[1], im.pos_ids, P * 2 * sizeof(int32_t)) ||
        !e->s2d(e->vit_in[2], im.pos_idx, P * 4 * sizeof(int32_t)) ||
        !e->s2d_float(e->vit_in[3], g->input_dtypes[3], im.pos_weight, P * 4)) {
      return false;
    }
    std::vector<bm_tensor_t> in, out;
    for (int i = 0; i < 4; i++) {
      bm_shape_t shp = g->stages[0].input_shapes[i];
      if (e->vit_dynamic) shp.dims[0] = im.patches;
      in.push_back(make_tensor(e->vit_in[i], g->input_dtypes[i], shp));
    }
    out.push_back(make_tensor(e->vit_out, g->output_dtypes[0],
                              g->stages[0].output_shapes[0]));
    return e->run(g, in, out);
  };
  auto splice_images = [&](int c0, int cur) -> bool {
    for (int k = 0; k < n_images; k++) {
      const VitImage& im = images[k];
      const int rows = im.patches / 4;
      const int a = std::max(im.offset, c0);
      const int b = std::min(im.offset + rows, c0 + cur);
      if (a >= b) continue;
      if (vit_loaded != k) {
        if (!run_vit(im)) return false;
        vit_loaded = k;
      }
      e->d2d(pm, static_cast<size_t>(a - c0) * e->hidden_bytes, e->vit_out,
             static_cast<size_t>(a - im.offset) * e->hidden_bytes,
             static_cast<size_t>(b - a) * e->hidden_bytes);
    }
    return true;
  };

  // ---- blocks, chunk by chunk ----
  bm_device_mem_t& hid = e->pf_out[0][0];  // first_hidden_states_output
  bm_device_mem_t last{};
  int old = old0;  // KV slots already filled
  // Rows from `exact_from` on are replayed through the decode graphs, whose
  // routed-expert MoE is exact (the prefill graphs' is not on CV84X6, see
  // set_exact_tail); applies to this call only.
  const int exact_from = n - std::min(n, std::max(0, s->exact_tail));
  s->exact_tail = 0;
  for (int c0 = 0; c0 < n; c0 += e->max_input) {
    const int cur = std::min(e->max_input, n - c0);
    if (!embed_chunk(c0, cur) || !splice_images(c0, cur)) return false;
    int L = cur;
    const int al = prefill_align();
    if (e->is_dynamic && cur > align_above() && cur % al != 0) L = (cur / al) * al;
    if (c0 + L > exact_from) L = std::max(0, (exact_from - c0) / al * al);

    if (L > 0) {  // L == 0: a chunk shorter than the alignment, all replayed
    std::vector<int32_t> pos_head(static_cast<size_t>(3) * L);
    for (int r = 0; r < 3; r++)
      for (int i = 0; i < L; i++)
        pos_head[static_cast<size_t>(r) * L + i] = pos3[static_cast<size_t>(r) * n + c0 + i];
    std::vector<uint16_t> pmask;
    if (e->prefill_mask) {
      if (old > 0) return e->fail("masked prefill graphs cannot extend a session");
      pmask.assign(static_cast<size_t>(L) * L, e->mask_value);
      for (int i = 0; i < L; i++)
        for (int j = 0; j <= i; j++) pmask[static_cast<size_t>(i) * L + j] = 0;
    }

    for (int idx = 0; idx < e->num_layers; idx++) {
      const bool fa = e->is_fa(idx);
      bm_device_mem_t in0 = idx == 0 ? view(pm, 0, static_cast<size_t>(L) * e->hidden_bytes)
                                     : hid;
      std::vector<bm_tensor_t> in, out;
      if (fa && old > 0) {
        // block_kv_<idx> with the past KV, bound to the template graph's own
        // IO memory as the demo does (some history bmodels misbehave when
        // these inputs live elsewhere).
        const bm_net_info_t* net = e->blocks_kv[idx];
        const auto& tst = e->blocks_kv[kFaInterval - 1]->stages[0];
        auto& kin = const_cast<bm_device_mem_t&>(tst.input_mems[2]);
        auto& vin = const_cast<bm_device_mem_t&>(tst.input_mems[3]);
        auto& pin1 = const_cast<bm_device_mem_t&>(tst.input_mems[1]);
        auto& kout = const_cast<bm_device_mem_t&>(tst.output_mems[1]);
        auto& vout = const_cast<bm_device_mem_t&>(tst.output_mems[2]);
        const size_t past = static_cast<size_t>(old) * e->kv_bytes;
        e->d2d(kin, 0, e->state_a(idx), 0, past);
        e->d2d(vin, 0, e->state_b(idx), 0, past);
        if (!e->s2d(pin1, pos_head.data(), pos_head.size() * sizeof(int32_t))) return false;
        bm_shape_t kshape = tst.input_shapes[2];
        kshape.dims[1] = old;
        in = {make_tensor(in0, net->input_dtypes[0], make_shape({1, L, e->hidden})),
              make_tensor(pin1, net->input_dtypes[1], make_shape({3, L})),
              make_tensor(kin, net->input_dtypes[2], kshape),
              make_tensor(vin, net->input_dtypes[3], kshape)};
        out = {make_tensor(hid, net->output_dtypes[0], tst.output_shapes[0]),
               make_tensor(kout, net->output_dtypes[1], tst.output_shapes[1]),
               make_tensor(vout, net->output_dtypes[2], tst.output_shapes[2])};
        if (!e->run(net, in, out)) return false;
        e->capture_rows(idx, hid, L, &s->dbg_rows);
        const size_t len = static_cast<size_t>(L) * e->kv_bytes;
        e->d2d(e->state_a(idx), past, kout, 0, len);
        e->d2d(e->state_b(idx), past, vout, 0, len);
        continue;
      }
      const int kind = fa ? 1 : 0;
      const bm_net_info_t* net = e->blocks[idx];
      const auto& st = net->stages[0];
      auto& pin = e->pf_in[kind];
      auto& pout = e->pf_out[kind];
      in.push_back(make_tensor(in0, net->input_dtypes[0], make_shape({1, L, e->hidden})));
      if (fa) {
        if (!e->s2d(pin[1], pos_head.data(), pos_head.size() * sizeof(int32_t))) return false;
        in.push_back(make_tensor(pin[1], net->input_dtypes[1], make_shape({3, L})));
        if (e->prefill_mask) {
          if (!e->s2d(pin[2], pmask.data(), pmask.size() * 2)) return false;
          in.push_back(make_tensor(pin[2], net->input_dtypes[2], make_shape({1, 1, L, L})));
        }
      } else {
        // Linear: input 1 is rec_state (updated in place); history bmodels
        // also take conv_state as input 2. Start from the session's state.
        for (int i = 1; i < net->input_num; i++) {
          if (old > 0 && i == 1) {
            e->d2d(pin[1], 0, e->state_b(idx), 0,
                   std::min(mem_size(pin[1]), mem_size(e->state_b(idx))));
          } else if (old > 0 && i == 2) {
            e->d2d(pin[2], 0, e->state_a(idx), 0,
                   std::min(mem_size(pin[2]), mem_size(e->state_a(idx))));
          } else {
            e->zero(pin[i]);
          }
          in.push_back(make_tensor(pin[i], net->input_dtypes[i], st.input_shapes[i]));
        }
      }
      for (int o = 0; o < net->output_num; o++) {
        bm_device_mem_t m = (o == 0) ? hid : pout[o];
        out.push_back(make_tensor(m, net->output_dtypes[o], st.output_shapes[o]));
      }
      if (!e->run(net, in, out)) return false;
      e->capture_rows(idx, hid, L, &s->dbg_rows);

      if (fa) {
        const size_t len = static_cast<size_t>(L) * e->kv_bytes;
        const size_t past = static_cast<size_t>(old) * e->kv_bytes;
        e->d2d(e->state_a(idx), past, pout[1], 0, len);
        e->d2d(e->state_b(idx), past, pout[2], 0, len);
      } else {
        e->d2d(e->state_a(idx), 0, pout[1], 0,
               std::min(mem_size(e->state_a(idx)), mem_size(pout[1])));
        e->d2d(e->state_b(idx), 0, pin[1], 0,
               std::min(mem_size(e->state_b(idx)), mem_size(pin[1])));
      }
    }
    last = view(hid, static_cast<size_t>(L - 1) * e->hidden_bytes, e->hidden_bytes);
    }

    // ---- tail of this chunk: rows [L, cur) through the decode graphs ----
    for (int t = L; t < cur; t++) {
      const int row = c0 + t;
      e->d2d(e->ec_out, 0, pm, static_cast<size_t>(t) * e->hidden_bytes, e->hidden_bytes);
      const int32_t p[3] = {pos3[row], pos3[static_cast<size_t>(n) + row],
                            pos3[static_cast<size_t>(2) * n + row]};
      bool ok = false;
      e->dbg_sink = &s->dbg_rows;
      last = e->decode_layers(e->ec_out, p, old + t, &ok);
      e->dbg_sink = nullptr;
      if (!ok) return false;
    }
    old += cur;
    s->history = old;  // keep in step so a failure later is not mistaken for KV
  }

  e->capture(last, &s->dbg_hidden);
  const int token = e->sample_lm(last);
  if (token < 0) return false;
  int max_pos = append ? s->pos_next - 1 : 0;
  for (size_t i = 0; i < static_cast<size_t>(3) * n; i++) max_pos = std::max(max_pos, pos3[i]);
  s->history = old;
  s->pos_next = max_pos + 1;
  s->last_id = token;
  s->pending = token;
  return true;
}

// ---------------------------------------------------------------------------
// Snapshots: the session's state at its current length, in its own NPU
// buffers -- FA K/V for the filled slots, linear conv/rec state whole -- plus
// every piece of the session's logical state that decode() reads.
//
// The device buffers alone are not a continuation: a session that has just
// prefilled holds H KV slots but its next decode() embeds the token prefill
// sampled (last_id), which is *not* among those slots. Restoring KV without
// that token would feed an invalid id to the embedding graph. Likewise
// `pending`: prefill/extend sample a token the first decode() hands back
// without running the NPU, so a snapshot taken in that window must reproduce
// that hand-back -- otherwise the original session returns token 1 while the
// restored one returns token 2, and the two streams to differ by one.
//
// Linear-attention state cannot be rolled back, so a snapshot is only valid
// for exactly the prefix it was taken at (same as the demo's prefix cache).
struct Snapshot {
  void* eng = nullptr;  // Engine::Impl*, which is private to Engine/Session
  int len = 0;
  int pos_next = 0;
  int last_id = -1;
  int pending = -1;
  size_t bytes = 0;
  std::vector<bm_device_mem_t> a, b;
};

void* Session::snapshot() {
  Impl* s = impl_;
  Engine::Impl* e = s->eng;
  std::lock_guard<std::mutex> guard(e->mu);
  if (s->history <= 0) {
    e->fail("snapshot of an empty session");
    return nullptr;
  }
  if (!s->activate(Impl::Reset::kKeepState)) return nullptr;
  auto* snap = new Snapshot();
  snap->eng = e;
  snap->len = s->history;
  snap->pos_next = s->pos_next;
  snap->last_id = s->last_id;
  snap->pending = s->pending;
  snap->a.assign(e->num_layers, bm_device_mem_t{});
  snap->b.assign(e->num_layers, bm_device_mem_t{});
  for (int i = 0; i < e->num_layers; i++) {
    const size_t sa = e->is_fa(i) ? static_cast<size_t>(snap->len) * e->kv_bytes
                                  : mem_size(e->state_a(i));
    const size_t sb = e->is_fa(i) ? sa : mem_size(e->state_b(i));
    if (bm_malloc_device_byte_heap_mask(e->handle, &snap->a[i], kNpuHeapMask,
                                        static_cast<unsigned int>(sa)) != BM_SUCCESS ||
        bm_malloc_device_byte_heap_mask(e->handle, &snap->b[i], kNpuHeapMask,
                                        static_cast<unsigned int>(sb)) != BM_SUCCESS) {
      Engine::free_snapshot_locked(snap);
      e->fail("NPU heap exhausted taking a snapshot");
      return nullptr;
    }
    e->d2d(snap->a[i], 0, e->state_a(i), 0, sa);
    e->d2d(snap->b[i], 0, e->state_b(i), 0, sb);
    snap->bytes += sa + sb;
  }
  return snap;
}

bool Session::restore(void* handle) {
  Impl* s = impl_;
  Engine::Impl* e = s->eng;
  auto* snap = static_cast<Snapshot*>(handle);
  std::lock_guard<std::mutex> guard(e->mu);
  if (!snap || snap->eng != e) return e->fail("snapshot belongs to another model");
  // A snapshot that does not fit this model's context cannot be laid down in
  // the session's buffers; copying it anyway would run the d2d past the end of
  // a device allocation, which the driver cannot reject -- it either reads
  // garbage or faults the TPU.
  if (snap->len <= 0 || snap->len >= e->seq_len) {
    return e->fail("snapshot length " + std::to_string(snap->len) +
                   " is outside this model's [1, " + std::to_string(e->seq_len) + ")");
  }
  // Reset::kRestore zeroes the whole per-layer state (FA KV included), so the
  // slots this snapshot leaves empty are already clean -- no stale KV from a
  // previous longer session can survive. Restore cannot skip that the way a
  // fresh prefill does: it copies only [0, len) and then decodes at `len`, so
  // slots past the snapshot stay readable and must be zero, not finite-stale.
  if (!s->activate(Impl::Reset::kRestore)) return false;
  for (int i = 0; i < e->num_layers; i++) {
    const size_t sa = mem_size(snap->a[i]);
    const size_t sb = mem_size(snap->b[i]);
    const size_t la = e->is_fa(i) ? static_cast<size_t>(snap->len) * e->kv_bytes : sa;
    const size_t lb = e->is_fa(i) ? la : sb;
    e->d2d(e->state_a(i), 0, snap->a[i], 0, std::min(la, sa));
    e->d2d(e->state_b(i), 0, snap->b[i], 0, std::min(lb, sb));
  }
  s->history = snap->len;
  s->pos_next = snap->pos_next;
  s->last_id = snap->last_id;
  s->pending = snap->pending;
  return true;
}

size_t Engine::snapshot_bytes(void* handle) {
  return handle ? static_cast<Snapshot*>(handle)->bytes : 0;
}

void Engine::free_snapshot(void* handle) {
  auto* snap = static_cast<Snapshot*>(handle);
  if (!snap) return;
  std::lock_guard<std::mutex> guard(static_cast<Impl*>(snap->eng)->mu);
  free_snapshot_locked(snap);
}

void Engine::free_snapshot_locked(void* handle) {
  auto* snap = static_cast<Snapshot*>(handle);
  for (auto* v : {&snap->a, &snap->b}) {
    for (auto& m : *v) {
      if (m.u.device.device_addr) bm_free_device(static_cast<Impl*>(snap->eng)->handle, m);
    }
  }
  delete snap;
}

int Session::decode() {
  Impl* s = impl_;
  Engine::Impl* e = s->eng;
  std::lock_guard<std::mutex> guard(e->mu);
  if (s->pending >= 0) {
    const int t = s->pending;
    s->pending = -1;
    return t;
  }
  if (s->history <= 0) {
    e->fail("decode before prefill");
    return -1;
  }
  if (s->history >= e->seq_len) {
    e->fail("context exhausted");
    return -1;
  }
  if (!s->activate(Impl::Reset::kKeepState)) return -1;

  const auto* g = e->net_embed_cache;
  const int32_t id = s->last_id;
  if (id < 0) {
    e->fail("decode requires a previous token; prefill or extend after restore");
    return -1;
  }
  if (!e->s2d(e->ec_in, &id, sizeof(id))) return -1;
  std::vector<bm_tensor_t> in{make_tensor(e->ec_in, g->input_dtypes[0],
                                          g->stages[0].input_shapes[0])};
  std::vector<bm_tensor_t> out{make_tensor(e->ec_out, g->output_dtypes[0],
                                           g->stages[0].output_shapes[0])};
  if (!e->run(g, in, out)) return -1;

  bool ok = false;
  const int32_t p[3] = {s->pos_next, s->pos_next, s->pos_next};
  bm_device_mem_t last = e->decode_layers(e->ec_out, p, s->history, &ok);
  if (!ok) return -1;
  e->capture(last, &s->dbg_hidden);
  const int token = e->sample_lm(last);
  if (token < 0) return -1;
  s->history++;
  s->pos_next++;
  s->last_id = token;
  return token;
}

}  // namespace cv84x6
