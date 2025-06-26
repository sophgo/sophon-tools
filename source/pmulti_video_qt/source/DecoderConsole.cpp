// ===----------------------------------------------------------------------===
// 
//  Copyright (C) 2022 Sophgo Technologies Inc.  All rights reserved.
// 
//  SOPHON-DEMO is licensed under the 2-Clause BSD License except for the
//  third-party components.
// 
// ===----------------------------------------------------------------------===

#include "DecoderConsole.h"

int DecoderConsole::get_channel_num(){
    std::lock_guard<std::mutex> lock(dec_map_mtx_);
    return dec_map_.size();
}

void DecoderConsole::addChannel(std::string url, bm_image* bimg, int dev_id, int fps){
    int channel_idx = get_channel_num();
    dec_map_.insert(std::make_pair(channel_idx,std::make_shared<ChannelDecoder>(url, bimg, dev_id, fps)));
    dec_map_[channel_idx]->start();
    std::cout<<"Decoder channel_idx "<<channel_idx<<" start!"<<std::endl;
}

ChannelDecoder* DecoderConsole::get_channel(int idx) {
    if(dec_map_.find(idx)==dec_map_.end()){
        std::cout<<"error!channel_idx doesn't exist!"<<std::endl;
        return NULL;
    }
    return dec_map_[idx].get();
}
