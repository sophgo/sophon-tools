// BGE-Reranker-v2-M3 on CV84X6 -- pure bmrt, no sail, no pybind.
//
// Port of LLM-TPU models/Bge_Reranker_V2_M3/python_demo/chat.cpp, the file whose
// demo produces the 0.8429 / 0.0003 scores MYS-2551 measured on this board.
//
// Shape of the bmodel (XLM-R base encoder, static SEQLEN):
//   embedding   (input_ids[1,L] int32, position_ids[1,L] int32)
//                 -> hidden[1,L,H] f32
//   block_<i>   (hidden[1,L,H] bf16, additive_mask[1,1,1,L] bf16)
//                 -> hidden[1,L,H] f32
//   classifier  (hidden[1,L,H] bf16) -> logit[1,1] bf16
//
// The reference converts f32<->bf16 on the host around every layer, and this
// port keeps that: the fused graphs' declared dtypes differ from what the demo
// feeds them, and "fixing" the conversion is exactly the change that would make
// the scores disagree with the demo.

#include "aux_engine.h"

#include "aux_common.h"
#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace cv84x6 {

namespace {

constexpr int kNpuHeapMask = 3;

}  // namespace

struct RerankEngine::Impl {
  bm_handle_t handle = nullptr;
  void* bmrt = nullptr;
  std::mutex mu;
  std::string last_error;

  const bm_net_info_t* net_embed = nullptr;
  const bm_net_info_t* net_classifier = nullptr;
  std::vector<const bm_net_info_t*> net_blocks;
  bm_device_mem_t bf16_buffer{};
  bool has_bf16_buffer = false;

  int seq_len = 0;
  int hidden_size = 0;
  int num_layers = 0;
  int hidden_bytes_bf16 = 0;

  bool fail(const std::string& msg) {
    last_error = msg;
    return false;
  }

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
};

RerankEngine::RerankEngine() : impl_(new Impl()) {}

RerankEngine::~RerankEngine() {
  if (!impl_) return;
  if (impl_->has_bf16_buffer && impl_->handle) {
    bm_free_device(impl_->handle, impl_->bf16_buffer);
  }
  if (impl_->bmrt) bmrt_destroy(impl_->bmrt);
  if (impl_->handle) bm_dev_free(impl_->handle);
  delete impl_;
}

int RerankEngine::seq_len() const { return impl_->seq_len; }
int RerankEngine::hidden_size() const { return impl_->hidden_size; }
std::string RerankEngine::last_error() const { return impl_->last_error; }

bool RerankEngine::load(const std::string& model_path, int dev_id) {
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

  e.net_classifier = bmrt_get_network_info(e.bmrt, "classifier");
  if (!e.net_classifier) return e.fail("bmodel has no 'classifier' graph");

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

  e.hidden_size = e.net_blocks[0]->stages[0].output_shapes[0].dims[2];
  e.hidden_bytes_bf16 = e.seq_len * e.hidden_size * 2;

  if (bm_malloc_device_byte_heap_mask(e.handle, &e.bf16_buffer, kNpuHeapMask,
                                      static_cast<size_t>(e.hidden_bytes_bf16)) !=
      BM_SUCCESS) {
    return e.fail("NPU heap exhausted allocating the bf16 buffer");
  }
  e.has_bf16_buffer = true;
  return true;
}

