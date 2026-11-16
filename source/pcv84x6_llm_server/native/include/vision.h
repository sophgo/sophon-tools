// Image decoding and the Qwen-VL / Qwen3-VL image preprocessing, without
// torch, transformers, pillow or qwen_vl_utils.
//
// Everything here is host-side arithmetic on an RGB buffer, so it is verified
// by comparing against the Python reference *element for element* on a normal
// workstation -- no NPU, no board. tests/vision_golden.json holds the reference
// output (tools/gen_vision_golden.py); tools/vision_check.cpp replays it.
//
// What is reproduced, and from where:
//
//   decode      JPEG via libjpeg (the same libjpeg-turbo the reference Pillow
//               is built against, so coefficients and IDCT are identical) and
//               PNG via zlib; both then flatten to RGB the way
//               Image.open(...).convert("RGB") does.
//   smart_resize qwen_vl_utils.vision_process.smart_resize, including its
//               round/floor/ceil-by-factor rules and its 200:1 aspect guard.
//   resize      PIL Image.resize(size) with the default BICUBIC filter: a
//               separable convolution with support 2.0*filterscale, fixed-point
//               coefficients (PRECISION_BITS 22) and Pillow's clip8. RGB images
//               are Pillow's "bands == 3" case, so the horizontal pass writes
//               through a 4-byte-per-pixel intermediate, exactly as Pillow does.
//   normalize   /255 then (x - mean) / std with mean = std = 0.5.
//   patchify    Qwen2VLImageProcessor._preprocess: the
//               (t, tc, C, gh, m, p, gw, m, p) -> (t, gh, gw, m, m, C, tc, p, p)
//               transpose, i.e. flatten order matching the reference.
//
// Note the images are resized twice on purpose, and both steps are visible in
// the reference: qwen_vl_utils' process_vision_info resizes to the patch grid,
// then the HF image processor is called with do_resize=False. Reproduce both.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace cv84x6 {

// A decoded 8-bit RGB image, row-major, 3 bytes per pixel.
struct Image {
  int width = 0;
  int height = 0;
  std::vector<uint8_t> rgb;

  bool empty() const { return width <= 0 || height <= 0; }
};

// True when the bytes look like a JPEG or PNG this decoder accepts.
bool is_supported_image(const std::string& bytes);

// Decodes and converts to RGB. Returns false and fills `err` otherwise.
bool decode_image(const std::string& bytes, Image* out, std::string* err);
bool decode_image(const std::string& bytes, Image* out, std::string* err,
                  int64_t max_source_pixels);
bool decode_image(const std::string& bytes, Image* out, std::string* err,
                  int64_t max_source_pixels, bool rgba_white_background);

// What the vision graphs need. All values come from the bmodel or the model
// config, never guessed.
struct VisionConfig {
  int patch_size = 16;
  int temporal_patch_size = 2;
  int spatial_merge = 2;
  int grid_per_side = 48;   // vit positional-embedding table side
  int max_patches = 0;      // vit row budget; t*h*w may not exceed it
  int64_t min_pixels = 4 * 32 * 32;  // qwen_vl_utils IMAGE_MIN_TOKEN_NUM * 32^2
  int64_t max_pixels = 0;            // defaults to max_patches * patch^2
  // Qwen3-VL-Embedding's Torchvision processor fuses rescale into mean/std:
  // (uint8 - 127.5) / 127.5 in float32. The older NumPy path stays default.
  bool fused_normalize = false;
  // WeMM passes original images to qwen-vl-utils: RGBA is pasted onto white.
  // Legacy callers explicitly convert to RGB first and retain their behavior.
  bool rgba_white_background = false;
  int64_t max_source_pixels = 0;  // optional bound checked before decode allocation
};

// PIL's resize for one plane: `src` is `src_w` x `src_h`, 8-bit, `bands` bytes
// per pixel interleaved. Bicubic with support 2.0, as Pillow's default filter.
// Exposed so the golden test can check the resampler on its own.
void pil_resize(const uint8_t* src, int src_w, int src_h, int bands,
                uint8_t* dst, int dst_w, int dst_h);

// qwen_vl_utils.smart_resize: the (height, width) the image is resized to, so
// the prompt's <|image_pad|> count and the pixel buffer can never disagree.
bool smart_resize(int height, int width, int64_t min_pixels, int64_t max_pixels,
                  int factor, int* out_h, int* out_w, std::string* err);

// One preprocessed image.
struct VisionInput {
  // [patches, 3 * temporal_patch_size * patch_size^2], row-major float32.
  std::vector<float> pixels;
  int grid_t = 1;
  int grid_h = 0;
  int grid_w = 0;
  int patches() const { return grid_t * grid_h * grid_w; }
};

// decode -> smart_resize -> pil_resize -> normalize -> patchify.
bool preprocess_image(const std::string& bytes, const VisionConfig& cfg,
                      VisionInput* out, std::string* err);

// The ViT position tables, ported from the demo's rot_pos and
// fast_pos_embed_interpolate. `pos_ids` is [patches, 2]; `pos_idx` and
// `pos_weight` are [patches, 4].
void vision_rot_pos(int grid_t, int grid_h, int grid_w, std::vector<int32_t>* pos_ids);
void vision_pos_embed_interpolate(int grid_t, int grid_h, int grid_w, int grid_per_side,
                                  std::vector<int32_t>* pos_idx,
                                  std::vector<float>* pos_weight);

// The M-RoPE position matrix for a prompt that may contain images: [3, n]
// row-major int32, ported from the demo's get_rope_index. `image_grids` is one
// {t, h, w} per <|vision_start|> in `ids` (h, w are the *patch* grid).
void vision_rope_index(const std::vector<int32_t>& ids,
                       const std::vector<std::vector<int>>& image_grids,
                       int32_t vision_start_id, int32_t image_pad_id,
                       int spatial_merge, std::vector<int32_t>* pos3);

}  // namespace cv84x6
