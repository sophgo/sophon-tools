// PaddleOCR-VL-1.5 decode with a KV cache that outlives a launch.
//
// MYS-2660. Stage A3 (MYS-2610) drove embedding, the 18 prefill blocks and
// lm_head through raw bmrt, but its decode step segfaulted as soon as
// block_cache_N's k_cache/v_cache outputs were pointed at caller memory, and
// the stage was closed with "this bmodel's outputs cannot leave its own stage
// memory -- that needs sail or native/". That conclusion was wrong, and how it
// was reached is worth stating, because it is the one thing this file exists to
// correct:
//
//   bm_memcpy_d2s copies bm_mem_get_device_size(src) bytes: the whole
//   descriptor (bmlib_memory.cpp:3113). A3's Python runner read each output
//   back through the descriptor it had *bound*, so when an output was bound to
//   a 1 MiB KV cache the readback memcpy'd 1 MiB into the 512-byte numpy array
//   holding that tensor. That overruns the heap in ctypes-land and surfaces as
//   a segfault inside bmrt.
//
// Measured on .157, one launch per process (probe transcript in
// tools/ocr/vl_native/README.md):
//
//   launch with k_cache/v_cache bound into a caller 1 MiB buffer, then sync  OK
//   ...then read k_cache back through a descriptor sized to the *tensor*     OK
//   ...then read it back through the *bound* descriptor                     SIGSEGV
//
// So bmrt does exactly what native/src/llm_engine.cpp already relies on: the
// caller owns the KV buffer and hands each launch a shifted view of it. That is
// KV option (a) in the card, and it is the one implemented here -- the graph
// writes each new row straight into the persistent cache, no copy at all.
//
// The bmodel contract, read off the board's own bmrt (not assumed):
//   vit             (patch[T,3,14,14] f32 [, mask [1,1,T,T]])
//                                              -> emb [1,T/4,1024] bf16
//   embedding       (ids [1,SEQ] i32)          -> [1,SEQ,1024] bf16
//   embedding_cache (ids [1,1] i32)            -> [1,1,1024] bf16
//   block_N         (x [1,SEQ,1024], pos [3,SEQ], mask [1,1,SEQ,SEQ])
//                     -> x' , k [1,SEQ,2,128] , v [1,SEQ,2,128]     addr_mode 0
//   block_cache_N   (x [1,1,1024], pos [3,1], mask [1,1,1,SEQ+1],
//                    history_k/v [1,SEQ,2,128])
//                     -> x' , k_new [1,1,2,128] , v_new [1,1,2,128] addr_mode 1
//   lm_head         (hidden [1,1024] bf16)     -> token [1,1] i32
//
// Everything on the wire is bf16 (dtype 8), which is raw 16-bit words and NOT
// a float; the widening/narrowing below is deliberate (see f32_to_bf16).
//
// Shaped so Python can stay the orchestrator: this program takes a prepared
// prompt (token ids) and pixels, runs the four stages on the NPU, and writes
// the token ids plus per-stage timings. It does no tokenisation, no image
// decode and no text comparison, so every reference comparison happens on the
// Python side against the same inputs.

#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

constexpr int kNpuHeapMask = 3;
// A3 measured this: a decode row whose key is masked to -9984 still gets ~0
// attention weight after softmax, while a -inf would produce NaN when a whole
// row is masked (which happens for padding positions).
constexpr float kMaskNeg = -9984.0f;

uint16_t f32_to_bf16(float f) {
  uint32_t bits;
  std::memcpy(&bits, &f, 4);
  bits += 0x7FFFu + ((bits >> 16) & 1u);   // round to nearest even
  return static_cast<uint16_t>(bits >> 16);
}

