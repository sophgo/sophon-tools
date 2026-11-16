// PaddleOCR-VL-1.5 on the NPU: one resident bmodel, one session at a time.
// See native/include/vl_engine.h for the contract and for why the KV scheme is
// "the graph writes into caller memory".

#include "vl_engine.h"

#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace cv84x6 {

namespace {

constexpr int kNpuHeapMask = 3;
// A3 measured this: a decode row whose key is masked to -9984 still gets ~0
// attention weight after softmax, while -inf produces NaN when a whole row is
// masked (which happens for padding positions).
constexpr float kMaskNeg = -9984.0f;
constexpr int kHidden = 1024;
constexpr int kKvElems = 2 * 128;   // num_key_value_heads * head_dim
constexpr int kPatch = 14;
constexpr int kMerge = 2;

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

}  // namespace

// ---------------------------------------------------------------------------
// One graph. Tensors are rebuilt per launch rather than cached, because the
// caller re-points inputs and outputs at different offsets inside shared
// buffers on every decode step; bm_tensor_t is 56 bytes, so this costs nothing.
struct VlNet {
  const bm_net_info_t* info = nullptr;
  std::string name;

  bool attach(void* rt, const char* net_name, std::string* err) {
    name = net_name;
    info = bmrt_get_network_info(rt, net_name);
    if (!info) {
      *err = "no network " + name;
      return false;
    }
    if (info->stage_num != 1) {
      *err = name + " has " + std::to_string(info->stage_num) + " stages, want 1";
      return false;
    }
    return true;
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
};

// ---------------------------------------------------------------------------
// Position ids for the 3-row (t,h,w) rotary table. Image rows are (0,h,w) on
// the 2x2-merged grid; text rows are plain sequential and coincide across all
// three. Transcribed from the reference's get_rope_index and pinned by
// tools/ocr/check_vl_mrope.py.
struct VlRope {
  std::vector<int32_t> pos;   // [3][seq]
  int seq = 0;

  bool build(int seq_len, int gh, int gw, int text_before, std::string* err) {
    seq = seq_len;
    const int h = gh / 2, w = gw / 2;
    const int img = h * w;
    if (text_before + img > seq_len) {
      *err = "prompt does not fit the sequence";
      return false;
    }
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
    return true;
  }
  int32_t at(int row, int t) const { return pos[row * seq + t]; }
};

// ---------------------------------------------------------------------------
struct VlEngine::Impl {
  bm_handle_t handle = nullptr;
  void* rt = nullptr;
  std::string last_error;
  std::vector<bm_device_mem_t> owned;

  VlNet vit, embed, embed_cache, lm;
  std::vector<VlNet> blocks, blocks_cache;

  int seq = 0;
  int layers = 0;
  int grid_h = 0, grid_w = 0;
  int n_img = 0;         // merged image rows
  int patches = 0;
  int prompt_len = 0;

  // Persistent buffers: allocated once at load and reused by every request.
  size_t row_bytes = 0;     // one KV row (k or v)
  size_t cache_bytes = 0;   // one k (or v) plane for the whole sequence
  std::vector<bm_device_mem_t> kv;

  bm_device_mem_t pix_mem;      // vit input
  bm_device_mem_t vout_mem;     // vit output (bf16 rows)
  bm_device_mem_t ids_mem;      // embedding input [1,SEQ]
  bm_device_mem_t xa, xb;       // prefill hidden double buffer
  bm_device_mem_t pos_mem;      // [3,SEQ] int32
  bm_device_mem_t mask_mem;     // [SEQ,SEQ] bf16
  bm_device_mem_t tok_mem;      // lm_head output
  bm_device_mem_t dpos_mem;     // [3,1] int32
  bm_device_mem_t dmask_mem;    // [SEQ+1] bf16
  bm_device_mem_t dx_a, dx_b;   // decode hidden double buffer
  bm_device_mem_t did_mem;      // embedding_cache input
  bm_device_mem_t demb_mem;     // embedding_cache output

