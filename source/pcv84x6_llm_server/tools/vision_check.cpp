// Vision pipeline conformance check against tests/vision_golden.json.
//
// Image preprocessing is pure host software, so this runs anywhere -- no board,
// no NPU. It decodes each fixture, runs the C++ pipeline, and compares against
// what the reference stack (torch/transformers/pillow/qwen_vl_utils) produced,
// bit for bit.
//
//   vision_check <golden.json> <fixtures dir>
//
// Exits non-zero on mismatch and reports which stage diverged first, so a
// decoder difference is not confused with a resize difference.

#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "json_lite.h"
#include "vision.h"

namespace {

std::string read_file(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  std::ostringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

// Minimal base64 decoder for the golden payload.
std::vector<uint8_t> b64decode(const std::string& in) {
  static int8_t map[256];
  static bool init = false;
  if (!init) {
    for (int i = 0; i < 256; ++i) map[i] = -1;
    const char* a = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (int i = 0; i < 64; ++i) map[static_cast<unsigned char>(a[i])] = int8_t(i);
    init = true;
  }
  std::vector<uint8_t> out;
  out.reserve(in.size() * 3 / 4);
  int val = 0, bits = 0;
  for (unsigned char c : in) {
    if (c == '=' || c == '\n' || c == '\r') continue;
    const int8_t d = map[c];
    if (d < 0) continue;
    val = (val << 6) | d;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push_back(static_cast<uint8_t>((val >> bits) & 0xFF));
    }
  }
  return out;
}

const float* as_floats(const std::vector<uint8_t>& b) {
  return reinterpret_cast<const float*>(b.data());
}

// Compares float32 buffers bitwise: the pipeline is deterministic, so any
// difference at all means the port diverged, not that it is "close enough".
bool same_bits(const std::vector<float>& got, const std::vector<uint8_t>& want) {
  if (got.size() * sizeof(float) != want.size()) return false;
  return std::memcmp(got.data(), want.data(), want.size()) == 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <golden.json> <fixtures dir>\n", argv[0]);
    return 2;
  }
  cv84x6::json::Value golden;
  std::string err;
  if (!cv84x6::json::parse(read_file(argv[1]), &golden, &err)) {
    std::fprintf(stderr, "golden parse failed: %s\n", err.c_str());
    return 1;
  }

  const cv84x6::json::Value* cfg = golden.get("config");
  cv84x6::VisionConfig vc;
  if (cfg) {
    vc.patch_size = static_cast<int>(cfg->get_int("patch_size", 16));
    vc.spatial_merge = static_cast<int>(cfg->get_int("spatial_merge", 2));
    vc.temporal_patch_size = static_cast<int>(cfg->get_int("temporal_patch_size", 2));
    vc.grid_per_side = static_cast<int>(cfg->get_int("grid_per_side", 48));
    vc.min_pixels = cfg->get_int("min_pixels", 4 * 32 * 32);
    vc.max_pixels = cfg->get_int("max_pixels", 0);
    vc.fused_normalize = cfg->get_bool("fused_normalize", false);
    vc.rgba_white_background = cfg->get_bool("rgba_white_background", false);
  }

  const std::string dir = argv[2];
  int failures = 0;
  int checked = 0;

  // -- standalone Pillow resize ------------------------------------------
  const cv84x6::json::Value* rcases = golden.get_array("resize_cases");
  if (rcases != nullptr) {
    for (const auto& rc : rcases->array()) {
      const std::string src_name = rc.get_string("src");
      const cv84x6::json::Value* dst = rc.get_array("dst");
      if (dst == nullptr || dst->array().size() != 2) continue;
      const int tw = static_cast<int>(dst->array()[0].integer());
      const int th = static_cast<int>(dst->array()[1].integer());

      cv84x6::Image img;
      if (!cv84x6::decode_image(read_file(dir + "/" + src_name), &img, &err)) {
        std::fprintf(stderr, "RESIZE: cannot decode %s: %s\n", src_name.c_str(), err.c_str());
        ++failures;
        continue;
      }
      std::vector<uint8_t> out(static_cast<size_t>(tw) * th * 3);
      cv84x6::pil_resize(img.rgb.data(), img.width, img.height, 3, out.data(), tw, th);

      const std::vector<uint8_t> want = b64decode(rc.get_string("b64"));
      ++checked;
      if (want.size() != out.size()) {
        std::fprintf(stderr, "RESIZE: size mismatch for %dx%d\n", tw, th);
        ++failures;
        continue;
      }
      size_t diff = 0, first = 0;
      bool have_first = false;
      for (size_t i = 0; i < out.size(); ++i) {
        if (out[i] != want[i]) {
          ++diff;
          if (!have_first) {
            first = i;
            have_first = true;
          }
        }
      }
      if (diff != 0) {
        ++failures;
        std::fprintf(stderr,
                     "RESIZE MISMATCH %dx%d -> %dx%d: %zu of %zu bytes differ "
                     "(first at %zu: got %d want %d)\n",
                     img.width, img.height, tw, th, diff, out.size(), first,
                     int(out[first]), int(want[first]));
      }
    }
  }

