// ===----------------------------------------------------------------------===
//
//  Copyright (C) 2022 Sophgo Technologies Inc.  All rights reserved.
//
//  SOPHON-DEMO is licensed under the 2-Clause BSD License except for the
//  third-party components.
//
// ===----------------------------------------------------------------------===

#ifndef CHANNEL_DECODER_H_
#define CHANNEL_DECODER_H_

#include "ff_avframe_convert.h"
#include "ff_video_decode.h"
#include <atomic>
#include <condition_variable>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <sys/time.h>
#include <thread>
#include <utility>

class ChannelDecoder {
public:
  ChannelDecoder(std::string _url, bm_image *_bimg, int _dev_id = 0,
                 int _fps = 25)
      : url_(_url), dev_id_(_dev_id), fps(_fps), stop_flag_(false) {
    bm_dev_request(&handle_, dev_id_);
    o_img_out = _bimg;
    fps_wait_time = 1000 * 1000 / _fps;
  }
  ~ChannelDecoder() {
    if (!stop_flag_)
      stop();
    bm_dev_free(handle_);
  }
  void start() {
    std::cout << "Stream: " + url_ + " daemon start!" << std::endl;
    if (!(daemon_thread_ && daemon_thread_->joinable()))
      daemon_thread_ =
          std::make_shared<std::thread>(&ChannelDecoder::daemon, this);
  }
  void start_dowork() {
    std::cout << "Stream: " + url_ + " dowork start!" << std::endl;
    thread_ = std::make_shared<std::thread>(&ChannelDecoder::dowork, this);
  }
  void stop() {
    stop_flag_ = true;
    if (daemon_thread_ && daemon_thread_->joinable())
      daemon_thread_->join();
    if (thread_ && thread_->joinable())
      thread_->join();
    std::cout << "Stream: " + url_ + " stop!" << std::endl;
  }
  unsigned long long get_time_stamp(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec * 1000000 + tv.tv_usec;
  };
  bm_image *o_img_out;
  int fps;
  int count;
  unsigned long long fps_wait_time;
  std::mutex o_img_out_mtx_;

private:
  void dowork();
  void daemon();

  std::string url_;
  int dev_id_;
  bm_handle_t handle_;

  std::atomic<bool> stop_flag_;
  std::shared_ptr<std::thread> thread_ = NULL;
  std::shared_ptr<std::thread> daemon_thread_ = NULL;
};

#endif
