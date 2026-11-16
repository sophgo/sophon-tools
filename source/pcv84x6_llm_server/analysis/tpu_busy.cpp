// Is the decode chain's wall time TPU-busy time, or CPU submit time?
//
//   ./tpu_busy <model.bmodel> [--net block_cache_0] [--iters N]
//
// The 33% figure in decode-optimization.md section 5.3 assumes the 585 us that
// each post-17th launch spends blocked is CPU cost a deeper queue would remove:
// "40 x 62 us = 2.5 ms instead of 13.6 ms, so ~11 ms/token". That only holds if
// the TPU would otherwise sit idle during those 13.6 ms.
//
// libsophon exposes the device's own accounting of that: bm_profile_t's
// tpu_process_time / tpu1_process_time and the sent/completed api counters,
// read through bm_get_profile(). Comparing TPU busy time against wall time for
// the same chain answers the question directly:
//
//   * wall ~= tpu_busy  -> the chain is TPU-bound. Deepening the queue cannot
//     shorten it; the submit stalls are the TPU working, not CPU overhead.
//   * wall >> tpu_busy  -> the CPU submit really is on the path, and the 33%
//     bound is at least directionally right.
//
// A one-layer isolated run is measured alongside so per-layer TPU time can be
// compared with the observed stall length. If they agree, each stall is exactly
// one layer of TPU time.
//
// Board safety: every graph input is zeroed before the first launch.
#include <algorithm>
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

bm_tensor_t tensor_of(bm_device_mem_t mem, bm_data_type_t dt, bm_shape_t shape) {
  bm_tensor_t t{};
  bmrt_tensor_with_device(&t, mem, dt, shape);
  t.st_mode = BM_STORE_1N;
  return t;
}

struct Snap {
  unsigned long tpu_us;    // tpu_process_time (us)
  unsigned long sent;      // sent_api_counter
  unsigned long done;      // completed_api_counter
  bool ok;
};

