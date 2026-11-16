// Qwen3-Embedding-0.6B on CV84X6 -- pure bmrt, no sail, no pybind.
//
// Port of LLM-TPU models/Qwen3_Embedding/python_demo/chat.cpp (the file whose
// demo produces the 0.6405 / 0.1494 / 0.5267 similarities MYS-2551 measured on
// this board). The dataflow is that file's, line for line, because every
// departure from it is silent numeric drift rather than an error:
//
//   embedding -> dev_buffer -> block_0 .. block_<N-1> -> read last row
//
// Two things are deliberately NOT the reference's:
//
//   * the reference allocates a fresh `std::vector` per call and does its FP16
//     decoding in a hand-written bit-twiddle loop; the loop is kept verbatim
//     (it matches, including denormals) but the buffers are reused, since one
//     worker serves many requests;
//   * pybind11 is gone. The class is driven through the C ABI in c_api.cpp.
//
// The embedding graph is static (this build is `_static_`), the block graphs
// are not: a variable-length input runs the dynamic launch path, which sets the
// sequence dimensions from the real token count.

#include "aux_engine.h"

#include "bmruntime_interface.h"
#include "bmlib_runtime.h"
#include "aux_common.h"

#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace cv84x6 {

namespace {

// Same heap mask the chat engine uses (see llm_engine.cpp): buffers the NPU
// touches must come from the NPU heap.
constexpr int kNpuHeapMask = 3;

}  // namespace

struct EmbedEngine::Impl {
  bm_handle_t handle = nullptr;
  void* bmrt = nullptr;
  std::mutex mu;  // one NPU: launches are serialised
  std::string last_error;

  const bm_net_info_t* net_embed = nullptr;
  std::vector<const bm_net_info_t*> net_blocks;
  bm_device_mem_t dev_buffer{};
  bool has_dev_buffer = false;

  int seq_len = 0;
  int hidden_size = 0;
  int num_layers = 0;
  bool is_dynamic = false;
  bool prefill_mask = false;   // block graphs take a third input: the mask
  bool is_same_addr = false;   // block output aliases its own input
  uint16_t mask_value = 0;     // -inf in the model's own dtype
  int hidden_bytes = 0;        // per token, in the output dtype

  bool fail(const std::string& msg) {
    last_error = msg;
    return false;
  }

  // Launches one graph over its own stage-0 memory.
  bool launch(const bm_net_info_t* net) {
    if (!net) return fail("null net");
    std::vector<bm_tensor_t> in(static_cast<size_t>(net->input_num));
    std::vector<bm_tensor_t> out(static_cast<size_t>(net->output_num));
    for (int i = 0; i < net->input_num; i++) {
      bmrt_tensor_with_device(&in[static_cast<size_t>(i)],
                              net->stages[0].input_mems[i], net->input_dtypes[i],
                              net->stages[0].input_shapes[i]);
    }
    for (int i = 0; i < net->output_num; i++) {
      bmrt_tensor_with_device(&out[static_cast<size_t>(i)],
                              net->stages[0].output_mems[i],
                              net->output_dtypes[i],
                              net->stages[0].output_shapes[i]);
    }
    if (!bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num,
                               out.data(), net->output_num, true, false)) {
      return fail(std::string("launch failed: ") + net->name);
    }
    return true;
  }

  // Dynamic launch: the sequence dimension comes from the real token count.
  bool launch_dyn(const bm_net_info_t* net, int real_len) {
    if (!net) return fail("null net");
    std::vector<bm_tensor_t> in(static_cast<size_t>(net->input_num));
    std::vector<bm_tensor_t> out(static_cast<size_t>(net->output_num));
    for (int i = 0; i < net->input_num; i++) {
      bmrt_tensor_with_device(&in[static_cast<size_t>(i)],
                              net->stages[0].input_mems[i], net->input_dtypes[i],
                              net->stages[0].input_shapes[i]);
    }
    for (int i = 0; i < net->output_num; i++) {
      bmrt_tensor_with_device(&out[static_cast<size_t>(i)],
                              net->stages[0].output_mems[i],
                              net->output_dtypes[i],
                              net->stages[0].output_shapes[i]);
    }
    if (net->input_num >= 2) {
      in[0].shape.dims[1] = real_len;
      in[1].shape.dims[1] = real_len;
    }
    if (prefill_mask && net->input_num >= 3) {
      in[2].shape.dims[2] = real_len;
      in[2].shape.dims[3] = real_len;
    }
    if (!bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num,
                               out.data(), net->output_num, true, false)) {
      return fail(std::string("dynamic launch failed: ") + net->name);
    }
    return true;
  }
};

