// Small pieces the auxiliary engines share.
//
// The dtype conversions are the reference demos' own (LLM-TPU
// models/*/python_demo/chat.cpp): bf16 is the upper half of an fp32, and the
// fp16 path is a hand-written bit expansion -- including the denormal branch,
// which a naive shift gets wrong on the tiny weights these models produce.
// Accuracy here is not cosmetic: a mis-decoded half float moves a cosine
// similarity by far more than the 0.002 the acceptance run allows.

#pragma once

#include "bmruntime_interface.h"

#include <cstdint>
#include <cstring>

namespace cv84x6::aux {

// A zero to hand bm_memset_device_ext. Non-const only because libsophon's
// signature takes ``void*`` rather than ``const void*``; nothing writes it.
inline int kZero = 0;

inline float bf16_to_f32(uint16_t v) {
  const uint32_t u = static_cast<uint32_t>(v) << 16;
  float f;
  std::memcpy(&f, &u, sizeof(f));
  return f;
}

inline float fp16_to_f32(uint16_t h) {
  const uint32_t sign = (h >> 15) & 1u;
  const uint32_t exp = (h >> 10) & 0x1fu;
  const uint32_t mant = h & 0x3ffu;
  uint32_t f;
  if (exp == 0) {
    if (mant == 0) {
      f = sign << 31;
    } else {
      // Denormal: normalise it into an fp32 with a real exponent.
      uint32_t m = mant;
      uint32_t e = 1;
      while (!(m & 0x400u)) {
        m <<= 1;
        e--;
      }
      m &= 0x3ffu;
      f = (sign << 31) | ((e + 127 - 15) << 23) | (m << 13);
    }
  } else if (exp == 31) {
    f = (sign << 31) | 0x7f800000u | (mant << 13);
  } else {
    f = (sign << 31) | ((exp + 127 - 15) << 23) | (mant << 13);
  }
  float out;
  std::memcpy(&out, &f, sizeof(out));
  return out;
}

// One element of a 16-bit-typed output buffer as float.
inline float to_float(uint16_t raw, bm_data_type_t dtype) {
  return dtype == BM_FLOAT16 ? fp16_to_f32(raw) : bf16_to_f32(raw);
}

// f32 -> bf16 by truncation (the reference's `f32_to_bf16`: no rounding, the
// upper 16 bits are taken as-is, which is what the demo feeds the classifier).
inline void f32_to_bf16(const float* src, uint16_t* dst, int count) {
  const uint16_t* p = reinterpret_cast<const uint16_t*>(src);
  for (int i = 0; i < count; i++) dst[i] = p[i * 2 + 1];
}

// f32 -> fp16, round-to-nearest-even. Only the generic network engine needs the
// reverse direction (it hands the graph whatever width the bmodel declares, and
// every shipped OCR build is f16 internally with an f32 interface); the other
// engines only ever read 16-bit values, which is why this did not exist.
// Overflow saturates to inf rather than wrapping, and the denormal range is
// rounded through the same path as the normals -- silently producing a wrong
// half float here would show up as a box score drifting, not as an error.
inline uint16_t float_to_fp16(float v) {
  uint32_t f;
  std::memcpy(&f, &v, sizeof(f));
  const uint32_t sign = (f >> 16) & 0x8000u;
  const uint32_t exp = (f >> 23) & 0xffu;
  uint32_t mant = f & 0x7fffffu;
  if (exp == 0xffu) {
    // inf or NaN: keep the payload's top bits so a NaN stays a NaN.
    return static_cast<uint16_t>(sign | 0x7c00u | (mant ? 0x200u : 0u));
  }
  const int32_t e = static_cast<int32_t>(exp) - 127 + 15;
  if (e >= 0x1f) {
    return static_cast<uint16_t>(sign | 0x7c00u);  // overflow -> inf
  }
  if (e <= 0) {
    // Denormal (or zero). Shift the implicit 1 in and round to nearest even.
    if (e < -10) return static_cast<uint16_t>(sign);
    mant |= 0x800000u;
    const uint32_t shift = static_cast<uint32_t>(14 - e);
    uint32_t half = mant >> shift;
    const uint32_t rem = mant & ((1u << shift) - 1u);
    const uint32_t halfway = 1u << (shift - 1);
    if (rem > halfway || (rem == halfway && (half & 1u))) half++;
    return static_cast<uint16_t>(sign | half);
  }
  uint32_t half = (static_cast<uint32_t>(e) << 10) | (mant >> 13);
  const uint32_t rem = mant & 0x1fffu;
  if (rem > 0x1000u || (rem == 0x1000u && (half & 1u))) half++;
  return static_cast<uint16_t>(sign | half);
}

}  // namespace cv84x6::aux
