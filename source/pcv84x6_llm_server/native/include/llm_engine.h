// Public interface of the CV84X6 inference engine (Qwen3.5 / Qwen3.6 bmodels).
//
// Deliberately small and free of any Sophon type: the Python worker talks to
// this through a thin ctypes binding (src/c_api.cpp), and the only concepts it
// needs are "load a model", "make a session", "prefill", "decode one token".
// Tokenisation, chat templates, image preprocessing and M-RoPE position ids
// live in Python, exactly as in the vendor demo (sophon-demo qwen3_5.py).

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace cv84x6 {

class Session;

// One image's vit inputs, laid out exactly as the model's image processor and
// the demo's rot_pos / fast_pos_embed_interpolate produce them.
struct VitImage {
  int offset = 0;      // prompt row of the first <|image_pad|> token
  int patches = 0;     // t*h*w; the image occupies patches/4 prompt rows
  const float* pixels = nullptr;      // [patches, vit_dims]
  const int* pos_ids = nullptr;       // [patches, 2]
  const int* pos_idx = nullptr;       // [patches, 4]
  const float* pos_weight = nullptr;  // [patches, 4]
};

// One loaded bmodel. Owns the NPU handle, the weights, and the graphs' internal
// state memory, which always holds the state of exactly one ("resident")
// session; the others are parked in their own device buffers.
class Engine {
 public:
  Engine();
  ~Engine();
  Engine(const Engine&) = delete;
  Engine& operator=(const Engine&) = delete;

  bool load(const std::string& model_path, int dev_id);

  // All shapes come from the bmodel graphs, never from config.json.
  int num_layers() const;
  int context_length() const;    // SEQLEN of the decode graphs
  int max_input_length() const;  // longest prompt one prefill accepts
  int hidden_size() const;
  bool has_vision() const;
  int vit_max_patches() const;
  int vit_dims() const;
  // True for _history_ bmodels (block_kv_<i> graphs): prompts up to the full
  // context in chunks, Session::extend, and snapshots worth taking.
  bool supports_history() const;
  // Size of the model's embedding table, or 0 when the caller has not told us.
  // The bmodel itself does not expose it (lm_head fuses its argmax, so the
  // vocabulary never appears in a graph shape), so the tokenizer's owner sets
  // it. Every prompt token is range-checked against it: an out-of-range id is
  // an out-of-bounds gather inside the embedding graph, which the TPU cannot
  // reject, only fault on.
  void set_vocab_size(int n);
  int vocab_size() const;
  // NPU bytes one session's state takes when parked (FA KV for the whole
  // context + linear state): what each concurrent session can cost on top of
  // the weights.
  size_t session_state_bytes() const;
  // What a parked session actually costs: FA K+V per token of its context,
  // plus the fixed linear-attention state. Parked FA KV grows with the
  // session, so short sessions stay cheap on long-context models.
  size_t kv_bytes_per_token() const;
  size_t linear_state_bytes() const;
  // FA slots a parked session's buffer is rounded up to (MYS-2785): parking
  // allocates `round_up(tokens, this)` slots, not `tokens`, so a scheduler that
  // budgets the raw token count under-reserves by up to one granule. Exposed so
  // the Python accounting reads the engine's own constant instead of keeping a
  // second copy of it.
  int park_granule() const;
  // True once a launch or sync failed: the TPU is wedged until a reboot.
  bool fault() const;
  std::string last_error() const;

  // Returns nullptr only on allocation failure. Sessions must not outlive the
  // engine.
  std::unique_ptr<Session> new_session();

  // Snapshots (Session::snapshot) own NPU memory; free them here.
  static void free_snapshot(void* snap);
  static size_t snapshot_bytes(void* snap);

 private:
  static void free_snapshot_locked(void* snap);
  friend class Session;
  struct Impl;
  Impl* impl_;
};

// One conversation. Prefill replaces whatever the session held before.
class Session {
 public:
  ~Session();
  Session(const Session&) = delete;
  Session& operator=(const Session&) = delete;

  // Tokens currently held in this session's KV.
  int token_len() const;

  // Debug (LLM_DEBUG_HIDDEN=1): the last lm_head input row as raw bf16/fp16,
  // copied into `out` (up to n values). Returns the count, 0 when disabled.
  int last_hidden(uint16_t* out, int n) const;
  // Debug (LLM_DEBUG_HIDDEN=2): last-layer outputs of every row prefilled
  // since the previous call, raw bf16/fp16, row-major; clears them.
  int debug_rows(uint16_t* out, int n);

  // Prefill `n` tokens and sample the first output token, which the next
  // decode() returns. `pos3` is the [3, n] M-RoPE position matrix (row-major);
  // nullptr means plain text (all three rows 0..n-1). `images` are spliced
  // into the prompt embedding before the blocks run.
  bool prefill(const int* tokens, int n, const int* pos3,
               const VitImage* images, int n_images);

  // Append `n` tokens after the session's current state (history bmodels
  // only); `pos3` positions are absolute. Samples the next token like prefill.
  bool extend(const int* tokens, int n, const int* pos3,
              const VitImage* images, int n_images);

  // Returns the next token id, or -1 on error (see Engine::last_error()).
  //
  // On return the token is final: the graphs for it have retired on the TPU and
  // the session's state is complete, so the session can immediately be parked,
  // snapshotted, extended or decoded again. Inside the call the layers are
  // queued back to back and one sync covers the batch (the reference cpp demo
  // does the same); the sync sits before the first consumer of the result, not
  // after it.
  int decode();

  // The next prefill()/extend() runs its last `rows` tokens through the decode
  // graphs (one token at a time, ~40 ms each) instead of the prefill graphs.
  // On CV84X6 the prefill graphs' routed-expert MoE is inaccurate (MYS-2293:
  // ~0.75 cosine to the reference at layer 0, vs 0.9999 for the decode
  // graphs); replaying the end of the prompt exactly corrects the state the
  // answer is generated from. Applies to one call, then resets to 0.
  void set_exact_tail(int rows);

  // Copy of the state at the current length (FA KV + linear state + last token).
  // Valid only for exactly this prefix: linear state cannot be rolled back.
  void* snapshot();
  // Replace this session's state with a snapshot. decode() continues with the
  // restored last token; extend() instead appends the next prompt segment.
  bool restore(void* snap);

 private:
  Session();
  bool prefill_impl(const int* tokens, int n, const int* pos3,
                    const VitImage* images, int n_images, bool append);
  friend class Engine;
  struct Impl;
  Impl* impl_ = nullptr;
};

}  // namespace cv84x6
