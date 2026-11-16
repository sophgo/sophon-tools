// A stand-in for libbmrt/libbmlib, so the engine's launch discipline can be
// tested on a plain x86 host with no NPU and no libsophon install.
//
// It implements exactly the C API the engine calls, plus enough of the graph
// metadata to make Engine::load() and Session::decode() run: a tiny one-layer
// linear + FA hybrid model whose "graphs" keep a counter instead of computing.
// Everything a real device would do that the tests care about is observed:
//
//   * launches are queued, not executed, until sync (the real
//     bmrt_launch_tensor_ex does not block -- bmruntime_interface.h:476);
//   * launching while another launch is still queued is recorded as
//     `overlap_launches`, so "the layers were submitted back to back" is a
//     measurement rather than an assumption;
//   * every launch is logged with the address its output was written to;
//   * d2d copies are counted per (src, dst) pair, which is how the
//     "conv_state copied onto itself" regression is caught;
//   * output_mems may be made to alias input_mems, mimicking addr_mode=1.
//
// Test control knobs are plain globals under fake_bm::.
#pragma once

#include "bmruntime_interface.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace fake_bm {

// ---- observation -----------------------------------------------------------
struct Launch {
  std::string net;
  std::vector<unsigned long long> out_addrs;
  int32_t first_input = 0;
  // Every int32 input's first element, by input index. Needed for the graphs
  // whose token id is not input 0 (block_kv_ carries it in input 1) and for
  // telling an embedding launch apart from a decode one.
  std::vector<int32_t> int_inputs;
  // Each input's shape dims, as the engine presented it. The past-KV length of
  // a block_kv launch and the row count of a block_ launch are what a
  // restore-then-extend has to get right, and neither is visible otherwise.
  std::vector<std::vector<int>> in_dims;
  // Each output's device address, so a test can tell which KV slot a decode
  // wrote by comparing against the session buffer's base address.
  std::vector<unsigned long long> out_sizes;
};
inline std::vector<Launch> launches;
// Number of launches issued at the moment of each sync. Consecutive entries
// bound the stretches the engine submitted without waiting.
inline std::vector<size_t> sync_points;
inline int syncs = 0;
inline int overlap_launches = 0;   // launch issued while a previous one was in flight
inline int pending = 0;            // launches queued but not synced
// Launches handed a token id outside the vocabulary. A real embedding graph
// would gather out of bounds there: the driver cannot reject it as a bad
// argument, so it reads garbage or faults the TPU. The fake only records it;
// the engine is expected to reject such a prompt before it ever gets here.
inline int out_of_range_id_launches = 0;
inline bool fail_launch = false;   // next launch returns false
inline bool fail_sync = false;     // next sync returns an error
inline std::map<std::pair<unsigned long long, unsigned long long>, int> d2d_counts;
inline unsigned long long next_addr = 0x10000000;
// Throw out of bmrt_destroy, mimicking libbmrt on this chip.
//
// ``ComputeMemory::Destroy`` shrinks the process-wide compute pool when the net
// being destroyed was the largest one left, and that shrink is a free followed
// by a fresh malloc. On the 84x6 board the malloc fails and ``BMRT_ASSERT``
// throws a std::runtime_error -- out of a destructor, which is why the worker
// died with "terminate called after throwing an instance of
// 'std::runtime_error'" on every OCR unload. This knob is how a host test can
// assert the engine survives that: a destructor must not let it escape.
inline bool bmrt_destroy_throws = false;
// Counted so a test can tell "destroy was skipped" from "destroy was called and
// its throw was absorbed".
inline int bmrt_destroys = 0;
// When set, a launch writes out[i] = in[i % in_elems] * 2 (halves converted on
// both sides) instead of the usual opaque token value. That is what lets a test
// prove the *input* arrived intact and the *output* came back through the
// dtype conversion -- the two things a generic runner exists to get right, and
// the two a value-of-the-address fake cannot show.
inline bool single_graph_echo = false;
// Vocabulary size the fake embedding table implies, so the fixture can tell an
// out-of-range id. 0 disables the observation.
inline int vocab = 0;
// Every bm_memset_device_ext, by the address it cleared and how many bytes.
// The FA per-session reset is 123 ms of memset on the board and leaves no other
// trace -- no launch, no copy -- so this is the only way a host test can tell
// whether a fresh prefill still pays it. A fresh prefill must clear the linear
// state and nothing else; a restore must still clear the FA K/V buffers.
struct Memset {
  unsigned long long addr;
  unsigned int size;
};
inline std::vector<Memset> memsets;

