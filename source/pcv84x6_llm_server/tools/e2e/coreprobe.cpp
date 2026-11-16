/* coreprobe.cpp -- print the bmodel's per-net `core_num`, the number the
 * runtime turns into `block_num` when it submits a LAUNCH_FUNC.
 *
 * Why this exists (MYS-2703): the engine's command trace names the graph that
 * never returned (`lm_head`) and reports the bmodel's `core_num` for it, while
 * the driver's kernel_fifo reports `block=0 send_core_num=0` for the same
 * submit. Those are different quantities computed on different paths, and the
 * only way to say which core layout a stuck `lm_head` really has is to ask the
 * bmodel. `ni->core_num` is exactly `stage_v[0]->core_num` (bmruntime_bmodel.cpp
 * :1500), which is what `Bmruntime::launch` uses to build `core_list`; the
 * driver's own `block_num` comes from that list's size.
 *
 * Build (on the board):
 *   g++ -O1 -o coreprobe coreprobe.cpp \
 *       -I/opt/sophon/libsophon-current/include \
 *       -L/opt/sophon/libsophon-current/lib -lbmrt -lbmlib
 * Run:  ./coreprobe <model.bmodel>
 *
 * Loading a bmodel here allocates NPU memory, so do NOT run it while a worker
 * has the same model resident -- unload first. It only reads metadata and
 * destroys the runtime before exiting.
 */
#include <cstdio>
#include <cstring>

#include "bmlib_runtime.h"
#include "bmruntime_interface.h"

int main(int argc, char** argv)
{
  if (argc < 2) {
    std::printf("usage: %s <model.bmodel> [substr...]\n", argv[0]);
    return 2;
  }
  bm_handle_t h;
  if (bm_dev_request(&h, 0) != BM_SUCCESS) {
    std::printf("bm_dev_request failed\n");
    return 1;
  }
  void* rt = bmrt_create(h);
  if (!rt) {
    std::printf("bmrt_create failed\n");
    bm_dev_free(h);
    return 1;
  }
  if (!bmrt_load_bmodel(rt, argv[1])) {
    std::printf("bmrt_load_bmodel failed: %s\n", argv[1]);
    bmrt_destroy(rt);
    bm_dev_free(h);
    return 1;
  }

  const char** names = nullptr;
  const int n = bmrt_get_network_number(rt);
  bmrt_get_network_names(rt, &names);
  std::printf("%-24s %8s %6s %5s %5s\n", "net", "core_num", "stages",
              "in", "out");
  for (int i = 0; i < n; i++) {
    const bm_net_info_t* ni = bmrt_get_network_info(rt, names[i]);
    if (!ni) continue;
    // No filter argument: print every net, so a caller can grep or read it all.
    if (argc > 2) {
      bool hit = false;
      for (int a = 2; a < argc; a++)
        if (std::strstr(names[i], argv[a])) hit = true;
      if (!hit) continue;
    }
    std::printf("%-24s %8d %6d %5d %5d\n", names[i], ni->core_num,
                ni->stage_num, ni->input_num, ni->output_num);
  }
  std::printf("total nets = %d\n", n);
  bmrt_destroy(rt);
  bm_dev_free(h);
  return 0;
}
