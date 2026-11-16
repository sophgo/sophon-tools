// Per-graph TPU time, and the inter-graph gap inside a chained token.
//
//   ./graph_tpu <model.bmodel> [--stage S] [--iters N]
//
// MYS-2469 asks whether merging the 40 block graphs into one net is worth doing
// as an alternative to a deeper queue. Both changes attack the same line item
// ("40 separate launches"), so both share a ceiling, and that ceiling is visible
// without touching the bmodel:
//
//   sum_iso  = sum over i of the TPU busy time of block_cache_<i> run alone
//   chain    = TPU busy time of the 40 graphs chained and synced once
//
//   chain - sum_iso = per-graph dispatch overhead *inside the TPU*, i.e. exactly
//                     what fusing the graphs into one net could remove.
//
// If that gap is small, fusing cannot pay for a recompile; if it is large, the
// experiment card for the compile side has a number to hit.
//
// TPU busy time comes from libsophon's own per-device accounting
// (bm_profile_t.tpu_process_time via bm_get_profile), not from wall clock, so it
// is unaffected by how the CPU happens to be scheduled.
//
// Board safety: every graph input is zeroed before its first launch.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
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

unsigned long tpu_us(bm_handle_t h) {
  bm_profile_t p{};
  if (bm_get_profile(h, &p) != BM_SUCCESS) return 0;
  return p.tpu_process_time;
}

struct Layer {
  const bm_net_info_t* net;
  std::vector<bm_tensor_t> in, out;
};

bool build(bm_handle_t h, const bm_net_info_t* net, int stage, Layer* L) {
  L->net = net;
  const auto& st = net->stages[stage < net->stage_num ? stage : 0];
  for (int i = 0; i < net->input_num; i++) {
    int zero = 0;
    bm_memset_device_ext(h, &zero, 1, st.input_mems[i]);
    L->in.push_back(tensor_of(st.input_mems[i], net->input_dtypes[i], st.input_shapes[i]));
  }
  for (int i = 0; i < net->output_num; i++)
    L->out.push_back(tensor_of(st.output_mems[i], net->output_dtypes[i], st.output_shapes[i]));
  return true;
}

bool launch(void* bmrt, Layer& L) {
  return bmrt_launch_tensor_ex(bmrt, L.net->name, L.in.data(), L.net->input_num, L.out.data(),
                               L.net->output_num, true, true);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--stage S] [--iters N]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  int stage = 6;
  int iters = 5;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--stage") && i + 1 < argc) stage = std::atoi(argv[++i]);
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

  std::vector<Layer> layers;
  for (int idx = 0;; idx++) {
    std::string nm = "block_cache_" + std::to_string(idx);
    const bm_net_info_t* net = bmrt_get_network_info(bmrt, nm.c_str());
    if (!net) break;
    Layer L;
    build(handle, net, stage, &L);
    layers.push_back(L);
  }
  if (layers.empty()) {
    std::fprintf(stderr, "no block_cache_* graphs\n");
    return 1;
  }
  std::printf("# %zu block graphs, stage=%d, iters=%d\n\n", layers.size(), stage, iters);

  // ---- Per graph, alone: TPU busy time and wall time, medians.
  std::printf("## each graph alone (median of %d)\n", iters);
  std::printf("%6s %-16s %10s %10s %10s\n", "idx", "net", "tpu_us", "wall_ms", "tpu/wall");
  std::vector<double> per_tpu;
  for (size_t i = 0; i < layers.size(); i++) {
    std::vector<double> tps, wls;
    for (int r = 0; r < iters + 1; r++) {  // +1 discarded warm
      unsigned long a = tpu_us(handle);
      double t0 = now_ms();
      launch(bmrt, layers[i]);
      bm_thread_sync(handle);
      double t1 = now_ms();
      unsigned long b = tpu_us(handle);
      if (r == 0) continue;
      tps.push_back((double)(b - a));
      wls.push_back(t1 - t0);
    }
    std::sort(tps.begin(), tps.end());
    std::sort(wls.begin(), wls.end());
    const double tp = tps[tps.size() / 2], wl = wls[wls.size() / 2];
    per_tpu.push_back(tp);
    std::printf("%6zu %-16s %10.0f %10.3f %10.2f\n", i, layers[i].net->name, tp, wl,
                tp > 0 ? tp / (wl * 1000) : 0);
  }
  double sum_iso = 0;
  for (size_t i = 0; i < per_tpu.size(); i++) sum_iso += per_tpu[i];

  // ---- The same graphs chained, one sync.
  for (size_t i = 0; i + 1 < layers.size(); i++)
    layers[i + 1].in[0].device_mem = layers[i].out[0].device_mem;

  std::printf("\n## all chained, one sync (median of %d)\n", iters);
  std::printf("%5s %10s %10s %10s %12s %12s\n", "rep", "submit_ms", "sync_ms", "wall_ms", "tpu_us",
              "tpu/wall");
  std::vector<double> ch_tpu, ch_wall, ch_sub;
  for (int r = 0; r < iters + 1; r++) {
    unsigned long a = tpu_us(handle);
    double t0 = now_ms();
    for (size_t i = 0; i < layers.size(); i++) launch(bmrt, layers[i]);
    double tm = now_ms();
    bm_thread_sync(handle);
    double t1 = now_ms();
    unsigned long b = tpu_us(handle);
    if (r == 0) continue;
    ch_sub.push_back(tm - t0);
    ch_wall.push_back(t1 - t0);
    ch_tpu.push_back((double)(b - a));
    std::printf("%5d %10.3f %10.3f %10.3f %12.0f %12.2f\n", r, tm - t0, t1 - tm, t1 - t0,
                (double)(b - a), (double)(b - a) / ((t1 - t0) * 1000));
  }
  std::sort(ch_tpu.begin(), ch_tpu.end());
  std::sort(ch_wall.begin(), ch_wall.end());
  const double ct = ch_tpu[ch_tpu.size() / 2], cw = ch_wall[ch_wall.size() / 2];

  const double gap_us = ct - sum_iso;
  std::printf("\n## graph-fusion ceiling (medians)\n");
  std::printf("sum of per-graph TPU time      = %.0f us (%.3f ms)\n", sum_iso, sum_iso / 1000);
  std::printf("chained TPU time               = %.0f us (%.3f ms)\n", ct, ct / 1000);
  std::printf("inter-graph TPU dispatch gap   = %.0f us (%.3f ms) over %zu graphs = %.1f us/graph\n",
              gap_us, gap_us / 1000, layers.size(), gap_us / layers.size());
  std::printf("chained wall                   = %.3f ms\n", cw);
  std::printf("wall - TPU busy                = %.3f ms (CPU enqueue + sync latency)\n",
              cw - ct / 1000);
  std::printf("\nA single fused net could remove the dispatch gap (%.3f ms) and the CPU\n",
              gap_us / 1000);
  std::printf("per-launch cost, bounded by wall-TPU (%.3f ms): combined ceiling %.3f ms\n",
              cw - ct / 1000, gap_us / 1000 + (cw - ct / 1000));
  std::printf("on a %.3f ms chain, i.e. %.1f%% of the decode chain.\n", cw,
              100.0 * (gap_us / 1000 + (cw - ct / 1000)) / cw);

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