inline int memsets_of(unsigned long long addr) {
  int n = 0;
  for (const auto& m : memsets) n += (m.addr == addr);
  return n;
}
// Bytes cleared at exactly this address (0 if never).
inline unsigned int memset_bytes_of(unsigned long long addr) {
  for (const auto& m : memsets)
    if (m.addr == addr) return m.size;
  return 0;
}

// One flat host allocation standing in for device memory, so the engine's
// memcpys are real (a self-copy is a no-op we can still count) and the fake
// graphs can write plausible values the engine then reads back.
inline constexpr size_t kHeapBytes = 256u << 20;
inline unsigned char* heap_base = nullptr;

inline void reset() {
  launches.clear();
  sync_points.clear();
  syncs = 0;
  overlap_launches = 0;
  pending = 0;
  out_of_range_id_launches = 0;
  fail_launch = false;
  fail_sync = false;
  bmrt_destroy_throws = false;
  bmrt_destroys = 0;
  d2d_counts.clear();
  memsets.clear();
  next_addr = 0x10000000;
  single_graph_echo = false;
  if (!heap_base) heap_base = static_cast<unsigned char*>(std::calloc(1, kHeapBytes));
}

inline void* host_ptr(unsigned long long addr) {
  if (!heap_base || addr < 0x10000000) return nullptr;
  const size_t off = static_cast<size_t>(addr - 0x10000000);
  return off < kHeapBytes ? heap_base + off : nullptr;
}

// Read one byte of "device" memory, so a test can assert on what a state buffer
// actually holds (e.g. that restore left no stale KV from a longer session
// behind). -1 when the address is outside the fake heap.
inline int read_byte(unsigned long long addr) {
  const auto* p = static_cast<const unsigned char*>(host_ptr(addr));
  return p ? *p : -1;
}

// Write one byte of "device" memory, so a test can plant a marker the engine
// must either preserve (park/unpark) or clear (restore).
inline void write_byte(unsigned long long addr, int v) {
  auto* p = static_cast<unsigned char*>(host_ptr(addr));
  if (p) *p = static_cast<unsigned char>(v);
}

// True when [addr, addr+len) reads back as `v` everywhere.
inline bool bytes_are(unsigned long long addr, size_t len, int v) {
  for (size_t i = 0; i < len; i++)
    if (read_byte(addr + i) != v) return false;
  return true;
}

inline unsigned long long alloc_addr(unsigned int size) {
  const unsigned long long a = next_addr;
  next_addr += (size + 0xFFF) & ~0xFFFULL;
  return a;
}

// How many launches of `net` happened at all.
inline int launches_of(const std::string& net) {
  int n = 0;
  for (const auto& l : launches) n += (l.net == net);
  return n;
}

// Longest run of launches with no sync in between -- i.e. how deep the engine
// submitted before it established a boundary. A launch still outstanding at
// the end counts: that would mean the engine returned with work in flight,
// which reads as a huge run and fails the depth assertions loudly.
inline int longest_unsynced_run() {
  int best = 0;
  size_t prev = 0;
  for (size_t p : sync_points) {
    best = std::max(best, static_cast<int>(p - prev));
    prev = p;
  }
  best = std::max(best, static_cast<int>(launches.size() - prev));
  return best;
}

// Did anything ever copy `src` onto `dst` at the same address (a self-copy)?
inline bool copied_onto_itself() {
  for (const auto& kv : d2d_counts)
    if (kv.first.first == kv.first.second && kv.second > 0) return true;
  return false;
}

