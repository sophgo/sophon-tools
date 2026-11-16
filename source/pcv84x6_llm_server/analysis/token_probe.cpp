// Reproduce one decode token's launch pattern to get a cost decomposition.
//
//   ./token_probe <model.bmodel> [--stage S] [--iters N] [--lm] [--sync-per-layer]
//
// Mimics native/src/llm_engine.cpp's decode_layers(): the 40 block_cache_<i>
// graphs are queued back to back through the shared hidden row, then one
// bm_thread_sync covers the batch. Two switches isolate the pieces:
//
//   --lm              also launch lm_head after the chain (what
//                     Engine::Impl::sample_lm does), timed separately
//   --sync-per-layer  sync after every layer, i.e. the pre-MYS-2377 behaviour,
//                     to price the batching change
//
// Nothing is written to weights, and every graph runs at a fixed decode shape,
// so this cannot trip the dynamic-width defect (kAlign). It does feed garbage
// activations (the template buffers hold stale bytes) -- that only changes the
// numbers, never the timing, and no graph here is data-dependent in shape.
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

constexpr int kFaInterval = 4;

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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr,
                 "usage: %s model.bmodel [--stage S] [--iters N] [--lm] "
                 "[--sync-per-layer]\n", argv[0]);
    return 2;
  }
  const char* path = argv[1];
  int stage = 6;
  int iters = 10;
  bool with_lm = false;
  bool sync_per_layer = false;
  for (int i = 2; i < argc; i++) {
    if (!std::strcmp(argv[i], "--stage") && i + 1 < argc) stage = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--iters") && i + 1 < argc) iters = std::atoi(argv[++i]);
    else if (!std::strcmp(argv[i], "--lm")) with_lm = true;
    else if (!std::strcmp(argv[i], "--sync-per-layer")) sync_per_layer = true;
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
  free(names);

  std::vector<const bm_net_info_t*> blocks;
  for (int i = 0;; i++) {
    const std::string n = "block_cache_" + std::to_string(i);
    if (std::find(all.begin(), all.end(), n) == all.end()) break;
    blocks.push_back(bmrt_get_network_info(bmrt, n.c_str()));
  }
  if (blocks.empty()) {
    std::fprintf(stderr, "no block_cache_<i> graphs\n");
    return 1;
  }
  auto find = [&](const char* n) -> const bm_net_info_t* {
    if (std::find(all.begin(), all.end(), std::string(n)) == all.end()) return nullptr;
    return bmrt_get_network_info(bmrt, n);
  };
  const bm_net_info_t* n_embed_cache = find("embedding_cache");
  const bm_net_info_t* n_lm = find("lm_head");

  const int layers = static_cast<int>(blocks.size());
  const int fa = kFaInterval - 1;
  const int st = std::min(stage, blocks[fa]->stage_num - 1);
  std::printf("layers=%d fa_interval=%d stage=%d (attention window %d)\n", layers,
              kFaInterval, st, blocks[fa]->stages[st].input_shapes[3].dims[1]);

  auto mk = [&](const bm_net_info_t* net) {
    const int s = net->is_dynamic ? 0 : std::min(st, net->stage_num - 1);
    const bm_stage_info_t& si = net->stages[s];
    std::vector<bm_tensor_t> in, out;
    for (int i = 0; i < net->input_num; i++)
      in.push_back(tensor_of(si.input_mems[i], net->input_dtypes[i], si.input_shapes[i]));
    for (int i = 0; i < net->output_num; i++)
      out.push_back(tensor_of(si.output_mems[i], net->output_dtypes[i], si.output_shapes[i]));
    return std::make_pair(in, out);
  };

  // Pre-build every tensor list once: the engine rebuilds them per token, and
  // that cost is measured separately below (--iters with rebuild on/off would
  // be a different experiment; here we want the runtime's cost only).
  // Zero every graph input once. The decode graphs index their KV/state with
  // the position ids they are given; template garbage would put that index
  // outside the buffer and wedge the TPU (an out-of-range device read inside a
  // graph is not reportable by the driver -- see docs/decode-submission.md).
  auto zero_all = [&](const bm_net_info_t* net, int s) {
    for (int i = 0; i < net->input_num; i++) {
      int v = 0;
      bm_memset_device_ext(handle, &v, 1, net->stages[s].input_mems[i]);
    }
  };
  for (int i = 0; i < layers; i++)
    zero_all(blocks[i], blocks[i]->is_dynamic ? 0 : std::min(st, blocks[i]->stage_num - 1));
  if (n_embed_cache) zero_all(n_embed_cache, 0);
  if (n_lm) zero_all(n_lm, 0);

  std::vector<std::pair<std::vector<bm_tensor_t>, std::vector<bm_tensor_t>>> tpl(layers);
  for (int i = 0; i < layers; i++) tpl[i] = mk(blocks[i]);
  auto ec = n_embed_cache ? mk(n_embed_cache)
                          : std::make_pair(std::vector<bm_tensor_t>{},
                                           std::vector<bm_tensor_t>{});
  auto lm = n_lm ? mk(n_lm) : std::make_pair(std::vector<bm_tensor_t>{},
                                             std::vector<bm_tensor_t>{});

  // The chain: layer i's output 0 is layer i+1's input 0.
  auto chain_mem = [&](int i) -> bm_device_mem_t {
    const int s = blocks[i]->is_dynamic ? 0 : std::min(st, blocks[i]->stage_num - 1);
    return blocks[i]->stages[s].output_mems[0];
  };
  auto run_one = [&](int i) {
    auto& t = tpl[i];
    t.first[0].device_mem = (i == 0) ? ec.second.empty() ? t.first[0].device_mem
                                                         : ec.second[0].device_mem
                                          : chain_mem(i - 1);
    return bmrt_launch_tensor_ex(bmrt, blocks[i]->name, t.first.data(),
                                 blocks[i]->input_num, t.second.data(),
                                 blocks[i]->output_num, true, true);
  };

  // Warm-up token.
  if (!ec.first.empty()) bmrt_launch_tensor_ex(bmrt, n_embed_cache->name, ec.first.data(),
                                               n_embed_cache->input_num, ec.second.data(),
                                               n_embed_cache->output_num, true, true);
  for (int i = 0; i < layers; i++) run_one(i);
  bm_thread_sync(handle);
  if (with_lm && n_lm) {
    lm.first[0].device_mem = chain_mem(layers - 1);
    bmrt_launch_tensor_ex(bmrt, n_lm->name, lm.first.data(), n_lm->input_num,
                          lm.second.data(), n_lm->output_num, true, true);
    bm_thread_sync(handle);
  }

  // --- timed: chain only ------------------------------------------------
  double submit = 0, sync = 0;
  for (int k = 0; k < iters; k++) {
    if (!ec.first.empty())
      bmrt_launch_tensor_ex(bmrt, n_embed_cache->name, ec.first.data(),
                            n_embed_cache->input_num, ec.second.data(),
                            n_embed_cache->output_num, true, true);
    const double t0 = now_ms();
    for (int i = 0; i < layers; i++) {
      run_one(i);
      if (sync_per_layer) bm_thread_sync(handle);
    }
    const double t1 = now_ms();
    if (!sync_per_layer) bm_thread_sync(handle);
    const double t2 = now_ms();
    submit += t1 - t0;
    sync += t2 - t1;
  }
  const double chain_total = (submit + sync) / iters;
  std::printf("chain        submit %.3f ms  sync %.3f ms  total %.3f ms/token\n",
              submit / iters, sync / iters, chain_total);

  if (with_lm && n_lm) {
    // lm_head the way sample_lm runs it: launch (which blocks) then sync.
    double lm_launch = 0, lm_sync = 0, chain = 0;
    for (int k = 0; k < iters; k++) {
      const double t0 = now_ms();
      for (int i = 0; i < layers; i++) run_one(i);
      bm_thread_sync(handle);
      const double t1 = now_ms();
      lm.first[0].device_mem = chain_mem(layers - 1);
      bmrt_launch_tensor_ex(bmrt, n_lm->name, lm.first.data(), n_lm->input_num,
                            lm.second.data(), n_lm->output_num, true, true);
      const double t2 = now_ms();
      bm_thread_sync(handle);
      const double t3 = now_ms();
      chain += t1 - t0;
      lm_launch += t2 - t1;
      lm_sync += t3 - t2;
    }
    std::printf("chain+sync   %.3f ms\n", chain / iters);
    std::printf("lm_head      launch %.3f ms  sync %.3f ms\n", lm_launch / iters,
                lm_sync / iters);
    std::printf("token        chain %.3f + lm_head %.3f = %.3f ms  (%.2f tok/s)\n",
                chain / iters, (lm_launch + lm_sync) / iters,
                (chain + lm_launch + lm_sync) / iters,
                1000.0 / ((chain + lm_launch + lm_sync) / iters));
  }

  bmrt_destroy(bmrt);
  bm_dev_free(handle);
  return 0;
}
