// Where does the 17-launch backlog limit live, and is it per device, per core,
// or per thread?
//
//   ./queue_scope <model.bmodel> [--net block_cache_0] [--threads N]
//
// MYS-2469 asks three vendor questions that can be partly answered from the
// board without any private switch:
//   (a) is the depth fixed or configurable at run time?
//   (b) is it per device, per core, or per thread?
//   (c) what is the safe upper bound?
//
// (b) is answerable here: libbmlib binds each submitting thread to one of the
// driver's hardware queues round-robin (the driver logs "Thread bound to HWQ %d
// (Round Robin)"), and the driver reports 8 HWQs of 16 slots each. If the
// backlog limit is per HWQ, N threads should accept ~N x 17 launches before any
// of them blocks. If it is a single global budget, N threads share 17.
//
// Occupancy is read from the driver itself, not inferred: /proc/bmtpu/kernel_info
// prints "free_slots" per HWQ, and /proc/bmtpu/wakeup_control repeats it. Those
// are the driver's own counters over the same hardware registers, so they are
// evidence of what the queue actually holds.
//
// Board safety: every graph input is zeroed before the first launch (see
// analysis/README.md).
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

// Per-HWQ free slots straight out of the driver's seq_file.
std::vector<int> hwq_free_slots() {
  std::vector<int> out;
  FILE* f = std::fopen("/proc/bmtpu/kernel_info", "r");
  if (!f) return out;
  char line[256];
  while (std::fgets(line, sizeof(line), f)) {
    int v = -1;
    if (std::sscanf(line, " free_slots: %d", &v) == 1) out.push_back(v);
  }
  std::fclose(f);
  return out;
}

int total_free_slots() {
  std::vector<int> v = hwq_free_slots();
  int s = 0;
  for (size_t i = 0; i < v.size(); i++) s += v[i];
  return v.empty() ? -1 : s;
}

std::string slots_str() {
  std::vector<int> v = hwq_free_slots();
  std::string s;
  char b[16];
  for (size_t i = 0; i < v.size(); i++) {
    std::snprintf(b, sizeof(b), "%s%d", i ? "," : "", v[i]);
    s += b;
  }
  return v.empty() ? std::string("n/a") : s;
}

struct Worker {
  void* bmrt;
  bm_handle_t handle;
  const bm_net_info_t* net;
  std::vector<bm_tensor_t> in, out;
  int n_launch;
  double submit_ms{0}, sync_ms{0}, total_ms{0};
  // Highest number of launches this thread got accepted before one blocked.
  // Measured separately: launch one at a time and watch each individual cost.
  std::vector<double> each_us;

  bool init(void* rt, bm_handle_t h, const bm_net_info_t* nt) {
    bmrt = rt; handle = h; net = nt;
    const auto& st = nt->stages[0];
    for (int i = 0; i < nt->input_num; i++) {
      int zero = 0;
      bm_memset_device_ext(handle, &zero, 1, st.input_mems[i]);
      in.push_back(tensor_of(st.input_mems[i], nt->input_dtypes[i], st.input_shapes[i]));
    }
    for (int i = 0; i < nt->output_num; i++)
      out.push_back(tensor_of(st.output_mems[i], nt->output_dtypes[i], st.output_shapes[i]));
    return true;
  }

  bool launch() {
    return bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num, out.data(),
                                 net->output_num, true, true);
  }

  void run() {
    double a = now_ms();
    for (int i = 0; i < n_launch; i++) launch();
    double b = now_ms();
    bm_thread_sync(handle);
    double c = now_ms();
    submit_ms = b - a;
    sync_ms = c - b;
    total_ms = c - a;
  }

  void run_per_launch() {
    each_us.clear();
    for (int i = 0; i < n_launch; i++) {
      double a = now_ms();
      launch();
      each_us.push_back((now_ms() - a) * 1000.0);
    }
    bm_thread_sync(handle);
  }
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--net NAME] [--threads N]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  const char* net_name = "block_cache_0";
  int threads = 2;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--net") && i + 1 < argc) net_name = argv[++i];
    else if (!std::strcmp(argv[i], "--threads") && i + 1 < argc) threads = std::atoi(argv[++i]);
  }
  if (threads < 1) threads = 1;

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

  std::printf("## driver-reported queue geometry (at rest)\n");
  std::printf("free slots per HWQ: [%s]  total=%d\n\n", slots_str().c_str(), total_free_slots());

  // ---- 1. Watch individual submit costs in one thread: where does it block?
  {
    Worker w;
    w.init(bmrt, handle, net);
    w.n_launch = 48;
    w.run_per_launch();
    std::printf("## one thread, 48 launches, individual submit cost (us)\n");
    for (size_t i = 0; i < w.each_us.size(); i++) {
      std::printf("%3zu %8.1f%s\n", i + 1, w.each_us[i],
                  (i == 0 || w.each_us[i] < 150.0) ? "" : "   <- blocked");
    }
    // First index whose cost jumps above 3x the cheap baseline.
    double base = w.each_us[0];
    int fill = -1;
    for (size_t i = 0; i < w.each_us.size(); i++)
      if (w.each_us[i] > 3.0 * base) { fill = (int)i; break; }
    std::printf("first blocking launch index = %d (1-based: %d)\n\n", fill,
                fill < 0 ? -1 : fill + 1);
  }

  // ---- 2. Does adding threads multiply the accepted backlog?
  std::printf("## N threads each launching 40 unsynced, one sync each\n");
  std::printf("%8s %12s %12s %12s %14s\n", "threads", "submit_ms", "sync_ms", "total_ms", "per_thread_ms");
  for (int nt = 1; nt <= threads; nt++) {
    std::vector<Worker> ws(nt);
    for (int i = 0; i < nt; i++) {
      ws[i].init(bmrt, handle, net);
      ws[i].n_launch = 40;
    }
    // Warm
    for (int i = 0; i < nt; i++) { ws[i].n_launch = 1; ws[i].run(); ws[i].n_launch = 40; }

    std::atomic<int> ready{0};
    std::vector<std::thread> ts;
    for (int i = 0; i < nt; i++) {
      ts.emplace_back([&, i]() {
        ready.fetch_add(1);
        while (ready.load() < nt) std::this_thread::yield();
        ws[i].run();
      });
    }
    for (size_t i = 0; i < ts.size(); i++) ts[i].join();

    double mx_tot = 0, mx_sub = 0, mx_syn = 0;
    for (int i = 0; i < nt; i++) {
      mx_tot = std::max(mx_tot, ws[i].total_ms);
      mx_sub = std::max(mx_sub, ws[i].submit_ms);
      mx_syn = std::max(mx_syn, ws[i].sync_ms);
    }
    std::printf("%8d %12.3f %12.3f %12.3f %14.3f\n", nt, mx_sub, mx_syn, mx_tot, mx_tot);
  }

  std::printf("\n## driver-reported queue geometry (after)\n");
  std::printf("free slots per HWQ: [%s]  total=%d\n", slots_str().c_str(), total_free_slots());

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
