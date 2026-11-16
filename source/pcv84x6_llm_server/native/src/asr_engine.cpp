// Qwen3-ASR on CV84X6 -- pure bmrt, no sail, no pybind.
//
// Port of LLM-TPU models/Qwen3_ASR/python_demo/chat.cpp. The dataflow is that
// file's, step for step, because every departure from it is silent numeric
// drift rather than an error:
//
//   text embedding -> dev_buffer          (reference forward_embed)
//   audio tower -> audio_buffer           (reference forward_audio)
//   splice audio into dev_buffer at the offsets the prompt reserved
//   block_0 .. block_<N-1> -> lm_head     (reference forward_first)
//   embedding_cache + block_cache_i + lm_head, once per token
//                                         (reference forward_next)
//
// Three things are deliberately NOT the reference's:
//
//   * pybind11 is gone; the class is driven through the C ABI in c_api.cpp.
//     numpy arrays became plain pointers plus a count.
//   * ``forward_audio`` stages the tower's output in a buffer of its own
//     instead of writing straight into the embedding output buffer. The
//     reference is free to write there because its call order is fixed (embed,
//     then audio); this ABI lets a caller run the tower first, and writing into
//     a buffer the *next* embedding launch will overwrite would make the two
//     orders mean different things. The splice happens in forward_first, in
//     the reference's order, for a 26 KB copy per second of audio.
//   * buffers are reused across requests instead of allocated per call: one
//     worker serves many requests, and the reference allocates nothing at all
//     after init.
//
// The graphs are static (this build is ``_static_``) but the dynamic launch
// path is kept, because a rebuild with a dynamic prefill graph must not need an
// engine change: it sets the sequence dimensions from the real token count.

#include "asr_engine.h"

#include "aux_common.h"
#include "bmruntime_interface.h"
#include "bmlib_runtime.h"

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

struct AsrEngine::Impl {
  bm_handle_t handle = nullptr;
  void* bmrt = nullptr;
  std::mutex mu;  // one NPU: launches are serialised
  std::string last_error;

  const bm_net_info_t* net_embed = nullptr;
  const bm_net_info_t* net_embed_cache = nullptr;
  const bm_net_info_t* net_audio = nullptr;
  const bm_net_info_t* net_lm = nullptr;
  const bm_net_info_t* net_greedy_head = nullptr;
  std::vector<const bm_net_info_t*> net_blocks;
  std::vector<const bm_net_info_t*> net_blocks_cache;

  //: kv cache, per layer. These ARE the decode graphs' history_k/history_v
  //: input memories (the reference aliases them the same way).
  std::vector<bm_device_mem_t> past_key;
  std::vector<bm_device_mem_t> past_value;
  //: [MAX_INPUT_LENGTH, HIDDEN] in the embedding dtype: the hidden states the
  //: prefill blocks read. Also where the audio splice lands.
  bm_device_mem_t dev_buffer{};
  //: [MAX_INPUT_LENGTH, HIDDEN] in the same dtype: what the audio tower wrote,
  //: before the splice.
  bm_device_mem_t audio_buffer{};
  bool has_buffers = false;

  int seq_len = 0;          // SEQLEN: rows in the KV cache
  int max_input_length = 0; // MAX_INPUT_LENGTH: rows the prefill graphs take
  int audio_length = 0;     // mel frames per tower call
  int hidden_size = 0;
  int num_layers = 0;
  int kv_bytes = 0;         // one row of past_key (and of past_value)
  int tokens_per_chunk = 0; // audio tokens one tower call emits
  bool is_dynamic = false;
  bool prefill_mask = false;
  bool lmhead_with_topk = false;
  bool support_history = false;
  uint16_t mask_value = 0;
  int vocab_size = 0;
  int im_end = -1;

  int token_length = 0;    // prompt tokens embedded by the last forward_first
  int history_length = 0;  // KV rows written: prompt + generated so far

  // Audio staged by forward_audio: chunk-major features and where each chunk's
  // tokens go. Sized once, at load, to the prefill graph's capacity.
  std::vector<float> staged_feats;
  std::vector<int32_t> staged_offsets;
  int staged_chunks = 0;

  bool fail(const std::string& msg) {
    last_error = msg;
    return false;
  }

  void zero(bm_device_mem_t& m) {
    bm_memset_device_ext(handle, &aux::kZero, 1, m);
  }

