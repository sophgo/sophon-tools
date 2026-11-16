// Is lm_head's 10 ms TPU work, or a driver stall the CPU could overlap?
// Launch lm_head and a block chain back to back with no sync in between, then
// compare the wall time against each run alone.
//   sum(t_lm, t_chain)  -> the TPU (or the driver) serialises them
//   ~max(t_lm, t_chain) -> they overlap, and batching sessions across the
//                          lm_head boundary is a real opportunity
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "bmlib_runtime.h"
#include "bmruntime_interface.h"
static double ms(){using C=std::chrono::steady_clock;return std::chrono::duration<double,std::milli>(C::now().time_since_epoch()).count();}
static bm_tensor_t T(bm_device_mem_t m,bm_data_type_t d,bm_shape_t s){bm_tensor_t t{};bmrt_tensor_with_device(&t,m,d,s);t.st_mode=BM_STORE_1N;return t;}
int main(int argc,char**argv){
  bm_handle_t h; if(bm_dev_request(&h,0)!=BM_SUCCESS)return 1;
  void*r=bmrt_create(h); bmrt_set_flags(r,BM_RUNTIME_SHARE_MEM);
  if(!bmrt_load_bmodel(r,argv[1])){printf("load fail\n");return 2;}
  bm_thread_sync(h);
  int n=bmrt_get_network_number(r); const char**names=nullptr; bmrt_get_network_names(r,&names);
  std::vector<std::string> all(names,names+n); free(names);
  auto get=[&](const char*s){for(auto&x:all)if(x==s)return bmrt_get_network_info(r,s);return (const bm_net_info_t*)nullptr;};
  const bm_net_info_t* lm=get("lm_head");
  std::vector<const bm_net_info_t*> blocks;
  for(int i=0;;i++){auto b=get(("block_cache_"+std::to_string(i)).c_str());if(!b)break;blocks.push_back(b);}
  // The graphs index their KV/state with the position ids they are handed.
  // Template bytes are uninitialised, and an out-of-range device read inside a
  // graph is not reportable by the driver on CV84X6: it wedges the TPU until
  // reboot. Zero every input before the first launch (analysis/README.md).
  auto mk=[&](const bm_net_info_t*net,int st){const auto&s=net->stages[st];std::vector<bm_tensor_t>i,o;
    for(int k=0;k<net->input_num;k++)i.push_back(T(s.input_mems[k],net->input_dtypes[k],s.input_shapes[k]));
    for(int k=0;k<net->output_num;k++)o.push_back(T(s.output_mems[k],net->output_dtypes[k],s.output_shapes[k]));
    for(int k=0;k<net->input_num;k++){int v=0;bm_memset_device_ext(h,&v,1,s.input_mems[k]);}
    return std::make_pair(i,o);};
  auto L=mk(lm,0);
  std::vector<std::pair<std::vector<bm_tensor_t>,std::vector<bm_tensor_t>>> B;
  for(auto*b:blocks) B.push_back(mk(b, b->is_dynamic?0:0));  // stage 0 for all (worst case FA window)
  auto chain=[&](){for(auto&b:B)bmrt_launch_tensor_ex(r,blocks[0]->name, b.first.data(),blocks[0]->input_num,b.second.data(),blocks[0]->output_num,true,true);};
  auto chain_ok=[&](){for(size_t k=0;k<B.size();k++)bmrt_launch_tensor_ex(r,blocks[k]->name,B[k].first.data(),blocks[k]->input_num,B[k].second.data(),blocks[k]->output_num,true,true);};
  auto lmc=[&](){bmrt_launch_tensor_ex(r,lm->name,L.first.data(),lm->input_num,L.second.data(),lm->output_num,true,true);};
  // warm
  chain_ok(); bm_thread_sync(h); lmc(); bm_thread_sync(h);
  const int it=5;
  double t;
  t=ms(); for(int k=0;k<it;k++){chain_ok(); bm_thread_sync(h);} double t_chain=(ms()-t)/it;
  t=ms(); for(int k=0;k<it;k++){lmc(); bm_thread_sync(h);} double t_lm=(ms()-t)/it;
  t=ms(); for(int k=0;k<it;k++){lmc(); chain_ok(); bm_thread_sync(h);} double t_both=(ms()-t)/it;
  printf("chain alone      %.2f ms\n",t_chain);
  printf("lm_head alone    %.2f ms\n",t_lm);
  printf("lm_head+chain    %.2f ms   (sum %.2f, max %.2f)\n",t_both,t_lm+t_chain,std::max(t_lm,t_chain));
  printf("=> %s\n", t_both < 0.9*(t_lm+t_chain) ? "OVERLAPS: batching across the lm_head boundary is worth it"
                                              : "SERIALISED: the TPU/driver is busy for the whole span");
  bmrt_destroy(r); bm_dev_free(h); return 0;
}
