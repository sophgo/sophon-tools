// Public interface of the ASR engine (Qwen3-ASR on CV84X6).
//
// Same contract as aux_engine.h: no Sophon type in the signature, errors come
// back as a bool plus a message, and the Python worker drives this through the
// flat C ABI in c_api.cpp. The class is a port of LLM-TPU's
// models/Qwen3_ASR/python_demo/chat.cpp with the pybind11 layer removed -- the
// numerics are the reference's, deliberately unchanged.
//
// The engine is a *generative* one (unlike embedding/rerank): it owns a KV
// cache and therefore a session's history. The service uses it as a single-shot
// machine -- one request = one clear/forward_first/forward_next... sequence --
// because holding context across requests would make one client's transcript
// depend on another's. ``clear`` is what makes that a fact rather than a
// convention.
//
// Three entry points mirror the reference's dataflow:
//
//   forward_audio(feats, n_chunks, offsets)   audio tower -> audio embeddings
//   forward_first(ids, n)                     text embedding (+ audio splice),
//                                             prefill, returns the first token
//   forward_next()                            one decode step, returns a token
//
// The reference's ``forward_embed`` is folded into ``forward_first`` so a
// caller cannot run the audio tower after the text embedding has overwritten
// the buffer the audio has to be spliced into; see the .cpp for why that is
// numerically identical to the reference's order.

#pragma once

#include <cstdint>
#include <string>

namespace cv84x6 {

class AsrEngine {
 public:
  AsrEngine();
  ~AsrEngine();
  AsrEngine(const AsrEngine&) = delete;
  AsrEngine& operator=(const AsrEngine&) = delete;

  // ``dev_id`` is the NPU index (0 on CV84X6). False on failure; see last_error.
  bool load(const std::string& model_path, int dev_id);

  int seq_len() const;         // SEQLEN from the decode graphs (KV capacity)
  int max_input_length() const;  // MAX_INPUT_LENGTH: prefill graph capacity
  int audio_length() const;    // mel frames per audio-tower call (AUDIO_LENGTH)
  int hidden_size() const;
  int num_layers() const;
  int tokens_per_chunk() const;  // audio tokens the tower emits per call (13)

  // Runs the audio tower over ``n_chunks`` feature blocks of
  // [1, 128, audio_length] floats (chunk-major: chunk 0's 128 rows, then chunk
  // 1's, ...). ``offsets[i]`` is the absolute prompt position the i-th chunk's
  // tokens occupy; they are applied by forward_first.
  //
  // The features are log-mel values (the Python front end produced them); no
  // scaling happens here, exactly as in the reference.
  bool forward_audio(const float* feats, int n_chunks, const int32_t* offsets);

  // Embeds ``n`` prompt token ids, splices the audio embeddings staged by the
  // last forward_audio, prefills, and returns the first generated token.
  // Returns -1 on failure (see last_error).
  //
  // Positions are 0..n-1 in all three M-RoPE planes, which is what the
  // reference's get_rope_index produces for one unpadded sequence -- and a
  // single request is always one unpadded sequence here.
  int forward_first(const int32_t* ids, int n);

  // One decode step: consumes the token forward_first/forward_next returned
  // last, and returns the next one, or -1 on failure.
  int forward_next();

  // Drops the KV state of the previous request. Called before every
  // transcription; see the .cpp for why this zeroes only the rows a previous
  // request actually wrote rather than the whole cache.
  void clear();

  std::string last_error() const;

  // The token the caller must stop on and the vocabulary size, so the engine
  // can reject an out-of-range id before it hands it to the embedding graph.
  // 0 disables the check; -1 means "no stop token known".
  void set_vocab(int vocab_size, int im_end_id);
  int im_end_id() const;
  int vocab_size() const;

 private:
  struct Impl;
  Impl* impl_;
};

}  // namespace cv84x6