  void zero_net(const bm_net_info_t* net, int stage = 0) {
    for (int i = 0; i < net->input_num; i++) zero(net->stages[stage].input_mems[i]);
    for (int i = 0; i < net->output_num; i++) zero(net->stages[stage].output_mems[i]);
  }

  void d2d(bm_device_mem_t& dst, size_t dst_off, bm_device_mem_t& src,
           size_t src_off, size_t bytes) {
    if (bytes == 0) return;
    bm_memcpy_d2d_byte(handle, dst, static_cast<unsigned int>(dst_off), src,
                       static_cast<unsigned int>(src_off),
                       static_cast<unsigned int>(bytes));
  }

  // Launches one graph over its own stage-0 memory.
  bool launch(const bm_net_info_t* net, int stage = 0) {
    if (!net) return fail("null net");
    std::vector<bm_tensor_t> in(static_cast<size_t>(net->input_num));
    std::vector<bm_tensor_t> out(static_cast<size_t>(net->output_num));
    for (int i = 0; i < net->input_num; i++) {
      bmrt_tensor_with_device(&in[static_cast<size_t>(i)],
                              net->stages[stage].input_mems[i], net->input_dtypes[i],
                              net->stages[stage].input_shapes[i]);
    }
    for (int i = 0; i < net->output_num; i++) {
      bmrt_tensor_with_device(&out[static_cast<size_t>(i)],
                              net->stages[stage].output_mems[i],
                              net->output_dtypes[i],
                              net->stages[stage].output_shapes[i]);
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

  // One decode step for layer `idx`, writing this token's K/V at kv_offset into
  // the layer's history. The reference's net_launch_decode, verbatim: the
  // position ids and the mask live in layer 0's input memories and every later
  // layer reads them from there, which is why only idx == 0 uploads them.
  bool launch_decode(int idx, int kv_offset, bm_device_mem_t& input_mem,
                     const int* pos_id, std::vector<uint16_t>& attention_mask) {
    const bm_net_info_t* net = net_blocks_cache[static_cast<size_t>(idx)];
    const bm_net_info_t* first = net_blocks_cache[0];
    std::vector<bm_tensor_t> in(5);
    std::vector<bm_tensor_t> out(3);
    bm_device_mem_t& in1_mem = first->stages[0].input_mems[1];
    bm_device_mem_t& in2_mem = first->stages[0].input_mems[2];
    bm_device_mem_t& in3_mem = net->stages[0].input_mems[3];
    bm_device_mem_t& in4_mem = net->stages[0].input_mems[4];
    bm_device_mem_t& out0_mem = net->stages[0].output_mems[0];

    bmrt_tensor_with_device(&in[0], input_mem, net->input_dtypes[0],
                            net->stages[0].input_shapes[0]);
    if (idx == 0) {
      if (bm_memcpy_s2d(handle, in1_mem, const_cast<int*>(pos_id)) != BM_SUCCESS) {
        return fail("copying decode position ids failed");
      }
      if (bm_memcpy_s2d(handle, in2_mem, attention_mask.data()) != BM_SUCCESS) {
        return fail("copying the decode attention mask failed");
      }
    }
    bmrt_tensor_with_device(&in[1], in1_mem, net->input_dtypes[1],
                            net->stages[0].input_shapes[1]);
    bmrt_tensor_with_device(&in[2], in2_mem, net->input_dtypes[2],
                            net->stages[0].input_shapes[2]);
    bmrt_tensor_with_device(&in[3], in3_mem, net->input_dtypes[3],
                            net->stages[0].input_shapes[3]);
    bmrt_tensor_with_device(&in[4], in4_mem, net->input_dtypes[4],
                            net->stages[0].input_shapes[4]);
    bmrt_tensor_with_device(&out[0], out0_mem, net->output_dtypes[0],
                            net->stages[0].output_shapes[0]);
    bm_device_mem_t k_mem = bm_mem_from_device(
        past_key[static_cast<size_t>(idx)].u.device.device_addr + kv_offset,
        static_cast<unsigned int>(kv_bytes));
    bm_device_mem_t v_mem = bm_mem_from_device(
        past_value[static_cast<size_t>(idx)].u.device.device_addr + kv_offset,
        static_cast<unsigned int>(kv_bytes));
    bmrt_tensor_with_device(&out[1], k_mem, net->output_dtypes[1],
                            net->stages[0].output_shapes[1]);
    bmrt_tensor_with_device(&out[2], v_mem, net->output_dtypes[2],
                            net->stages[0].output_shapes[2]);
    if (!bmrt_launch_tensor_ex(bmrt, net->name, in.data(), 5, out.data(), 3, true,
                              false)) {
      return fail(std::string("decode launch failed: ") + net->name);
    }
    return true;
  }

  // Argmax over the logits row, through the greedy_head graph (a separate graph
  // in bmodels whose lm_head returns logits rather than an id).
  int greedy_search(bm_device_mem_t& logits_mem) {
    if (!net_greedy_head) {
      fail("bmodel has no greedy_head and lm_head does not return a token id");
      return -1;
    }
    bm_device_mem_t& in_mem = net_greedy_head->stages[0].input_mems[0];
    bm_device_mem_t& out_mem = net_greedy_head->stages[0].output_mems[0];
    d2d(in_mem, 0, logits_mem, 0, bm_mem_get_device_size(logits_mem));
    if (!launch(net_greedy_head)) return -1;
    int token = 0;
    if (bm_memcpy_d2s(handle, &token, out_mem) != BM_SUCCESS) {
      fail("reading the greedy head's token failed");
      return -1;
    }
    return token;
  }

  // Launches lm_head over `hidden` (one row) and returns the token id. `row_off`
  // is the byte offset of that row inside `hidden`.
  int sample_lm(bm_device_mem_t& hidden, size_t row_off) {
    const size_t bytes = static_cast<size_t>(hidden_size) * sizeof(uint16_t);
    bm_device_mem_t& lm_in = net_lm->stages[0].input_mems[0];
    bm_device_mem_t& lm_out = net_lm->stages[0].output_mems[0];
    d2d(lm_in, 0, hidden, row_off, bytes);
    if (!launch(net_lm)) return -1;
    int token = 0;
    if (lmhead_with_topk) {
      if (bm_memcpy_d2s(handle, &token, lm_out) != BM_SUCCESS) {
        fail("reading the lm_head token failed");
        return -1;
      }
      return token;
    }
    return greedy_search(lm_out);
  }

  // The audio tower over the staged chunks. Writes chunk i's 13 tokens into
  // audio_buffer at i * 13 * HIDDEN * 2.
  bool run_audio_tower() {
    if (staged_chunks <= 0) return true;
    zero_net(net_audio);
    bm_device_mem_t& in_mem = net_audio->stages[0].input_mems[0];
    bm_device_mem_t& out_mem = net_audio->stages[0].output_mems[0];
    const size_t in_bytes = bm_mem_get_device_size(in_mem);
    const size_t out_bytes = bm_mem_get_device_size(out_mem);
    const size_t chunk_floats = in_bytes / sizeof(float);
    const size_t chunk_bytes = static_cast<size_t>(tokens_per_chunk) * hidden_size * 2;
    for (int i = 0; i < staged_chunks; i++) {
      const float* src = staged_feats.data() + static_cast<size_t>(i) * chunk_floats;
      if (bm_memcpy_s2d(handle, in_mem, const_cast<float*>(src)) != BM_SUCCESS) {
        return fail("copying audio features failed");
      }
      if (!launch(net_audio)) return false;
      d2d(audio_buffer, static_cast<size_t>(i) * chunk_bytes, out_mem, 0, out_bytes);
    }
    return true;
  }
};

AsrEngine::AsrEngine() : impl_(new Impl()) {}

AsrEngine::~AsrEngine() {
  if (!impl_) return;
  if (impl_->has_buffers && impl_->handle) {
    bm_free_device(impl_->handle, impl_->dev_buffer);
    bm_free_device(impl_->handle, impl_->audio_buffer);
  }
  if (impl_->bmrt) bmrt_destroy(impl_->bmrt);
  if (impl_->handle) bm_dev_free(impl_->handle);
  delete impl_;
}

int AsrEngine::seq_len() const { return impl_->seq_len; }
int AsrEngine::max_input_length() const { return impl_->max_input_length; }
int AsrEngine::audio_length() const { return impl_->audio_length; }
int AsrEngine::hidden_size() const { return impl_->hidden_size; }
int AsrEngine::num_layers() const { return impl_->num_layers; }
int AsrEngine::tokens_per_chunk() const { return impl_->tokens_per_chunk; }
int AsrEngine::im_end_id() const { return impl_->im_end; }
int AsrEngine::vocab_size() const { return impl_->vocab_size; }
std::string AsrEngine::last_error() const { return impl_->last_error; }

void AsrEngine::set_vocab(int vocab, int im_end) {
  impl_->vocab_size = vocab;
  impl_->im_end = im_end;
}

bool AsrEngine::load(const std::string& model_path, int dev_id) {
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
  e.net_embed_cache = bmrt_get_network_info(e.bmrt, "embedding_cache");
  e.net_audio = bmrt_get_network_info(e.bmrt, "audio");
  e.net_lm = bmrt_get_network_info(e.bmrt, "lm_head");
  if (!e.net_embed) return e.fail("bmodel has no 'embedding' graph");
  if (!e.net_embed_cache) return e.fail("bmodel has no 'embedding_cache' graph");
  if (!e.net_audio) return e.fail("bmodel has no 'audio' graph");
  if (!e.net_lm) return e.fail("bmodel has no 'lm_head' graph");

  const char** net_names = nullptr;
  const int num_nets = bmrt_get_network_number(e.bmrt);
  bmrt_get_network_names(e.bmrt, &net_names);
  auto exists = [&](const std::string& name) {
    for (int i = 0; i < num_nets; i++) {
      if (name == net_names[i]) return true;
    }
    return false;
  };
  e.net_greedy_head = exists("greedy_head")
                          ? bmrt_get_network_info(e.bmrt, "greedy_head")
                          : nullptr;
  for (int i = 0;; i++) {
    const std::string block = "block_" + std::to_string(i);
    const std::string cache = "block_cache_" + std::to_string(i);
    if (!exists(block) || !exists(cache)) break;
    e.net_blocks.push_back(bmrt_get_network_info(e.bmrt, block.c_str()));
    e.net_blocks_cache.push_back(bmrt_get_network_info(e.bmrt, cache.c_str()));
  }
  free(net_names);
  e.num_layers = static_cast<int>(e.net_blocks.size());
  if (e.num_layers == 0) return e.fail("bmodel has no block_<i>/block_cache_<i> graphs");

  const bm_data_type_t attn_dtype = e.net_embed_cache->output_dtypes[0];
  if (attn_dtype == BM_FLOAT16) {
    e.mask_value = 0xF0E2;  // -inf in fp16
  } else if (attn_dtype == BM_BFLOAT16) {
    e.mask_value = 0xC61C;  // -10000 in bf16, as the reference uses
  } else {
    return e.fail("attention dtype is neither fp16 nor bf16; unsupported");
  }

  // The reference's ``support_history`` (chat.cpp:294): prefill blocks that take
  // the previous turn's K/V as *inputs*. This build's do not -- block_0 takes
  // (states, positions, mask) and *outputs* this prompt's K/V, which
  // forward_first copies into the cache the decode graphs read. So history is
  // supported either way; the flag only decides whether ``clear`` has to zero
  // anything, because without the inputs there is no cross-request path into
  // the cache at all.
  e.support_history = e.net_blocks[0]->input_num == 5;
  e.is_dynamic = e.net_blocks[0]->is_dynamic;
  e.prefill_mask = e.net_blocks[0]->input_num > 2;
  if (!e.prefill_mask) {
    return e.fail("prefill blocks take no attention mask; this bmodel cannot "
                  "serve a single unpadded request");
  }
  if (e.net_blocks[0]->output_num < 3) {
    // forward_first copies output 1 and 2 into the KV cache; a block that does
    // not emit them cannot feed the decode graphs.
    return e.fail("prefill blocks do not emit a KV cache; this bmodel cannot generate");
  }
  e.lmhead_with_topk = e.net_lm->stages[0].output_shapes[0].dims[1] == 1;
  e.max_input_length = e.net_embed->stages[0].input_shapes[0].dims[1];
  e.hidden_size = e.net_lm->stages[0].input_shapes[0].dims[1];
  e.seq_len = e.net_blocks_cache[0]->stages[0].input_shapes[3].dims[1];
  e.audio_length = e.net_audio->stages[0].input_shapes[0].dims[3];
  e.kv_bytes = static_cast<int>(
      bm_mem_get_device_size(e.net_blocks_cache[0]->stages[0].output_mems[1]));
  // 13 tokens per 1 s chunk, i.e. what the three stride-2 convolutions in the
  // tower produce from `audio_length` mel frames. Read from the graph rather
  // than hard-coded so a rebuild with a different window still lines up.
  e.tokens_per_chunk = e.net_audio->stages[0].output_shapes[0].dims[1];

  if (e.max_input_length <= 0 || e.hidden_size <= 0 || e.seq_len <= 0 ||
      e.audio_length <= 0 || e.kv_bytes <= 0 || e.tokens_per_chunk <= 0) {
    return e.fail("bmodel reports a nonsensical graph shape");
  }
  if (e.seq_len < e.max_input_length) {
    return e.fail("SEQLEN is smaller than MAX_INPUT_LENGTH; the prompt would "
                  "not fit the KV cache");
  }

  // The KV memories are the decode graphs' own history inputs.
  e.past_key.resize(static_cast<size_t>(e.num_layers));
  e.past_value.resize(static_cast<size_t>(e.num_layers));
  for (int i = 0; i < e.num_layers; i++) {
    const bm_net_info_t* cache = e.net_blocks_cache[static_cast<size_t>(i)];
    e.past_key[static_cast<size_t>(i)] = cache->stages[0].input_mems[3];
    e.past_value[static_cast<size_t>(i)] = cache->stages[0].input_mems[4];
    e.zero(e.past_key[static_cast<size_t>(i)]);
    e.zero(e.past_value[static_cast<size_t>(i)]);
  }

  const auto buffer_size =
      bm_mem_get_device_size(e.net_embed->stages[0].output_mems[0]);
  if (bm_malloc_device_byte_heap_mask(e.handle, &e.dev_buffer, kNpuHeapMask,
                                      buffer_size) != BM_SUCCESS) {
    return e.fail("NPU heap exhausted allocating the embedding buffer");
  }
  if (bm_malloc_device_byte_heap_mask(e.handle, &e.audio_buffer, kNpuHeapMask,
                                      buffer_size) != BM_SUCCESS) {
    return e.fail("NPU heap exhausted allocating the audio buffer");
  }
  e.has_buffers = true;

  e.staged_feats.assign(
      static_cast<size_t>(e.max_input_length) * e.audio_length, 0.0f);
  e.staged_offsets.assign(static_cast<size_t>(e.max_input_length), 0);
  return true;
}

bool AsrEngine::forward_audio(const float* feats, int n_chunks,
                              const int32_t* offsets) {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  e.staged_chunks = 0;
  if (n_chunks <= 0) return true;  // no audio: a text-only prompt is legal
  if (!feats || !offsets) return e.fail("forward_audio: null features or offsets");
  const int cap = e.max_input_length / e.tokens_per_chunk;
  if (n_chunks > cap) {
    return e.fail("forward_audio: " + std::to_string(n_chunks) +
                  " audio chunks exceed the prompt capacity of " +
                  std::to_string(cap));
  }
  const size_t per_chunk = static_cast<size_t>(128) * e.audio_length;
  const size_t need = static_cast<size_t>(n_chunks) * per_chunk;
  if (e.staged_feats.size() < need) e.staged_feats.resize(need);
  std::memcpy(e.staged_feats.data(), feats, need * sizeof(float));

  const int audio_tokens = n_chunks * e.tokens_per_chunk;
  for (int i = 0; i < n_chunks; i++) {
    const int at = offsets[i];
    if (at < 0 || at + e.tokens_per_chunk > e.max_input_length) {
      return e.fail("forward_audio: chunk " + std::to_string(i) +
                    " lands outside the prompt");
    }
    e.staged_offsets[static_cast<size_t>(i)] = at;
  }
  if (audio_tokens <= 0) return e.fail("forward_audio: no audio tokens");
  e.staged_chunks = n_chunks;
  return true;
}

int AsrEngine::forward_first(const int32_t* ids, int n) {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  if (!ids || n <= 0) {
    e.fail("forward_first: empty prompt");
    return -1;
  }
  if (n > e.max_input_length) {
    e.fail("forward_first: prompt is " + std::to_string(n) +
           " tokens, this bmodel takes at most " +
           std::to_string(e.max_input_length));
    return -1;
  }
  if (n + 1 > e.seq_len) {
    e.fail("forward_first: prompt is " + std::to_string(n) +
           " tokens, more than the KV cache holds (" +
           std::to_string(e.seq_len) + ")");
    return -1;
  }
  if (e.vocab_size > 0) {
    for (int i = 0; i < n; i++) {
      if (ids[i] < 0 || ids[i] >= e.vocab_size) {
        e.fail("forward_first: token " + std::to_string(ids[i]) +
               " is outside the vocabulary (0.." +
               std::to_string(e.vocab_size - 1) + ")");
        return -1;
      }
    }
  }

  // -- text embedding (reference forward_embed) ----------------------------
  // The graph reads MAX_INPUT_LENGTH rows, so the tail past `n` must be zero
  // rather than whatever the previous request left there.
  bm_device_mem_t& embed_in = e.net_embed->stages[0].input_mems[0];
  bm_device_mem_t& embed_out = e.net_embed->stages[0].output_mems[0];
  if (bm_memset_device_ext(e.handle, &aux::kZero, 1, embed_in) != BM_SUCCESS) {
    e.fail("memset of the embedding input failed");
    return -1;
  }
  if (bm_memcpy_s2d_partial(e.handle, embed_in, const_cast<int32_t*>(ids),
                            static_cast<unsigned int>(n * sizeof(int32_t))) !=
      BM_SUCCESS) {
    e.fail("copying prompt tokens to the device failed");
    return -1;
  }
  if (!e.launch(e.net_embed)) return -1;
  e.d2d(e.dev_buffer, 0, embed_out, 0, bm_mem_get_device_size(embed_out));
  e.token_length = n;

  // -- audio tower + splice (reference forward_audio) ---------------------
  // Runs after the embedding, exactly as the reference does, so the audio
  // overwrites the placeholder rows the embedding produced for the audio pad
  // tokens -- never the other way round.
  if (!e.run_audio_tower()) return -1;
  const size_t chunk_bytes =
      static_cast<size_t>(e.tokens_per_chunk) * e.hidden_size * sizeof(uint16_t);
  for (int i = 0; i < e.staged_chunks; i++) {
    e.d2d(e.dev_buffer,
          static_cast<size_t>(e.staged_offsets[static_cast<size_t>(i)]) *
              e.hidden_size * sizeof(uint16_t),
          e.audio_buffer, static_cast<size_t>(i) * chunk_bytes, chunk_bytes);
  }

  // -- prefill -----------------------------------------------------------
  // Causal mask: 0 on and below the diagonal, mask_value above. The static
  // graphs read the whole MAX_INPUT_LENGTH square; the dynamic ones read n.
  std::vector<uint16_t> attn_mask;
  if (e.prefill_mask) {
    const int dim = e.is_dynamic ? n : e.max_input_length;
    attn_mask.assign(static_cast<size_t>(dim) * dim, e.mask_value);
    for (int i = 0; i < n; i++) {
      for (int j = 0; j <= i; j++) attn_mask[static_cast<size_t>(i) * dim + j] = 0;
    }
  }
  // Positions 0..n-1 in all three M-RoPE planes: one unpadded sequence.
  std::vector<int32_t> pos;
  if (e.is_dynamic) {
    pos.assign(static_cast<size_t>(n) * 3, 0);
    for (int plane = 0; plane < 3; plane++) {
      for (int i = 0; i < n; i++) {
        pos[static_cast<size_t>(plane) * n + i] = i;
      }
    }
  } else {
    pos.assign(static_cast<size_t>(e.max_input_length) * 3, 0);
    for (int plane = 0; plane < 3; plane++) {
      for (int i = 0; i < n; i++) {
        pos[static_cast<size_t>(plane) * e.max_input_length + i] = i;
      }
    }
  }

  bm_device_mem_t* out_mem = &e.dev_buffer;
  e.zero_net(e.net_blocks[0]);
  for (int idx = 0; idx < e.num_layers; idx++) {
    const bm_net_info_t* block = e.net_blocks[static_cast<size_t>(idx)];
    bm_device_mem_t& in0 = block->stages[0].input_mems[0];
    bm_device_mem_t& in1 = block->stages[0].input_mems[1];
    bm_device_mem_t& in2 = block->stages[0].input_mems[2];
    e.d2d(in0, 0, *out_mem, 0, bm_mem_get_device_size(*out_mem));
    if (idx == 0) {
      if (e.is_dynamic) {
        if (bm_memcpy_s2d_partial(e.handle, in1, pos.data(),
                                  static_cast<unsigned int>(n * 3 * sizeof(int32_t))) !=
            BM_SUCCESS) {
          e.fail("copying prefill position ids failed");
          return -1;
        }
        if (e.prefill_mask &&
            bm_memcpy_s2d_partial(e.handle, in2, attn_mask.data(),
                                  static_cast<unsigned int>(n * n * sizeof(uint16_t))) !=
                BM_SUCCESS) {
          e.fail("copying the prefill attention mask failed");
          return -1;
        }
      } else {
        if (bm_memcpy_s2d(e.handle, in1, pos.data()) != BM_SUCCESS) {
          e.fail("copying prefill position ids failed");
          return -1;
        }
        if (e.prefill_mask &&
            bm_memcpy_s2d(e.handle, in2, attn_mask.data()) != BM_SUCCESS) {
          e.fail("copying the prefill attention mask failed");
          return -1;
        }
      }
    }
    if (e.is_dynamic) {
      if (!e.launch_dyn(block, n)) return -1;
    } else if (!e.launch(block)) {
      return -1;
    }
    out_mem = &block->stages[0].output_mems[0];
    // The prefill blocks emit this layer's K/V for all n prompt tokens; copy
    // them into the cache the decode graphs read.
    e.d2d(e.past_key[static_cast<size_t>(idx)], 0,
          block->stages[0].output_mems[1], 0,
          bm_mem_get_device_size(block->stages[0].output_mems[1]));
    e.d2d(e.past_value[static_cast<size_t>(idx)], 0,
          block->stages[0].output_mems[2], 0,
          bm_mem_get_device_size(block->stages[0].output_mems[2]));
  }

  const int token =
      e.sample_lm(*out_mem, static_cast<size_t>(n - 1) * e.hidden_size * sizeof(uint16_t));
  if (token < 0) return -1;
  e.token_length = n + 1;
  e.history_length = n + 1;
  return token;
}

int AsrEngine::forward_next() {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  if (e.history_length <= 0 || e.token_length <= 0) {
    e.fail("forward_next: no prompt has been pre-filled yet");
    return -1;
  }
  if (e.history_length >= e.seq_len) {
    e.fail("forward_next: the KV cache is full (" + std::to_string(e.seq_len) +
           " tokens)");
    return -1;
  }

  // Keys 0 .. history_length-2 are visible; the row this step writes is not.
  // The decode graphs' mask is SEQLEN + 1 wide (one slot for the new row).
  std::vector<uint16_t> attn_mask(static_cast<size_t>(e.seq_len) + 1, 0);
  for (int i = e.history_length - 1; i < e.seq_len; i++) {
    attn_mask[static_cast<size_t>(i)] = e.mask_value;
  }
  const int plane[1] = {e.history_length - 1};

  // The token lm_head produced last is still in its output memory; embed it.
  bm_device_mem_t& lm_out = e.net_lm->stages[0].output_mems[0];
  bm_device_mem_t& cache_in = e.net_embed_cache->stages[0].input_mems[0];
  bm_device_mem_t& cache_out = e.net_embed_cache->stages[0].output_mems[0];
  e.d2d(cache_in, 0, lm_out, 0, bm_mem_get_device_size(lm_out));
  if (!e.launch(e.net_embed_cache)) return -1;

  bm_device_mem_t* out_mem = &cache_out;
  const int token_offset = (e.history_length - 1) * e.kv_bytes;
  for (int idx = 0; idx < e.num_layers; idx++) {
    if (!e.launch_decode(idx, token_offset, *out_mem, plane, attn_mask)) return -1;
    out_mem = &e.net_blocks_cache[static_cast<size_t>(idx)]->stages[0].output_mems[0];
  }

  const int token = e.sample_lm(*out_mem, 0);
  if (token < 0) return -1;
  e.token_length++;
  e.history_length++;
  return token;
}

void AsrEngine::clear() {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  // Every generation starts from an empty history: a request must never see a
  // previous request's context. The whole cache is zeroed (as the reference
  // does) rather than only the rows the last request wrote -- the KV memory is
  // the decode graphs' own input, and leaving a stale row reachable through a
  // mask that was built for a different length is exactly the kind of state
  // leak that shows up later as one request's transcript bleeding into the
  // next.
  for (int i = 0; i < e.num_layers; i++) {
    e.zero(e.past_key[static_cast<size_t>(i)]);
    e.zero(e.past_value[static_cast<size_t>(i)]);
  }
  e.history_length = 0;
  e.token_length = 0;
  e.staged_chunks = 0;
}

}  // namespace cv84x6