  // -- full pipeline ------------------------------------------------------
  const cv84x6::json::Value* cases = golden.get_array("cases");
  if (cases == nullptr) {
    std::fprintf(stderr, "golden has no cases\n");
    return 1;
  }
  for (const auto& c : cases->array()) {
    const std::string name = c.get_string("name");
    const std::string raw = read_file(dir + "/" + name);
    if (raw.empty()) {
      std::fprintf(stderr, "PIPELINE: missing fixture %s\n", name.c_str());
      ++failures;
      continue;
    }

    // Grid first: it is derived from smart_resize alone, so a mismatch here
    // points at sizing rather than pixels.
    cv84x6::Image img;
    if (!cv84x6::decode_image(raw, &img, &err)) {
      std::fprintf(stderr, "PIPELINE: decode %s failed: %s\n", name.c_str(), err.c_str());
      ++failures;
      continue;
    }
    const int factor = vc.patch_size * vc.spatial_merge;
    int rh = 0, rw = 0;
    if (!cv84x6::smart_resize(img.height, img.width, vc.min_pixels, vc.max_pixels,
                              factor, &rh, &rw, &err)) {
      std::fprintf(stderr, "PIPELINE: smart_resize %s failed: %s\n", name.c_str(), err.c_str());
      ++failures;
      continue;
    }
    const cv84x6::json::Value* pil_size = c.get_array("resized_wh");
    if (pil_size != nullptr && pil_size->array().size() == 2) {
      const int pw = static_cast<int>(pil_size->array()[0].integer());
      const int ph = static_cast<int>(pil_size->array()[1].integer());
      if (pw != rw || ph != rh) {
        std::fprintf(stderr,
                     "SIZE MISMATCH %s: smart_resize gave %dx%d, reference %dx%d "
                     "(source %dx%d, max_pixels %lld)\n",
                     name.c_str(), rw, rh, pw, ph, img.width, img.height,
                     static_cast<long long>(vc.max_pixels));
        ++failures;
        continue;
      }
    }

    cv84x6::VisionInput vi;
    if (!cv84x6::preprocess_image(raw, vc, &vi, &err)) {
      std::fprintf(stderr, "PIPELINE: preprocess %s failed: %s\n", name.c_str(), err.c_str());
      ++failures;
      continue;
    }

    const cv84x6::json::Value* grid = c.get_array("grid_thw");
    if (grid != nullptr && grid->array().size() == 3) {
      const int gt = static_cast<int>(grid->array()[0].integer());
      const int gh = static_cast<int>(grid->array()[1].integer());
      const int gw = static_cast<int>(grid->array()[2].integer());
      if (gt != vi.grid_t || gh != vi.grid_h || gw != vi.grid_w) {
        std::fprintf(stderr, "GRID MISMATCH %s: got {%d,%d,%d} want {%d,%d,%d}\n",
                     name.c_str(), vi.grid_t, vi.grid_h, vi.grid_w, gt, gh, gw);
        ++failures;
        continue;
      }
    }

    const std::vector<uint8_t> want = b64decode(c.get_string("pixel_values_b64"));
    ++checked;
    if (!same_bits(vi.pixels, want)) {
      ++failures;
      const std::vector<uint8_t> gb(
          reinterpret_cast<const uint8_t*>(vi.pixels.data()),
          reinterpret_cast<const uint8_t*>(vi.pixels.data()) +
              vi.pixels.size() * sizeof(float));
      size_t diff = 0, first = 0;
      bool have_first = false;
      const size_t n = std::min(gb.size(), want.size());
      for (size_t i = 0; i < n; ++i) {
        if (gb[i] != want[i]) {
          ++diff;
          if (!have_first) {
            first = i;
            have_first = true;
          }
        }
      }
      std::fprintf(stderr,
                   "PIXELS MISMATCH %s: %zu of %zu bytes differ (first at %zu)\n",
                   name.c_str(), diff, want.size(), first);
      if (have_first && first / 4 < vi.pixels.size()) {
        const float g = as_floats(gb)[first / 4];
        const float w = as_floats(want)[first / 4];
        std::fprintf(stderr, "  element %zu: got %.9g want %.9g\n", first / 4, g, w);
      }
    }
  }

  if (failures == 0) {
    std::printf("vision: %d checks passed\n", checked);
    return 0;
  }
  std::fprintf(stderr, "vision: %d of %d checks FAILED\n", failures, checked);
  return 1;
}
