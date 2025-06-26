#include "mainwindow.h"
#include "BMLabel.h"

#include <QLabel>
#include <QPixmap>
#include <QVBoxLayout>
#include <qglobal.h>

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent) {

  QWidget *central = new QWidget(this);
  setCentralWidget(central);
  /* BM1684X VPP支持图像最小长宽为16 */
  this->setMinimumSize(7*16, 7*16);

  imageLabel = new BMLabel(central);
  imageLabel->setAlignment(Qt::AlignCenter);
  imageLabel->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);

  QVBoxLayout *layout = new QVBoxLayout(central);
  layout->addWidget(imageLabel);

  fpsApp.config("hdmi flash image fps", 100);

  multi_dec = new DecoderConsole();
}

MainWindow::~MainWindow() {
  disconnect(timer, &QTimer::timeout, this, &MainWindow::flashImage);
  timer->stop();
  delete timer;
  delete multi_dec;
  bm_image_destroy(oimage);
  for (int i = 0; i < channel_num; i++) {
    bm_image_destroy(bmimgs[i]);
  }
  bm_dev_free(handle);
}

void MainWindow::InitBMimage(int _dev_id, std::vector<std::string> _url_vec_,
                             std::vector<int> _url_fps_) {
  dev_id = _dev_id;
  display_channel_rows = 1;
  display_channel_cols = 1;
  url_vec_ = _url_vec_;
  url_fps_ = _url_fps_;
  channel_num = url_vec_.size();
  channel_num = channel_num > MAX_VIDEO_NUM ? MAX_VIDEO_NUM : channel_num;
  calc_rows_cols(channel_num, &display_channel_rows, &display_channel_cols);

  for (int i = 0; i < channel_num; i++)
    qDebug("ID: %d, url: %s, fps: %d", i, url_vec_.at(i).c_str(),
           url_fps_.at(i));
  if (BM_SUCCESS != bm_dev_request(&handle, dev_id)) {
    std::cout << "Error: cannot get handle" << std::endl;
    return;
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
  
  /* 创建解码管理对象 */
  for (int i = 0; i < channel_num; i++) {
    multi_dec->addChannel(url_vec_[i], bmimgs + i, 0, url_fps_.at(i));
  }
  /* 等待解码器完成初始化 */
  std::this_thread::sleep_for(std::chrono::seconds(3));

  /* 拼接后大图image */
  bm_image_create(handle, MAX_VIDEO_H, MAX_VIDEO_W, FORMAT_RGB_PACKED, DATA_TYPE_EXT_1N_BYTE,
                  &oimage);
  bm_image_alloc_dev_mem(oimage);

  /* 底图色彩初始化 */
  bmcv_rect_t rect_full = {0, 0, MAX_VIDEO_W, MAX_VIDEO_H};
  bmcv_image_fill_rectangle(handle, oimage, 1, &rect_full, 0, 255, 0);

  /* 完成多路视频布局 */
  for (int i = 0; i < channel_num; i++) {
    rects[i] = {
        .start_x =
            (MAX_VIDEO_W / display_channel_cols) * (i % display_channel_cols) + 2,
        .start_y =
            (MAX_VIDEO_H / display_channel_rows) * (i / display_channel_cols) + 2,
        .crop_w = (MAX_VIDEO_W / display_channel_cols) - 4,
        .crop_h = (MAX_VIDEO_H / display_channel_rows) - 4};
  }

  /* 初始化刷新图像定时器 */
  timer = new QTimer(this);
  timer->setInterval(1000 / 25);
  connect(timer, &QTimer::timeout, this, &MainWindow::flashImage);
  timer->start();
}

void MainWindow::flashImage() {
  bmcv_image_vpp_stitch(handle, channel_num, bmimgs, oimage, rects, NULL,
                        BMCV_INTER_LINEAR);
  imageLabel->show_img(&oimage);
  fpsApp.add();
}

/* 计算最合适的行列数 */
void MainWindow::calc_rows_cols(int N, int *rows, int *cols) {
  int r = (int)sqrt(N);
  int c = (N + r - 1) / r;
  while (r * c < N) {
    r++;
    c = (N + r - 1) / r;
  }
  *rows = r;
  *cols = c;
  qDebug("Num: %d, Rows: %d, Cols: %d", N, *rows, *cols);
}
