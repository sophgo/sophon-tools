// Board memory-bandwidth calibration, so a per-graph time can be judged against
// the roofline instead of being called "slow" by eye.
//
//   ./bw_probe <model.bmodel> [--mb N]
//
// Reads N MiB out of the loaded weights with an on-device d2d copy (both ends
// in the NPU heap, so this is the same path a graph's weight fetch takes) and
// reports GB/s. Also times an s2d of the same size, which crosses PCIe-free
// on-SoC DDR and is therefore the upper bound the TPU itself can reach.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

namespace {
double now_ms() {
  using clock = std::chrono::steady_clock;
  return std::chrono::duration<double, std::milli>(clock::now().time_since_epoch()).count();
}
}  // namespace

int main(int argc, char** argv) {
  int mb = 256;
  for (int i = 1; i < argc; i++)
    if (!std::strcmp(argv[i], "--mb") && i + 1 < argc) mb = std::atoi(argv[++i]);

  bm_handle_t handle;
  if (bm_dev_request(&handle, 0) != BM_SUCCESS) {
    std::fprintf(stderr, "bm_dev_request failed\n");
    return 1;
  }
  const size_t bytes = static_cast<size_t>(mb) << 20;
  bm_device_mem_t a{}, b{};
  if (bm_malloc_device_byte_heap_mask(handle, &a, 3, static_cast<unsigned int>(bytes)) != BM_SUCCESS ||
      bm_malloc_device_byte_heap_mask(handle, &b, 3, static_cast<unsigned int>(bytes)) != BM_SUCCESS) {
    std::fprintf(stderr, "alloc %d MiB failed\n", mb);
    return 1;
  }
  std::vector<char> host(bytes, 1);

  // d2d: read `bytes` and write `bytes`.
  bm_memcpy_s2d(handle, a, host.data());
  bm_thread_sync(handle);
  const int iters = 10;
  double t0 = now_ms();
  for (int k = 0; k < iters; k++) bm_memcpy_d2d_byte(handle, b, 0, a, 0, bytes);
  bm_thread_sync(handle);
  const double d2d_ms = (now_ms() - t0) / iters;

  t0 = now_ms();
  for (int k = 0; k < iters; k++) bm_memcpy_s2d(handle, a, host.data());
  bm_thread_sync(handle);
  const double s2d_ms = (now_ms() - t0) / iters;

  std::printf("size %d MiB\n", mb);
  // bytes / ms * 1000 = bytes/s; /1e9 = GB/s. A d2d copy moves `bytes` and
  // touches `bytes` at each end, so both figures are printed and the report
  // always says which one it means.
  const double d2d_gbs = bytes / d2d_ms * 1000 / 1e9;
  const double s2d_gbs = bytes / s2d_ms * 1000 / 1e9;
  std::printf("d2d  %8.3f ms  -> %7.1f GB/s moved  (%7.1f GB/s touched)\n", d2d_ms,
              d2d_gbs, 2 * d2d_gbs);
  std::printf("s2d  %8.3f ms  -> %7.1f GB/s\n", s2d_ms, s2d_gbs);

  bm_free_device(handle, a);
  bm_free_device(handle, b);
  bm_dev_free(handle);
  return 0;
}
