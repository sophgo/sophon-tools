// The real per-token shape: 40 distinct block_cache_<i> graphs chained through
// the shared hidden row, then lm_head, with TPU busy time measured alongside.
//
//   ./token_shape <model.bmodel> [--stage S] [--iters N] [--net-zero]
//
// This is the measurement MYS-2469 needs to price "deepen the queue to >=40".
// decode-optimization.md section 5.3 gives that change an 11 ms/token (33%)
// ceiling, computed as "40 x 62 us of enqueue instead of 13.6 ms of submit". The
// ceiling is only real if the CPU is the resource that runs out. So each rep
// records, from libsophon's own counters:
//
//   submit_ms  -- time inside the 40 bmrt_launch_tensor_ex calls
//   sync_ms    -- time inside the single bm_thread_sync
//   wall_ms    -- submit + sync (+ lm_head)
//   tpu_us     -- bm_profile_t.tpu_process_time delta over the same window
//
// If tpu_us tracks wall_ms, the TPU is busy the whole time and stalling the CPU
// on a full queue costs nothing that a deeper queue could recover: the stall is
// the TPU finishing the previous layer. The remaining headroom is then only
// wall - tpu, which is the true ceiling for any queue-depth change.
//
// Distinct graphs, not one graph repeated: each block_cache_<i> has its own
// coefficient set and its own vertex stream, so its launch cost differs from
// block_cache_0's. The chain is wired the way Engine::Impl::decode_layers does
// it -- layer i's output 0 becomes layer i+1's input 0 -- so the runtime sees
// the same dependency structure the service sees.
//
// Board safety: every graph input is zeroed before the first launch, and the
// whole chain then runs at a fixed decode shape. Feeding template garbage to a
// decode graph can drive an out-of-range device read that wedges the TPU on
// CV84X6 (see analysis/README.md in MYS-2457).
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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--stage S] [--iters N]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  int stage = 0;
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

  // Collect the decode chain the same way the engine does: every net whose name
  // starts with block_cache_, in index order.
  std::vector<Layer> layers;
  const char** names = nullptr;
  int num = bmrt_get_network_number(bmrt);
  bmrt_get_network_names(bmrt, &names);
  for (int idx = 0;; idx++) {
    std::string nm = "block_cache_" + std::to_string(idx);
    const bm_net_info_t* net = bmrt_get_network_info(bmrt, nm.c_str());
    if (!net) break;
    Layer L;
    L.net = net;
    const auto& st = net->stages[stage < net->stage_num ? stage : 0];
    for (int i = 0; i < net->input_num; i++) {
      int zero = 0;
      bm_memset_device_ext(handle, &zero, 1, st.input_mems[i]);
      L.in.push_back(tensor_of(st.input_mems[i], net->input_dtypes[i], st.input_shapes[i]));
    }
    for (int i = 0; i < net->output_num; i++)
      L.out.push_back(tensor_of(st.output_mems[i], net->output_dtypes[i], st.output_shapes[i]));
    layers.push_back(L);
  }
  const bm_net_info_t* lm = bmrt_get_network_info(bmrt, "lm_head");
  Layer Lm;
  Lm.net = lm;
  if (lm) {
    const auto& st = lm->stages[0];
    for (int i = 0; i < lm->input_num; i++) {
      int zero = 0;
      bm_memset_device_ext(handle, &zero, 1, st.input_mems[i]);
      Lm.in.push_back(tensor_of(st.input_mems[i], lm->input_dtypes[i], st.input_shapes[i]));
    }
    for (int i = 0; i < lm->output_num; i++)
      Lm.out.push_back(tensor_of(st.output_mems[i], lm->output_dtypes[i], st.output_shapes[i]));
  }

  std::printf("# model=%s\n", path);
  std::printf("# block graphs=%zu  lm_head=%s  stage=%d  iters=%d\n\n", layers.size(),
              lm ? "yes" : "no", stage, iters);
  if (layers.empty()) {
    std::fprintf(stderr, "no block_cache_* graphs found\n");
    return 1;
  }

  // Build the chain: layer i's out0 becomes layer i+1's in0 (addr_mode=1 means
  // the graph writes output 0 into its own template memory, which is exactly
  // what decode_layers relies on).
  for (size_t i = 0; i + 1 < layers.size(); i++)
    layers[i + 1].in[0].device_mem = layers[i].out[0].device_mem;
  if (lm) Lm.in[0].device_mem = layers.back().out[0].device_mem;

  auto run_chain = [&]() {
    for (size_t i = 0; i < layers.size(); i++)
      if (!bmrt_launch_tensor_ex(bmrt, layers[i].net->name, layers[i].in.data(),
                                 layers[i].net->input_num, layers[i].out.data(),
                                 layers[i].net->output_num, true, true))
        return false;
    return true;
  };

  // Warm
  for (int w = 0; w < 3; w++) { run_chain(); bm_thread_sync(handle); }

  std::printf("## %zu distinct block graphs, one sync, no lm_head\n", layers.size());
  std::printf("%5s %10s %10s %10s %12s %10s %12s\n", "rep", "submit_ms", "sync_ms", "wall_ms",
              "tpu_us", "tpu/wall", "wall-tpu_ms");
  std::vector<double> wall, tpu, sub;
  for (int r = 0; r < iters; r++) {
    unsigned long ta = tpu_us(handle);
    double t0 = now_ms();
    run_chain();
    double tm = now_ms();
    bm_thread_sync(handle);
    double t1 = now_ms();
    unsigned long tb = tpu_us(handle);
    double w = t1 - t0, tp = (double)(tb - ta);
    sub.push_back(tm - t0);
    wall.push_back(w);
    tpu.push_back(tp);
    std::printf("%5d %10.3f %10.3f %10.3f %12.0f %10.2f %12.3f\n", r + 1, tm - t0, t1 - tm, w, tp,
                tp > 0 ? tp / (w * 1000) : 0, w - tp / 1000.0);
  }

  if (lm) {
    // lm_head measured with an empty queue, so its launch time is its own cost
    // and not the chain still draining. Without this, the launch below reads as
    // ~20 ms because queue back-pressure from the 40 block graphs is attributed
    // to it: wall(+lm) - wall(chain only) is the honest per-token contribution.
    std::printf("\n## lm_head alone, queue empty (median of %d)\n", iters);
    std::printf("%5s %12s %10s %12s\n", "rep", "launch_ms", "sync_ms", "tpu_us");
    std::vector<double> lmis;
    for (int r = 0; r < iters + 1; r++) {
      bm_thread_sync(handle);  // drain so the launch is not waiting on anything
      unsigned long a = tpu_us(handle);
      double t0 = now_ms();
      bmrt_launch_tensor_ex(bmrt, lm->name, Lm.in.data(), lm->input_num, Lm.out.data(),
                            lm->output_num, true, true);
      double tm = now_ms();
      bm_thread_sync(handle);
      double t1 = now_ms();
      unsigned long b = tpu_us(handle);
      if (r == 0) continue;
      lmis.push_back(tm - t0);
      std::printf("%5d %12.3f %10.3f %12.0f\n", r, tm - t0, t1 - tm, (double)(b - a));
    }
    std::sort(lmis.begin(), lmis.end());
    const double lm_alone = lmis[lmis.size() / 2];

    std::printf("\n## %zu block graphs + lm_head, one sync (the real token shape)\n",
                layers.size());
    std::printf("%5s %10s %12s %10s %10s %12s %10s %12s\n", "rep", "chain_ms", "lm_launch_ms",
                "sync_ms", "wall_ms", "tpu_us", "tpu/wall", "wall-tpu_ms");
    std::printf("#   lm_launch_ms here includes the chain still draining; see lm_head-alone above.\n");
    std::vector<double> w2, t2, s2, lml;
    for (int r = 0; r < iters; r++) {
      unsigned long ta = tpu_us(handle);
      double t0 = now_ms();
      run_chain();
      double tm = now_ms();
      bmrt_launch_tensor_ex(bmrt, lm->name, Lm.in.data(), lm->input_num, Lm.out.data(),
                            lm->output_num, true, true);
      double tm2 = now_ms();
      bm_thread_sync(handle);
      double t1 = now_ms();
      unsigned long tb = tpu_us(handle);
      double w = t1 - t0, tp = (double)(tb - ta);
      s2.push_back(tm - t0);
      lml.push_back(tm2 - tm);
      w2.push_back(w);
      t2.push_back(tp);
      std::printf("%5d %10.3f %12.3f %10.3f %10.3f %12.0f %10.2f %12.3f\n", r + 1, tm - t0,
                  tm2 - tm, t1 - tm2, w, tp, tp > 0 ? tp / (w * 1000) : 0, w - tp / 1000.0);
    }
    std::sort(w2.begin(), w2.end());
    std::sort(t2.begin(), t2.end());
    std::sort(lml.begin(), lml.end());
    const double cw = w2[w2.size() / 2], ct = t2[t2.size() / 2];
    const double mlm = lml[lml.size() / 2];
    std::printf("\n## per-token verdict (medians)\n");
    std::printf("wall = %.3f ms  tpu_busy = %.3f ms  tpu/wall = %.2f\n", cw, ct / 1000.0,
                ct / (cw * 1000));
    std::printf("lm_head launch, empty queue = %.3f ms  (header: a launch must not block the\n"
                "  CPU, bmruntime_interface.h:475; TPU busy for this graph over a full token is\n"
                "  visible as the wall(+lm) - wall(chain) difference)\n", lm_alone);
    std::printf("headroom (wall - tpu_busy) = %.3f ms/token\n", cw - ct / 1000.0);
    std::printf("That headroom is the whole prize for any queue-depth increase.\n");
    std::printf("If it is near zero, deepening the queue cannot beat it, however deep it goes.\n");
  }

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  (void)num;
  (void)names;
  return 0;
}
