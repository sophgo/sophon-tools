// How deep is bmrt's launch queue really?
//
// bmruntime_interface.h says bmrt_launch_tensor_ex does not block, and the
// engine (MYS-2377) relies on that: it queues all 40 block graphs and syncs
// once. But a launch that has to wait for queue space is not free, and its cost
// lands in the submit time rather than in bm_thread_sync -- which is exactly
// the split the LD_PRELOAD profile shows. Launching one graph N times without
// syncing, timing each launch, shows where the queue fills up.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <vector>
#include "bmlib_runtime.h"
#include "bmruntime_interface.h"
static double ms(){using C=std::chrono::steady_clock;return std::chrono::duration<double,std::milli>(C::now().time_since_epoch()).count();}
static bm_tensor_t T(bm_device_mem_t m,bm_data_type_t d,bm_shape_t s){bm_tensor_t t{};bmrt_tensor_with_device(&t,m,d,s);t.st_mode=BM_STORE_1N;return t;}
int main(int c,char**v){
  bm_handle_t h; if(bm_dev_request(&h,0)!=BM_SUCCESS)return 1;
  void*r=bmrt_create(h); bmrt_set_flags(r,BM_RUNTIME_SHARE_MEM);
  if(!bmrt_load_bmodel(r,v[1])){printf("load fail\n");return 2;}
  bm_thread_sync(h);
  const bm_net_info_t* net=bmrt_get_network_info(r,"block_cache_0");
  const auto&s=net->stages[0];
  std::vector<bm_tensor_t> in,out;
  for(int i=0;i<net->input_num;i++){int z=0;bm_memset_device_ext(h,&z,1,s.input_mems[i]);
    in.push_back(T(s.input_mems[i],net->input_dtypes[i],s.input_shapes[i]));}
  for(int i=0;i<net->output_num;i++)out.push_back(T(s.output_mems[i],net->output_dtypes[i],s.output_shapes[i]));
  auto L=[&](){return bmrt_launch_tensor_ex(r,net->name,in.data(),net->input_num,out.data(),net->output_num,true,true);};
  L(); bm_thread_sync(h);            // warm
  const int N=24;
  std::vector<double> each;
  for(int k=0;k<N;k++){double a=ms(); L(); each.push_back(ms()-a);}
  double a=ms(); bm_thread_sync(h); double sync=ms()-a;
  printf("launch #  submit_us\n");
  for(int k=0;k<N;k++) printf("%7d  %8.1f\n", k+1, each[k]*1000);
  printf("final sync %.1f us\n", sync*1000);
  bmrt_destroy(r); bm_dev_free(h); return 0;
}