// ---- fake graph metadata ---------------------------------------------------
struct FakeNet {
  std::string name;
  std::vector<bm_device_mem_t> in, out;
  std::vector<bm_shape_t> in_shape, out_shape;
  std::vector<bm_data_type_t> in_dt, out_dt;
  bm_stage_info_t stage{};
  bm_net_info_t info{};
};

inline std::vector<FakeNet*> nets;

inline bm_device_mem_t mem(unsigned long long addr, unsigned int size) {
  bm_device_mem_t m{};
  m.u.device.device_addr = addr;
  m.size = size;
  return m;
}

inline bm_shape_t shape2(int a, int b) {
  bm_shape_t s{};
  s.num_dims = 2;
  s.dims[0] = a;
  s.dims[1] = b;
  return s;
}
inline bm_shape_t shape3(int a, int b, int c) {
  bm_shape_t s{};
  s.num_dims = 3;
  s.dims[0] = a;
  s.dims[1] = b;
  s.dims[2] = c;
  return s;
}
inline bm_shape_t shape4(int a, int b, int c, int d) {
  bm_shape_t s{};
  s.num_dims = 4;
  s.dims[0] = a;
  s.dims[1] = b;
  s.dims[2] = c;
  s.dims[3] = d;
  return s;
}

// Element count of a shape, as the engine computes it.
inline long long elements_of(const bm_shape_t& s) {
  long long n = 1;
  for (int i = 0; i < s.num_dims; i++) n *= s.dims[i];
  return n;
}

// Bytes of one linear-attention state tensor. The engine copies these whole
// with std::min(state, graph buffer), so the fixture must size them like a
// real bmodel's (a few KiB) and never 0 -- a 0-byte device_mem would make the
// copy a no-op the tests could not tell from a missing one.
inline constexpr unsigned int kStateBytes = 64;