double now_ms() {
  using namespace std::chrono;
  return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

[[noreturn]] void die(const char* what) {
  std::fprintf(stderr, "vl_native: %s\n", what);
  std::exit(2);
}

// ---------------------------------------------------------------------------

struct Engine {
  bm_handle_t handle = nullptr;
  void* rt = nullptr;
  std::vector<bm_device_mem_t> owned;

  void open(const char* bmodel) {
    if (bm_dev_request(&handle, 0) != BM_SUCCESS || !handle) die("bm_dev_request");
    rt = bmrt_create(handle);
    if (!rt || !bmrt_load_bmodel(rt, bmodel)) die("bmrt_load_bmodel");
  }
  ~Engine() {
    for (auto& m : owned) bm_free_device(handle, m);
    if (rt) bmrt_destroy(rt);
    if (handle) bm_dev_free(handle);
  }

  bm_device_mem_t alloc(size_t bytes) {
    bm_device_mem_t m;
    if (bm_malloc_device_byte_heap_mask(handle, &m, kNpuHeapMask,
                                        static_cast<unsigned int>(bytes)) != BM_SUCCESS) {
      std::fprintf(stderr, "vl_native: NPU heap exhausted at %zu bytes\n", bytes);
      std::exit(3);
    }
    owned.push_back(m);
    return m;
  }

  // The one primitive the whole KV scheme needs: a descriptor pointing N bytes
  // into an existing buffer. sail spells this Tensor(mem, shape, offset).
  static bm_device_mem_t view(const bm_device_mem_t& base, size_t byte_off,
                              size_t bytes) {
    return bm_mem_from_device(bm_mem_get_device_addr(base) + byte_off,
                              static_cast<unsigned int>(bytes));
  }

  void s2d(const bm_device_mem_t& dst, const void* src, size_t bytes) {
    if (bm_memcpy_s2d_partial(handle, dst, const_cast<void*>(src),
                              static_cast<unsigned int>(bytes)) != BM_SUCCESS) {
      die("bm_memcpy_s2d");
    }
  }
  // Read exactly `bytes`, never the descriptor's size -- that is the A3 bug.
  void d2s(void* dst, const bm_device_mem_t& src, size_t bytes) {
    bm_device_mem_t sized = view(src, 0, bytes);
    if (bm_memcpy_d2s(handle, dst, sized) != BM_SUCCESS) die("bm_memcpy_d2s");
  }
  void sync() {
    if (bm_thread_sync(handle) != BM_SUCCESS) die("bm_thread_sync");
  }
};

// One graph. Tensors are rebuilt per launch rather than cached, because the
// caller routinely re-points inputs and outputs at different offsets inside
// shared buffers; bm_tensor_t is 56 bytes, so this costs nothing.
struct Net {
  const bm_net_info_t* info = nullptr;

  void attach(Engine& eng, const char* name) {
    info = bmrt_get_network_info(eng.rt, name);
    if (!info) {
      std::fprintf(stderr, "vl_native: no network %s\n", name);
      std::exit(4);
    }
    if (info->stage_num != 1) {
      std::fprintf(stderr, "vl_native: %s has %d stages, want 1\n", name,
                   info->stage_num);
      std::exit(4);
    }
  }
  bm_shape_t in_shape(int i) const { return info->stages[0].input_shapes[i]; }
  bm_shape_t out_shape(int i) const { return info->stages[0].output_shapes[i]; }
  bm_data_type_t in_dt(int i) const { return info->input_dtypes[i]; }
  bm_data_type_t out_dt(int i) const { return info->output_dtypes[i]; }

  static size_t bytes(const bm_shape_t& s, bm_data_type_t dt) {
    return bmrt_shape_count(&s) * bmrt_data_type_size(dt);
  }
  static bm_tensor_t tensor(bm_device_mem_t mem, bm_data_type_t dt,
                            const bm_shape_t& s) {
    bm_tensor_t t{};
    bmrt_tensor_with_device(&t, mem, dt, s);
    t.st_mode = BM_STORE_1N;
    return t;
  }

  // `in`/`out` are caller-owned descriptors; the shapes and dtypes always come
  // from the graph so a wrong call cannot get past bmrt silently.
  void run(Engine& eng, const std::vector<bm_device_mem_t>& ins,
           const std::vector<bm_device_mem_t>& outs, bool wait) const {
    if (static_cast<int>(ins.size()) != info->input_num ||
        static_cast<int>(outs.size()) != info->output_num) {
      std::fprintf(stderr, "vl_native: %s arity mismatch\n", info->name);
      std::exit(5);
    }
    std::vector<bm_tensor_t> tin(ins.size()), tout(outs.size());
    for (size_t i = 0; i < ins.size(); i++)
      tin[i] = tensor(ins[i], in_dt(static_cast<int>(i)),
                      in_shape(static_cast<int>(i)));
    for (size_t i = 0; i < outs.size(); i++)
      tout[i] = tensor(outs[i], out_dt(static_cast<int>(i)),
                       out_shape(static_cast<int>(i)));
    if (!bmrt_launch_tensor_ex(eng.rt, info->name, tin.data(),
                               static_cast<int>(tin.size()), tout.data(),
                               static_cast<int>(tout.size()), true, true)) {
      std::fprintf(stderr, "vl_native: launch failed: %s\n", info->name);
      std::exit(6);
    }
    if (wait) eng.sync();
  }
};

// ---------------------------------------------------------------------------
// The prepared prompt, written by tools/ocr/vl_native_prep.py.

struct Prep {
  std::vector<int32_t> ids;
  std::vector<float> patches;
  int head_len = 0;      // text tokens before the image block
  int grid_h = 0, grid_w = 0;
  int max_new = 32;
  int eos_id = 2;
  int seq = 2048;
};

std::vector<char> slurp(const std::string& path) {
  FILE* f = std::fopen(path.c_str(), "rb");
  if (!f) {
    std::fprintf(stderr, "vl_native: cannot open %s\n", path.c_str());
    std::exit(7);
  }
  std::fseek(f, 0, SEEK_END);
  long n = std::ftell(f);
  std::fseek(f, 0, SEEK_SET);
  std::vector<char> buf(static_cast<size_t>(n));
  if (n && std::fread(buf.data(), 1, static_cast<size_t>(n), f) !=
               static_cast<size_t>(n)) {
    die("short read");
  }
  std::fclose(f);
  return buf;
}

void spit(const std::string& path, const void* data, size_t bytes) {
  FILE* f = std::fopen(path.c_str(), "wb");
  if (!f) {
    std::fprintf(stderr, "vl_native: cannot write %s\n", path.c_str());
    std::exit(7);
  }
  if (bytes && std::fwrite(data, 1, bytes, f) != bytes) die("short write");
  std::fclose(f);
}

// meta.txt is "key value" lines: no JSON parser, no dependency.
Prep read_prep(const std::string& dir) {
  Prep p;
  auto meta = slurp(dir + "/meta.txt");
  std::string text(meta.begin(), meta.end());
  size_t pos = 0;
  while (pos < text.size()) {
    size_t eol = text.find('\n', pos);
    if (eol == std::string::npos) eol = text.size();
    std::string line = text.substr(pos, eol - pos);
    pos = eol + 1;
    size_t sp = line.find(' ');
    if (sp == std::string::npos) continue;
    std::string k = line.substr(0, sp);
    long v = std::atol(line.c_str() + sp + 1);
    if (k == "head_len") p.head_len = static_cast<int>(v);
    else if (k == "grid_h") p.grid_h = static_cast<int>(v);
    else if (k == "grid_w") p.grid_w = static_cast<int>(v);
    else if (k == "max_new") p.max_new = static_cast<int>(v);
    else if (k == "eos_id") p.eos_id = static_cast<int>(v);
    else if (k == "seq") p.seq = static_cast<int>(v);
  }
  auto ids = slurp(dir + "/ids.i32");
  p.ids.resize(ids.size() / 4);
  std::memcpy(p.ids.data(), ids.data(), ids.size());
  auto pat = slurp(dir + "/patches.f32");
  p.patches.resize(pat.size() / 4);
  std::memcpy(p.patches.data(), pat.data(), pat.size());
  return p;
}

// ---------------------------------------------------------------------------

// Position ids for the 3-row (t,h,w) rotary table. Image rows are (0,h,w) on
// the 2x2-merged grid; text rows are plain sequential and coincide across all
// three. Transcribed from the reference's get_rope_index and pinned by
// tools/ocr/check_vl_mrope.py.
struct Rope {
  std::vector<int32_t> pos;   // [3][seq]
  int seq = 0;

  void build(int seq_len, int gh, int gw, int text_before) {
    seq = seq_len;
    const int h = gh / 2, w = gw / 2;
    const int img = h * w;
    if (text_before + img > seq_len) die("prompt does not fit the sequence");
    pos.assign(static_cast<size_t>(3) * seq_len, 0);
    for (int t = 0; t < text_before; t++)
      for (int r = 0; r < 3; r++) pos[r * seq_len + t] = t;
    for (int i = 0; i < img; i++) {
      pos[0 * seq_len + text_before + i] = 0;
      pos[1 * seq_len + text_before + i] = (i / w) + text_before;
      pos[2 * seq_len + text_before + i] = (i % w) + text_before;
    }
    const int tail = text_before + img;
    if (tail < seq_len) {
      int start = 0;
      for (int r = 0; r < 3; r++)
        for (int t = 0; t < tail; t++)
          start = std::max(start, pos[r * seq_len + t]);
      start += 1;
      for (int t = tail; t < seq_len; t++)
        for (int r = 0; r < 3; r++) pos[r * seq_len + t] = start + (t - tail);
    }
  }
  int32_t at(int row, int t) const { return pos[row * seq + t]; }
};

struct Timings {
  double vit = 0, embed = 0, prefill = 0, lm = 0, decode = 0;
  std::vector<double> per_token;
  int kv_bytes_per_layer = 0;
  int decode_steps = 0;
};

// ---------------------------------------------------------------------------

int run(const std::string& bmodel, const std::string& work,
        const std::string& out_dir) {
  Prep p = read_prep(work);
  const int L = static_cast<int>(p.ids.size());
  const int SEQ = p.seq;
  if (L + p.max_new >= SEQ) die("prompt + max_new does not fit the sequence");
  if (p.grid_h % 2 || p.grid_w % 2) die("grid must be even for the 2x2 merge");
  const int n_img = (p.grid_h / 2) * (p.grid_w / 2);
  if (p.head_len + n_img > L) die("head_len + image tokens exceeds the prompt");
  const int patches = p.grid_h * p.grid_w;
  if (static_cast<int>(p.patches.size()) != patches * 3 * 14 * 14)
    die("patches.f32 does not match grid_h*grid_w");

  Engine eng;
  eng.open(bmodel.c_str());

  Net vit, embed, embed_cache, lm;
  vit.attach(eng, "vit");
  embed.attach(eng, "embedding");
  embed_cache.attach(eng, "embedding_cache");
  lm.attach(eng, "lm_head");
  const int n_layers = bmrt_get_network_number(eng.rt) > 0 ? 18 : 0;
  std::vector<Net> blocks(n_layers), blocks_cache(n_layers);
  for (int i = 0; i < n_layers; i++) {
    blocks[i].attach(eng, ("block_" + std::to_string(i)).c_str());
    blocks_cache[i].attach(eng, ("block_cache_" + std::to_string(i)).c_str());
  }

  Timings tm;
  const int HID = 1024, KV_ELEMS = 2 * 128;
  const size_t row_bytes = static_cast<size_t>(KV_ELEMS) * 2;      // one KV row
  const size_t cache_bytes = static_cast<size_t>(SEQ) * row_bytes; // per k or v
  tm.kv_bytes_per_layer = static_cast<int>(cache_bytes * 2);

  // ---- vit ---------------------------------------------------------------
  std::vector<bm_device_mem_t> vin, vout;
  int vit_ins = vit.info->input_num;
  size_t pix_bytes = p.patches.size() * sizeof(float);
  bm_device_mem_t pix_mem = eng.alloc(pix_bytes);
  eng.s2d(pix_mem, p.patches.data(), pix_bytes);
  vin.push_back(pix_mem);
  if (vit_ins > 1) {           // the 576-patch build takes full_attn_mask
    size_t mb = Net::bytes(vit.in_shape(1), vit.in_dt(1));
    bm_device_mem_t mask = eng.alloc(mb);
    std::vector<char> zeros(mb, 0);
    eng.s2d(mask, zeros.data(), mb);
    vin.push_back(mask);
  }
  size_t vout_bytes = Net::bytes(vit.out_shape(0), vit.out_dt(0));
  bm_device_mem_t vout_mem = eng.alloc(vout_bytes);
  vout.push_back(vout_mem);

  double t0 = now_ms();
  vit.run(eng, vin, vout, true);
  tm.vit = now_ms() - t0;

  // vit is bf16 on the way out; the splice needs floats.
  std::vector<uint16_t> emb_raw(vout_bytes / 2);
  eng.d2s(emb_raw.data(), vout_mem, vout_bytes);
  spit(out_dir + "/vit_emb.bf16", emb_raw.data(), vout_bytes);
  if (static_cast<int>(emb_raw.size()) != n_img * HID)
    die("vit output does not match the merged grid");

  // ---- embedding / prompt ------------------------------------------------
  std::vector<int32_t> ids_pad(static_cast<size_t>(SEQ), 0);
  std::copy(p.ids.begin(), p.ids.end(), ids_pad.begin());
  size_t ids_bytes = ids_pad.size() * sizeof(int32_t);
  bm_device_mem_t ids_mem = eng.alloc(ids_bytes);
  eng.s2d(ids_mem, ids_pad.data(), ids_bytes);
  size_t hidden_bytes = Net::bytes(blocks[0].in_shape(0), blocks[0].in_dt(0));
  bm_device_mem_t xa = eng.alloc(hidden_bytes), xb = eng.alloc(hidden_bytes);

  t0 = now_ms();
  embed.run(eng, {ids_mem}, {xa}, true);
  tm.embed = now_ms() - t0;

  // Splice vit rows into the placeholder rows. Done on the host because it is
  // one copy per element and it keeps the graph count at 40.
  {
    std::vector<uint16_t> hidden(hidden_bytes / 2);
    eng.d2s(hidden.data(), xa, hidden_bytes);
    for (int i = 0; i < n_img; i++)
      std::memcpy(&hidden[static_cast<size_t>(p.head_len + i) * HID],
                  &emb_raw[static_cast<size_t>(i) * HID], HID * 2);
    eng.s2d(xa, hidden.data(), hidden_bytes);
  }

  // ---- prefill -----------------------------------------------------------
  // The table must cover every position decode will ask for, not just the
  // prompt: decode reads position L, L+1, ... up to L+max_new. Building it for
  // L entries only and then indexing past the end reads heap garbage, which
  // makes every decoded position id wrong while leaving every tensor shape
  // valid -- measured as a correct first token followed by padding tokens.
  Rope rope;
  rope.build(SEQ, p.grid_h, p.grid_w, p.head_len);
  std::vector<int32_t> pos_pad(rope.pos.begin(),
                               rope.pos.begin() + static_cast<long>(3) * SEQ);
  bm_device_mem_t pos_mem = eng.alloc(pos_pad.size() * sizeof(int32_t));
  eng.s2d(pos_mem, pos_pad.data(), pos_pad.size() * sizeof(int32_t));

  // Additive mask: -9984 for every position a real row must not attend to.
  //
  // That is BOTH the causal future (c > r) and the whole padding tail
  // (c >= L). Masking only the causal part leaves columns L..SEQ-1 at zero
  // weight-penalty, and softmax then gives those positions real probability
  // mass -- their keys come from embedding(0) pushed through 18 layers, which
  // is not zero, so the prefill output is wrong by a little on every element.
  // It still "runs" and still emits tokens, which is why this is easy to miss.
  const size_t mask_elems = static_cast<size_t>(SEQ) * SEQ;
  std::vector<uint16_t> mask(mask_elems, 0);
  const uint16_t neg = f32_to_bf16(kMaskNeg);
  for (int r = 0; r < L; r++)
    for (int c = r + 1; c < SEQ; c++) mask[static_cast<size_t>(r) * SEQ + c] = neg;
  bm_device_mem_t mask_mem = eng.alloc(mask_elems * 2);
  eng.s2d(mask_mem, mask.data(), mask.size() * 2);

  // One persistent KV cache per layer, k first then v, exactly [1,SEQ,2,128].
  std::vector<bm_device_mem_t> kv(n_layers);
  for (int i = 0; i < n_layers; i++) {
    kv[i] = eng.alloc(cache_bytes * 2);
    std::vector<char> zeros(cache_bytes * 2, 0);
    eng.s2d(kv[i], zeros.data(), zeros.size());
  }

  t0 = now_ms();
  bm_device_mem_t cur = xa, nxt = xb;
  for (int i = 0; i < n_layers; i++) {
    bm_device_mem_t k_full = Engine::view(kv[i], 0, cache_bytes);
    bm_device_mem_t v_full = Engine::view(kv[i], cache_bytes, cache_bytes);
    blocks[i].run(eng, {cur, pos_mem, mask_mem}, {nxt, k_full, v_full}, true);
    std::swap(cur, nxt);
  }
  tm.prefill = now_ms() - t0;

  // ---- first token -------------------------------------------------------
  bm_device_mem_t tok_mem = eng.alloc(2 * sizeof(int32_t));
  auto lm_step = [&](bm_device_mem_t hidden_base, size_t byte_off) {
    bm_device_mem_t row = Engine::view(hidden_base, byte_off, HID * 2);
    double s = now_ms();
    lm.run(eng, {row}, {tok_mem}, true);
    tm.lm += now_ms() - s;
    int32_t tok = -1;
    eng.d2s(&tok, tok_mem, sizeof(int32_t));
    return tok;
  };
  std::vector<int32_t> out_ids;
  out_ids.push_back(lm_step(cur, static_cast<size_t>(L - 1) * HID * 2));

  // ---- decode ------------------------------------------------------------
  // The row buffers and masks are allocated once and re-pointed per step; the
  // only thing that changes per token is where inside the KV cache the graph
  // writes, which is exactly what Engine::view does.
  bm_device_mem_t dpos_mem = eng.alloc(3 * sizeof(int32_t));
  size_t dmask_elems = static_cast<size_t>(SEQ) + 1;
  bm_device_mem_t dmask_mem = eng.alloc(dmask_elems * 2);
  bm_device_mem_t dx_a = eng.alloc(static_cast<size_t>(HID) * 2);
  bm_device_mem_t dx_b = eng.alloc(static_cast<size_t>(HID) * 2);
  bm_device_mem_t did_mem = eng.alloc(sizeof(int32_t));
  bm_device_mem_t demb_mem = eng.alloc(static_cast<size_t>(HID) * 2);

  std::vector<uint16_t> dmask(dmask_elems, 0);
  int32_t pos1[3];

  double dec_t0 = now_ms();
  bm_device_mem_t dx_cur = dx_a, dx_nxt = dx_b;
  for (int step = 0; step < p.max_new - 1; step++) {
    const int32_t tok = out_ids.back();
    if (tok == p.eos_id) break;
    const int n = L + step;          // the position being written
    if (n + 1 >= SEQ) break;

    double s = now_ms();
    eng.s2d(did_mem, &tok, sizeof(tok));
    embed_cache.run(eng, {did_mem}, {demb_mem}, true);
    // Layer 0 eats the token embedding; every later layer eats the previous
    // layer's output. Using the stale dx_cur here instead (i.e. forgetting this
    // line) feeds the whole stack garbage that still has the right shape and
    // still produces tokens -- measured as a correct first token followed by
    // 23 copies of the padding token.
    bm_device_mem_t x_in = demb_mem;

    pos1[0] = rope.at(0, n);
    pos1[1] = rope.at(1, n);
    pos1[2] = rope.at(2, n);
    eng.s2d(dpos_mem, pos1, sizeof(pos1));

    // History slots n..SEQ-1 are masked; the new key (slot SEQ) is not.
    std::fill(dmask.begin(), dmask.end(), 0);
    for (int i = n; i < SEQ; i++) dmask[i] = neg;
    eng.s2d(dmask_mem, dmask.data(), dmask.size() * 2);

    for (int i = 0; i < n_layers; i++) {
      bm_device_mem_t hist_k = Engine::view(kv[i], 0, cache_bytes);
      bm_device_mem_t hist_v = Engine::view(kv[i], cache_bytes, cache_bytes);
      bm_device_mem_t new_k = Engine::view(kv[i], static_cast<size_t>(n) * row_bytes,
                                           row_bytes);
      bm_device_mem_t new_v = Engine::view(kv[i],
                                           cache_bytes + static_cast<size_t>(n) * row_bytes,
                                           row_bytes);
      blocks_cache[i].run(eng, {x_in, dpos_mem, dmask_mem, hist_k, hist_v},
                          {dx_nxt, new_k, new_v}, true);
      // Swap first, then point at the buffer that now holds this layer's
      // output: taking it before the swap hands the next layer the buffer the
      // previous layer *read*, not the one it wrote.
      std::swap(dx_cur, dx_nxt);
      x_in = dx_cur;
    }
    // The row the token was just decoded from is L+step; the next token comes
    // from the row we just produced, which lives in a standalone buffer.
    out_ids.push_back(lm_step(dx_cur, 0));
    tm.per_token.push_back(now_ms() - s);
    tm.decode_steps++;
    if (out_ids.back() == p.eos_id) break;
  }
  tm.decode = now_ms() - dec_t0;

  // ---- report ------------------------------------------------------------
  spit(out_dir + "/tokens.i32", out_ids.data(), out_ids.size() * sizeof(int32_t));
  FILE* f = std::fopen((out_dir + "/timings.txt").c_str(), "w");
  if (!f) die("cannot write timings.txt");
  std::fprintf(f, "vit_ms %.2f\nembed_ms %.2f\nprefill_ms %.2f\nlm_ms %.2f\n",
               tm.vit, tm.embed, tm.prefill, tm.lm);
  std::fprintf(f, "decode_ms %.2f\ndecode_steps %d\nn_tokens %zu\n",
               tm.decode, tm.decode_steps, out_ids.size());
  std::fprintf(f, "kv_bytes_per_layer %d\nprompt_tokens %d\nimage_tokens %d\n",
               tm.kv_bytes_per_layer, L, n_img);
  std::fprintf(f, "grid_h %d\ngrid_w %d\npatches %d\n", p.grid_h, p.grid_w, patches);
  if (!tm.per_token.empty()) {
    std::vector<double> v = tm.per_token;
    std::sort(v.begin(), v.end());
    std::fprintf(f, "decode_per_token_median_ms %.2f\n", v[v.size() / 2]);
    std::fprintf(f, "decode_per_token_min_ms %.2f\n", v.front());
    std::fprintf(f, "decode_per_token_max_ms %.2f\n", v.back());
  }
  std::fprintf(f, "tokens");
  for (int32_t t : out_ids) std::fprintf(f, " %d", t);
  std::fprintf(f, "\n");
  std::fclose(f);

  std::fprintf(stderr,
               "vit %.1f ms | embed %.1f ms | prefill %.1f ms | decode %.1f ms "
               "(%d steps, median %.1f ms) | %zu tokens\n",
               tm.vit, tm.embed, tm.prefill, tm.decode, tm.decode_steps,
               tm.per_token.empty() ? 0.0
                                    : *std::min_element(tm.per_token.begin(),
                                                        tm.per_token.end()),
               out_ids.size());
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  std::string bmodel, work, out;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() -> std::string {
      if (i + 1 >= argc) die("missing value");
      return argv[++i];
    };
    if (a == "--bmodel") bmodel = next();
    else if (a == "--work") work = next();
    else if (a == "--out") out = next();
    else {
      std::fprintf(stderr,
                   "usage: vl_native --bmodel X.bmodel --work DIR --out DIR\n");
      return 1;
    }
  }
  if (bmodel.empty() || work.empty() || out.empty()) {
    std::fprintf(stderr, "usage: vl_native --bmodel X.bmodel --work DIR --out DIR\n");
    return 1;
  }
  return run(bmodel, work, out);
}
