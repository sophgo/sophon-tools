// Qwen3-VL/WeMM: one resident encoder, no state retained between inputs.
#pragma once

#include "vision.h"
#include <cstdint>
#include <memory>
#include <string>

namespace cv84x6 {

struct VlEmbedTimings {
  double embedding_ms = 0;
  double vision_ms = 0;
  double encoder_ms = 0;
};

class VlEmbedEngine {
 public:
  VlEmbedEngine();
  ~VlEmbedEngine();
  VlEmbedEngine(const VlEmbedEngine&) = delete;
  VlEmbedEngine& operator=(const VlEmbedEngine&) = delete;
  bool load(const std::string& path, int device);
  int seq_len() const;
  int hidden_size() const;
  int max_patches() const;
  bool is_wemm() const;
  bool faulted() const;
  std::string last_error() const;
  // image may be null. offset is the first image_pad token, and all of that
  // image's patches must fit in the prompt. Returns a normalised MRL prefix.
  bool forward(const int32_t* ids, int n, const VisionInput* image, int offset,
               int dimensions, float* out, VlEmbedTimings* timings);
 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace cv84x6
