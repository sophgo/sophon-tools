// Run one stateless operator probe on a quiescent board.
// Usage: gdn_probe model.bmodel fixture-directory
#include "bmruntime_interface.h"
#include "bmlib_runtime.h"
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  bm_handle_t handle{};
  if (bm_dev_request(&handle, 0) != BM_SUCCESS) return 3;
  void* rt = bmrt_create(handle);
  if (!bmrt_load_bmodel(rt, argv[1])) return 4;
  const char** names = nullptr;
  bmrt_get_network_names(rt, &names);
  if (bmrt_get_network_number(rt) != 1) return 5;
  const auto* net = bmrt_get_network_info(rt, names[0]);
  std::free(names);
  std::vector<bm_tensor_t> in(net->input_num), out(net->output_num);
  for (int i = 0; i < net->input_num; ++i) {
    if (net->input_dtypes[i] != BM_FLOAT32) return 6;
    if (!bmrt_tensor(&in[i], rt, net->input_dtypes[i], net->stages[0].input_shapes[i])) return 13;
    size_t bytes = bmrt_tensor_bytesize(&in[i]);
    std::vector<char> data(bytes);
    std::ifstream file(std::string(argv[2]) + "/input" + std::to_string(i) + ".bin", std::ios::binary);
    if (!file.read(data.data(), bytes)) return 7;
    if (bm_memcpy_s2d_partial(handle, in[i].device_mem, data.data(), bytes) != BM_SUCCESS) return 8;
  }
  for (int i = 0; i < net->output_num; ++i)
    if (!bmrt_tensor(&out[i], rt, net->output_dtypes[i], net->stages[0].output_shapes[i])) return 14;
  std::cerr << "launch " << net->name << std::endl;
  auto start = std::chrono::steady_clock::now();
  if (!bmrt_launch_tensor_ex(rt, net->name, in.data(), in.size(), out.data(), out.size(), true, false)) return 9;
  if (bm_thread_sync(handle) != BM_SUCCESS) return 10;
  std::cerr << "complete ms=" << std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count() << std::endl;
  for (size_t i = 0; i < out.size(); ++i) {
    std::vector<char> data(bmrt_tensor_bytesize(&out[i]));
    auto mem = bm_mem_from_device(out[i].device_mem.u.device.device_addr, data.size());
    if (bm_memcpy_d2s(handle, data.data(), mem) != BM_SUCCESS) return 11;
    std::ofstream file(std::string(argv[2]) + "/output" + std::to_string(i) + ".bin", std::ios::binary);
    file.write(data.data(), data.size());
    if (!file) return 12;
  }
  for (auto& t : in) bm_free_device(handle, t.device_mem);
  for (auto& t : out) bm_free_device(handle, t.device_mem);
  bmrt_destroy(rt);
  bm_dev_free(handle);
}
