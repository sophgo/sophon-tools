// Per-graph cost probe on CV84X6: what does one launch of each net actually
// cost, split into "submit" (time inside bmrt_launch_tensor_ex) and "complete"
// (time in bm_thread_sync after it)?
//
//   ./graph_probe <model.bmodel> [--iters N] [--stage S] [--net NAME ...]
//
// Every net is launched with the bmodel's own template IO memory and shapes
// (addr_mode=1 for the decode blocks), exactly the way native/src/llm_engine.cpp
// does, and nothing is written to the buffers -- the numbers are latency, not
// numerics. This isolates one graph from the 40-graph chain so a claim such as
// "lm_head costs 10 ms per token" can be checked on its own.
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

struct Result {
  std::string name;
  double submit_ms = 0;
  double sync_ms = 0;
  int n = 0;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s model.bmodel [--iters N] [--stage S] [--net NAME]...\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  int iters = 20;
  int stage = 0;
  std::vector<std::string> want;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--iters") && i + 1 < argc) iters = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--stage") && i + 1 < argc) stage = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--net") && i + 1 < argc) want.push_back(argv[++i]);
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

  const int num = bmrt_get_network_number(bmrt);
  const char** names = nullptr;
  bmrt_get_network_names(bmrt, &names);
  std::vector<std::string> all(names, names + num);

  auto selected = [&](const std::string& n) {
    if (want.empty()) return true;
    for (const auto& w : want)
      if (n == w) return true;
    return false;
  };

  // Zero every input once. Some decode graphs index their history buffers with
  // the position ids they are handed; uninitialised template bytes would put
  // that index outside the buffer, and on CV84X6 an out-of-range device read
  // from a graph does not fault the process -- it wedges the TPU until reboot
  // (bmdrv_thread_sync_api timeout, bdc_reg_read oops). Zero is in range.
  auto zero_all = [&](const bm_net_info_t* net, int st) {
    for (int i = 0; i < net->input_num; i++) {
      int v = 0;
      bm_memset_device_ext(handle, &v, 1, net->stages[st].input_mems[i]);
    }
  };

  std::vector<Result> results;
  for (const auto& name : all) {
    if (!selected(name)) continue;
    const bm_net_info_t* net = bmrt_get_network_info(bmrt, name.c_str());
    if (!net) continue;
    const int st = std::min(stage, net->stage_num - 1);
    const bm_stage_info_t& s = net->stages[st];
    if (!s.input_mems || !s.output_mems) continue;
    // A dynamic graph needs concrete shapes; its stage-0 shape is the max, and
    // this probe is about per-launch overhead, so the max shape is right.
    std::vector<bm_tensor_t> in, out;
    for (int i = 0; i < net->input_num; i++)
      in.push_back(tensor_of(s.input_mems[i], net->input_dtypes[i], s.input_shapes[i]));
    for (int i = 0; i < net->output_num; i++)
      out.push_back(tensor_of(s.output_mems[i], net->output_dtypes[i], s.output_shapes[i]));

    zero_all(net, st);
    // Warm up once so first-touch page faults and kernel uploads are not timed.
    if (!bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num, out.data(),
                               net->output_num, true, true)) {
      std::fprintf(stderr, "launch failed: %s\n", net->name);
      continue;
    }
    bm_thread_sync(handle);

    Result r;
    r.name = name;
    for (int k = 0; k < iters; k++) {
      const double t0 = now_ms();
      bmrt_launch_tensor_ex(bmrt, net->name, in.data(), net->input_num, out.data(),
                            net->output_num, true, true);
      const double t1 = now_ms();
      bm_thread_sync(handle);
      const double t2 = now_ms();
      r.submit_ms += t1 - t0;
      r.sync_ms += t2 - t1;
      r.n++;
    }
    results.push_back(r);
  }

  std::printf("%-18s %5s %12s %12s %12s\n", "net", "n", "submit_ms", "sync_ms", "total_ms");
  double tot_submit = 0, tot_sync = 0;
  for (const auto& r : results) {
    const double sub = r.submit_ms / r.n, syn = r.sync_ms / r.n;
    tot_submit += sub;
    tot_sync += syn;
    std::printf("%-18s %5d %12.3f %12.3f %12.3f\n", r.name.c_str(), r.n, sub, syn, sub + syn);
  }
  std::printf("%-18s %5s %12.3f %12.3f %12.3f\n", "SUM", "", tot_submit, tot_sync,
              tot_submit + tot_sync);

  free(names);
  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
