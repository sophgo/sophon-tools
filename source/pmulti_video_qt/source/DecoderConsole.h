// ===----------------------------------------------------------------------===
// 
//  Copyright (C) 2022 Sophgo Technologies Inc.  All rights reserved.
// 
//  SOPHON-DEMO is licensed under the 2-Clause BSD License except for the
//  third-party components.
// 
// ===----------------------------------------------------------------------===

#ifndef MULTI_DECODER_H_
#define MULTI_DECODER_H_

#include "ChannelDecoder.h"
#include <string>
#include <unordered_map>
#include <mutex>
#include <utility>

class DecoderConsole{
public:
    DecoderConsole(int que_size=1):que_size_(que_size){};
    ~DecoderConsole(){
        std::cout << "DecoderConsole" << std::endl;
        std::lock_guard<std::mutex> lock(dec_map_mtx_);
        for(auto& it : dec_map_){
            it.second->stop();
        }
    };

    int get_channel_num();
    void addChannel(std::string url, bm_image* bimg,int dev_id=0, int fps=25);
    ChannelDecoder* get_channel(int idx);
private:
    std::unordered_map<int, std::shared_ptr<ChannelDecoder>> dec_map_;
    std::mutex dec_map_mtx_;
    int que_size_;
};


#endif