Snap read_profile(bm_handle_t h) {
  bm_profile_t p{};
  Snap s{0, 0, 0, false};
  if (bm_get_profile(h, &p) != BM_SUCCESS) return s;
  s.tpu_us = p.tpu_process_time;
  s.sent = p.sent_api_counter;
  s.done = p.completed_api_counter;
  s.ok = true;
  return s;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--net NAME] [--iters N]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  const char* net_name = "block_cache_0";
  int iters = 5;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--net") && i + 1 < argc) net_name = argv[++i];
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

  const bm_net_info_t* net = bmrt_get_network_info(bmrt, net_name);
  if (!net) {
    std::fprintf(stderr, "no net named %s\n", net_name);
    return 1;
  }
  const auto& st = net->stages[0];
  std::vector<bm_tensor_t> in, out;
  for (int i = 0; i < net->input_num; i++) {
    int zero = 0;
    bm_memset_device_ext(handle, &zero, 1, st.input_mems[i]);
    in.push_back(tensor_of(st.input_mems[i], net->input_dtypes[i], st.input_shapes[i]));
  }
  for (int i = 0; i < net->output_num; i++)
    out.push_back(tensor_of(st.output_mems[i], net->output_dtypes[i], st.output_shapes[i]));
  auto launch = [&]() {
    return bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num, out.data(),
                                 net->output_num, true, true);
  };

  Snap probe = read_profile(handle);
  if (!probe.ok) {
    std::printf("bm_get_profile unsupported on this device; cannot separate TPU busy time\n");
  }

  // Warm up; counters are read as deltas so warm-up cost is discarded anyway.
  for (int i = 0; i < 3; i++) { launch(); bm_thread_sync(handle); }

  std::printf("# net=%s  iters=%d\n\n", net->name, iters);

  // ---- 1 layer, 1 sync: pure per-layer TPU time.
  std::printf("## 1 layer then sync, %d reps\n", iters);
  std::printf("%5s %10s %12s %12s\n", "rep", "wall_ms", "tpu_us", "tpu/wall");
  std::vector<double> iso_wall, iso_tpu;
  for (int r = 0; r < iters; r++) {
    Snap a = read_profile(handle);
    double t0 = now_ms();
    launch();
    bm_thread_sync(handle);
    double t1 = now_ms();
    Snap b = read_profile(handle);
    double wall = t1 - t0;
    double tpu = (double)(b.tpu_us - a.tpu_us);
    iso_wall.push_back(wall);
    iso_tpu.push_back(tpu);
    std::printf("%5d %10.3f %12.0f %12.2f\n", r + 1, wall, tpu, tpu > 0 ? tpu / (wall * 1000) : 0);
  }

  // ---- 40 layers, 1 sync: the shipped decode chain shape.
  std::printf("\n## 40 layers then one sync, %d reps\n", iters);
  std::printf("%5s %10s %10s %10s %12s %12s %10s\n", "rep", "submit_ms", "sync_ms", "wall_ms",
              "tpu_us", "tpu/wall", "tpu_ms/40");
  std::vector<double> ch_wall, ch_tpu, ch_sub, ch_syn;
  for (int r = 0; r < iters; r++) {
    Snap a = read_profile(handle);
    double t0 = now_ms();
    for (int i = 0; i < 40; i++) launch();
    double tmid = now_ms();
    bm_thread_sync(handle);
    double t1 = now_ms();
    Snap b = read_profile(handle);
    double wall = t1 - t0;
    double tpu = (double)(b.tpu_us - a.tpu_us);
    ch_wall.push_back(wall);
    ch_tpu.push_back(tpu);
    ch_sub.push_back(tmid - t0);
    ch_syn.push_back(t1 - tmid);
    std::printf("%5d %10.3f %10.3f %10.3f %12.0f %12.2f %10.4f\n", r + 1, tmid - t0, t1 - tmid,
                wall, tpu, tpu > 0 ? tpu / (wall * 1000) : 0, tpu / 1000.0 / 40);
  }

  std::sort(iso_wall.begin(), iso_wall.end());
  std::sort(iso_tpu.begin(), iso_tpu.end());
  std::sort(ch_wall.begin(), ch_wall.end());
  std::sort(ch_tpu.begin(), ch_tpu.end());
  std::sort(ch_sub.begin(), ch_sub.end());
  std::sort(ch_syn.begin(), ch_syn.end());
  const double iw = iso_wall[iso_wall.size() / 2];
  const double it = iso_tpu[iso_tpu.size() / 2];
  const double cw = ch_wall[ch_wall.size() / 2];
  const double ct = ch_tpu[ch_tpu.size() / 2];
  const double cs = ch_sub[ch_sub.size() / 2];

  std::printf("\n## verdict inputs (medians)\n");
  std::printf("1 layer:  wall=%.3f ms  tpu=%.0f us  tpu/wall=%.2f\n", iw, it,
              it > 0 ? it / (iw * 1000) : 0);
  std::printf("40 layers wall=%.3f ms  tpu=%.0f us  tpu/wall=%.2f\n", cw, ct,
              ct > 0 ? ct / (cw * 1000) : 0);
  std::printf("40 layers submit=%.3f ms  (= CPU enqueue + TPU back-pressure)\n", cs);
  if (ct > 0) {
    std::printf("TPU busy time = %.3f ms; wall time = %.3f ms; slack = %+.3f ms\n", ct / 1000.0, cw,
                cw - ct / 1000.0);
    std::printf("per-layer TPU time = %.4f ms; observed stall after fill ~ 0.585 ms\n", ct / 1000.0 / 40);
    std::printf("A deeper queue could remove at most the CPU enqueue part of submit.\n");
    std::printf("CPU enqueue (40 x ~60 us) ~= %.2f ms; TPU busy = %.2f ms; total is bound by max()\n",
                40 * 0.060, ct / 1000.0);
    std::printf("=> best case with an infinite queue: %.2f ms vs actual %.2f ms (saving %.2f ms)\n",
                std::max(40 * 0.060, ct / 1000.0), cw, cw - std::max(40 * 0.060, ct / 1000.0));
  }

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
