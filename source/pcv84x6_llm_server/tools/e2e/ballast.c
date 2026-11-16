/* ballast.c -- hold NPU heap without using it, so a run can be given the same
 * headroom the 6-model configuration has while only 5 models are resident.
 *
 * Why (MYS-2703 step 2): R11 (6 models, NPU 30440/30720 MiB) wedges in ~125 s
 * with chat x2; R15 (5 models, 28363 MiB, i.e. ~2 GiB more free) is clean on
 * the same load. Two things differ at once -- which models are resident, and
 * how much heap is left -- so the two cannot be told apart without changing one
 * of them alone. This program changes only the second: it allocates a block and
 * never touches it.
 *
 * It is deliberately a separate process. The workers own their own heap
 * allocations, and a ballast inside one of them would be freed by its unload;
 * holding it here keeps it alive for exactly as long as the load run needs it,
 * and its death returns the heap.
 *
 * Usage:
 *   ./ballast --mb 2047 --hold-s 1800
 * Prints one line when the allocation succeeded (the run script waits for it)
 * and one line when it exits. `bm_malloc_device_byte_heap_mask` with mask 1 is
 * the NPU heap, the same one `native/src/llm_engine.cpp` uses (mask 3 there
 * covers NPU+VPP; mask 1 pins this to NPU so it reproduces the R11 figure).
 */
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <unistd.h>

#include "bmlib_runtime.h"

int main(int argc, char** argv)
{
  long mb = 2047;
  long hold_s = 1800;
  for (int i = 1; i < argc; i++) {
    if (!std::strcmp(argv[i], "--mb") && i + 1 < argc) mb = std::atol(argv[++i]);
    else if (!std::strcmp(argv[i], "--hold-s") && i + 1 < argc)
      hold_s = std::atol(argv[++i]);
  }
  bm_handle_t h;
  if (bm_dev_request(&h, 0) != BM_SUCCESS) {
    std::printf("BALLAST_FAIL device\n");
    return 1;
  }
  bm_device_mem_t mem{};
  const unsigned int bytes = static_cast<unsigned int>(mb * 1024L * 1024L);
  // Mask 1 = the NPU heap alone, the one the 6-model figure is measured on.
  const bm_status_t st = bm_malloc_device_byte_heap_mask(h, &mem, 1, bytes);
  if (st != BM_SUCCESS) {
    std::printf("BALLAST_FAIL alloc %ld MiB status=%d\n", mb, st);
    bm_dev_free(h);
    return 1;
  }
  std::printf("BALLAST_OK %ld MiB addr=0x%llx\n", mb,
              (unsigned long long)bm_mem_get_device_addr(mem));
  std::fflush(stdout);
  for (long i = 0; i < hold_s; i++) sleep(1);
  bm_free_device(h, mem);
  std::printf("BALLAST_RELEASED\n");
  bm_dev_free(h);
  return 0;
}
