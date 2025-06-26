#include "DecoderConsole.h"
#include "bmcv_api.h"
#include "bmcv_api_ext.h"
#include "bmlib_runtime.h"
#include "json.h"
#include "opencv2/opencv.hpp"
#include <chrono>
#include <csignal>
#include <fstream>
#include <iostream>
#include <string>

#define MAX_VIDEO_NUM (32)
#define MAX_VIDEO_W (1920)
#define MAX_VIDEO_H (1080)

int exit_flag = 0;

void signalHandler(int signum) {
  (void)signum;
  std::cout << "get CTRL+C, please wait..." << std::endl;
  if (!exit_flag) {
    exit_flag = 1;
  } else {
    exit(0);
  }
}

void calc_rows_cols(int N, int *rows, int *cols) {
  int r = (int)sqrt(N);
  int c = (N + r - 1) / r;
  while (r * c < N) {
    r++;
    c = (N + r - 1) / r;
  }
  *rows = r;
  *cols = c;
  printf("Num: %d, Rows: %d, Cols: %d\r\n", N, *rows, *cols);
}

int main(int argc, char *argv[]) {
  std::string keys =
      "{config | ./config/yolov5_app.json | path to config.json}";
  cv::CommandLineParser parser(argc, argv, keys);
  std::string config_file = parser.get<std::string>("config");

  std::ifstream file(config_file.c_str());
  if (!file.is_open()) {
    std::cerr << "Failed to open json file." << std::endl;
    return 1;
  }
  nlohmann::json config;
  file >> config;
  bm_image *bmimgs = new bm_image[MAX_VIDEO_NUM];

  // 此处需要按顺序填写需要处理的rtsp流地址。
  std::vector<std::string> url_vec_ = config["decoder"]["urls"];
  std::vector<int> url_fps_ = config["decoder"]["fpss"];
  int dev_id = config["decoder"]["dev_id"];
  int channel_num = url_vec_.size();
  int display_channel_rows;
  int display_channel_cols;
  channel_num = channel_num > MAX_VIDEO_NUM ? MAX_VIDEO_NUM : channel_num;
  bm_handle_t handle;
  calc_rows_cols(channel_num, &display_channel_rows, &display_channel_cols);
  std::signal(SIGINT, signalHandler);

  if (BM_SUCCESS != bm_dev_request(&handle, dev_id)) {
    std::cout << "Error: cannot get handle" << std::endl;
    return -1;
  }

  for (int i = 0; i < channel_num; i++) {
    /* 这里必须配置,不然直接全尺寸图进入下方拼接阶段会占用大量VPP资源 */
    /* 如果需要动态的话推荐建立多个组,不同大小的image,改变时直接改变解码线程的push对象
     */
    bm_image_create(handle, MAX_VIDEO_H / display_channel_rows,
                    MAX_VIDEO_W / display_channel_cols, FORMAT_RGB_PACKED,
                    DATA_TYPE_EXT_1N_BYTE, bmimgs + i);
    bm_image_alloc_dev_mem(bmimgs[i]);
    bmcv_rect_t rect_s = {0, 0, MAX_VIDEO_W / display_channel_cols - 4,
                          MAX_VIDEO_H / display_channel_rows - 4};
    bmcv_image_fill_rectangle(handle, bmimgs[i], 1, &rect_s, 255, 0, 0);
  }

  DecoderConsole *multi_dec = new DecoderConsole();
  /* 创建解码管理对象 */
  for (int i = 0; i < channel_num; i++) {
    multi_dec->addChannel(url_vec_[i], bmimgs + i, 0, url_fps_.at(i));
  }
  /* 等待解码 */
  while(!exit_flag) {
    usleep(3 * 1000 * 1000);
  }

  delete multi_dec;

  for (int i = 0; i < channel_num; i++) {
    bm_image_destroy(bmimgs[i]);
  }
  delete[] bmimgs;
  bm_dev_free(handle);
}
