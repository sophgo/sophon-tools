// PaddleOCR-VL-1.5 on the NPU: one resident bmodel, one session at a time.
//
// This is the service-side port of tools/ocr/vl_native/vl_native.cpp (MYS-2660),
// which proved the decode path against the x86 reference on `.157`. The
// arithmetic is deliberately the same -- including the three fixes that were
// hard to find because each one produced valid tensor shapes and plausible
// tokens -- and the tests in tests/test_ocr_vl_native.py pin the parts of it
// that live in Python.
//
// What changed in the port, and why:
//
//   * the bmodel is loaded once and stays resident. The prototype reloaded the
//     2.27 GB file per element, which measured ~7 s of the ~8 s an element cost
//     (docs/ocr-vl.md §6): the cost was loading, not arithmetic.
//   * the KV buffers are allocated once with the weights and reused by every
//     request. There is exactly one session (one prompt at a time); the worker
//     serialises requests in front of it.
//   * the token ids, the image pixels and the vit grid come from the caller
//     rather than from a work directory: this runs inside the service, where
//     the prompt was rendered, tokenised and preprocessed in the worker.
//
// The KV scheme is option (a) from the card: block_cache_N's k_cache/v_cache
// outputs are bound to `bm_mem_from_device(cache + n * row)` -- a view of the
// persistent buffer at the row being written -- so the graph writes each new
// row straight into the cache and nothing is copied. MYS-2660 established that
// bmrt accepts caller memory here; what segfaulted in the earlier stage was the
// *readback* through a descriptor sized to the whole buffer (bmlib's
// bm_memcpy_d2s copies the descriptor's size, not the tensor's).
//
// The bmodel contract, read off the board's own bmrt:
//   vit             patch[T,3,14,14] f32 -> emb [1,T/4,1024] bf16
//   embedding       ids [1,SEQ] i32      -> [1,SEQ,1024] bf16
//   embedding_cache ids [1,1] i32        -> [1,1,1024] bf16
//   block_N         (x [1,SEQ,1024], pos [3,SEQ], mask [1,1,SEQ,SEQ])
//                     -> x', k [1,SEQ,2,128], v [1,SEQ,2,128]     addr_mode 0
//   block_cache_N   (x [1,1,1024], pos [3,1], mask [1,1,1,SEQ+1],
//                    history_k/v [1,SEQ,2,128])
//                     -> x', k_new [1,1,2,128], v_new [1,1,2,128]  addr_mode 1
//   lm_head         hidden [1,1024] bf16 -> token [1,1] i32
//
// Everything on the wire is bf16, which is raw 16-bit words and NOT a float;
// the widening and narrowing below are deliberate.

#pragma once

#include <cstdint>
#include <memory>
#include <string>

namespace cv84x6 {

// Wall-clock milliseconds of the last request's stages, so the service can log
// what an OCR request actually cost instead of a single opaque total.
struct VlTimings {
  double vit_ms;
  double embed_ms;
  double prefill_ms;
  double decode_ms;
  double lm_ms;
  int prompt_tokens;
  int image_tokens;
  int decode_steps;
};

// One loaded PaddleOCR-VL bmodel plus the persistent KV cache.
//
// Not thread-safe: the NPU is one device and the worker serialises requests in
// front of it. There is one session at a time by construction (single KV
// buffer), which is what the card asks for.
class VlEngine {
 public:
  VlEngine();
  ~VlEngine();
  VlEngine(const VlEngine&) = delete;
  VlEngine& operator=(const VlEngine&) = delete;

  bool load(const std::string& bmodel_path, int dev_id);
  std::string last_error() const;

  int seq_len() const;         // the decode graphs' SEQLEN (2048)
  int num_layers() const;      // 18
  int hidden_size() const;     // 1024
  int image_tokens() const;    // vit rows / spatial_merge^2, for a square grid
  int vit_patches() const;     // the vit graph's own patch count
  size_t kv_bytes_per_layer() const;

  // Runs one whole prompt: vit -> embedding -> splice -> prefill -> lm_head,
  // and leaves the first generated token ready for step().
  //
  // `ids` is the prompt with `head_len` text tokens before the image block and
  // `grid_h/2 * grid_w/2` placeholder rows there; `patches` is
  // grid_h*grid_w*3*14*14 floats, patch-major, already normalised (see
  // app/engine/paddle_vl.py -- the preprocessing is the same arithmetic
  // tools/ocr/vl_native_prep.py uses).
  bool prefill(const int32_t* ids, int n_ids, int head_len,
               int grid_h, int grid_w, const float* patches);

  // The next token: the one prefill left ready, then one decode step each call.
  // Returns -1 on error (see last_error()).
  int32_t step();

  VlTimings timings() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace cv84x6