  // Where the decode loop is.
  VlRope rope;                  // position table for the whole sequence
  bm_device_mem_t cur;          // prefill output holding the last prompt row
  bm_device_mem_t dx_cur, dx_nxt;
  bool has_pending = false;     // lm_head produced a token step() has not returned
  int32_t pending = -1;
  int32_t last_sampled = -1;    // the last token handed out; decoded next
  int step_pos = 0;             // position the next decode writes
  VlTimings tm{};

  ~Impl() {
    for (auto& m : owned) {
      if (handle) bm_free_device(handle, m);
    }
    if (rt) bmrt_destroy(rt);
    if (handle) bm_dev_free(handle);
  }

  bool alloc(size_t bytes, bm_device_mem_t* out) {
    if (bm_malloc_device_byte_heap_mask(handle, out, kNpuHeapMask,
                                        static_cast<unsigned int>(bytes)) != BM_SUCCESS) {
      last_error = "NPU heap exhausted at " + std::to_string(bytes) + " bytes";
      return false;
    }
    owned.push_back(*out);
    return true;
  }

  // The one primitive the whole KV scheme needs: a descriptor pointing N bytes
  // into an existing buffer. sail spells this Tensor(mem, shape, offset).
  static bm_device_mem_t view(const bm_device_mem_t& base, size_t byte_off,
                              size_t bytes) {
    return bm_mem_from_device(bm_mem_get_device_addr(base) + byte_off,
                              static_cast<unsigned int>(bytes));
  }

  bool s2d(const bm_device_mem_t& dst, const void* src, size_t bytes) {
    bm_device_mem_t sized = view(dst, 0, bytes);
    if (bm_memcpy_s2d(handle, sized, const_cast<void*>(src)) != BM_SUCCESS) {
      last_error = "bm_memcpy_s2d failed";
      return false;
    }
    return true;
  }
  // Read exactly `bytes`, never the descriptor's size -- that is the A3 bug.
  bool d2s(void* dst, const bm_device_mem_t& src, size_t bytes) {
    bm_device_mem_t sized = view(src, 0, bytes);
    if (bm_memcpy_d2s(handle, dst, sized) != BM_SUCCESS) {
      last_error = "bm_memcpy_d2s failed";
      return false;
    }
    return true;
  }
  bool sync() {
    if (bm_thread_sync(handle) != BM_SUCCESS) {
      last_error = "bm_thread_sync failed";
      return false;
    }
    return true;
  }

  bool run(const VlNet& net, const std::vector<bm_device_mem_t>& ins,
           const std::vector<bm_device_mem_t>& outs) {
    if (static_cast<int>(ins.size()) != net.info->input_num ||
        static_cast<int>(outs.size()) != net.info->output_num) {
      last_error = net.name + " arity mismatch";
      return false;
    }
    std::vector<bm_tensor_t> tin(ins.size()), tout(outs.size());
    for (size_t i = 0; i < ins.size(); i++)
      tin[i] = VlNet::tensor(ins[i], net.in_dt(static_cast<int>(i)),
                             net.in_shape(static_cast<int>(i)));
    for (size_t i = 0; i < outs.size(); i++)
      tout[i] = VlNet::tensor(outs[i], net.out_dt(static_cast<int>(i)),
                              net.out_shape(static_cast<int>(i)));
    if (!bmrt_launch_tensor_ex(rt, net.name.c_str(), tin.data(),
                               static_cast<int>(tin.size()), tout.data(),
                               static_cast<int>(tout.size()), true, true)) {
      last_error = "launch failed: " + net.name;
      return false;
    }
    return sync();
  }

