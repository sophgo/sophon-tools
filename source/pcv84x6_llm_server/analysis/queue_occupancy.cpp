// Direct observation of queue occupancy while it is saturated.
//
//   ./queue_occupancy <model.bmodel> [--nets N] [--iters N]
//
// Every other claim about "the unfinished queue is 17 deep" in this repo is
// inferred from submit *timing*. This probe instead reads the driver's own
// per-HWQ free-slot counters (/proc/bmtpu/kernel_info) from a watcher process
// while the launching thread is deliberately backlogged, so occupancy is
// measured rather than deduced.
//
// It also reports which HWQ each launching thread landed on, via the driver's
// own pushed_cnt per HWQ, which settles whether the queue budget is per device
// or per thread.
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

bm_tensor_t tensor_of(bm_device_mem_t mem, bm_data_type_t dt, bm_shape_t shape) {
  bm_tensor_t t{};
  bmrt_tensor_with_device(&t, mem, dt, shape);
  t.st_mode = BM_STORE_1N;
  return t;
}

// Parse "--- HWQ Index: N ---" blocks; return {free_slots, pushed_cnt} per HWQ.
struct HwqStat {
  int free_slots = -1;
  unsigned long long pushed = 0;
  unsigned long long done = 0;
};

std::vector<HwqStat> read_hwq() {
  std::vector<HwqStat> out;
  FILE* f = std::fopen("/proc/bmtpu/kernel_info", "r");
  if (!f) return out;
  char line[256];
  HwqStat cur;
  bool have = false;
  while (std::fgets(line, sizeof(line), f)) {
    int v = -1;
    unsigned long long u = 0;
    if (std::strstr(line, "--- HWQ Index:")) {
      if (have) out.push_back(cur);
      cur = HwqStat();
      have = true;
    } else if (std::sscanf(line, " free_slots: %d", &v) == 1) {
      cur.free_slots = v;
    } else if (std::sscanf(line, " pushed_cnt: %llu", &u) == 1) {
      cur.pushed = u;
    } else if (std::sscanf(line, " total done: %llu", &u) == 1) {
      cur.done = u;
    }
  }
  if (have) out.push_back(cur);
  std::fclose(f);
  return out;
}

std::string slots_str(const std::vector<HwqStat>& v) {
  std::string s;
  char b[24];
  for (size_t i = 0; i < v.size(); i++) {
    std::snprintf(b, sizeof(b), "%s%d", i ? "," : "", v[i].free_slots);
    s += b;
  }
  return v.empty() ? std::string("n/a") : s;
}

unsigned long long total_pushed(const std::vector<HwqStat>& v) {
  unsigned long long t = 0;
  for (size_t i = 0; i < v.size(); i++) t += v[i].pushed;
  return t;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--nets N] [--iters N]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  int nets = 8;
  int iters = 20;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--nets") && i + 1 < argc) nets = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--iters") && i + 1 < argc) iters = std::atoi(argv[++i]);
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

  std::vector<const bm_net_info_t*> ns;
  std::vector<std::vector<bm_tensor_t> > ins(nets), outs(nets);
  for (int i = 0; i < nets; i++) {
    std::string nm = "block_cache_" + std::to_string(i);
    const bm_net_info_t* net = bmrt_get_network_info(bmrt, nm.c_str());
    if (!net) break;
    const auto& st = net->stages[6 < net->stage_num ? 6 : 0];
    for (int k = 0; k < net->input_num; k++) {
      int zero = 0;
      bm_memset_device_ext(handle, &zero, 1, st.input_mems[k]);
      ins[i].push_back(tensor_of(st.input_mems[k], net->input_dtypes[k], st.input_shapes[k]));
    }
    for (int k = 0; k < net->output_num; k++)
      outs[i].push_back(tensor_of(st.output_mems[k], net->output_dtypes[k], st.output_shapes[k]));
    ns.push_back(net);
  }
  std::printf("# %zu graphs, %d iterations of a saturated run\n\n", ns.size(), iters);

  std::vector<HwqStat> before = read_hwq();
  std::printf("## at rest\n  free_slots=[%s]  pushed=[", slots_str(before).c_str());
  for (size_t i = 0; i < before.size(); i++)
    std::printf("%s%llu", i ? "," : "", before[i].pushed);
  std::printf("]\n\n");

  // Watcher thread: sample occupancy as fast as the proc read allows while the
  // launcher deliberately keeps the queue full (it queues `nets` graphs and only
  // syncs once every `nets` launches, so the backlog stays deep).
  std::atomic<bool> stop(false);
  std::atomic<int> min_total{1 << 30};
  std::atomic<int> min_first{1 << 30};
  std::atomic<int> samples{0};
  std::thread watcher([&]() {
    while (!stop.load()) {
      std::vector<HwqStat> v = read_hwq();
      if (!v.empty()) {
        int tot = 0;
        for (size_t i = 0; i < v.size(); i++) tot += v[i].free_slots;
        if (tot < min_total.load()) min_total.store(tot);
        if (v[0].free_slots < min_first.load()) min_first.store(v[0].free_slots);
        samples.fetch_add(1);
      }
      std::this_thread::yield();
    }
  });

  double submit_total = 0;
  for (int r = 0; r < iters; r++) {
    auto t0 = std::chrono::steady_clock::now();
    for (size_t i = 0; i < ns.size(); i++)
      bmrt_launch_tensor_ex(bmrt, ns[i]->name, ins[i].data(), ns[i]->input_num, outs[i].data(),
                            ns[i]->output_num, true, true);
    bm_thread_sync(handle);
    auto t1 = std::chrono::steady_clock::now();
    submit_total += std::chrono::duration<double, std::milli>(t1 - t0).count();
  }
  stop.store(true);
  watcher.join();

  std::vector<HwqStat> after = read_hwq();
  std::printf("## while saturated\n");
  std::printf("  watcher samples            = %d\n", samples.load());
  std::printf("  min free slots on HWQ 0    = %d  (of %d at rest)\n", min_first.load(),
              before.empty() ? -1 : before[0].free_slots);
  std::printf("  min free slots, all HWQs   = %d  (of %d at rest)\n", min_total.load(),
              (int)(before.size() * (before.empty() ? 0 : before[0].free_slots)));
  std::printf("  mean wall per saturated run= %.3f ms\n", submit_total / iters);

  std::printf("\n## push distribution after the run (which HWQ each thread used)\n");
  std::printf("  HWQ  pushed_delta  done_delta\n");
  for (size_t i = 0; i < after.size() && i < before.size(); i++) {
    std::printf("  %3zu %12llu %11llu\n", i, after[i].pushed - before[i].pushed,
                after[i].done - before[i].done);
  }
  std::printf("  total pushed delta = %llu\n", total_pushed(after) - total_pushed(before));

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
