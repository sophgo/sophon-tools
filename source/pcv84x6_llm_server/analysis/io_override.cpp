// Is the per-launch submit cost in the decode chain caused by overriding the
// graphs' IO addresses? Each layer is handed the PREVIOUS layer's output memory
// as input 0 (that is how the chain works: hidden state flows in device memory
// instead of being copied). Launching the same graphs with their OWN template
// IO instead isolates the price of that override.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
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
  int n=bmrt_get_network_number(r); const char**nm=nullptr; bmrt_get_network_names(r,&nm);
  std::vector<std::string> all(nm,nm+n); free(nm);
  auto get=[&](const std::string&s){for(auto&x:all)if(x==s)return bmrt_get_network_info(r,s.c_str());return (const bm_net_info_t*)nullptr;};
  std::vector<const bm_net_info_t*> bl;
  for(int i=0;;i++){auto b=get("block_cache_"+std::to_string(i));if(!b)break;bl.push_back(b);}
  const int stage=6; // the window a 64-token context selects
  struct Net{std::vector<bm_tensor_t> in,out; bm_device_mem_t out0;};
  std::vector<Net> nets(bl.size());
  for(size_t k=0;k<bl.size();k++){
    const auto&s=bl[k]->stages[std::min(stage,bl[k]->stage_num-1)];
    for(int i=0;i<bl[k]->input_num;i++){int z=0;bm_memset_device_ext(h,&z,1,s.input_mems[i]);
      nets[k].in.push_back(T(s.input_mems[i],bl[k]->input_dtypes[i],s.input_shapes[i]));}
    for(int i=0;i<bl[k]->output_num;i++)nets[k].out.push_back(T(s.output_mems[i],bl[k]->output_dtypes[i],s.output_shapes[i]));
    nets[k].out0=s.output_mems[0];
  }
  auto launch=[&](size_t k,bm_device_mem_t in0){
    nets[k].in[0].device_mem=in0;
    return bmrt_launch_tensor_ex(r,bl[k]->name,nets[k].in.data(),bl[k]->input_num,
                                 nets[k].out.data(),bl[k]->output_num,true,true);
  };
  const int it=10;
  // warm both shapes
  for(size_t k=0;k<bl.size();k++) launch(k,nets[k].in[0].device_mem);
  bm_thread_sync(h);
  for(size_t k=0;k<bl.size();k++) launch(k,k?nets[k-1].out0:nets[k].in[0].device_mem);
  bm_thread_sync(h);

  // Separate the submit side from the TPU side: without this split a difference
  // between the two shapes could be either.
  double sub_own=0, sub_ch=0;
  double t=ms();
  for(int q=0;q<it;q++){
    const double a=ms();
    for(size_t k=0;k<bl.size();k++) launch(k,nets[k].in[0].device_mem);
    sub_own+=ms()-a; bm_thread_sync(h);
  }
  const double own=(ms()-t)/it;
  t=ms();
  for(int q=0;q<it;q++){
    const double a=ms();
    for(size_t k=0;k<bl.size();k++) launch(k,k?nets[k-1].out0:nets[k].in[0].device_mem);
    sub_ch+=ms()-a; bm_thread_sync(h);
  }
  const double chained=(ms()-t)/it;
  printf("submit own %.2f ms, submit chained %.2f ms\n", sub_own/it, sub_ch/it);
  printf("own template IO   %7.2f ms/token  (%.0f us/launch)\n",own,own*1000/bl.size());
  printf("chained (override)%7.2f ms/token  (%.0f us/launch)\n",chained,chained*1000/bl.size());
  printf("override cost     %7.2f ms/token\n",chained-own);
  bmrt_destroy(r); bm_dev_free(h); return 0;
}
