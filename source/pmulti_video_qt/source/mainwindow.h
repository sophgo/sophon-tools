#pragma once
#include <QMainWindow>
#include <QTimer>

#include "BMLabel.h"
#include "DecoderConsole.h"
#include "opencv2/opencv.hpp"
#include "profiler.h"

#define MAX_VIDEO_NUM (32)
#define MAX_VIDEO_W (1920)
#define MAX_VIDEO_H (1080)

class BMLabel;

class MainWindow : public QMainWindow {
  Q_OBJECT
public:
  MainWindow(QWidget *parent = nullptr);
  ~MainWindow();

  void InitBMimage(int _dev_id, std::vector<std::string> _url_vec_,
                   std::vector<int> _url_fps_);
  
private slots:
  /* 刷新图像 */
  void flashImage();

private:
  void calc_rows_cols(int N, int *rows, int *cols);
  
  FpsProfiler fpsApp;
  std::vector<std::string> url_vec_;
  std::vector<int> url_fps_;
  int dev_id;
  int channel_num;
  int display_channel_rows;
  int display_channel_cols;
  bm_handle_t handle;
  bm_image bmimgs[MAX_VIDEO_NUM];
  bm_image oimage;
  BMLabel *imageLabel;
  QTimer *timer;
  DecoderConsole *multi_dec = NULL;
  bmcv_rect_t rects[MAX_VIDEO_NUM];
};