EmbedEngine::EmbedEngine() : impl_(new Impl()) {}

EmbedEngine::~EmbedEngine() {
  if (!impl_) return;
  if (impl_->has_dev_buffer && impl_->handle) {
    bm_free_device(impl_->handle, impl_->dev_buffer);
  }
  if (impl_->bmrt) bmrt_destroy(impl_->bmrt);
  if (impl_->handle) bm_dev_free(impl_->handle);
  delete impl_;
}

int EmbedEngine::seq_len() const { return impl_->seq_len; }
int EmbedEngine::hidden_size() const { return impl_->hidden_size; }
std::string EmbedEngine::last_error() const { return impl_->last_error; }

bool EmbedEngine::load(const std::string& model_path, int dev_id) {
  Impl& e = *impl_;
  if (bm_dev_request(&e.handle, dev_id) != BM_SUCCESS) {
    return e.fail("bm_dev_request failed");
  }
  e.bmrt = bmrt_create(e.handle);
  if (!e.bmrt) return e.fail("bmrt_create failed");
  bmrt_set_flags(e.bmrt, BM_RUNTIME_SHARE_MEM);
  if (!bmrt_load_bmodel(e.bmrt, model_path.c_str())) {
    return e.fail("bmrt_load_bmodel failed (wrong chip or corrupt file?)");
  }

  e.net_embed = bmrt_get_network_info(e.bmrt, "embedding");
  if (!e.net_embed) return e.fail("bmodel has no 'embedding' graph");
  e.seq_len = e.net_embed->stages[0].input_shapes[0].dims[1];

  const char** net_names = nullptr;
  const int num_nets = bmrt_get_network_number(e.bmrt);
  bmrt_get_network_names(e.bmrt, &net_names);
  auto exists = [&](const std::string& name) {
    for (int i = 0; i < num_nets; i++) {
      if (name == net_names[i]) return true;
    }
    return false;
  };
  for (int i = 0;; i++) {
    const std::string block = "block_" + std::to_string(i);
    if (!exists(block)) break;
    e.net_blocks.push_back(bmrt_get_network_info(e.bmrt, block.c_str()));
  }
  free(net_names);
  e.num_layers = static_cast<int>(e.net_blocks.size());
  if (e.num_layers == 0) return e.fail("bmodel has no block_<i> graphs");

  e.is_dynamic = e.net_blocks[0]->is_dynamic;
  e.prefill_mask = e.net_blocks[0]->input_num > 2;
  e.hidden_size = e.net_blocks[0]->stages[0].output_shapes[0].dims[2];

  const bm_data_type_t out_dtype = e.net_blocks[0]->output_dtypes[0];
  if (out_dtype == BM_FLOAT16) {
    e.mask_value = 0xF0E2;   // -inf in fp16
    e.hidden_bytes = e.hidden_size * 2;
  } else if (out_dtype == BM_BFLOAT16) {
    e.mask_value = 0xC61C;   // -10000 in bf16, as the reference uses
    e.hidden_bytes = e.hidden_size * 2;
  } else {
    e.mask_value = 0;
    e.hidden_bytes = e.hidden_size * 4;
  }

  const auto buffer_size =
      bm_mem_get_device_size(e.net_embed->stages[0].output_mems[0]);
  if (bm_malloc_device_byte_heap_mask(e.handle, &e.dev_buffer, kNpuHeapMask,
                                      buffer_size) != BM_SUCCESS) {
    return e.fail("NPU heap exhausted allocating the embedding buffer");
  }
  e.has_dev_buffer = true;

  e.is_same_addr =
      e.net_blocks[0]->stages[0].input_mems[0].u.device.device_addr ==
      e.net_blocks[0]->stages[0].output_mems[0].u.device.device_addr;
  return true;
}

