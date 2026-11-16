// Resize-only conformance check against Pillow's bicubic output.
//
// Pillow's resampler is the piece of the image path with real algorithmic risk
// (fixed-point coefficients, a two-pass separable convolution, its own clip8),
// so it gets its own check that needs nothing but Pillow to produce the golden
// data. tools/gen_vision_golden.py covers the whole pipeline end to end.
//
//   resize_check <resize_golden.json> <fixture images dir>

#include <cstdint>
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
    if (c == '=') continue;
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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s <resize_golden.json> <fixtures dir>\n", argv[0]);
    return 2;
  }
  cv84x6::json::Value golden;
  std::string err;
  if (!cv84x6::json::parse(read_file(argv[1]), &golden, &err)) {
    std::fprintf(stderr, "golden parse failed: %s\n", err.c_str());
    return 1;
  }
  const std::string dir = argv[2];

  // Fixture sources are decoded once from their PNG/JPEG files, which also
  // exercises the decoder that feeds the resampler.
  struct Loaded {
    int w = 0, h = 0;
    std::vector<uint8_t> rgb;
  };
  std::vector<std::pair<std::string, Loaded>> cache;
  auto load = [&](const std::string& name) -> const Loaded* {
    for (const auto& c : cache) {
      if (c.first == name) return &c.second;
    }
    cv84x6::Image img;
    if (!cv84x6::decode_image(read_file(dir + "/" + name), &img, &err)) return nullptr;
    cache.push_back({name, Loaded{img.width, img.height, img.rgb}});
    return &cache.back().second;
  };

  int failures = 0, checked = 0;
  const cv84x6::json::Value* cases = golden.get_array("cases");
  if (cases == nullptr) {
    std::fprintf(stderr, "golden has no cases\n");
    return 1;
  }
  for (const auto& c : cases->array()) {
    const std::string src = c.get_string("src");
    const cv84x6::json::Value* dst = c.get_array("dst");
    if (dst == nullptr || dst->array().size() != 2) continue;
    const int tw = static_cast<int>(dst->array()[0].integer());
    const int th = static_cast<int>(dst->array()[1].integer());

    const Loaded* img = load(src);
    if (img == nullptr) {
      std::fprintf(stderr, "cannot decode fixture %s: %s\n", src.c_str(), err.c_str());
      ++failures;
      continue;
    }
    std::vector<uint8_t> out(static_cast<size_t>(tw) * th * 3);
    cv84x6::pil_resize(img->rgb.data(), img->w, img->h, 3, out.data(), tw, th);

    const std::vector<uint8_t> want = b64decode(c.get_string("b64"));
    ++checked;
    if (want.size() != out.size()) {
      std::fprintf(stderr, "SIZE MISMATCH %s -> %dx%d: got %zu want %zu bytes\n",
                   src.c_str(), tw, th, out.size(), want.size());
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
                   "MISMATCH %s %dx%d -> %dx%d: %zu of %zu bytes differ "
                   "(first at %zu: got %d want %d)\n",
                   src.c_str(), img->w, img->h, tw, th, diff, out.size(), first,
                   int(out[first]), int(want[first]));
    }
  }

  if (failures == 0) {
    std::printf("resize: %d checks passed (byte-identical to Pillow)\n", checked);
    return 0;
  }
  std::fprintf(stderr, "resize: %d of %d checks FAILED\n", failures, checked);
  return 1;
}
