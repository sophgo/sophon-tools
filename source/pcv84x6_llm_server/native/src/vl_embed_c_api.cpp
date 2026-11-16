#include "vl_embed_engine.h"
#include <exception>
#include <memory>

namespace {
thread_local std::string error_text;
void error(const char** out, const std::string& message) {
  error_text = message;
  if (out) *out = error_text.c_str();
}
}

extern "C" {
void* cv_vle_create(const char* path, int dev, const char** err) {
  try {
    if (!path) { error(err, "null model path"); return nullptr; }
    auto engine = std::make_unique<cv84x6::VlEmbedEngine>();
    if (!engine->load(path, dev)) { error(err, engine->last_error()); return nullptr; }
    return engine.release();
  } catch (const std::exception& e) { error(err, e.what()); return nullptr; }
}
void cv_vle_destroy(void* h) { delete static_cast<cv84x6::VlEmbedEngine*>(h); }
int cv_vle_fault(void* h) {
  return !h || static_cast<cv84x6::VlEmbedEngine*>(h)->faulted();
}
int cv_vle_info(void* h, int* seq, int* hidden, int* patches) {
  if (!h || !seq || !hidden || !patches) return -1;
  auto* e = static_cast<cv84x6::VlEmbedEngine*>(h);
  *seq = e->seq_len(); *hidden = e->hidden_size(); *patches = e->max_patches();
  return 0;
}
int cv_vle_family(void* h) {
  return h ? (static_cast<cv84x6::VlEmbedEngine*>(h)->is_wemm() ? 1 : 0) : -1;
}
void* cv_vle_image_create_ex(const unsigned char* data, int len, int max_patches, int min_pixels,
                           int rgba_white_background, int* grid_h, int* grid_w, const char** err) {
  try {
    if (!data || len <= 0 || max_patches <= 0 || !grid_h || !grid_w ||
        (rgba_white_background != 0 && rgba_white_background != 1) ||
        min_pixels < 1024 || min_pixels > static_cast<int64_t>(max_patches) * 256) {
      error(err, "invalid image arguments"); return nullptr;
    }
    cv84x6::VisionConfig config;
    config.fused_normalize = true;
    config.max_source_pixels = 16 * 1024 * 1024;
    config.max_patches = max_patches;
    config.max_pixels = static_cast<int64_t>(max_patches) * 256;
    config.min_pixels = min_pixels;
    config.rgba_white_background = rgba_white_background != 0;
    auto input = std::make_unique<cv84x6::VisionInput>();
    std::string why;
    if (!cv84x6::preprocess_image(std::string(reinterpret_cast<const char*>(data), len),
                                config, input.get(), &why)) {
      error(err, why); return nullptr;
    }
    *grid_h = input->grid_h; *grid_w = input->grid_w;
    return input.release();
  } catch (const std::exception& e) { error(err, e.what()); return nullptr; }
}
void* cv_vle_image_create(const unsigned char* data, int len, int max_patches,
                         int* grid_h, int* grid_w, const char** err) {
  return cv_vle_image_create_ex(data, len, max_patches, 4096, 0, grid_h, grid_w, err);
}
void cv_vle_image_destroy(void* h) { delete static_cast<cv84x6::VisionInput*>(h); }
int cv_vle_forward(void* h, const int32_t* ids, int n, void* image, int offset,
                    int dimensions, float* out, double* timing, const char** err) {
  try {
    if (!h) { error(err, "null encoder handle"); return -1; }
    auto* e = static_cast<cv84x6::VlEmbedEngine*>(h);
    cv84x6::VlEmbedTimings t;
    if (!e->forward(ids, n, static_cast<cv84x6::VisionInput*>(image), offset, dimensions, out, &t)) {
      error(err, e->last_error()); return -1;
    }
    if (timing) { timing[0] = t.embedding_ms; timing[1] = t.vision_ms; timing[2] = t.encoder_ms; }
    return 0;
  } catch (const std::exception& e) { error(err, e.what()); return -1; }
}
}
