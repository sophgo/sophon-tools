// A generic single-graph runner: one bmodel in, one forward out.
//
// The three engines beside this one (embed / rerank / ASR) each know their
// bmodel's topology by name -- "embedding", "block_3", "lm_head" -- because
// each reproduces one reference pipeline. That is the wrong shape for OCR,
// whose det and rec builds are plain static CNN graphs with one input and one
// output and no fixed names at all (``x`` in, ``fetch_name_0_Sigmoid`` out).
// So this class knows nothing about the graph: it reports the tensor shapes it
// found and runs whatever is loaded.
//
// What it deliberately does NOT do is pre- or post-process. Every number that
// turns pixels into a tensor -- resize, normalise, pad, softmax, CTC -- belongs
// to the pipeline in app/engine/ocr_ppocr.py, because those are the numbers the
// reference produces and they are checked against a golden. The engine only
// moves bytes: host float32 in, host float32 out, with the graph's own dtype
// handled here so a bf16 or fp16 rebuild needs no Python change.
//
// Host buffers are ALWAYS float32, on both sides. A graph that declares another
// width is converted here rather than in numpy: the conversion is the same
// arithmetic the other engines already do (aux_common.h), and doing it in one
// place keeps "what the model saw" and "what the caller computed" from being
// two different roundings.

#pragma once

#include <cstdint>
#include <string>

namespace cv84x6 {

class NetEngine {
 public:
  NetEngine();
  ~NetEngine();
  NetEngine(const NetEngine&) = delete;
  NetEngine& operator=(const NetEngine&) = delete;

  // Loads a bmodel that holds exactly one graph. False on failure; the reason
  // is in last_error() and names the graph count when that is what is wrong,
  // because "this file has 94 graphs" is a different mistake from "corrupt".
  bool load(const std::string& model_path, int dev_id);

  int num_inputs() const;
  int num_outputs() const;
  //: Number of stages (1 for every static build; kept for the dynamic case).
  int num_stages() const;

  // Writes the tensor's dims into `dims` (up to `cap`) and returns the rank, or
  // -1 when the index is out of range. A caller sizes its buffer from this.
  int input_dims(int index, int* dims, int cap) const;
  int output_dims(int index, int* dims, int cap) const;

  //: Element counts, i.e. what a caller must allocate.
  long long input_elements(int index) const;
  long long output_elements(int index) const;

  //: The graph's own dtype, as a bm_data_type_t value (see bmdef.h).
  int input_dtype(int index) const;
  int output_dtype(int index) const;

  // Runs the graph. `in` has num_inputs() float32 pointers of exactly
  // input_elements(i) each; `out` has num_outputs() float32 pointers of
  // output_elements(i) each. False on failure, reason in last_error().
  bool run(int stage, const float* const* in, float* const* out);

  std::string last_error() const;

 private:
  struct Impl;
  Impl* impl_;
};

}  // namespace cv84x6