// Build the fake model. Layout mirrors a Qwen3.5 bmodel: embedding +
// embedding_cache + lm_head (argmax fused, [1,1] output) + 4 block_<i> and
// 4 block_cache_<i>, layer 3 being the FA one (kFaInterval).
//
// `linear_inplace` controls the property under test: true makes a linear
// decode graph's output_mems[1] be input_mems[1] (addr_mode=1, as every
// shipped bmodel does), false gives it a separate buffer.
//
// `prefill_mask` mirrors whether the FA prefill graph takes its own attention
// mask as a third input. The shipped 35B history bmodels do NOT (the mask is
// internal), and that matters: the engine refuses to extend a session on a
// masked prefill graph, because a fresh causal mask is only correct when no KV
// exists yet. Default false = the shipped layout, so the extend path is
// reachable; the masked variant is built explicitly where it is under test.
inline void build(const std::string& hidden_name, bool linear_inplace,
                  int hidden = 16, int seq = 256, bool prefill_mask = false) {
  // The name is kept for the fixture's readability (`build("qwen", ...)`); no
  // graph reads it, since every graph's own name is set below.
  (void)hidden_name;
  reset();
  for (auto* n : nets) delete n;
  nets.clear();
  const int H = hidden;

  auto add = [&](const std::string& name) -> FakeNet* {
    auto* n = new FakeNet();
    n->name = name;
    nets.push_back(n);
    return n;
  };

  // embedding: [1, max_input] ids -> [1, max_input, H] bf16
  {
    auto* n = add("embedding");
    n->in.push_back(mem(alloc_addr(4 * 512), 4 * 512));
    n->out.push_back(mem(alloc_addr(2 * 512 * H), 2 * 512 * H));
    n->in_shape = {shape2(1, 512)};
    n->out_shape = {shape3(1, 512, H)};
    n->in_dt = {BM_INT32};
    n->out_dt = {BM_BFLOAT16};
    n->info.is_dynamic = true;
  }
  // embedding_cache: [1,1] -> [1,1,H]
  {
    auto* n = add("embedding_cache");
    n->in.push_back(mem(alloc_addr(8), 8));
    n->out.push_back(mem(alloc_addr(2 * H), 2 * H));
    n->in_shape = {shape2(1, 1)};
    n->out_shape = {shape3(1, 1, H)};
    n->in_dt = {BM_INT32};
    n->out_dt = {BM_BFLOAT16};
  }
  // lm_head: [1,H] -> [1,1] int32 (topk fused)
  {
    auto* n = add("lm_head");
    n->in.push_back(mem(alloc_addr(2 * H), 2 * H));
    n->out.push_back(mem(alloc_addr(8), 8));
    n->in_shape = {shape2(1, H)};
    n->out_shape = {shape2(1, 1)};
    n->in_dt = {BM_BFLOAT16};
    n->out_dt = {BM_INT32};
  }
  // 4 prefill blocks; layer 3 = FA (input: hidden, pos, mask).
  //
  // The linear ones carry the session's recurrent/conv state, exactly as a
  // shipped bmodel does, because the engine's prefill path reads and writes
  // them: a history bmodel's block_<i> takes (hidden, rec_state, conv_state)
  // and returns (hidden, conv_state); rec_state is updated in place at input
  // 1. Leaving them out (1 input, 1 output) is what previously hid the whole
  // extend path from these tests.
  for (int i = 0; i < 4; i++) {
    auto* n = add("block_" + std::to_string(i));
    n->in.push_back(mem(alloc_addr(2 * 512 * H), 2 * 512 * H));
    n->out.push_back(mem(alloc_addr(2 * 512 * H), 2 * 512 * H));
    n->in_shape = {shape3(1, 512, H)};
    n->out_shape = {shape3(1, 512, H)};
    n->in_dt = {BM_BFLOAT16};
    n->out_dt = {BM_BFLOAT16};
    if (i == 3) {
      n->in.push_back(mem(alloc_addr(4 * 4 * 512), 4 * 4 * 512));
      n->in_shape.push_back(shape2(3, 512));
      n->in_dt = {BM_BFLOAT16, BM_INT32};
      if (prefill_mask) {
        n->in.push_back(mem(alloc_addr(2 * 512 * 512), 2 * 512 * 512));
        n->in_shape.push_back(shape4(1, 1, 512, 512));
        n->in_dt.push_back(BM_BFLOAT16);
      }
      n->out.push_back(mem(alloc_addr(2 * 512), 2 * 512));
      n->out.push_back(mem(alloc_addr(2 * 512), 2 * 512));
      n->out_shape.push_back(shape2(1, 512));
      n->out_shape.push_back(shape2(1, 512));
      n->out_dt = {BM_BFLOAT16, BM_BFLOAT16, BM_BFLOAT16};
    } else {
      // rec_state (input 1, updated in place) and conv_state (input 2).
      const unsigned long long rec = alloc_addr(kStateBytes);
      const unsigned long long conv = alloc_addr(kStateBytes);
      n->in.push_back(mem(rec, kStateBytes));
      n->in.push_back(mem(conv, kStateBytes));
      n->in_shape.push_back(shape3(1, 4, 4));
      n->in_shape.push_back(shape3(1, 4, 4));
      n->in_dt = {BM_BFLOAT16, BM_BFLOAT16, BM_BFLOAT16};
      n->out.push_back(mem(conv, kStateBytes));  // conv_state out, own buffer
      n->out_shape.push_back(shape3(1, 4, 4));
      n->out_dt = {BM_BFLOAT16, BM_BFLOAT16};
    }
    n->info.is_dynamic = true;
  }
  // 4 decode blocks; layer 3 = FA. Linear: (hidden, conv, rec) -> (hidden [,conv'])
  const int kv_tok = 2 * H;  // 2 bytes * H
  for (int i = 0; i < 4; i++) {
    auto* n = add("block_cache_" + std::to_string(i));
    const unsigned long long hid_in = alloc_addr(2 * H);
    n->in.push_back(mem(hid_in, 2 * H));
    n->in_shape = {shape3(1, 1, H)};
    n->in_dt = {BM_BFLOAT16};
    if (i == 3) {
      n->in.push_back(mem(alloc_addr(12), 12));
      n->in.push_back(mem(alloc_addr(2 * (seq + 1)), 2 * (seq + 1)));
      n->in.push_back(mem(alloc_addr(kv_tok * seq), kv_tok * seq));
      n->in.push_back(mem(alloc_addr(kv_tok * seq), kv_tok * seq));
      n->in_shape.push_back(shape3(3, 1, 1));
      n->in_shape.push_back(shape4(1, 1, 1, seq + 1));
      n->in_shape.push_back(shape4(1, seq, 4, kv_tok / 4 / 2));
      n->in_shape.push_back(shape4(1, seq, 4, kv_tok / 4 / 2));
      n->in_dt = {BM_BFLOAT16, BM_INT32, BM_BFLOAT16, BM_BFLOAT16, BM_BFLOAT16};
      // hidden output aliases the hidden input, as addr_mode=1 does
      n->out.push_back(mem(hid_in, 2 * H));
      n->out.push_back(mem(alloc_addr(kv_tok), kv_tok));
      n->out.push_back(mem(alloc_addr(kv_tok), kv_tok));
      n->out_shape = {shape3(1, 1, H), shape4(1, 1, 4, kv_tok / 4 / 2),
                      shape4(1, 1, 4, kv_tok / 4 / 2)};
      n->out_dt = {BM_BFLOAT16, BM_BFLOAT16, BM_BFLOAT16};
    } else {
      const unsigned long long conv = alloc_addr(64);
      n->in.push_back(mem(conv, 64));
      n->in.push_back(mem(alloc_addr(2 * H * H), 2 * H * H));
      n->in_shape.push_back(shape3(1, 4, 4));
      n->in_shape.push_back(shape4(1, 1, H, H));
      n->in_dt = {BM_BFLOAT16, BM_BFLOAT16, BM_BFLOAT16};
      n->out.push_back(mem(hid_in, 2 * H));
      // addr_mode=1: conv_state comes back at its input buffer
      n->out.push_back(mem(conv, 64));
      n->out_shape = {shape3(1, 1, H), shape3(1, 4, 4)};
      n->out_dt = {BM_BFLOAT16, BM_BFLOAT16};
      if (!linear_inplace) {
        n->out[1] = mem(alloc_addr(64), 64);  // separate output buffer
      }
    }
    // addr_mode=1 for shipped bmodels
    n->info.addr_mode = 1;
  }
  // history bmodel: block_kv_<i> for the FA layer
  {
    auto* n = add("block_kv_3");
    n->in.push_back(mem(alloc_addr(2 * 512 * H), 2 * 512 * H));
    n->in.push_back(mem(alloc_addr(4 * 4 * 512), 4 * 4 * 512));
    n->in.push_back(mem(alloc_addr(kv_tok * seq), kv_tok * seq));
    n->in.push_back(mem(alloc_addr(kv_tok * seq), kv_tok * seq));
    n->in_shape = {shape3(1, 512, H), shape2(3, 512),
                   shape4(1, seq, 4, kv_tok / 4 / 2),
                   shape4(1, seq, 4, kv_tok / 4 / 2)};
    n->in_dt = {BM_BFLOAT16, BM_INT32, BM_BFLOAT16, BM_BFLOAT16};
    n->out.push_back(mem(alloc_addr(2 * 512 * H), 2 * 512 * H));
    n->out.push_back(mem(alloc_addr(kv_tok * 512), kv_tok * 512));
    n->out.push_back(mem(alloc_addr(kv_tok * 512), kv_tok * 512));
    n->out_shape = {shape3(1, 512, H), shape4(1, 512, 4, kv_tok / 4 / 2),
                    shape4(1, 512, 4, kv_tok / 4 / 2)};
    n->out_dt = {BM_BFLOAT16, BM_BFLOAT16, BM_BFLOAT16};
    n->info.is_dynamic = true;
  }

  for (auto* n : nets) {
    n->stage.input_mems = n->in.data();
    n->stage.output_mems = n->out.data();
    n->stage.input_shapes = n->in_shape.data();
    n->stage.output_shapes = n->out_shape.data();
    n->info.name = n->name.c_str();
    n->info.input_num = static_cast<int>(n->in.size());
    n->info.output_num = static_cast<int>(n->out.size());
    n->info.input_dtypes = n->in_dt.data();
    n->info.output_dtypes = n->out_dt.data();
    n->info.stage_num = 1;
    n->info.stages = &n->stage;
  }
}