  // Hidden state of the row the next token comes from -> one token id.
  bool lm_head_at(const bm_device_mem_t& hidden_base, size_t byte_off,
                  int32_t* tok) {
    bm_device_mem_t row = view(hidden_base, byte_off, kHidden * 2);
    const double s = now_ms();
    if (!run(lm, {row}, {tok_mem})) return false;
    tm.lm_ms += now_ms() - s;
    return d2s(tok, tok_mem, sizeof(int32_t));
  }
};

// ---------------------------------------------------------------------------
VlEngine::VlEngine() : impl_(new Impl()) {}
VlEngine::~VlEngine() = default;

std::string VlEngine::last_error() const { return impl_->last_error; }
int VlEngine::seq_len() const { return impl_->seq; }
int VlEngine::num_layers() const { return impl_->layers; }
int VlEngine::hidden_size() const { return kHidden; }
int VlEngine::image_tokens() const { return impl_->n_img; }
int VlEngine::vit_patches() const { return impl_->patches; }
size_t VlEngine::kv_bytes_per_layer() const { return impl_->cache_bytes * 2; }
VlTimings VlEngine::timings() const { return impl_->tm; }

bool VlEngine::load(const std::string& bmodel_path, int dev_id) {
  Impl& e = *impl_;
  if (bm_dev_request(&e.handle, dev_id) != BM_SUCCESS || !e.handle) {
    e.last_error = "bm_dev_request failed";
    return false;
  }
  e.rt = bmrt_create(e.handle);
  if (!e.rt || !bmrt_load_bmodel(e.rt, bmodel_path.c_str())) {
    e.last_error = "bmrt_load_bmodel failed: " + bmodel_path;
    return false;
  }

  auto attach = [&](VlNet* net, const char* name) {
    return net->attach(e.rt, name, &e.last_error);
  };
  if (!attach(&e.vit, "vit")) return false;
  if (!attach(&e.embed, "embedding")) return false;
  if (!attach(&e.embed_cache, "embedding_cache")) return false;
  if (!attach(&e.lm, "lm_head")) return false;

  // The layer count comes from the graphs, never from a constant: a bmodel
  // built with a different depth must announce it rather than be indexed past.
  e.layers = 0;
  while (bmrt_get_network_info(e.rt, ("block_" + std::to_string(e.layers)).c_str())) {
    ++e.layers;
  }
  if (e.layers == 0) {
    e.last_error = "no block_0 network";
    return false;
  }
  e.blocks.resize(e.layers);
  e.blocks_cache.resize(e.layers);
  for (int i = 0; i < e.layers; ++i) {
    if (!attach(&e.blocks[i], ("block_" + std::to_string(i)).c_str())) return false;
    if (!attach(&e.blocks_cache[i], ("block_cache_" + std::to_string(i)).c_str()))
      return false;
  }

  // Shapes that the rest of this file assumes, checked against the graphs so a
  // mismatched bmodel fails at load instead of producing wrong tokens.
  const bm_shape_t emb_in = e.embed.in_shape(0);
  if (emb_in.num_dims != 2 || emb_in.dims[1] != 2048) {
    e.last_error = "embedding input is not [1,2048]";
    return false;
  }
  e.seq = emb_in.dims[1];
  const bm_shape_t hist = e.blocks_cache[0].in_shape(3);
  if (hist.num_dims != 4 || hist.dims[1] != e.seq || hist.dims[2] * hist.dims[3] != kKvElems) {
    e.last_error = "history_k is not [1,SEQ,2,128]";
    return false;
  }

  // The vit grid: the graph's patch count divided by the merged grid can be
  // many rectangles, so the grid has to come from the caller (see prefill()).
  // Only the patch count is known here.
  e.patches = static_cast<int>(e.vit.in_shape(0).dims[0]);

  e.row_bytes = static_cast<size_t>(kKvElems) * 2;
  e.cache_bytes = static_cast<size_t>(e.seq) * e.row_bytes;

  // Everything below is allocated once, for the life of the worker.
  const size_t pix_bytes = static_cast<size_t>(e.patches) * 3 * kPatch * kPatch * 4;
  const size_t vout_bytes = VlNet::bytes(e.vit.out_shape(0), e.vit.out_dt(0));
  const size_t hidden_bytes = static_cast<size_t>(e.seq) * kHidden * 2;
  const size_t mask_elems = static_cast<size_t>(e.seq) * e.seq;
  const size_t dmask_elems = static_cast<size_t>(e.seq) + 1;

  if (!e.alloc(pix_bytes, &e.pix_mem)) return false;
  if (!e.alloc(vout_bytes, &e.vout_mem)) return false;
  if (!e.alloc(hidden_bytes, &e.ids_mem)) return false;   // same shape as a hidden
  if (!e.alloc(hidden_bytes, &e.xa)) return false;
  if (!e.alloc(hidden_bytes, &e.xb)) return false;
  if (!e.alloc(static_cast<size_t>(3) * e.seq * sizeof(int32_t), &e.pos_mem)) return false;
  if (!e.alloc(mask_elems * 2, &e.mask_mem)) return false;
  if (!e.alloc(2 * sizeof(int32_t), &e.tok_mem)) return false;
  if (!e.alloc(3 * sizeof(int32_t), &e.dpos_mem)) return false;
  if (!e.alloc(dmask_elems * 2, &e.dmask_mem)) return false;
  if (!e.alloc(static_cast<size_t>(kHidden) * 2, &e.dx_a)) return false;
  if (!e.alloc(static_cast<size_t>(kHidden) * 2, &e.dx_b)) return false;
  if (!e.alloc(sizeof(int32_t), &e.did_mem)) return false;
  if (!e.alloc(static_cast<size_t>(kHidden) * 2, &e.demb_mem)) return false;

  // One persistent KV cache per layer, k first then v, exactly [1,SEQ,2,128].
  // Both planes are zeroed: the decode mask uses -9984 rather than -inf (see
  // kMaskNeg), so a slot nothing has written yet still gets a sliver of
  // attention weight, and leftover bytes would be exactly the kind of
  // 0.01-logit nudge that flips a near-tie.
  e.kv.resize(e.layers);
  std::vector<char> zeros(e.cache_bytes * 2, 0);
  for (int i = 0; i < e.layers; ++i) {
    if (!e.alloc(e.cache_bytes * 2, &e.kv[i])) return false;
    if (!e.s2d(e.kv[i], zeros.data(), zeros.size())) return false;
  }
  return true;
}

bool VlEngine::prefill(const int32_t* ids, int n_ids, int head_len,
                       int grid_h, int grid_w, const float* patches) {
  Impl& e = *impl_;
  e.tm = VlTimings{};
  if (n_ids <= 0 || n_ids >= e.seq) {
    e.last_error = "prompt does not fit the sequence";
    return false;
  }
  if (grid_h % kMerge || grid_w % kMerge) {
    e.last_error = "grid must be even for the 2x2 merge";
    return false;
  }
  const int n_patches = grid_h * grid_w;
  if (n_patches != e.patches) {
    e.last_error = "vit grid " + std::to_string(grid_h) + "x" + std::to_string(grid_w) +
                   " needs " + std::to_string(n_patches) +
                   " patches, the bmodel takes " + std::to_string(e.patches);
    return false;
  }
  const int n_img = (grid_h / kMerge) * (grid_w / kMerge);
  if (head_len + n_img > n_ids) {
    e.last_error = "head_len + image tokens exceeds the prompt";
    return false;
  }
  e.grid_h = grid_h;
  e.grid_w = grid_w;
  e.n_img = n_img;
  e.prompt_len = n_ids;
  e.tm.prompt_tokens = n_ids;
  e.tm.image_tokens = n_img;

  // ---- vit ---------------------------------------------------------------
  const size_t pix_bytes = static_cast<size_t>(n_patches) * 3 * kPatch * kPatch * 4;
  double t0 = now_ms();
  if (!e.s2d(e.pix_mem, patches, pix_bytes)) return false;
  if (!e.run(e.vit, {e.pix_mem}, {e.vout_mem})) return false;
  e.tm.vit_ms = now_ms() - t0;

  // vit is bf16 on the way out; the splice needs the raw 16-bit words.
  const size_t vout_bytes = VlNet::bytes(e.vit.out_shape(0), e.vit.out_dt(0));
  if (static_cast<int>(vout_bytes / 2) != n_img * kHidden) {
    e.last_error = "vit output does not match the merged grid";
    return false;
  }
  std::vector<uint16_t> emb_raw(vout_bytes / 2);
  if (!e.d2s(emb_raw.data(), e.vout_mem, vout_bytes)) return false;

  // ---- embedding / prompt ------------------------------------------------
  std::vector<int32_t> ids_pad(static_cast<size_t>(e.seq), 0);
  std::copy(ids, ids + n_ids, ids_pad.begin());
  const size_t ids_bytes = ids_pad.size() * sizeof(int32_t);
  t0 = now_ms();
  if (!e.s2d(e.ids_mem, ids_pad.data(), ids_bytes)) return false;
  if (!e.run(e.embed, {e.ids_mem}, {e.xa})) return false;
  e.tm.embed_ms = now_ms() - t0;

  // Splice vit rows into the placeholder rows, on the host: one copy per
  // element, and it keeps the graph count at 40.
  {
    const size_t hidden_bytes = static_cast<size_t>(e.seq) * kHidden * 2;
    std::vector<uint16_t> hidden(hidden_bytes / 2);
    if (!e.d2s(hidden.data(), e.xa, hidden_bytes)) return false;
    for (int i = 0; i < n_img; i++)
      std::memcpy(&hidden[static_cast<size_t>(head_len + i) * kHidden],
                  &emb_raw[static_cast<size_t>(i) * kHidden], kHidden * 2);
    if (!e.s2d(e.xa, hidden.data(), hidden_bytes)) return false;
  }

  // ---- prefill -----------------------------------------------------------
  // The table must cover every position decode will ask for, not just the
  // prompt: decode reads L, L+1, ... up to the sequence end. Building it for L
  // entries and indexing past the end reads heap garbage, which makes every
  // decoded position id wrong while leaving every tensor shape valid --
  // measured as a correct first token followed by padding.
  if (!e.rope.build(e.seq, grid_h, grid_w, head_len, &e.last_error)) return false;
  if (!e.s2d(e.pos_mem, e.rope.pos.data(), e.rope.pos.size() * sizeof(int32_t)))
    return false;

  // Additive mask: -9984 for every position a real row must not attend to.
  //
  // That is BOTH the causal future (c > r) and the whole padding tail (c >= L).
  // Masking only the causal part leaves columns L..SEQ-1 at zero penalty, and
  // softmax then gives those positions real probability mass -- their keys come
  // from embedding(0) pushed through 18 layers, which is not zero, so the
  // prefill output is wrong by a little on every element. It still runs and
  // still emits tokens, which is why this is easy to miss.
  const size_t mask_elems = static_cast<size_t>(e.seq) * e.seq;
  std::vector<uint16_t> mask(mask_elems, 0);
  const uint16_t neg = f32_to_bf16(kMaskNeg);
  for (int r = 0; r < n_ids; r++)
    for (int c = r + 1; c < e.seq; c++) mask[static_cast<size_t>(r) * e.seq + c] = neg;
  if (!e.s2d(e.mask_mem, mask.data(), mask.size() * 2)) return false;

  t0 = now_ms();
  bm_device_mem_t cur = e.xa, nxt = e.xb;
  for (int i = 0; i < e.layers; i++) {
    bm_device_mem_t k_full = Impl::view(e.kv[i], 0, e.cache_bytes);
    bm_device_mem_t v_full = Impl::view(e.kv[i], e.cache_bytes, e.cache_bytes);
    if (!e.run(e.blocks[i], {cur, e.pos_mem, e.mask_mem}, {nxt, k_full, v_full}))
      return false;
    std::swap(cur, nxt);
  }
  e.tm.prefill_ms = now_ms() - t0;

  // ---- first token -------------------------------------------------------
  e.cur = cur;
  int32_t first = -1;
  if (!e.lm_head_at(e.cur, static_cast<size_t>(n_ids - 1) * kHidden * 2, &first))
    return false;
  e.pending = first;
  e.has_pending = true;
  e.step_pos = n_ids;
  e.dx_cur = e.dx_a;
  e.dx_nxt = e.dx_b;
  return true;
}

int32_t VlEngine::step() {
  Impl& e = *impl_;
  // The token lm_head already produced. The *next* call decodes from it, and
  // needs it as the input token, so it is remembered on the way out.
  if (e.has_pending) {
    const int32_t tok = e.pending;
    e.has_pending = false;
    e.last_sampled = tok;
    return tok;
  }

  const int n = e.step_pos;          // the position this step writes
  if (n + 1 >= e.seq) {
    e.last_error = "sequence exhausted";
    return -1;
  }
  const int32_t tok = e.last_sampled;
  if (tok < 0) {
    e.last_error = "step() before prefill()";
    return -1;
  }
  const double s = now_ms();
  if (!e.s2d(e.did_mem, &tok, sizeof(tok))) return -1;
  if (!e.run(e.embed_cache, {e.did_mem}, {e.demb_mem})) return -1;
  // Layer 0 eats the token embedding; every later layer eats the previous
  // layer's output. Using a stale buffer here instead feeds the whole stack
  // garbage that still has the right shape and still produces tokens --
  // measured as a correct first token followed by padding tokens.
  bm_device_mem_t x_in = e.demb_mem;

  int32_t pos1[3];
  pos1[0] = e.rope.at(0, n);
  pos1[1] = e.rope.at(1, n);
  pos1[2] = e.rope.at(2, n);
  if (!e.s2d(e.dpos_mem, pos1, sizeof(pos1))) return -1;

  // History slots n..SEQ-1 are masked; the new key (slot SEQ) is not.
  std::vector<uint16_t> dmask(static_cast<size_t>(e.seq) + 1, 0);
  const uint16_t neg = f32_to_bf16(kMaskNeg);
  for (int i = n; i < e.seq; i++) dmask[static_cast<size_t>(i)] = neg;
  if (!e.s2d(e.dmask_mem, dmask.data(), dmask.size() * 2)) return -1;

  for (int i = 0; i < e.layers; i++) {
    bm_device_mem_t hist_k = Impl::view(e.kv[i], 0, e.cache_bytes);
    bm_device_mem_t hist_v = Impl::view(e.kv[i], e.cache_bytes, e.cache_bytes);
    bm_device_mem_t new_k = Impl::view(e.kv[i], static_cast<size_t>(n) * e.row_bytes,
                                       e.row_bytes);
    bm_device_mem_t new_v = Impl::view(
        e.kv[i], e.cache_bytes + static_cast<size_t>(n) * e.row_bytes, e.row_bytes);
    if (!e.run(e.blocks_cache[i], {x_in, e.dpos_mem, e.dmask_mem, hist_k, hist_v},
               {e.dx_nxt, new_k, new_v}))
      return -1;
    // Swap first, then point at the buffer that now holds this layer's output:
    // taking it before the swap hands the next layer the buffer the previous
    // layer *read*, not the one it wrote.
    std::swap(e.dx_cur, e.dx_nxt);
    x_in = e.dx_cur;
  }
  int32_t out = -1;
  if (!e.lm_head_at(e.dx_cur, 0, &out)) return -1;
  e.tm.decode_ms += now_ms() - s;
  e.tm.decode_steps++;
  e.step_pos = n + 1;
  e.last_sampled = out;
  return out;
}

}  // namespace cv84x6