bool EmbedEngine::forward(const int32_t* tokens, int n, int dim, float* out) {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  if (n <= 0) return e.fail("forward: empty input");
  if (n > e.seq_len) return e.fail("forward: input longer than SEQLEN");
  if (dim <= 0 || dim > e.hidden_size) return e.fail("forward: bad dim");

  // Positions are 0..n-1; the rest of the buffer is ZEROED, which is what the
  // reference does implicitly (`std::vector<int> position_id(SEQLEN, 0)`).
  std::vector<int32_t> position_id(static_cast<size_t>(e.seq_len), 0);
  for (int i = 0; i < n; i++) position_id[static_cast<size_t>(i)] = i;

  // Causal mask in the model's dtype: 0 on and below the diagonal, -inf above.
  std::vector<uint16_t> attn_mask;
  if (e.prefill_mask) {
    const int mask_dim = e.is_dynamic ? n : e.seq_len;
    attn_mask.assign(static_cast<size_t>(mask_dim) * mask_dim, e.mask_value);
    for (int i = 0; i < n; i++) {
      for (int j = 0; j <= i; j++) {
        attn_mask[static_cast<size_t>(i) * mask_dim + j] = 0;
      }
    }
  }

  auto in_mem = e.net_embed->stages[0].input_mems[0];
  auto out_mem = e.net_embed->stages[0].output_mems[0];
  // The embedding graph reads the whole static row count, so the tail past `n`
  // must be zero rather than whatever the last request left there.
  if (bm_memset_device_ext(e.handle, &aux::kZero, 1, in_mem) != BM_SUCCESS) {
    return e.fail("memset of the embedding input failed");
  }
  if (bm_memcpy_s2d_partial(e.handle, in_mem, const_cast<int32_t*>(tokens),
                            static_cast<unsigned int>(n * sizeof(int32_t))) !=
      BM_SUCCESS) {
    return e.fail("copying tokens to the device failed");
  }
  if (!e.launch(e.net_embed)) return false;
  // The blocks write into their own input memory on the first layer, so the
  // embedding output is copied to a buffer of our own first.
  if (bm_memcpy_d2d_byte(e.handle, e.dev_buffer, 0, out_mem, 0,
                         bm_mem_get_device_size(out_mem)) != BM_SUCCESS) {
    return e.fail("copying the embedding output failed");
  }
  out_mem = e.dev_buffer;

  // Zero every block's own input/output memory once, as the reference does:
  // stale values there are stale state, not scratch.
  for (int i = 0; i < e.num_layers; i++) {
    const bm_net_info_t* block = e.net_blocks[static_cast<size_t>(i)];
    for (int k = 0; k < block->input_num; k++) {
      bm_memset_device_ext(e.handle, &aux::kZero, 1, block->stages[0].input_mems[k]);
    }
    for (int k = 0; k < block->output_num; k++) {
      bm_memset_device_ext(e.handle, &aux::kZero, 1, block->stages[0].output_mems[k]);
    }
  }

  for (int idx = 0; idx < e.num_layers; idx++) {
    const bm_net_info_t* block = e.net_blocks[static_cast<size_t>(idx)];
    bm_device_mem_t& in0 = block->stages[0].input_mems[0];
    if (!e.is_same_addr || idx == 0) {
      if (bm_memcpy_d2d_byte(e.handle, in0, 0, out_mem, 0,
                             static_cast<unsigned int>(n * e.hidden_bytes)) !=
          BM_SUCCESS) {
        return e.fail("copying hidden states into a block failed");
      }
    }
    if (idx == 0) {
      if (bm_memcpy_s2d(e.handle, block->stages[0].input_mems[1],
                        position_id.data()) != BM_SUCCESS) {
        return e.fail("copying position ids failed");
      }
      if (e.prefill_mask) {
        if (bm_memcpy_s2d(e.handle, block->stages[0].input_mems[2],
                          attn_mask.data()) != BM_SUCCESS) {
          return e.fail("copying the attention mask failed");
        }
      }
    }
    if (e.is_dynamic) {
      if (!e.launch_dyn(block, n)) return false;
    } else if (!e.launch(block)) {
      return false;
    }
    out_mem = block->stages[0].output_mems[0];
  }
  if (bm_thread_sync(e.handle) != BM_SUCCESS) return e.fail("bm_thread_sync failed");

  // Last-token pooling. Every row is copied because the output memory may be
  // bf16/fp16 with no strided read available on the device; the reference does
  // the same (`read_hidden(out_mem, token_length)`), and at SEQLEN 8192 with
  // hidden 1024 this is 16 MB per call -- a rounding error next to the launch.
  const int total = n * e.hidden_size;
  std::vector<uint16_t> raw(static_cast<size_t>(total));
  const int out_bytes = n * e.hidden_bytes;
  if (bm_memcpy_d2s_partial(e.handle, raw.data(), out_mem,
                            static_cast<unsigned int>(out_bytes)) != BM_SUCCESS) {
    return e.fail("copying hidden states back failed");
  }
  const bm_data_type_t out_dtype = e.net_blocks[0]->output_dtypes[0];
  const int base = (n - 1) * e.hidden_size;  // first element of the last row
  for (int i = 0; i < dim; i++) {
    out[i] = aux::to_float(raw[static_cast<size_t>(base + i)], out_dtype);
  }
  return true;
}

}  // namespace cv84x6