// Build a fake model with exactly one graph, the shape an OCR det/rec build
// has: NCHW float32 in, one float32 output. `out_shape` is given as a vector so
// a test can model det ([1,1,H,W]) and rec ([1,T,C]) with the same helper.
//
// A second knob makes the graph's *internal* dtype differ from the f32 interface
// -- an f16 bmodel with an f32 input, which is what the shipped OCR builds are
// once tpu-mlir has folded the cast. The engine is expected to convert, so the
// fake stores the input as halves and writes halves back.
//: ``addr_mode`` the next build_single_graph records. Set it to ADDR_MODE_IO_TAG
//: (2) to reproduce what tpu-mlir emits for a plain single graph: the graph's
//: own input_mems/output_mems are then **synthetic** addresses that no copy can
//: reach, and an engine that uses them fails with "copying input 0 to the device
//: failed" on a perfectly good bmodel. That is not a hypothetical -- it is what
//: the first board run of the generic runner hit -- so the fake has to be able
//: to present it, with the placeholder addresses set well outside the heap and a
//: copy to them rejected exactly as bmlib rejects them.
inline void build_single_graph(const std::string& name,
                               const std::vector<int>& in_shape,
                               const std::vector<int>& out_shape,
                               bool fp16_io = false,
                               int addr_mode = 0) {
  reset();
  for (auto* n : nets) delete n;
  nets.clear();

  auto* n = new FakeNet();
  n->name = name;
  nets.push_back(n);

  long long in_elems = 1;
  for (int d : in_shape) in_elems *= d;
  long long out_elems = 1;
  for (int d : out_shape) out_elems *= d;
  const int elem_bytes = fp16_io ? 2 : 4;
  const unsigned int in_bytes = static_cast<unsigned int>(in_elems * 4);  // host f32
  const unsigned int out_bytes = static_cast<unsigned int>(out_elems * elem_bytes);

  if (addr_mode == ADDR_MODE_IO_TAG || addr_mode == ADDR_MODE_IO_TAG_FUSE) {
    // Synthetic tag addresses, as the real runtime reports them (0x4.../0x5...).
    // Far outside the fake heap, so any copy into them is rejected.
    n->in.push_back(mem(0x40000000000ULL, in_bytes));
    n->out.push_back(mem(0x50000000000ULL, out_bytes));
  } else {
    n->in.push_back(mem(alloc_addr(in_bytes), in_bytes));
    n->out.push_back(mem(alloc_addr(out_bytes), out_bytes));
  }

  auto to_shape = [](const std::vector<int>& dims) {
    bm_shape_t s{};
    s.num_dims = static_cast<int>(dims.size());
    for (size_t i = 0; i < dims.size(); i++) s.dims[i] = dims[i];
    return s;
  };
  n->in_shape = {to_shape(in_shape)};
  n->out_shape = {to_shape(out_shape)};
  // Both tensors carry the graph's own width. The engine's contract is that the
  // *caller* always speaks float32, so with fp16_io it has to convert on the way
  // in as well as on the way out -- which is exactly the path under test.
  n->in_dt = {fp16_io ? BM_FLOAT16 : BM_FLOAT32};
  n->out_dt = {fp16_io ? BM_FLOAT16 : BM_FLOAT32};

  n->stage.input_mems = n->in.data();
  n->stage.output_mems = n->out.data();
  n->stage.input_shapes = n->in_shape.data();
  n->stage.output_shapes = n->out_shape.data();
  n->info.name = n->name.c_str();
  n->info.input_num = 1;
  n->info.output_num = 1;
  n->info.input_dtypes = n->in_dt.data();
  n->info.output_dtypes = n->out_dt.data();
  n->info.stage_num = 1;
  n->info.stages = &n->stage;
  n->info.addr_mode = addr_mode;
}

}  // namespace fake_bm
