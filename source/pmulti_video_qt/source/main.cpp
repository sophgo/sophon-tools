#include "json.h"
#include "mainwindow.h"
#include <QApplication>
#include <chrono>
#include <csignal>
#include <fstream>
#include <iostream>
#include <string>

QApplication *app_ptr = nullptr;

void signalHandler(int signum) {
  (void)signum;
  std::cout << "get CTRL+C, please wait..." << std::endl;
  if (app_ptr) {
    QMetaObject::invokeMethod(app_ptr, "quit", Qt::QueuedConnection);
    app_ptr = nullptr;
  } else {
    exit(0);
  }
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

  // 此处需要按顺序填写需要处理的rtsp流地址。
  std::vector<std::string> url_vec_ = config["decoder"]["urls"];
  std::vector<int> url_fps_ = config["decoder"]["fpss"];
  int dev_id = config["decoder"]["dev_id"];

  /* 初始化QT */
  QApplication app(argc, argv);
  app_ptr = &app;
  std::signal(SIGINT, signalHandler);
  MainWindow w;
  w.resize(1200, 800);
  w.show();
  w.InitBMimage(dev_id, url_vec_, url_fps_);
  return app.exec();
}
