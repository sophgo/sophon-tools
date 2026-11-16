// Qwen3-VL dataflow follows SOPHGO LLM-TPU/models/Qwen3_VL; only the
// normalised last-token encoder state is returned. DeepStack is added after
// language blocks 0, 1 and 2, exactly as in the official Qwen3-VL model.
// WeMM uses Qwen3.5's 24-layer hybrid encoder and no DeepStack. Its recurrent
// state starts from zero on every input; only the final token is pooled.
#include "vl_embed_engine.h"
#include "aux_common.h"
#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <vector>

namespace cv84x6 {
namespace {
using Clock = std::chrono::steady_clock;
double elapsed(Clock::time_point start) {
  return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}
constexpr int kHidden = 2048;
}  // namespace

struct VlEmbedEngine::Impl {
  bm_handle_t handle = nullptr;
  void* rt = nullptr;
  const bm_net_info_t *embed = nullptr, *vit = nullptr, *add = nullptr;
  struct Encoder {
    int rows;
    bool dynamic;
    std::vector<const bm_net_info_t*> blocks;
    bm_device_mem_t mask{};
  };
  std::vector<Encoder> encoders;
  std::vector<bm_device_mem_t> owned;
  bm_device_mem_t hidden{};
  std::vector<bm_device_mem_t> deep;
  int seq = 0, patches = 0;
  bool wemm = false;
  int layers = 28, vocab = 151936;
  int vision_start = 151652, vision_end = 151653, image_pad = 151655;
  bool linear(int layer) const { return wemm && layer % 4 != 3; }
  bool ready = false;
  std::atomic<bool> fault{false};
  std::string error;
  std::mutex mutex;
  bool trace = std::getenv("CV_VLE_TRACE") != nullptr;

