// Image decode, Pillow-compatible bicubic resize and the Qwen-VL preprocessing
// pipeline. See vision.h for the provenance of each piece.
//
// Two external libraries, both already on the board:
//   libjpeg  -- matches the libjpeg-turbo the reference Pillow links, so JPEG
//               coefficients and IDCT are identical rather than merely similar.
//               The board ships the runtime .so; its headers are vendored under
//               native/include/jpeg/ because the SDK image has no -dev package.
//   zlib     -- PNG inflate; base-system, stable ABI.

#include "vision.h"

#include <algorithm>
#include <cmath>
#include <csetjmp>
#include <cstdio>
#include <cstring>
#include <set>

#include <zlib.h>

#include "jpeg/jpeglib.h"

namespace cv84x6 {
namespace {

void set_err(std::string* err, const std::string& msg) {
  if (err) *err = msg;
}

bool starts_with(const std::string& s, const char* sig, size_t n) {
  return s.size() >= n && std::memcmp(s.data(), sig, n) == 0;
}

inline uint8_t clamp8(int v) { return static_cast<uint8_t>(v < 0 ? 0 : (v > 255 ? 255 : v)); }

// ===========================================================================
// JPEG
// ===========================================================================

struct JpegErr {
  jpeg_error_mgr pub;
  jmp_buf jump;
  char message[JMSG_LENGTH_MAX];
};

void jpeg_error_exit(j_common_ptr cinfo) {
  auto* e = reinterpret_cast<JpegErr*>(cinfo->err);
  (*cinfo->err->format_message)(cinfo, e->message);
  longjmp(e->jump, 1);
}

bool jpeg_decode(const std::string& in, Image* out, std::string* err, int64_t max_pixels) {
  jpeg_decompress_struct cinfo;
  JpegErr jerr;
  cinfo.err = jpeg_std_error(&jerr.pub);
  jerr.pub.error_exit = jpeg_error_exit;
  if (setjmp(jerr.jump)) {
    jpeg_destroy_decompress(&cinfo);
    set_err(err, std::string("JPEG: ") + jerr.message);
    return false;
  }
  jpeg_create_decompress(&cinfo);
  jpeg_mem_src(&cinfo, reinterpret_cast<const unsigned char*>(in.data()),
               static_cast<unsigned long>(in.size()));
  jpeg_read_header(&cinfo, TRUE);
  if (max_pixels > 0 && static_cast<int64_t>(cinfo.image_width) * cinfo.image_height > max_pixels) {
    jpeg_destroy_decompress(&cinfo);
    set_err(err, "JPEG exceeds source pixel limit (16 megapixels)");
    return false;
  }
  // The reference goes through Pillow, whose JPEG decoder is libjpeg-turbo and
  // which converts whatever colour space it finds to RGB the same way. Forcing
  // the output colours here keeps CMYK/YCCK inputs on the same path as Pillow's
  // convert("RGB").
  if (cinfo.jpeg_color_space == JCS_CMYK || cinfo.jpeg_color_space == JCS_YCCK) {
    cinfo.out_color_space = JCS_CMYK;
  } else {
    cinfo.out_color_space = JCS_RGB;
  }
  jpeg_start_decompress(&cinfo);

  const int w = static_cast<int>(cinfo.output_width);
  const int h = static_cast<int>(cinfo.output_height);
  const int comps = cinfo.output_components;

  out->width = w;
  out->height = h;
  out->rgb.assign(static_cast<size_t>(w) * h * 3, 0);

  std::vector<uint8_t> row(static_cast<size_t>(w) * comps);
  while (cinfo.output_scanline < cinfo.output_height) {
    uint8_t* rows[1] = {row.data()};
    const JDIMENSION y = cinfo.output_scanline;
    jpeg_read_scanlines(&cinfo, rows, 1);
    uint8_t* dst = out->rgb.data() + static_cast<size_t>(y) * w * 3;
    for (int x = 0; x < w; ++x) {
      if (comps == 3) {
        dst[3 * x] = row[3 * x];
        dst[3 * x + 1] = row[3 * x + 1];
        dst[3 * x + 2] = row[3 * x + 2];
      } else if (comps == 4) {
        // Adobe CMYK JPEGs store inverted values; Pillow inverts too.
        dst[3 * x] = static_cast<uint8_t>(row[4 * x] * row[4 * x + 3] / 255);
        dst[3 * x + 1] = static_cast<uint8_t>(row[4 * x + 1] * row[4 * x + 3] / 255);
        dst[3 * x + 2] = static_cast<uint8_t>(row[4 * x + 2] * row[4 * x + 3] / 255);
      } else {
        dst[3 * x] = dst[3 * x + 1] = dst[3 * x + 2] = row[x];
      }
    }
  }
  jpeg_finish_decompress(&cinfo);
  jpeg_destroy_decompress(&cinfo);
  return true;
}

// ===========================================================================
// PNG
// ===========================================================================

uint32_t be32(const uint8_t* p) {
  return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | uint32_t(p[3]);
}

int paeth(int a, int b, int c) {
  const int p = a + b - c;
  const int pa = std::abs(p - a), pb = std::abs(p - b), pc = std::abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

bool png_decode(const std::string& in, Image* out, std::string* err, int64_t max_pixels,
                bool rgba_white_background) {
  const auto* p = reinterpret_cast<const uint8_t*>(in.data());
  const size_t n = in.size();
  size_t off = 8;  // past the signature

  uint32_t width = 0, height = 0;
  int bit_depth = 0, color_type = 0, interlace = 0, channels = 0;
  bool have_header = false;
  std::vector<uint8_t> idat, palette, palette_a;

  while (off + 8 <= n) {
    const uint32_t len = be32(p + off);
    const char* type = reinterpret_cast<const char*>(p + off + 4);
    off += 8;
    if (off + len + 4 > n) {
      set_err(err, "PNG: truncated chunk");
      return false;
    }
    const uint8_t* data = p + off;

    if (std::memcmp(type, "IHDR", 4) == 0 && len >= 13) {
      width = be32(data);
      height = be32(data + 4);
      bit_depth = data[8];
      color_type = data[9];
      interlace = data[12];
      switch (color_type) {
        case 0: channels = 1; break;
        case 2: channels = 3; break;
        case 3: channels = 1; break;
        case 4: channels = 2; break;
        case 6: channels = 4; break;
        default:
          set_err(err, "PNG: unsupported colour type");
          return false;
      }
      have_header = true;
    } else if (std::memcmp(type, "PLTE", 4) == 0) {
      palette.assign(data, data + len);
    } else if (std::memcmp(type, "tRNS", 4) == 0) {
      palette_a.assign(data, data + len);
    } else if (std::memcmp(type, "IDAT", 4) == 0) {
      idat.insert(idat.end(), data, data + len);
    } else if (std::memcmp(type, "IEND", 4) == 0) {
      break;
    }
    off += len + 4;  // data + CRC
  }

  if (!have_header) {
    set_err(err, "PNG: no IHDR");
    return false;
  }
  if (interlace != 0) {
    set_err(err, "PNG: interlaced images are not supported");
    return false;
  }
  if (width == 0 || height == 0 || width > 32768 || height > 32768) {
    set_err(err, "PNG: unreasonable dimensions");
    return false;
  }
  if (max_pixels > 0 && static_cast<int64_t>(width) * height > max_pixels) {
    set_err(err, "PNG exceeds source pixel limit (16 megapixels)");
    return false;
  }
  if (bit_depth != 1 && bit_depth != 2 && bit_depth != 4 && bit_depth != 8 && bit_depth != 16) {
    set_err(err, "PNG: unsupported bit depth");
    return false;
  }
  // Greyscale and palette images may be sub-byte (1/2/4 bits); truecolour and
  // alpha-bearing types are 8 or 16 bits only.
  if ((color_type == 0 || color_type == 3) ? (bit_depth != 1 && bit_depth != 2 &&
                                              bit_depth != 4 && bit_depth != 8 &&
                                              bit_depth != 16)
                                           : (bit_depth != 8 && bit_depth != 16)) {
    set_err(err, "PNG: unsupported bit depth for this colour type");
    return false;
  }

  const size_t bits_per_pixel = size_t(channels) * size_t(bit_depth);
  const size_t stride = (size_t(width) * bits_per_pixel + 7) / 8;
  const size_t raw_size = (stride + 1) * size_t(height);
  std::vector<uint8_t> raw(raw_size);
  {
    z_stream zs;
    std::memset(&zs, 0, sizeof(zs));
    if (inflateInit(&zs) != Z_OK) {
      set_err(err, "PNG: zlib init failed");
      return false;
    }
    zs.next_in = const_cast<Bytef*>(idat.data());
    zs.avail_in = static_cast<uInt>(idat.size());
    zs.next_out = raw.data();
    zs.avail_out = static_cast<uInt>(raw.size());
    const int rc = inflate(&zs, Z_FINISH);
    const size_t produced = raw.size() - zs.avail_out;
    inflateEnd(&zs);
    if (rc != Z_STREAM_END || produced < raw_size) {
      set_err(err, "PNG: inflate failed");
      return false;
    }
  }

  // Undo the per-scanline filters in place.
  const size_t filter_bpp = std::max<size_t>(1, (bits_per_pixel + 7) / 8);
  for (size_t y = 0; y < height; ++y) {
    const size_t row = y * (stride + 1);
    const uint8_t filter = raw[row];
    uint8_t* cur = raw.data() + row + 1;
    const uint8_t* prev = y > 0 ? raw.data() + (y - 1) * (stride + 1) + 1 : nullptr;
    switch (filter) {
      case 0:
        break;
      case 1:
        for (size_t i = filter_bpp; i < stride; ++i) cur[i] = uint8_t(cur[i] + cur[i - filter_bpp]);
        break;
      case 2:
        if (prev) {
          for (size_t i = 0; i < stride; ++i) cur[i] = uint8_t(cur[i] + prev[i]);
        }
        break;
      case 3:
        for (size_t i = 0; i < stride; ++i) {
          const int a = i >= filter_bpp ? cur[i - filter_bpp] : 0;
          const int b = prev ? prev[i] : 0;
          cur[i] = uint8_t(cur[i] + ((a + b) >> 1));
        }
        break;
      case 4:
        for (size_t i = 0; i < stride; ++i) {
          const int a = i >= filter_bpp ? cur[i - filter_bpp] : 0;
          const int b = prev ? prev[i] : 0;
          const int c = (prev && i >= filter_bpp) ? prev[i - filter_bpp] : 0;
          cur[i] = uint8_t(cur[i] + paeth(a, b, c));
        }
        break;
      default:
        set_err(err, "PNG: unknown row filter");
        return false;
    }
  }

  out->width = int(width);
  out->height = int(height);
  out->rgb.assign(size_t(width) * height * 3, 0);

  const int max_sample = (1 << bit_depth) - 1;
  for (size_t y = 0; y < height; ++y) {
    const uint8_t* row = raw.data() + y * (stride + 1) + 1;
    uint8_t* dst = out->rgb.data() + y * size_t(width) * 3;
    for (size_t x = 0; x < width; ++x) {
      auto sample = [&](int c) -> int {
        // Reads channel c of pixel x at this bit depth, scaled to 0..255.
        if (bit_depth == 8) return row[x * channels + c];
        if (bit_depth == 16) {
          return int((int(row[(x * channels + c) * 2]) << 8) | row[(x * channels + c) * 2 + 1]) >> 8;
        }
        const int per_byte = 8 / bit_depth;
        const size_t byte = x / per_byte;
        const int shift = 8 - bit_depth * (int(x % per_byte) + 1);
        const int v = (row[byte] >> shift) & max_sample;
        return v * 255 / max_sample;
      };
      int r = 0, g = 0, b = 0;
      if (color_type == 0 || color_type == 4) {
        r = g = b = sample(0);
      } else if (color_type == 2 || color_type == 6) {
        r = sample(0);
        g = sample(1);
        b = sample(2);
      } else {  // palette
        int index = 0;
        if (bit_depth < 8) {
          const int per_byte = 8 / bit_depth;
          const size_t byte = x / per_byte;
          const int shift = 8 - bit_depth * (int(x % per_byte) + 1);
          index = (row[byte] >> shift) & max_sample;
        } else if (bit_depth == 8) {
          index = row[x];
        } else {
          index = int((int(row[x * 2]) << 8) | row[x * 2 + 1]) >> 8;
        }
        if (size_t(index) * 3 + 2 < palette.size()) {
          r = palette[index * 3];
          g = palette[index * 3 + 1];
          b = palette[index * 3 + 2];
        }
      }
      if (rgba_white_background && color_type == 6) {
        // qwen_vl_utils.to_rgb handles only RGBA this way. LA and palette
        // images still use Pillow convert("RGB"), which drops transparency.
        const int alpha = sample(3);
        auto composite = [alpha](int value) {
          return (value * alpha + 255 * (255 - alpha) + 127) / 255;
        };
        r = composite(r); g = composite(g); b = composite(b);
      }
      dst[3 * x] = clamp8(r);
      dst[3 * x + 1] = clamp8(g);
      dst[3 * x + 2] = clamp8(b);
    }
  }
  return true;
}

}  // namespace

bool is_supported_image(const std::string& bytes) {
  static const char kPng[8] = {'\x89', 'P', 'N', 'G', '\r', '\n', '\x1a', '\n'};
  return starts_with(bytes, "\xFF\xD8\xFF", 3) || starts_with(bytes, kPng, 8);
}

bool decode_image(const std::string& bytes, Image* out, std::string* err) {
  return decode_image(bytes, out, err, 0);
}

bool decode_image(const std::string& bytes, Image* out, std::string* err, int64_t max_source_pixels) {
  return decode_image(bytes, out, err, max_source_pixels, false);
}

bool decode_image(const std::string& bytes, Image* out, std::string* err,
                  int64_t max_source_pixels, bool rgba_white_background) {
  if (out == nullptr) return false;
  if (starts_with(bytes, "\xFF\xD8\xFF", 3)) return jpeg_decode(bytes, out, err, max_source_pixels);
  static const char kPng[8] = {'\x89', 'P', 'N', 'G', '\r', '\n', '\x1a', '\n'};
  if (starts_with(bytes, kPng, 8))
    return png_decode(bytes, out, err, max_source_pixels, rgba_white_background);
  set_err(err, "unsupported image format (only JPEG and PNG)");
  return false;
}

// ===========================================================================
// Pillow-compatible bicubic resample
// ===========================================================================
namespace {

// Pillow's Resample.c constants.
constexpr int kPrecisionBits = 32 - 8 - 2;  // 22
constexpr double kBicubicSupport = 2.0;

double bicubic_filter(double x) {
  const double a = -0.5;
  if (x < 0.0) x = -x;
  if (x < 1.0) return ((a + 2.0) * x - (a + 3.0)) * x * x + 1;
  if (x < 2.0) return (((x - 5) * x + 8) * x - 4) * a;
  return 0.0;
}

// Pillow's precompute_coeffs + normalize_coeffs_8bpc, verbatim in structure:
// double-precision weights, normalised to sum 1, then rounded to fixed point
// with the same tie-breaking (round half away from zero via +/- 0.5).
struct Coeffs {
  int ksize = 0;
  std::vector<int32_t> k;      // out_size * ksize
  std::vector<int32_t> bounds; // out_size * 2: {xmin, xmax}
};

Coeffs precompute_coeffs(int in_size, int out_size) {
  Coeffs c;
  double scale = static_cast<double>(in_size) / out_size;
  double filterscale = scale < 1.0 ? 1.0 : scale;
  const double support = kBicubicSupport * filterscale;
  const double inv_filterscale = 1.0 / filterscale;

  c.ksize = static_cast<int>(std::ceil(support)) * 2 + 1;
  c.k.assign(static_cast<size_t>(out_size) * c.ksize, 0);
  c.bounds.assign(static_cast<size_t>(out_size) * 2, 0);

  for (int xx = 0; xx < out_size; ++xx) {
    const double center = (xx + 0.5) * scale;
    int xmin = static_cast<int>(center - support + 0.5);
    if (xmin < 0) xmin = 0;
    int xmax = static_cast<int>(center + support + 0.5);
    if (xmax > in_size) xmax = in_size;
    xmax -= xmin;

    std::vector<double> w(static_cast<size_t>(xmax), 0.0);
    double ww = 0.0;
    for (int x = 0; x < xmax; ++x) {
      const double v = bicubic_filter((x + xmin - center + 0.5) * inv_filterscale);
      w[x] = v;
      ww += v;
    }
    if (ww != 0.0) {
      for (int x = 0; x < xmax; ++x) w[x] /= ww;
    }
    // Fixed point, exactly Pillow's normalize_coeffs_8bpc.
    for (int x = 0; x < xmax; ++x) {
      const double v = w[x] * (1 << kPrecisionBits);
      c.k[static_cast<size_t>(xx) * c.ksize + x] =
          static_cast<int32_t>(v < 0 ? -0.5 + v : 0.5 + v);
    }
    c.bounds[2 * xx] = xmin;
    c.bounds[2 * xx + 1] = xmax;
  }
  return c;
}

inline uint8_t clip8(int32_t in) {
  const int v = in >> kPrecisionBits;
  return static_cast<uint8_t>(v < 0 ? 0 : (v > 255 ? 255 : v));
}

}  // namespace

void pil_resize(const uint8_t* src, int src_w, int src_h, int bands,
                uint8_t* dst, int dst_w, int dst_h) {
  // Pillow resamples in two passes: horizontal into a 4-byte-per-pixel
  // intermediate, then vertical. Its 8-bit path always works on 4-byte pixels
  // even for 3 bands, so the intermediate is padded the same way here.
  const Coeffs hc = precompute_coeffs(src_w, dst_w);
  std::vector<uint8_t> tmp(static_cast<size_t>(dst_w) * src_h * 4, 0);
  const int32_t half = 1 << (kPrecisionBits - 1);

  for (int y = 0; y < src_h; ++y) {
    const uint8_t* line_in = src + static_cast<size_t>(y) * src_w * bands;
    uint8_t* line_out = tmp.data() + static_cast<size_t>(y) * dst_w * 4;
    for (int x = 0; x < dst_w; ++x) {
      const int xmin = hc.bounds[2 * x];
      const int xmax = hc.bounds[2 * x + 1];
      const int32_t* k = &hc.k[static_cast<size_t>(x) * hc.ksize];
      int32_t ss[4] = {half, half, half, half};
      for (int i = 0; i < xmax; ++i) {
        const uint8_t* px = line_in + static_cast<size_t>(i + xmin) * bands;
        for (int b = 0; b < bands; ++b) ss[b] += px[b] * k[i];
      }
      for (int b = 0; b < bands; ++b) line_out[x * 4 + b] = clip8(ss[b]);
    }
  }

  const Coeffs vc = precompute_coeffs(src_h, dst_h);
  for (int y = 0; y < dst_h; ++y) {
    uint8_t* line_out = dst + static_cast<size_t>(y) * dst_w * bands;
    const int ymin = vc.bounds[2 * y];
    const int ymax = vc.bounds[2 * y + 1];
    const int32_t* k = &vc.k[static_cast<size_t>(y) * vc.ksize];
    for (int x = 0; x < dst_w; ++x) {
      int32_t ss[4] = {half, half, half, half};
      for (int i = 0; i < ymax; ++i) {
        const uint8_t* px = tmp.data() + static_cast<size_t>(i + ymin) * dst_w * 4 + x * 4;
        for (int b = 0; b < bands; ++b) ss[b] += px[b] * k[i];
      }
      for (int b = 0; b < bands; ++b) line_out[x * bands + b] = clip8(ss[b]);
    }
  }
}

// ===========================================================================
// smart_resize
// ===========================================================================
namespace {

int64_t round_by_factor(int64_t n, int64_t f) {
  // Python's round() is banker's rounding; qwen_vl_utils relies on it.
  const double q = static_cast<double>(n) / static_cast<double>(f);
  const double r = std::nearbyint(q);  // default FE_TONEAREST == banker's
  return static_cast<int64_t>(r) * f;
}
int64_t floor_by_factor(int64_t n, int64_t f) {
  return static_cast<int64_t>(std::floor(static_cast<double>(n) / f)) * f;
}
int64_t ceil_by_factor(int64_t n, int64_t f) {
  return static_cast<int64_t>(std::ceil(static_cast<double>(n) / f)) * f;
}

}  // namespace

bool smart_resize(int height, int width, int64_t min_pixels, int64_t max_pixels,
                  int factor, int* out_h, int* out_w, std::string* err) {
  if (height <= 0 || width <= 0 || factor <= 0) {
    set_err(err, "smart_resize: non-positive input");
    return false;
  }
  if (max_pixels < min_pixels) {
    set_err(err, "smart_resize: max_pixels < min_pixels");
    return false;
  }
  const int64_t big = std::max(height, width), small = std::min(height, width);
  if (static_cast<double>(big) / small > 200.0) {
    set_err(err, "absolute aspect ratio must be smaller than 200");
    return false;
  }
  int64_t h_bar = std::max<int64_t>(factor, round_by_factor(height, factor));
  int64_t w_bar = std::max<int64_t>(factor, round_by_factor(width, factor));
  if (h_bar * w_bar > max_pixels) {
    const double beta = std::sqrt(static_cast<double>(height) * width / max_pixels);
    // No max(factor, ...) here on purpose: the reference does not clamp this
    // branch, so for an extremely elongated image it returns a 0 side. Matching
    // that exactly keeps the port bit-identical; preprocess_image rejects the
    // degenerate result with a clear error instead of changing the maths.
    h_bar = floor_by_factor(static_cast<int64_t>(height / beta), factor);
    w_bar = floor_by_factor(static_cast<int64_t>(width / beta), factor);
  } else if (h_bar * w_bar < min_pixels) {
    const double beta = std::sqrt(static_cast<double>(min_pixels) / (height * width));
    h_bar = ceil_by_factor(static_cast<int64_t>(height * beta), factor);
    w_bar = ceil_by_factor(static_cast<int64_t>(width * beta), factor);
  }
  *out_h = static_cast<int>(h_bar);
  *out_w = static_cast<int>(w_bar);
  return true;
}

// ===========================================================================
// Pipeline
// ===========================================================================

bool preprocess_image(const std::string& bytes, const VisionConfig& cfg,
                      VisionInput* out, std::string* err) {
  if (out == nullptr) return false;
  Image img;
  if (!decode_image(bytes, &img, err, cfg.max_source_pixels, cfg.rgba_white_background)) return false;

  const int factor = cfg.patch_size * cfg.spatial_merge;
  const int64_t max_pixels = cfg.max_pixels > 0 ? cfg.max_pixels
                                                : int64_t(cfg.max_patches) *
                                                      cfg.patch_size * cfg.patch_size;
  int rh = 0, rw = 0;
  if (!smart_resize(img.height, img.width, cfg.min_pixels, max_pixels, factor, &rh, &rw, err)) {
    return false;
  }
  if (rh <= 0 || rw <= 0) {
    // smart_resize returns 0 for an extremely elongated image (it does not clamp
    // its down-scale branch). The reference stack would fail later and less
    // clearly; naming the cause here is strictly more useful than a crash.
    set_err(err, "image is too elongated to fit " + std::to_string(max_pixels) +
                     " pixels at this patch grid");
    return false;
  }

  // Step 1: qwen_vl_utils' fetch_image resizes with Pillow's *default* filter
  // (no resample argument), which is BICUBIC.
  Image resized;
  resized.width = rw;
  resized.height = rh;
  resized.rgb.assign(static_cast<size_t>(rw) * rh * 3, 0);
  pil_resize(img.rgb.data(), img.width, img.height, 3, resized.rgb.data(), rw, rh);

  // Step 2: the HF processor runs with do_resize=False, so this is the buffer it
  // sees. Two details decide the last bits, both from transformers'
  // image_transforms.py:
  //   rescale  does `image.astype(float64) * scale` and then casts to float32,
  //            so the division by 255 is exact-double before rounding once;
  //   normalize then works in float32: (x - mean) / std with mean = std = 0.5.
  const int t = 1;
  const int gh = rh / cfg.patch_size;
  const int gw = rw / cfg.patch_size;
  if (gh <= 0 || gw <= 0) {
    set_err(err, "image smaller than one patch after resize");
    return false;
  }
  const int m = cfg.spatial_merge;
  if (gh % m != 0 || gw % m != 0) {
    set_err(err, "patch grid is not a multiple of the spatial merge size");
    return false;
  }

  const int p = cfg.patch_size;
  const int C = 3;
  const int tc = cfg.temporal_patch_size;
  // Qwen2VLImageProcessor packs `temporal_patch_size` frames per patch row. A
  // still image is one frame, so the processor repeats it to fill the group
  // (`np.repeat(patches[-1], tc - n % tc)`) and the patch vector is
  // C * tc * p * p wide -- which is exactly the vit graph's input width
  // (llm_engine vit_dims). Every frame in the group is the same picture, so the
  // buffer is that first frame's channel block copied tc times.
  const size_t frame_elems = size_t(C) * p * p;
  const size_t patch_elems = frame_elems * tc;
  out->grid_t = t;
  out->grid_h = gh;
  out->grid_w = gw;
  out->pixels.assign(size_t(t) * gh * gw * patch_elems, 0.0f);

  // Flatten order from _preprocess's
  //   transpose(0, 3, 6, 4, 7, 2, 1, 5, 8)
  // over (grid_t, tc, C, gh/m, m, p, gw/m, m, p):
  //   merge-row, merge-col, channel, temporal, patch-row, patch-col.
  size_t k = 0;
  for (int i_blk = 0; i_blk < gh / m; ++i_blk) {
    for (int j_blk = 0; j_blk < gw / m; ++j_blk) {
      for (int i2 = 0; i2 < m; ++i2) {
        for (int j2 = 0; j2 < m; ++j2) {
          const int y0 = (i_blk * m + i2) * p;
          const int x0 = (j_blk * m + j2) * p;
          for (int c = 0; c < C; ++c) {
            for (int ti = 0; ti < tc; ++ti) {
              for (int py = 0; py < p; ++py) {
                const uint8_t* row = resized.rgb.data() +
                                     (static_cast<size_t>(y0 + py) * rw + x0) * 3;
                for (int px = 0; px < p; ++px) {
                  // rescale in double (exact), cast to float32, then normalize
                  // in float32 -- the reference's order, kept so values match
                  // bit for bit rather than approximately.
                  const float scaled = static_cast<float>(
                      static_cast<double>(row[px * 3 + c]) * (1.0 / 255.0));
                  out->pixels[k++] = cfg.fused_normalize
                      ? (static_cast<float>(row[px * 3 + c]) - 127.5f) / 127.5f
                      : (scaled - 0.5f) / 0.5f;
                }
              }
            }
          }
        }
      }
    }
  }

  if (cfg.max_patches > 0 && out->patches() > cfg.max_patches) {
    set_err(err, "image needs " + std::to_string(out->patches()) + " vit rows, max is " +
                     std::to_string(cfg.max_patches));
    return false;
  }
  return true;
}

// ===========================================================================
// ViT position tables (demo rot_pos / fast_pos_embed_interpolate)
// ===========================================================================

void vision_rot_pos(int grid_t, int grid_h, int grid_w, std::vector<int32_t>* pos_ids) {
  const int m = 2;  // spatial_merge_size
  const size_t frames = size_t(grid_t) * grid_h * grid_w;
  pos_ids->assign(frames * 2, 0);
  size_t k = 0;
  for (int t = 0; t < grid_t; ++t) {
    for (int i_blk = 0; i_blk < grid_h / m; ++i_blk) {
      for (int j_blk = 0; j_blk < grid_w / m; ++j_blk) {
        for (int i2 = 0; i2 < m; ++i2) {
          for (int j2 = 0; j2 < m; ++j2) {
            (*pos_ids)[k++] = i_blk * m + i2;
            (*pos_ids)[k++] = j_blk * m + j2;
          }
        }
      }
    }
  }
}

void vision_pos_embed_interpolate(int grid_t, int grid_h, int grid_w, int grid_per_side,
                                  std::vector<int32_t>* pos_idx,
                                  std::vector<float>* pos_weight) {
  const int side = grid_per_side;

  // The reference builds these with torch.linspace(0, side-1, n), which
  // accumulates in double and stores float32: `start + step*i` with a double
  // step, rounded to float once. Multiplying by a float32 step instead shifts
  // the last bits, so keep the accumulation in double here.
  auto linspace = [](int n, double start, double end) {
    std::vector<float> o(static_cast<size_t>(n));
    if (n == 1) {
      o[0] = static_cast<float>(start);
      return o;
    }
    const double step = (end - start) / static_cast<double>(n - 1);
    for (int i = 0; i < n; ++i) {
      o[static_cast<size_t>(i)] = static_cast<float>(start + step * static_cast<double>(i));
    }
    o[static_cast<size_t>(n - 1)] = static_cast<float>(end);
    return o;
  };

  const std::vector<float> h_idxs = linspace(grid_h, 0.0, static_cast<double>(side - 1));
  const std::vector<float> w_idxs = linspace(grid_w, 0.0, static_cast<double>(side - 1));

  std::vector<int> base_h(grid_h), base_h_ceil(grid_h);
  std::vector<float> dh(grid_h);
  std::vector<int> w_floor(grid_w), w_ceil(grid_w);
  std::vector<float> dw(grid_w);
  for (int i = 0; i < grid_h; ++i) {
    const int f = static_cast<int>(h_idxs[static_cast<size_t>(i)]);  // .int() truncates
    base_h[static_cast<size_t>(i)] = f * side;
    base_h_ceil[static_cast<size_t>(i)] = std::min(f + 1, side - 1) * side;
    dh[static_cast<size_t>(i)] = h_idxs[static_cast<size_t>(i)] - static_cast<float>(f);
  }
  for (int j = 0; j < grid_w; ++j) {
    const int f = static_cast<int>(w_idxs[static_cast<size_t>(j)]);
    w_floor[static_cast<size_t>(j)] = f;
    w_ceil[static_cast<size_t>(j)] = std::min(f + 1, side - 1);
    dw[static_cast<size_t>(j)] = w_idxs[static_cast<size_t>(j)] - static_cast<float>(f);
  }

  const size_t frames = size_t(grid_t) * grid_h * grid_w;
  pos_idx->assign(frames * 4, 0);
  pos_weight->assign(frames * 4, 0.0f);
  size_t k = 0;
  for (int t = 0; t < grid_t; ++t) {
    for (int i_blk = 0; i_blk < grid_h / 2; ++i_blk) {
      for (int j_blk = 0; j_blk < grid_w / 2; ++j_blk) {
        for (int i2 = 0; i2 < 2; ++i2) {
          const int i = i_blk * 2 + i2;
          const float dh_i = dh[static_cast<size_t>(i)];
          const float one_dh = 1.0f - dh_i;
          const int base_i = base_h[static_cast<size_t>(i)];
          const int base_i_ceil = base_h_ceil[static_cast<size_t>(i)];
          for (int j2 = 0; j2 < 2; ++j2) {
            const int j = j_blk * 2 + j2;
            const float dw_j = dw[static_cast<size_t>(j)];
            const float one_dw = 1.0f - dw_j;
            (*pos_idx)[k + 0] = base_i + w_floor[static_cast<size_t>(j)];
            (*pos_idx)[k + 1] = base_i + w_ceil[static_cast<size_t>(j)];
            (*pos_idx)[k + 2] = base_i_ceil + w_floor[static_cast<size_t>(j)];
            (*pos_idx)[k + 3] = base_i_ceil + w_ceil[static_cast<size_t>(j)];
            (*pos_weight)[k + 0] = one_dh * one_dw;
            (*pos_weight)[k + 1] = one_dh * dw_j;
            (*pos_weight)[k + 2] = dh_i * one_dw;
            (*pos_weight)[k + 3] = dh_i * dw_j;
            k += 4;
          }
        }
      }
    }
  }
}

// ===========================================================================
// M-RoPE position matrix (demo get_rope_index)
// ===========================================================================

void vision_rope_index(const std::vector<int32_t>& ids,
                       const std::vector<std::vector<int>>& image_grids,
                       int32_t vision_start_id, int32_t image_pad_id,
                       int spatial_merge, std::vector<int32_t>* pos3) {
  // Faithful to the demo's get_rope_index, including a detail that is easy to
  // get wrong: the text run is everything up to the *first <|image_pad|>* after
  // the cursor, so <|vision_start|> carries an ordinary text position, and the
  // 3-D image block starts at the pad. Each image_pad covers spatial_merge^2
  // patches, so a block is t * (h/m) * (w/m) tokens long.
  const size_t n = ids.size();
  pos3->assign(n * 3, 0);
  auto put = [&](size_t row, int32_t t, int32_t h, int32_t w) {
    (*pos3)[row] = t;
    (*pos3)[n + row] = h;
    (*pos3)[2 * n + row] = w;
  };

  size_t image_index = 0;
  size_t st = 0;         // cursor into `ids`
  int32_t st_idx = 0;    // next position value
  const size_t images = image_grids.size();
  size_t seen_images = 0;
  (void)vision_start_id;

  while (st < n) {
    // The reference walks vision_start occurrences; each one owns one image.
    if (seen_images < images) {
      // ed = first image_pad at or after st (the demo's input_tokens.index).
      size_t ed = n;
      for (size_t k = st; k < n; ++k) {
        if (ids[k] == image_pad_id) {
          ed = k;
          break;
        }
      }
      if (ed < n) {
        const std::vector<int>& g = image_grids[image_index];
        const int t = g[0], h = g[1], w = g[2];
        const int lt = t, lh = h / spatial_merge, lw = w / spatial_merge;
        const size_t block = size_t(lt) * lh * lw;
        const int32_t text_len = static_cast<int32_t>(ed - st);

        // Text run [st, ed), including <|vision_start|>.
        for (size_t k = st; k < ed; ++k) {
          const int32_t p = st_idx + static_cast<int32_t>(k - st);
          put(k, p, p, p);
        }
        // 3-D block, ordered t-major then row then column.
        size_t row = ed;
        for (int ti = 0; ti < lt; ++ti) {
          for (int hi = 0; hi < lh; ++hi) {
            for (int wi = 0; wi < lw; ++wi) {
              if (row >= n) break;
              put(row, st_idx + text_len + ti, st_idx + text_len + hi,
                  st_idx + text_len + wi);
              ++row;
            }
          }
        }
        // Next st_idx continues past the block's largest value.
        st_idx += text_len + std::max({lt, lh, lw});
        st = ed + block;
        ++image_index;
        ++seen_images;
        continue;
      }
    }
    // No more images: the rest of the prompt is plain text.
    for (size_t k = st; k < n; ++k) {
      const int32_t p = st_idx + static_cast<int32_t>(k - st);
      put(k, p, p, p);
    }
    break;
  }
}

}  // namespace cv84x6
