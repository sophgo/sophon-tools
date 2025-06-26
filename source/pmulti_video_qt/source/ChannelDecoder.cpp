// ===----------------------------------------------------------------------===
//
//  Copyright (C) 2022 Sophgo Technologies Inc.  All rights reserved.
//
//  SOPHON-DEMO is licensed under the 2-Clause BSD License except for the
//  third-party components.
//
// ===----------------------------------------------------------------------===

#include "ChannelDecoder.h"

void ChannelDecoder::daemon() {
  while (!stop_flag_) {
    start_dowork();
    if (thread_ && thread_->joinable()) {
      thread_->join();
    }
    usleep(100 * 1000);
  }
}

void ChannelDecoder::dowork() {
  unsigned int count = 0, count_enable_flag = 0;
  unsigned long long start_time, c_time = 0, c2_time = 0;
  start_time = get_time_stamp();
  AVFrame *frame;
  int ret = 0, got_frame = 0;
  VideoDec_FFMPEG reader;
  usleep(100 * 1000);

  ret = reader.openDec(url_.c_str(), 0, "no", 101, dev_id_, 1);
  if (ret < 0) {
    printf("open input media failed\n");
    usleep(100 * 1000);
    reader.closeDec();
    return;
  }
  frame = av_frame_alloc();
  while (true) {
    if (stop_flag_)
      break;
    /* 获取一帧 */
    got_frame = reader.grabFrame(frame);
    if (!got_frame) {
      printf("no frame!\n");
      break;
    }
    /* 根据输出image格式直接一步转换到位 */
    if (avframe_to_bm_image_by_out(handle_, *frame, *o_img_out) != BM_SUCCESS) {
      printf("avframe to bm_image failed!\n");
      break;
    }
    /* 解码稳定帧率 */
    if (count_enable_flag == 0) {
      count_enable_flag = 1;
      start_time = get_time_stamp();
      count = 0;
    } else {
      c_time = start_time + count * fps_wait_time;
      c2_time = get_time_stamp();
      if (c_time > c2_time)
        usleep(c_time - c2_time);
      else {
        std::cout << "Warning: ChannelDecoder::dowork ffmpeg get frame timeout!"
                  << std::endl;
        start_time = get_time_stamp();
        count = 0;
      }
      count += 1;
      if (count == 10000) {
        start_time += count * fps_wait_time;
        count = 0;
      }
    }
  }

  av_frame_unref(frame);
  av_frame_free(&frame);
  reader.closeDec();
}