  ~Impl() {
    // A failed sync can leave a launch outstanding. Drain before releasing
    // its buffers, including on a partially failed load/forward.
    if (handle) bm_thread_sync(handle);
    for (auto mem : owned) bm_free_device(handle, mem);
    if (rt) {
      // CV84X6 bmrt may throw while shrinking its shared compute pool.
      // No exception may cross the destructor/C boundary during unload.
      try { bmrt_destroy(rt); }
      catch (const std::exception& ex) {
        std::fprintf(stderr, "[vl-embed] bmrt_destroy: %s\n", ex.what());
      } catch (...) {
        std::fprintf(stderr, "[vl-embed] bmrt_destroy: unknown exception\n");
      }
    }
    if (handle) bm_dev_free(handle);
  }
  bool fail(const std::string& why, bool device_fault = false) {
    error = why;
    if (device_fault) fault.store(true);
    return false;
  }
  bool allocate(bm_device_mem_t* mem, unsigned int bytes) {
    if (bm_malloc_device_byte_heap_mask(handle, mem, 3, bytes) != BM_SUCCESS)
      return fail("NPU heap exhausted", true);
    owned.push_back(*mem);
    return true;
  }
  bool zero(bm_device_mem_t mem) {
    return bm_memset_device_ext(handle, &aux::kZero, 1, mem) == BM_SUCCESS ||
           fail("device memset failed", true);
  }
  bool upload(bm_device_mem_t mem, const void* data, size_t bytes) {
    if (bytes > bm_mem_get_device_size(mem)) return fail("upload exceeds graph input");
    return bm_memcpy_s2d_partial(handle, mem, const_cast<void*>(data), bytes) == BM_SUCCESS ||
           fail("host-to-device copy failed", true);
  }
  bool copy(bm_device_mem_t dst, size_t offset, bm_device_mem_t src, size_t bytes) {
    if (offset + bytes > bm_mem_get_device_size(dst) || bytes > bm_mem_get_device_size(src))
      return fail("device copy exceeds graph buffer");
    if (dst.u.device.device_addr + offset == src.u.device.device_addr) return true;
    return bm_memcpy_d2d_byte(handle, dst, offset, src, 0, bytes) == BM_SUCCESS ||
           fail("device-to-device copy failed", true);
  }
  bool launch(const bm_net_info_t* net, int rows = 0) {
    if (trace) std::fprintf(stderr, "[vl-embed] launch %s rows=%d\n", net->name, rows);
    std::vector<bm_tensor_t> in(net->input_num), out(net->output_num);
    for (int i = 0; i < net->input_num; ++i) {
      bmrt_tensor_with_device(&in[i], net->stages[0].input_mems[i],
                              net->input_dtypes[i], net->stages[0].input_shapes[i]);
      if (rows && net->is_dynamic) {
        if (net == vit) in[i].shape.dims[0] = rows;
        else in[i].shape.dims[1] = rows;
      }
    }
    for (int i = 0; i < net->output_num; ++i)
      bmrt_tensor_with_device(&out[i], net->stages[0].output_mems[i],
                              net->output_dtypes[i], net->stages[0].output_shapes[i]);
    if (!bmrt_launch_tensor_ex(rt, net->name, in.data(), net->input_num,
                               out.data(), net->output_num, true, false))
      return fail(std::string("launch failed: ") + net->name, true);
    if (bm_thread_sync(handle) != BM_SUCCESS)
      return fail(std::string("device sync failed: ") + net->name, true);
    if (trace) std::fprintf(stderr, "[vl-embed] complete %s\n", net->name);
    return true;
  }
};

VlEmbedEngine::VlEmbedEngine() : impl_(new Impl()) {}
VlEmbedEngine::~VlEmbedEngine() = default;
int VlEmbedEngine::seq_len() const { return impl_->seq; }
int VlEmbedEngine::hidden_size() const { return kHidden; }
int VlEmbedEngine::max_patches() const { return impl_->patches; }
bool VlEmbedEngine::is_wemm() const { return impl_->wemm; }
bool VlEmbedEngine::faulted() const { return impl_->fault.load(); }
std::string VlEmbedEngine::last_error() const { return impl_->error; }

bool VlEmbedEngine::load(const std::string& path, int device) {
  auto& e = *impl_;
  if (e.rt) return e.fail("engine already loaded");
  if (bm_dev_request(&e.handle, device) != BM_SUCCESS) return e.fail("bm_dev_request failed");
  e.rt = bmrt_create(e.handle);
  if (!e.rt) return e.fail("bmrt_create failed");
  bmrt_set_flags(e.rt, BM_RUNTIME_SHARE_MEM);
  if (e.trace) std::fprintf(stderr, "[vl-embed] load bmodel\n");
  if (!bmrt_load_bmodel(e.rt, path.c_str())) return e.fail("bmodel loading failed");
  if (e.trace) std::fprintf(stderr, "[vl-embed] bmodel loaded\n");
  const char** raw_names = nullptr;
  const int network_count = bmrt_get_network_number(e.rt);
  bmrt_get_network_names(e.rt, &raw_names);
  std::vector<std::string> names;
  for (int i = 0; raw_names && i < network_count; ++i) names.emplace_back(raw_names[i]);
  std::free(raw_names);
  auto has = [&](const char* name) { return std::find(names.begin(), names.end(), name) != names.end(); };
  e.wemm = has("wemm_embedding");
  const char* embedding_name = e.wemm ? "wemm_embedding" : "embedding";
  if (has(embedding_name)) e.embed = bmrt_get_network_info(e.rt, embedding_name);
  if (e.wemm) {
    e.layers = 24; e.vocab = 248078;
    e.vision_start = 248053; e.vision_end = 248054; e.image_pad = 248056;
    if (has("embedding")) return e.fail("ambiguous embedding family");
  }
  if (has("vit")) e.vit = bmrt_get_network_info(e.rt, "vit");
  if (!e.wemm && has("add")) e.add = bmrt_get_network_info(e.rt, "add");
  if (!e.embed || !e.vit || (!e.wemm && !e.add)) return e.fail("missing embedding, vit or add graph");
  if (e.embed->stage_num != 1 || e.vit->stage_num != 1 || (e.add && e.add->stage_num != 1))
    return e.fail("unsupported graph stages");
  if (e.embed->is_dynamic || e.embed->input_num != 1 || e.embed->output_num != 1 ||
      e.embed->input_dtypes[0] != BM_INT32 || e.embed->output_dtypes[0] != BM_BFLOAT16 ||
      e.embed->stages[0].input_shapes[0].num_dims != 2 ||
      e.embed->stages[0].input_shapes[0].dims[0] != 1 ||
      e.embed->stages[0].output_shapes[0].num_dims != 3 ||
      e.embed->stages[0].output_shapes[0].dims[0] != 1 ||
      e.embed->stages[0].output_shapes[0].dims[1] != e.embed->stages[0].input_shapes[0].dims[1] ||
      e.embed->stages[0].output_shapes[0].dims[2] != kHidden)
    return e.fail("unsupported embedding graph contract");
  e.seq = e.embed->stages[0].input_shapes[0].dims[1];
  if (e.seq < 64 || e.seq > 32768) return e.fail("unsupported encoder context length");
  if (e.wemm && e.seq % 128) return e.fail("WeMM context must be aligned to 128 tokens");
  if (!e.vit->is_dynamic || e.vit->input_num != 4 || e.vit->output_num != (e.wemm ? 1 : 4) ||
      e.vit->stages[0].input_shapes[0].num_dims != 2 ||
      e.vit->stages[0].input_shapes[0].dims[1] != 1536 ||
      (e.add && (e.add->input_num != 2 || e.add->output_num != 1)))
    return e.fail("unsupported ViT/DeepStack graph contract");
  const bm_data_type_t vtypes[] = {BM_FLOAT32, BM_INT32, BM_INT32, BM_FLOAT32};
  for (int i = 0; i < 4; ++i)
    if (e.vit->input_dtypes[i] != vtypes[i])
      return e.fail("unsupported ViT dtypes");
  e.patches = e.vit->stages[0].input_shapes[0].dims[0];
  if (e.patches <= 0 || e.patches % 4 || e.patches / 4 + 32 > e.seq)
    return e.fail("invalid ViT patch budget");
  for (int i = 0; i < e.vit->output_num; ++i) {
    const auto& output = e.vit->stages[0].output_shapes[i];
    if (e.vit->output_dtypes[i] != BM_BFLOAT16 || output.num_dims != 2 ||
        output.dims[0] != e.patches / 4 || output.dims[1] != kHidden)
      return e.fail("unsupported ViT output");
  }
  for (int i = 0; i < 4; ++i) {
    const auto& input = e.vit->stages[0].input_shapes[i];
    if (input.dims[0] != e.patches || input.num_dims != (i == 3 ? 3 : 2) ||
        input.dims[1] != (i == 0 ? 1536 : i == 1 ? 2 : 4) || (i == 3 && input.dims[2] != 1))
      return e.fail("unsupported ViT shape");
  }
  const unsigned int bytes = e.seq * kHidden * sizeof(uint16_t);
  for (int i = 0; e.add && i < 2; ++i)
    if (e.add->input_dtypes[i] != BM_BFLOAT16 ||
        bm_mem_get_device_size(e.add->stages[0].input_mems[i]) < bytes)
      return e.fail("unsupported DeepStack input");
  if (e.add && e.add->output_dtypes[0] != BM_BFLOAT16) return e.fail("unsupported DeepStack output");
  const bool dynamic = has("block_0"), middle_bucket = has("block_0_s1024");
  if (e.wemm && dynamic) return e.fail("WeMM requires static primitive GDN buckets");
  std::vector<int> buckets{e.seq};
  if (!dynamic) {
    if (e.seq > 8192) return e.fail("static encoder context exceeds 8192");
    buckets = {std::min(128, e.seq), std::min(512, e.seq)};
    // Older bmodels have three buckets. Use the 1024 graph when present to
    // avoid padding 513 tokens to 2048, without rejecting those older models.
    if (e.seq > 1024 && middle_bucket) buckets.push_back(1024);
    buckets.push_back(e.seq);
    buckets.erase(std::unique(buckets.begin(), buckets.end()), buckets.end());
  }
  for (int rows : buckets) {
    Impl::Encoder encoder{rows, dynamic, {}, {}};
    for (int i = 0; i < e.layers; ++i) {
      const bool linear = e.linear(i);
      const std::string name = "block_" + std::to_string(i) +
                              (dynamic ? "" : "_s" + std::to_string(rows));
      const auto* block = bmrt_get_network_info(e.rt, name.c_str());
      if (!block || block->stage_num != 1 || bool(block->is_dynamic) != dynamic ||
        block->input_num != (linear || dynamic ? 2 : 3) || block->output_num < 1 ||
        block->input_dtypes[0] != BM_BFLOAT16 ||
        block->output_dtypes[0] != BM_BFLOAT16 ||
        block->stages[0].input_shapes[0].num_dims != 3 ||
        block->stages[0].input_shapes[0].dims[0] != 1 ||
        block->stages[0].input_shapes[0].dims[1] != rows ||
        block->stages[0].input_shapes[0].dims[2] != kHidden ||
        block->stages[0].output_shapes[0].num_dims != 3 ||
        block->stages[0].output_shapes[0].dims[0] != 1 ||
        block->stages[0].output_shapes[0].dims[1] != rows ||
        block->stages[0].output_shapes[0].dims[2] != kHidden)
        return e.fail("unsupported encoder graph: " + name);
      const auto& second = block->stages[0].input_shapes[1];
      if (linear) {
        // The supported static primitive implementation accumulates state in
        // FP32. Reject experimental fused GDN models before device submission.
        if (block->input_dtypes[1] != BM_FLOAT32 ||
            second.num_dims != 4 || second.dims[0] != 1 || second.dims[1] != 16 ||
            second.dims[2] != 128 || second.dims[3] != 128)
          return e.fail("unsupported WeMM recurrent state: " + name);
      } else if (block->input_dtypes[1] != BM_INT32 || second.num_dims != 2 ||
                 second.dims[0] != 3 || second.dims[1] != rows) {
        return e.fail("unsupported encoder positions: " + name);
      }
      if (!dynamic && !linear) {
        const auto& mask = block->stages[0].input_shapes[2];
        if (block->input_dtypes[2] != BM_BFLOAT16 || mask.num_dims != 4 ||
            mask.dims[0] != 1 || mask.dims[1] != 1 || mask.dims[2] != rows || mask.dims[3] != rows)
          return e.fail("unsupported causal mask: " + name);
      }
      encoder.blocks.push_back(block);
    }
    if (!dynamic) {
      std::vector<uint16_t> mask(static_cast<size_t>(rows) * rows, 0);
      for (int r = 0; r < rows; ++r)
        std::fill(mask.begin() + static_cast<size_t>(r) * rows + r + 1,
                  mask.begin() + static_cast<size_t>(r + 1) * rows, 0xc61c); // BF16 -9984
      if (!e.allocate(&encoder.mask, mask.size() * sizeof(uint16_t)) ||
          !e.upload(encoder.mask, mask.data(), mask.size() * sizeof(uint16_t))) return false;
    }
    e.encoders.push_back(std::move(encoder));
  }
  if (!e.allocate(&e.hidden, bytes)) return false;
  for (int i = 0; !e.wemm && i < 3; ++i) {
    bm_device_mem_t mem{};
    if (!e.allocate(&mem, bytes)) return false;
    e.deep.push_back(mem);
  }
  e.ready = true;
  return true;
}

bool VlEmbedEngine::forward(const int32_t* ids, int n, const VisionInput* image,
                            int offset, int dimensions, float* out, VlEmbedTimings* timings) {
  auto& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mutex);
  if (!e.ready) return e.fail("encoder is not loaded");
  if (e.fault) return e.fail("NPU engine faulted; reload required");
  if (!ids || !out || n <= 0 || n > e.seq || dimensions < 64 || dimensions > kHidden)
    return e.fail("invalid encoder input length or dimensions");
  for (int i = 0; i < n; ++i)
    if (ids[i] < 0 || ids[i] >= e.vocab) return e.fail("token id outside the model vocabulary");
  const auto& encoder = *std::find_if(e.encoders.begin(), e.encoders.end(),
                                     [n](const Impl::Encoder& v) { return v.rows >= n; });
  const int work_rows = encoder.dynamic ? n : encoder.rows;
  const size_t bytes = static_cast<size_t>(work_rows) * kHidden * sizeof(uint16_t);
  std::vector<int32_t> tokens(ids, ids + n), positions;
  if (image) {
    const int patches = image->patches(), count = patches / 4;
    if (image->grid_t != 1 || image->grid_h <= 0 || image->grid_w <= 0 ||
        image->grid_h % 2 || image->grid_w % 2 || patches > e.patches ||
        image->pixels.size() != static_cast<size_t>(patches) * 1536 ||
        offset <= 0 || offset + count >= n || ids[offset - 1] != e.vision_start ||
        ids[offset + count] != e.vision_end ||
        std::count(tokens.begin(), tokens.end(), e.vision_start) != 1)
      return e.fail("image grid and prompt do not match");
    for (int i = offset; i < offset + count; ++i)
      if (ids[i] != e.image_pad) return e.fail("image placeholder span is invalid");
    vision_rope_index(tokens, {{1, image->grid_h, image->grid_w}},
                       e.vision_start, e.image_pad, 2, &positions);
  } else {
    positions.resize(3 * n);
    for (int r = 0; r < 3; ++r)
      for (int i = 0; i < n; ++i) positions[r * n + i] = i;
  }
  if (positions.size() != static_cast<size_t>(3 * n)) return e.fail("invalid M-RoPE positions");
  for (auto pos : positions)
    if (pos < 0 || pos >= e.seq) return e.fail("M-RoPE position exceeds compiled table");
  if (work_rows != n) {
    std::vector<int32_t> padded(3 * work_rows, 0);
    for (int axis = 0; axis < 3; ++axis)
      std::copy_n(positions.begin() + axis * n, n, padded.begin() + axis * work_rows);
    positions.swap(padded);
  }

