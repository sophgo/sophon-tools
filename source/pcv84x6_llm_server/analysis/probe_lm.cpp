// Does bmrt_launch_tensor_ex block for lm_head, or does it queue like the blocks?
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "bmlib_runtime.h"
#include "bmruntime_interface.h"
static double now_ms(){using C=std::chrono::steady_clock;return std::chrono::duration<double,std::milli>(C::now().time_since_epoch()).count();}
static bm_tensor_t T(bm_device_mem_t m,bm_data_type_t d,bm_shape_t s){bm_tensor_t t{};bmrt_tensor_with_device(&t,m,d,s);t.st_mode=BM_STORE_1N;return t;}
int main(int argc,char**argv){
  bm_handle_t h; if(bm_dev_request(&h,0)!=BM_SUCCESS)return 1;
  void*r=bmrt_create(h); bmrt_set_flags(r,BM_RUNTIME_SHARE_MEM);
  if(!bmrt_load_bmodel(r,argv[1])){printf("load fail\n");return 2;}
  bm_thread_sync(h);
  auto get=[&](const char*n){return bmrt_get_network_info(r,n);};
  const bm_net_info_t* lm=get("lm_head"); const bm_net_info_t* bc=get("block_cache_0");
  // The graphs index their KV/state with the position ids they are handed.
  // Template bytes are uninitialised, and an out-of-range device read inside a
  // graph is not reportable by the driver on CV84X6: it wedges the TPU until
  // reboot. Zero every input before the first launch (analysis/README.md).
  auto mk=[&](const bm_net_info_t*n){const auto&s=n->stages[0];std::vector<bm_tensor_t> i,o;
    for(int k=0;k<n->input_num;k++)i.push_back(T(s.input_mems[k],n->input_dtypes[k],s.input_shapes[k]));
    for(int k=0;k<n->output_num;k++)o.push_back(T(s.output_mems[k],n->output_dtypes[k],s.output_shapes[k]));
    for(int k=0;k<n->input_num;k++){int v=0;bm_memset_device_ext(h,&v,1,s.input_mems[k]);}
    return std::make_pair(i,o);};
  auto L=mk(lm); auto B=mk(bc);
  // warm
  bmrt_launch_tensor_ex(r,lm->name,L.first.data(),lm->input_num,L.second.data(),lm->output_num,true,true); bm_thread_sync(h);
  bmrt_launch_tensor_ex(r,bc->name,B.first.data(),bc->input_num,B.second.data(),bc->output_num,true,true); bm_thread_sync(h);

  printf("--- lm_head launched twice with no sync in between ---\n");
  double t0=now_ms();
  bmrt_launch_tensor_ex(r,lm->name,L.first.data(),lm->input_num,L.second.data(),lm->output_num,true,true);
  double t1=now_ms();
  bmrt_launch_tensor_ex(r,lm->name,L.first.data(),lm->input_num,L.second.data(),lm->output_num,true,true);
  double t2=now_ms();
  bm_thread_sync(h);
  double t3=now_ms();
  printf("launch1 %.3f ms, launch2 %.3f ms, sync %.3f ms\n",t1-t0,t2-t1,t3-t2);

  printf("--- 40 block_cache_0 launches, one sync ---\n");
  t0=now_ms();
  for(int i=0;i<40;i++) bmrt_launch_tensor_ex(r,bc->name,B.first.data(),bc->input_num,B.second.data(),bc->output_num,true,true);
  t1=now_ms(); bm_thread_sync(h); t2=now_ms();
  printf("40 launches %.3f ms (%.3f each), sync %.3f ms\n",t1-t0,(t1-t0)/40,t2-t1);
  bmrt_destroy(r); bm_dev_free(h); return 0;
}
