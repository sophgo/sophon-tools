// Is the backlog budget per device, per core, or per thread?
//
//   ./queue_threads <model.bmodel> [--threads N] [--launch K]
//
// MYS-2469's vendor question list asks whether the unfinished-queue depth is a
// device-wide resource or one per submitting thread. That is testable here.
//
// libbmlib binds each submitting thread to one of the driver's eight hardware
// queues round-robin; the driver logs it and /proc/bmtpu/kernel_info reports the
// per-HWQ push counters. Two observations settle the question:
//
//   1. Which HWQ each thread's launches land on (pushed_cnt delta per HWQ).
//      One HWQ per thread and N distinct HWQs means the queues are per thread.
//
//   2. Where each thread's submit cost jumps from ~60 us to ~585 us. If every
//      thread independently gets ~17 cheap launches before its own first stall,
//      the backlog budget is per thread. If the threads share one budget, the
//      first thread's stalls start earlier once the others are also queueing.
//
// Thread K only starts after all threads have reached the barrier, so the
// shared-budget case is given every chance to show up.
//
// Board safety: every graph input is zeroed before the first launch.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

namespace {

double now_ms() {
  using clock = std::chrono::steady_clock;
  return std::chrono::duration<double, std::milli>(clock::now().time_since_epoch()).count();
}

bm_tensor_t tensor_of(bm_device_mem_t mem, bm_data_type_t dt, bm_shape_t shape) {
  bm_tensor_t t{};
  bmrt_tensor_with_device(&t, mem, dt, shape);
  t.st_mode = BM_STORE_1N;
  return t;
}

std::vector<unsigned long long> hwq_pushed() {
  std::vector<unsigned long long> out;
  FILE* f = std::fopen("/proc/bmtpu/kernel_info", "r");
  if (!f) return out;
  char line[256];
  while (std::fgets(line, sizeof(line), f)) {
    unsigned long long u = 0;
    if (std::sscanf(line, " pushed_cnt: %llu", &u) == 1) out.push_back(u);
  }
  std::fclose(f);
  return out;
}

struct Ctx {
  void* bmrt;
  bm_handle_t handle;
  const bm_net_info_t* net;
  std::vector<bm_tensor_t> in, out;
  std::vector<double> each_us;
  int k;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--threads N] [--launch K]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  int threads = 4;
  int k = 40;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--threads") && i + 1 < argc) threads = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--launch") && i + 1 < argc) k = std::atoi(argv[++i]);
  }

  bm_handle_t handle;
  if (bm_dev_request(&handle, 0) != BM_SUCCESS) {
    std::fprintf(stderr, "bm_dev_request failed\n");
    return 1;
  }
  void* bmrt = bmrt_create(handle);
  bmrt_set_flags(bmrt, BM_RUNTIME_SHARE_MEM);
  if (!bmrt_load_bmodel(bmrt, path)) {
    std::fprintf(stderr, "bmrt_load_bmodel failed\n");
    return 1;
  }
  bm_thread_sync(handle);
  const bm_net_info_t* net = bmrt_get_network_info(bmrt, "block_cache_0");
  if (!net) {
    std::fprintf(stderr, "no block_cache_0\n");
    return 1;
  }

  std::vector<Ctx> cs(threads);
  for (int i = 0; i < threads; i++) {
    cs[i].bmrt = bmrt;
    cs[i].handle = handle;
    cs[i].net = net;
    cs[i].k = k;
    const auto& st = net->stages[0];
    for (int j = 0; j < net->input_num; j++) {
      int zero = 0;
      bm_memset_device_ext(handle, &zero, 1, st.input_mems[j]);
      cs[i].in.push_back(tensor_of(st.input_mems[j], net->input_dtypes[j], st.input_shapes[j]));
    }
    for (int j = 0; j < net->output_num; j++)
      cs[i].out.push_back(tensor_of(st.output_mems[j], net->output_dtypes[j], st.output_shapes[j]));
  }

  // Warm each thread's path once so the first sample is not a page fault.
  for (int i = 0; i < threads; i++) {
    bmrt_launch_tensor_ex(bmrt, net->name, cs[i].in.data(), net->input_num, cs[i].out.data(),
                          net->output_num, true, true);
    bm_thread_sync(handle);
  }

  std::vector<unsigned long long> before = hwq_pushed();

  std::atomic<int> ready{0};
  std::vector<std::thread> ts;
  for (int i = 0; i < threads; i++) {
    ts.emplace_back([&, i]() {
      ready.fetch_add(1);
      while (ready.load() < threads) std::this_thread::yield();
      for (int j = 0; j < k; j++) {
        double a = now_ms();
        bmrt_launch_tensor_ex(bmrt, net->name, cs[i].in.data(), net->input_num, cs[i].out.data(),
                              net->output_num, true, true);
        cs[i].each_us.push_back((now_ms() - a) * 1000.0);
      }
      bm_thread_sync(handle);
    });
  }
  for (size_t i = 0; i < ts.size(); i++) ts[i].join();

  std::vector<unsigned long long> after = hwq_pushed();

  std::printf("# %d threads x %d unsynced launches each, one sync per thread\n\n", threads, k);
  std::printf("## where each thread's submit cost jumps (first index above 3x its own baseline)\n");
  std::printf("%8s %14s %14s %14s\n", "thread", "baseline_us", "first_stall", "stall_us");
  std::vector<int> fills;
  for (int i = 0; i < threads; i++) {
    const std::vector<double>& e = cs[i].each_us;
    if (e.size() < 3) continue;
    double base = e[0];
    int fill = -1;
    for (size_t j = 0; j < e.size(); j++)
      if (e[j] > 3.0 * base) { fill = (int)j; break; }
    double stall = fill >= 0 ? e[fill] : 0;
    fills.push_back(fill);
    std::printf("%8d %14.1f %14d %14.1f\n", i, base, fill < 0 ? -1 : fill + 1, stall);
  }

  std::printf("\n## per-HWQ push counts during the run\n");
  std::printf("%6s %14s\n", "HWQ", "pushed_delta");
  int used = 0;
  for (size_t i = 0; i < after.size() && i < before.size(); i++) {
    unsigned long long d = after[i] - before[i];
    std::printf("%6zu %14llu%s\n", i, d, d ? "  <- used" : "");
    if (d) used++;
  }
  std::printf("\ndistinct HWQs used by %d threads: %d\n", threads, used);

  std::printf("\n## interpretation\n");
  int min_fill = fills.empty() ? -1 : *std::min_element(fills.begin(), fills.end());
  int max_fill = fills.empty() ? -1 : *std::max_element(fills.begin(), fills.end());
  std::printf("first-stall index per thread ranges %d..%d\n", min_fill, max_fill);
  if (min_fill >= 15 && used >= threads)
    std::printf("=> each thread got its own ~16-deep budget on its own HWQ: per-thread/per-HWQ\n");
  else if (max_fill < 15)
    std::printf("=> the budget shrank when threads shared it: a shared resource\n");
  else
    std::printf("=> inconclusive: inspect the per-thread columns above\n");

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