  VlEmbedTimings measured;
  auto start = Clock::now();
  if (!e.zero(e.embed->stages[0].input_mems[0]) ||
      !e.upload(e.embed->stages[0].input_mems[0], ids, n * sizeof(int32_t)) ||
      !e.launch(e.embed) || !e.copy(e.hidden, 0, e.embed->stages[0].output_mems[0], bytes))
    return false;
  measured.embedding_ms = elapsed(start);
  if (image) {
    start = Clock::now();
    for (auto mem : e.deep) if (!e.zero(mem)) return false;
    std::vector<int32_t> rot, idx;
    std::vector<float> weights;
    vision_rot_pos(1, image->grid_h, image->grid_w, &rot);
    vision_pos_embed_interpolate(1, image->grid_h, image->grid_w, 48, &idx, &weights);
    const auto& v = e.vit->stages[0];
    if (!e.upload(v.input_mems[0], image->pixels.data(), image->pixels.size() * sizeof(float)) ||
        !e.upload(v.input_mems[1], rot.data(), rot.size() * sizeof(int32_t)) ||
        !e.upload(v.input_mems[2], idx.data(), idx.size() * sizeof(int32_t)) ||
        !e.upload(v.input_mems[3], weights.data(), weights.size() * sizeof(float)) ||
        !e.launch(e.vit, image->patches())) return false;
    const size_t at = static_cast<size_t>(offset) * kHidden * sizeof(uint16_t);
    const size_t count = static_cast<size_t>(image->patches() / 4) * kHidden * sizeof(uint16_t);
    if (!e.copy(e.hidden, at, v.output_mems[0], count)) return false;
    for (int i = 0; i < static_cast<int>(e.deep.size()); ++i)
      if (!e.copy(e.deep[i], at, v.output_mems[i + 1], count)) return false;
    measured.vision_ms = elapsed(start);
  }
  start = Clock::now();
  auto current = e.hidden;
  for (int i = 0; i < e.layers; ++i) {
    const auto* net = encoder.blocks[i];
    // Both GDN and full attention use the selected static bucket. Causal
    // padding after the valid prefix cannot affect the pooled token.
    // Each item and each layer starts from zero state; hidden is owned
    // separately from BMRT's shared scratch pool.
    if (e.linear(i) && !e.zero(net->stages[0].input_mems[1])) return false;
    if (!e.copy(net->stages[0].input_mems[0], 0, current, bytes) ||
        (!e.linear(i) && !e.upload(net->stages[0].input_mems[1], positions.data(), positions.size() * sizeof(int32_t))) ||
        (!encoder.dynamic && !e.linear(i) && !e.copy(net->stages[0].input_mems[2], 0, encoder.mask,
                                     static_cast<size_t>(work_rows) * work_rows * sizeof(uint16_t))) ||
        !e.launch(net, work_rows)) return false;
    current = net->stages[0].output_mems[0];
    if (e.wemm) {
      if (!e.copy(e.hidden, 0, current, bytes)) return false;
      current = e.hidden;
    }
    if (image && e.add && i < 3) {
      const auto& a = e.add->stages[0];
      if (!e.copy(a.input_mems[0], 0, current, bytes) ||
          !e.copy(a.input_mems[1], 0, e.deep[i], e.seq * kHidden * sizeof(uint16_t)) ||
          !e.launch(e.add)) return false;
      current = a.output_mems[0];
    }
  }
  std::vector<uint16_t> raw(dimensions);
  auto last = bm_mem_from_device(current.u.device.device_addr +
      static_cast<size_t>(n - 1) * kHidden * sizeof(uint16_t), dimensions * sizeof(uint16_t));
  if (bm_memcpy_d2s(e.handle, raw.data(), last) != BM_SUCCESS)
    return e.fail("reading encoder output failed", true);
  double norm = 0;
  for (int i = 0; i < dimensions; ++i) {
    out[i] = aux::bf16_to_f32(raw[i]);
    if (!std::isfinite(out[i])) return e.fail("encoder returned a non-finite vector", true);
    norm += static_cast<double>(out[i]) * out[i];
  }
  if (norm <= 0) return e.fail("encoder returned a zero vector", true);
  norm = std::sqrt(norm);
  for (int i = 0; i < dimensions; ++i) out[i] = static_cast<float>(out[i] / norm);
  measured.encoder_ms = elapsed(start);
  if (timings) *timings = measured;
  return true;
}

}  // namespace cv84x6
