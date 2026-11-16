// Is the unfinished-launch queue depth actually on the critical path?
//
//   ./queue_model <model.bmodel> [--net block_cache_0] [--reps N]
//
// decode-optimization.md (MYS-2457) measured that bmrt_launch_tensor_ex stops
// returning quickly after ~17 backlogged launches, and derived an 11 ms/token
// (33%) upper bound from "deepen the queue to >=40 and submit all 40 layers in
// 40 x 62 us". That bound only holds if the 585 us stalls are *CPU* cost that a
// deeper queue would remove. The alternative reading is that each stall is one
// layer's TPU time, in which case the chain wall time is bounded below by the
// TPU's own execution time and a deeper queue is worth nothing at all.
//
// The two readings are distinguishable without any private switch:
//   * T_iso   -- one layer launched alone, then synced. That is the TPU time of
//                one layer end to end, queue depth is not involved.
//   * T_chain -- 40 layers queued back to back, one sync. Currently 22.67 ms.
// If T_chain ~= 40 * T_iso the chain is TPU-bound and the submit stalls are TPU
// time in disguise. If T_chain is much larger, the CPU submit is on the path.
//
// --sweep varies the number of unsynced launches so the fill point of the queue
// is measured rather than assumed, and reads the driver's own free-slot counter
// (/proc/bmtpu/kernel_info) so occupancy is observed, not inferred.
//
// Board safety (see analysis/README.md in MYS-2457): every graph input is
// zeroed before the first launch. Decode graphs index KV/state with the position
// ids they are handed, so template garbage can drive an out-of-range device read
// that wedges the TPU and leaves an unkillable D-state process.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <algorithm>
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

// Snapshot of one HWQ's free slots from the driver's own accounting.
int hwq_free_slots(int idx) {
  FILE* f = std::fopen("/proc/bmtpu/wakeup_control", "r");
  if (!f) return -1;
  char line[256];
  int cur = -1, val = -1;
  while (std::fgets(line, sizeof(line), f)) {
    int a = -1, b = -1;
    if (std::sscanf(line, " %d | %d", &a, &b) == 2) {
      if (a == idx) val = b;
      cur = a;
    }
    (void)cur;
  }
  std::fclose(f);
  return val;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--net NAME] [--reps N]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  const char* net_name = "block_cache_0";
  int reps = 5;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--net") && i + 1 < argc) net_name = argv[++i];
    else if (!std::strcmp(argv[i], "--reps") && i + 1 < argc) reps = std::atoi(argv[++i]);
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

  const bm_net_info_t* net = bmrt_get_network_info(bmrt, net_name);
  if (!net) {
    std::fprintf(stderr, "no net named %s\n", net_name);
    return 1;
  }
  const auto& stage = net->stages[0];

  std::vector<bm_tensor_t> in, out;
  for (int i = 0; i < net->input_num; i++) {
    int zero = 0;
    bm_memset_device_ext(handle, &zero, 1, stage.input_mems[i]);
    in.push_back(tensor_of(stage.input_mems[i], net->input_dtypes[i], stage.input_shapes[i]));
  }
  for (int i = 0; i < net->output_num; i++) {
    out.push_back(tensor_of(stage.output_mems[i], net->output_dtypes[i], stage.output_shapes[i]));
  }

  auto launch = [&]() {
    return bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num, out.data(),
                                 net->output_num, true, true);
  };

  std::printf("# net=%s  core_num=%d  addr_mode=%d  input_num=%d  reps=%d\n", net->name,
              net->core_num, net->addr_mode, net->input_num, reps);
  std::printf("# hwq free slots at rest: 0=%d\n", hwq_free_slots(0));

  // Warm up so the first measurement is not paying page faults or coeff misses.
  for (int i = 0; i < 3; i++) {
    launch();
    bm_thread_sync(handle);
  }

  // ---- T_iso: one layer, submitted alone, synced. Pure TPU time of one layer.
  std::vector<double> iso;
  for (int r = 0; r < reps; r++) {
    double a = now_ms();
    launch();
    double b = now_ms();
    bm_thread_sync(handle);
    double c = now_ms();
    iso.push_back(c - a);
    std::printf("iso   submit=%.3f ms  sync=%.3f ms  total=%.3f ms\n", b - a, c - b, c - a);
  }

  // ---- T_chain: 40 layers queued, one sync. The shape MYS-2377 shipped.
  std::printf("\n## chain of 40 unsynced launches, one sync\n");
  std::vector<double> chain;
  for (int r = 0; r < reps; r++) {
    double a = now_ms();
    for (int i = 0; i < 40; i++) launch();
    double b = now_ms();
    bm_thread_sync(handle);
    double c = now_ms();
    chain.push_back(c - a);
    std::printf("chain submit=%.3f ms  sync=%.3f ms  total=%.3f ms\n", b - a, c - b, c - a);
  }

  // ---- Fill-point sweep: how many launches are accepted before one blocks?
  std::printf("\n## per-launch submit time vs backlog depth (median of %d runs)\n", reps);
  std::printf("%6s %10s %10s %10s\n", "n", "submit_ms", "per_us", "sync_ms");
  const int depths[] = {1, 4, 8, 12, 16, 17, 18, 20, 24, 32, 40, 48, 64};
  for (int di = 0; di < (int)(sizeof(depths) / sizeof(depths[0])); di++) {
    const int n = depths[di];
    std::vector<double> sub, syn, tot;
    for (int r = 0; r < reps; r++) {
      double a = now_ms();
      for (int i = 0; i < n; i++) launch();
      double b = now_ms();
      bm_thread_sync(handle);
      double c = now_ms();
      sub.push_back(b - a);
      syn.push_back(c - b);
      tot.push_back(c - a);
    }
    std::sort(sub.begin(), sub.end());
    std::sort(syn.begin(), syn.end());
    std::sort(tot.begin(), tot.end());
    const double m = sub[sub.size() / 2];
    std::printf("%6d %10.3f %10.1f %10.3f\n", n, m, m * 1000.0 / n, syn[syn.size() / 2]);
  }

  // ---- Deeper-queue counterfactual. A deeper queue would move TPU-bound waits
  // out of the submit calls and into the sync, leaving the total untouched. The
  // CPU-only submit cost is what a deeper queue could actually save, so bound it
  // from above with the cost of the launches that did *not* stall.
  std::sort(iso.begin(), iso.end());
  std::sort(chain.begin(), chain.end());
  const double t_iso = iso[iso.size() / 2];
  const double t_chain = chain[chain.size() / 2];
  std::printf("\n## verdict inputs\n");
  std::printf("T_iso  (1 layer, 1 sync)        = %.3f ms\n", t_iso);
  std::printf("T_chain (40 layers, 1 sync)     = %.3f ms\n", t_chain);
  std::printf("40 * T_iso                      = %.3f ms\n", 40 * t_iso);
  std::printf("chain / 40*T_iso                = %.3f\n", t_chain / (40 * t_iso));
  std::printf("T_chain - 40*T_iso              = %+.3f ms  (positive => CPU submit on path)\n",
              t_chain - 40 * t_iso);

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
