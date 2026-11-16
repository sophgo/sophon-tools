// Public interface of the auxiliary-model engines (embedding / rerank).
//
// Same contract as llm_engine.h: no Sophon type in the signature, errors come
// back as a bool plus a message, and the Python worker drives this through the
// flat C ABI in c_api.cpp. The two engines are ports of LLM-TPU's
// models/Qwen3_Embedding/python_demo/chat.cpp and
// models/Bge_Reranker_V2_M3/python_demo/chat.cpp with the pybind11 layer
// removed -- the numerics are the reference's, deliberately unchanged, because
// the numbers those demos produce are what this service has to reproduce.
//
// Both are single-shot: no KV cache, no sessions, no state between calls. One
// call = one forward over the tokens given, which is why they live in their own
// classes rather than behind cv84x6::Engine (whose whole complexity is the
// resident/parked session state a chat model needs).

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace cv84x6 {

// Non-generative text embedder: last-token pooling over the hidden states, then
// (optionally) MRL truncation, then L2 normalisation.
class EmbedEngine {
 public:
  EmbedEngine();
  ~EmbedEngine();
  EmbedEngine(const EmbedEngine&) = delete;
  EmbedEngine& operator=(const EmbedEngine&) = delete;

  // `dev_id` is the NPU index (0 on CV84X6). False on failure; see last_error.
  bool load(const std::string& model_path, int dev_id);

  int seq_len() const;      // longest input the graphs accept
  int hidden_size() const;  // width of the pooled vector before truncation

  // Runs `n` tokens through the model and fills `out` with `dim` floats: the
  // last row of the output hidden state, truncated to `dim` and L2-normalised.
  // `dim` is clamped to hidden_size(); it is NOT required to be in
  // [32, hidden] here -- the HTTP layer owns that rule, because it is a policy
  // about the API, not about the graph.
  bool forward(const int32_t* tokens, int n, int dim, float* out);

  std::string last_error() const;

 private:
  struct Impl;
  Impl* impl_;
};

// Cross-encoder reranker (XLM-R base): returns one raw logit per query/document
// pair. Padding, position ids and the additive mask follow the reference demo
// exactly -- the differences there are silent numeric drift, not errors.
class RerankEngine {
 public:
  RerankEngine();
  ~RerankEngine();
  RerankEngine(const RerankEngine&) = delete;
  RerankEngine& operator=(const RerankEngine&) = delete;

  bool load(const std::string& model_path, int dev_id);

  int seq_len() const;
  int hidden_size() const;

  // `input_ids` and `attention_mask` are `seq_len` long (right-padded, as the
  // reference tokenises them); `position_ids` are `seq_len` long too and are
  // derived by the caller to match the demo's XLM-R rule. Returns the raw logit
  // in `*out`.
  bool forward(const int32_t* input_ids, const int32_t* position_ids,
               const int32_t* attention_mask, float* out);

  std::string last_error() const;

 private:
  struct Impl;
  Impl* impl_;
};

}  // namespace cv84x6
