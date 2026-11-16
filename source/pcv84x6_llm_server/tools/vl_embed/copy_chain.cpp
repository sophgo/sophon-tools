// MYS-2913: model-free A -> B -> C device-copy chain probe.
//
// The WeMM encoder does this: copy a graph's output into an independent buffer,
// then feed that buffer to the next graph. Nothing in between waits for the
// copy to retire. This program reproduces exactly that dependency pattern with
// no model, no image and no customer data:
//
//   A: filled with deterministic non-zero bytes on the host
//   B, C: zeroed on the host
//   A -> B   (bm_memcpy_d2d_byte)
//   [optional device sync here -- the "fence" arm]
//   B -> C   (bm_memcpy_d2d_byte)
//   sync, then read C back and compare byte for byte against A
//
// If the second copy reads B before the first copy has landed, C comes back
// wrong; the observed failure is an entire block of zeros, i.e. C still holds
// its pre-clear contents. With the fence, every byte matches.
//
// Every API return value is checked and the process exits non-zero on any
// failure, so "exit 0" cannot be mistaken for "all data correct". All buffers
// are allocated by this process and freed on every exit path.
//
// Build (board, links the installed libsophon) -- see copy_chain_build.sh:
//   bash copy_chain_build.sh [out-dir]
//
// Run:
//   ./copy-chain --trials 64 --no-fence     # expect intermittent whole-block zeros
//   ./copy-chain --trials 64 --fence        # expect 0 mismatched bytes every trial
//
// Exit codes: 0 all requested trials were byte-identical; 1 at least one trial
// mismatched (a real finding, not a tool error); 2..9 setup/API failure.

#include "bmlib_runtime.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

constexpr unsigned kBlockBytes = 2u * 1024u * 1024u;

// Deterministic, never-zero payload: a zero byte in the source would make a
// "still zero" destination indistinguishable from a correct copy.
unsigned char payload(unsigned index, int trial) {
  return static_cast<unsigned char>(1 + (index * 17u + trial * 23u) % 251u);
}

struct Buffers {
  bm_handle_t handle = nullptr;
  bm_device_mem_t a{}, b{}, c{};
  bool a_ok = false, b_ok = false, c_ok = false;

  ~Buffers() {
    // Free in reverse order of allocation; ignore errors here because the
    // process is already tearing down and the trial results are printed.
    if (handle) bm_thread_sync(handle);
    if (c_ok) bm_free_device(handle, c);
    if (b_ok) bm_free_device(handle, b);
    if (a_ok) bm_free_device(handle, a);
    if (handle) bm_dev_free(handle);
  }
};

}  // namespace

int main(int argc, char** argv) {
  int trials = 64;
  bool fence = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--fence") {
      fence = true;
    } else if (arg == "--no-fence") {
      fence = false;
    } else if (arg == "--trials" && i + 1 < argc) {
      trials = std::atoi(argv[++i]);
    } else if (arg.rfind("--trials=", 0) == 0) {
      trials = std::atoi(arg.c_str() + 9);
    } else {
      std::fprintf(stderr, "usage: %s [--trials N] [--fence|--no-fence]\n", argv[0]);
      return 2;
    }
  }
  if (trials <= 0) {
    std::fprintf(stderr, "trials must be positive\n");
    return 2;
  }

  Buffers buf;
  if (bm_dev_request(&buf.handle, 0) != BM_SUCCESS) {
    std::fprintf(stderr, "bm_dev_request failed\n");
    return 3;
  }
  if (bm_malloc_device_byte(buf.handle, &buf.a, kBlockBytes) != BM_SUCCESS) {
    std::fprintf(stderr, "allocate A failed\n");
    return 4;
  }
  buf.a_ok = true;
  if (bm_malloc_device_byte(buf.handle, &buf.b, kBlockBytes) != BM_SUCCESS) {
    std::fprintf(stderr, "allocate B failed\n");
    return 4;
  }
  buf.b_ok = true;
  if (bm_malloc_device_byte(buf.handle, &buf.c, kBlockBytes) != BM_SUCCESS) {
    std::fprintf(stderr, "allocate C failed\n");
    return 4;
  }
  buf.c_ok = true;

  std::printf("block_bytes=%u trials=%d fence=%d\n", kBlockBytes, trials, int(fence));
  std::vector<unsigned char> source(kBlockBytes), zeros(kBlockBytes, 0), result(kBlockBytes);
  unsigned bad_trials = 0;
  unsigned zero_blocks = 0;
  unsigned total_mismatched = 0;

  for (int trial = 0; trial < trials; ++trial) {
    for (unsigned i = 0; i < kBlockBytes; ++i) source[i] = payload(i, trial);

    // Seed the three buffers. A holds the payload, B and C are cleared so that
    // "C still zero" can only mean the A->B->C chain never delivered data.
    if (bm_memcpy_s2d(buf.handle, buf.a, source.data()) != BM_SUCCESS ||
        bm_memcpy_s2d(buf.handle, buf.b, zeros.data()) != BM_SUCCESS ||
        bm_memcpy_s2d(buf.handle, buf.c, zeros.data()) != BM_SUCCESS) {
      std::fprintf(stderr, "trial %d: host-to-device seed failed\n", trial);
      return 5;
    }
    if (bm_memcpy_d2d_byte(buf.handle, buf.b, 0, buf.a, 0, kBlockBytes) != BM_SUCCESS) {
      std::fprintf(stderr, "trial %d: copy A->B failed\n", trial);
      return 6;
    }
    if (fence && bm_thread_sync(buf.handle) != BM_SUCCESS) {
      std::fprintf(stderr, "trial %d: fence sync failed\n", trial);
      return 7;
    }
    // The dependent copy: this is the step that reads B. Without the fence it
    // may run before A->B has landed.
    if (bm_memcpy_d2d_byte(buf.handle, buf.c, 0, buf.b, 0, kBlockBytes) != BM_SUCCESS) {
      std::fprintf(stderr, "trial %d: copy B->C failed\n", trial);
      return 6;
    }
    if (bm_thread_sync(buf.handle) != BM_SUCCESS) {
      std::fprintf(stderr, "trial %d: final sync failed\n", trial);
      return 7;
    }
    if (bm_memcpy_d2s(buf.handle, result.data(), buf.c) != BM_SUCCESS) {
      std::fprintf(stderr, "trial %d: device-to-host read failed\n", trial);
      return 8;
    }

    unsigned mismatched = 0, zeros_seen = 0;
    for (unsigned i = 0; i < kBlockBytes; ++i) {
      if (result[i] != source[i]) ++mismatched;
      if (result[i] == 0) ++zeros_seen;
    }
    total_mismatched += mismatched;
    if (mismatched) {
      ++bad_trials;
      if (zeros_seen == kBlockBytes) ++zero_blocks;
      std::printf(
          "trial=%d fence=%d mismatched=%u/%u zero_bytes=%u "
          "first_actual=%u first_expected=%u\n",
          trial, int(fence), mismatched, kBlockBytes, zeros_seen,
          unsigned(result[0]), unsigned(source[0]));
    }
  }

  std::printf(
      "summary fence=%d bad_trials=%u/%d zero_blocks=%u total_mismatched=%u\n",
      int(fence), bad_trials, trials, zero_blocks, total_mismatched);
  // A mismatched trial is the finding under test, not a tool failure, but the
  // exit code must still say so: callers cannot treat 0 as "data was correct".
  return bad_trials == 0 ? 0 : 1;
}