bool RerankEngine::forward(const int32_t* input_ids, const int32_t* position_ids,
                           const int32_t* attention_mask, float* out) {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  if (!input_ids || !position_ids || !attention_mask || !out) {
    return e.fail("forward: null argument");
  }

  const size_t total = static_cast<size_t>(e.seq_len) * e.hidden_size;
  std::vector<float> hidden_f32(total);
  std::vector<uint16_t> hidden_bf16(total);

  // -- step 1: embedding ----------------------------------------------------
  bm_device_mem_t& embed_in0 = e.net_embed->stages[0].input_mems[0];
  bm_device_mem_t& embed_in1 = e.net_embed->stages[0].input_mems[1];
  bm_device_mem_t& embed_out = e.net_embed->stages[0].output_mems[0];
  bm_memset_device_ext(e.handle, &aux::kZero, 1, embed_in0);
  bm_memset_device_ext(e.handle, &aux::kZero, 1, embed_in1);
  // The reference copies only the first `token_length` ids and relies on the
  // two memsets above for the rest. Here the whole SEQLEN row is already
  // materialised by the caller (it is what the tokenizer padded to), so the
  // full row is copied -- same values, one round trip.
  if (bm_memcpy_s2d(e.handle, embed_in0, const_cast<int32_t*>(input_ids)) !=
      BM_SUCCESS) {
    return e.fail("copying input ids failed");
  }
  if (bm_memcpy_s2d(e.handle, embed_in1, const_cast<int32_t*>(position_ids)) !=
      BM_SUCCESS) {
    return e.fail("copying position ids failed");
  }
  if (!e.launch(e.net_embed)) return false;
  if (bm_thread_sync(e.handle) != BM_SUCCESS) return e.fail("bm_thread_sync failed");

  if (bm_memcpy_d2s(e.handle, hidden_f32.data(), embed_out) != BM_SUCCESS) {
    return e.fail("reading the embedding output failed");
  }
  aux::f32_to_bf16(hidden_f32.data(), hidden_bf16.data(),
                   static_cast<int>(total));
  if (bm_memcpy_s2d(e.handle, e.bf16_buffer, hidden_bf16.data()) != BM_SUCCESS) {
    return e.fail("staging hidden states failed");
  }

  // -- step 2: additive attention mask --------------------------------------
  // 0 for a real token, -10000 for padding; the block graphs take it per row.
  std::vector<uint16_t> additive_mask(static_cast<size_t>(e.seq_len), 0);
  const float neg = -10000.0f;
  uint16_t neg_bf16 = 0;
  aux::f32_to_bf16(&neg, &neg_bf16, 1);
  for (int i = 0; i < e.seq_len; i++) {
    additive_mask[static_cast<size_t>(i)] =
        attention_mask[i] == 0 ? neg_bf16 : 0;
  }

  // -- step 3: encoder blocks ----------------------------------------------
  for (int idx = 0; idx < e.num_layers; idx++) {
    const bm_net_info_t* block = e.net_blocks[static_cast<size_t>(idx)];
    if (bm_memcpy_d2d_byte(e.handle, block->stages[0].input_mems[0], 0,
                           e.bf16_buffer, 0,
                           static_cast<unsigned int>(e.hidden_bytes_bf16)) !=
        BM_SUCCESS) {
      return e.fail("copying hidden states into a block failed");
    }
    if (bm_memcpy_s2d(e.handle, block->stages[0].input_mems[1],
                      additive_mask.data()) != BM_SUCCESS) {
      return e.fail("copying the attention mask failed");
    }
    if (!e.launch(block)) return false;
    if (bm_thread_sync(e.handle) != BM_SUCCESS) return e.fail("bm_thread_sync failed");

    if (bm_memcpy_d2s(e.handle, hidden_f32.data(),
                      block->stages[0].output_mems[0]) != BM_SUCCESS) {
      return e.fail("reading a block output failed");
    }
    aux::f32_to_bf16(hidden_f32.data(), hidden_bf16.data(),
                     static_cast<int>(total));
    if (bm_memcpy_s2d(e.handle, e.bf16_buffer, hidden_bf16.data()) != BM_SUCCESS) {
      return e.fail("staging hidden states failed");
    }
  }

  // -- step 4: classifier ---------------------------------------------------
  if (bm_memcpy_d2d_byte(e.handle, e.net_classifier->stages[0].input_mems[0], 0,
                         e.bf16_buffer, 0,
                         static_cast<unsigned int>(e.hidden_bytes_bf16)) !=
      BM_SUCCESS) {
    return e.fail("copying hidden states into the classifier failed");
  }
  if (!e.launch(e.net_classifier)) return false;
  if (bm_thread_sync(e.handle) != BM_SUCCESS) return e.fail("bm_thread_sync failed");

  uint16_t logit_bf16 = 0;
  if (bm_memcpy_d2s_partial(e.handle, &logit_bf16,
                            e.net_classifier->stages[0].output_mems[0],
                            sizeof(logit_bf16)) != BM_SUCCESS) {
    return e.fail("reading the classifier output failed");
  }
  *out = aux::bf16_to_f32(logit_bf16);
  return true;
}

}  // namespace cv84x6
