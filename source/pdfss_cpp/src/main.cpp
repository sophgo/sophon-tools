#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>
#if defined(__GNUC__) && !defined(__clang__) && (__GNUC__ > 4) && (__GNUC__ < 8)
#include <experimental/filesystem>
#else
#include <filesystem>
#endif

#include "cxxopts.hpp"
#include "json.hpp"
#include "libssh2.h"
#include "libssh2_sftp.h"
#include "sftp_conn.h"

#ifdef WIN32
#include <windows.h>
#include <winsock2.h>
#else
#include <arpa/inet.h>
#include <limits.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

extern "C" {
#include "log.h"
}

#ifndef GIT_COMMIT_HASH
#define GIT_COMMIT_HASH "Unknown"
#endif

#ifndef GIT_COMMIT_DATE
#define GIT_COMMIT_DATE "Unknown"
#endif

using namespace std;
using json = nlohmann::json;
#if defined(__GNUC__) && !defined(__clang__) && (__GNUC__ > 4) && (__GNUC__ < 8)
namespace fs = std::experimental::filesystem;
#else
namespace fs = std::filesystem;
#endif

static uint64_t connect_timeout = 5;
static int ret_flag = 0;
struct ServerInfo* fast_server = nullptr;
struct ThreadArgs {
  bool test_speed;
  ServerInfo* server_in;
  pthread_t* threads;
  size_t num_threads;
};

pthread_mutex_t log_mtx = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_t mtx_get_server = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_t cv_m = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
bool cv_ready = false;
void Lk_mux(bool lock, void*) {
  if (lock)
    pthread_mutex_lock(&log_mtx);
  else
    pthread_mutex_unlock(&log_mtx);
}

// 内置服务器列表：没有配置文件，或配置文件损坏时使用
static const std::vector<struct ServerInfo> kDefaultSdkServers = {
    {0, "172.26.175.10", 32022, "oponIn", "oponIn", false, false, 0.0},
    {1, "172.24.12.75", 32022, "open", "open", true, false, 0.0},
    {3, "172.26.166.163", 32022, "oponIn", "oponIn", false, false, 0.0},
    {4, "106.38.208.114", 32022, "open", "open", false, false, 0.0},
    {5, "103.68.183.114", 32022, "open", "open", false, false, 0.0},
};

static const std::vector<struct ServerInfo> kDefaultHdkServers = {
    {100, "219.142.246.77", 18822, "", "", false, false, 0.0},
    {101, "172.29.128.15", 8822, "", "", false, false, 0.0},
};

static std::vector<struct ServerInfo> sdk_server_info = kDefaultSdkServers;

static std::vector<struct ServerInfo> hdk_server_info = kDefaultHdkServers;

/* 删除服务器信息 */
static void remove_some_server_info(
    std::vector<struct ServerInfo>& server_infos, bool match_to_rm,
    int match_id) {
  log_debug("remove server info, match id: %d, match to rm: %d", match_id,
            match_to_rm);
  if (match_to_rm == true) {
    server_infos.erase(std::remove_if(server_infos.begin(), server_infos.end(),
                                      [&](const ServerInfo& info) {
                                        return info.id == match_id;
                                      }),
                       server_infos.end());
  } else {
    server_infos.erase(std::remove_if(server_infos.begin(), server_infos.end(),
                                      [&](const ServerInfo& info) {
                                        return info.id != match_id;
                                      }),
                       server_infos.end());
  }
}

static void print_server_info(const std::vector<struct ServerInfo>& server_infos) {
  log_info("ID IP PORT");
  for (auto it = server_infos.begin(); it != server_infos.end();) {
    log_info("%d %s %d", it->id, it->host.c_str(), it->port);
    it += 1;
  }
}

static std::string getFileNameFromPath(string path) {
  fs::path filePath = path;
  std::string fileName = filePath.filename().string();
  return fileName;
}

static std::string to_string_with_precision(double value, int precision = 2) {
  std::ostringstream out;
  out << std::fixed << std::setprecision(precision) << value;
  return out.str();
}

static std::string file_size_h(uint64_t size_byte) {
  if (size_byte < 1024)
    return to_string_with_precision(size_byte) + " " + std::string("Byte");
  else if (size_byte < 1024 * 1024)
    return to_string_with_precision((double)size_byte / 1024.0) + " " +
           std::string("KiB");
  else if (size_byte < 1024 * 1024 * 1024)
    return to_string_with_precision((double)size_byte / 1024.0 / 1024.0) + " " +
           std::string("MiB");
  else
    return to_string_with_precision((double)size_byte / 1024.0 / 1024.0 /
                                    1024.0) +
           " " + std::string("GiB");
}

std::string format_duration(int total_seconds) {
  total_seconds = total_seconds < 1 ? 0 : total_seconds;
  const int seconds_in_minute = 60;
  const int seconds_in_hour = 3600;
  const int seconds_in_day = 86400;

  int days = total_seconds / seconds_in_day;
  total_seconds %= seconds_in_day;

  int hours = total_seconds / seconds_in_hour;
  total_seconds %= seconds_in_hour;

  int minutes = total_seconds / seconds_in_minute;
  int seconds = total_seconds % seconds_in_minute;

  std::string result;
  if (days > 0) result += std::to_string(days) + "d" + " ";
  if (hours > 0) result += std::to_string(hours) + "h" + " ";
  if (minutes > 0) result += std::to_string(minutes) + "m" + " ";
  result += std::to_string(seconds) + "s";

  return result;
}

void print_progress(long long total_downloaded, long long file_size,
                    double elapsed_ms) {
  int bar_width = 20;
  float progress = total_downloaded * 1.0 / file_size;
  int pos = bar_width * progress;
  double speed = elapsed_ms > 0 ? (total_downloaded / elapsed_ms) * 1000
                                : 0;  // Kbytes per second
  double remaining_data = file_size - total_downloaded;
  double remaining_time = speed > 0 ? remaining_data / speed : 0;  // seconds

  printf("[%s] %3d%% [", file_size_h(total_downloaded).c_str(),
         (int)(progress * 100));
  for (int i = 0; i < bar_width; ++i) {
    if (i < pos)
      printf("=");
    else if (i == pos)
      printf(">");
    else
      printf(" ");
  }
  printf("] %s/s, ETA: %s   \r", file_size_h(speed).c_str(),
         format_duration(remaining_time).c_str());
  fflush(stdout);
}

void sftp_test_speed(struct ServerInfo* server) {
  log_info("start test server %s speed via sftp...", server->host.c_str());
  if (server->is_ok == false) {
    server->speed = 0.0;
    return;
  }
  const string hostname = server->host;

  SftpConn conn;
  std::string err;
  if (!conn.open(*server, (int)(connect_timeout * 1000), &err)) {
    log_debug("[%s] sftp speed test connect failed: %s", hostname.c_str(),
              err.c_str());
    server->speed = 0.0;
    return;
  }

  LIBSSH2_SFTP_HANDLE* sftp_handle = libssh2_sftp_open(
      conn.sftp(), "/.sophgo_speed", LIBSSH2_FXF_READ, 0);
  if (!sftp_handle) {
    log_debug("[%s] sftp speed test cannot open /.sophgo_speed",
              hostname.c_str());
    server->speed = 0.0;
    return;
  }

  std::vector<char> speed_buf(1024 * 64);
  size_t total_bytes = 0;
  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  ssize_t n;
  while ((n = libssh2_sftp_read(sftp_handle, speed_buf.data(),
                                speed_buf.size())) > 0) {
    total_bytes += n;
    clock_gettime(CLOCK_MONOTONIC, &current_time);
    double elapsed_ms =
        (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
        (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
    if (elapsed_ms > 5000) break;
  }
  clock_gettime(CLOCK_MONOTONIC, &current_time);
  double elapsed_ms = (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
                      (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
  double speed = elapsed_ms > 0 ? (total_bytes / (elapsed_ms / 1000.0)) : 0.0;
  log_info("server %s sftp speed %s/s", server->host.c_str(),
           file_size_h(speed).c_str());
  server->speed = speed;

  libssh2_sftp_close(sftp_handle);
}

// SFTP 文件句柄的 RAII 守卫：提前返回时也能关闭句柄。
class SftpFileHandle {
 public:
  explicit SftpFileHandle(LIBSSH2_SFTP_HANDLE* h = nullptr) : h_(h) {}
  ~SftpFileHandle() {
    if (h_ != nullptr) libssh2_sftp_close(h_);
  }
  SftpFileHandle(const SftpFileHandle&) = delete;
  SftpFileHandle& operator=(const SftpFileHandle&) = delete;
  LIBSSH2_SFTP_HANDLE* get() const { return h_; }
  explicit operator bool() const { return h_ != nullptr; }
  void reset(LIBSSH2_SFTP_HANDLE* h) {
    if (h_ != nullptr) libssh2_sftp_close(h_);
    h_ = h;
  }

 private:
  LIBSSH2_SFTP_HANDLE* h_;
};

// 下载远端文件。返回值语义（阶段 1 起统一）：
//   >= 0 : 成功，值为下载的字节数（0 字节文件是合法的成功）
//   -1   : 任意环节失败（连接、握手、认证、sftp_init、open、stat、读取、长度不符）
// 调用方必须用 >= 0 判断成功，不要用 > 0，否则 0 字节文件会被误判为失败；
// 反过来也绝不能用 0 表示失败（历史 bug：全部服务器不可达时 --dflag 假成功）。
int64_t sftp_get_file(struct ServerInfo* server, string path,
                      string* file_buf = nullptr) {
  const string hostname = server->host;
  string file_name = getFileNameFromPath(path.c_str());

  if (nullptr == file_buf)
    log_info("sftp get file from sftp://%s:%d -> %s", server->host.c_str(),
             server->port, file_name.c_str());
  else
    log_info("sftp get file from sftp://%s:%d -> buffer", server->host.c_str(),
             server->port);

  SftpConn conn;
  std::string err;
  if (!conn.open(*server, (int)(connect_timeout * 1000), &err)) {
    log_error("sftp get file %s failed: %s", path.c_str(), err.c_str());
    return -1;
  }

  SftpFileHandle handle(
      libssh2_sftp_open(conn.sftp(), path.c_str(), LIBSSH2_FXF_READ, 0));
  if (!handle) {
    log_error("Unable to open file with SFTP: %s (errno %d)", path.c_str(),
              libssh2_sftp_last_error(conn.sftp()));
    return -1;
  }

  LIBSSH2_SFTP_ATTRIBUTES attributes;
  if (libssh2_sftp_stat(conn.sftp(), path.c_str(), &attributes) != 0) {
    log_error("Failed to get file attributes: %s", path.c_str());
    return -1;
  }
  uint64_t file_size = attributes.filesize;

  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  std::ostringstream oss;
  std::ofstream local_file;
  if (nullptr == file_buf) {
    local_file.open(file_name, std::ios::binary);
    if (!local_file.is_open()) {
      log_error("Failed to open file for writing: %s", file_name.c_str());
      return -1;
    }
  }

  ssize_t n;
  uint64_t total_downloaded = 0;
  std::vector<char> read_buf(1024 * 128);
  while ((n = libssh2_sftp_read(handle.get(), read_buf.data(),
                                read_buf.size())) > 0) {
    total_downloaded += (uint64_t)n;
    if (nullptr != file_buf) {
      oss.write(read_buf.data(), n);
      if (total_downloaded > 1024 * 1024 * 4) {
        log_error("get file to buf, size bigger 4M");
        return -1;
      }
    } else {
      local_file.write(read_buf.data(), n);
      if (!local_file.good()) {
        log_error("Failed to write local file: %s", file_name.c_str());
        return -1;
      }
      clock_gettime(CLOCK_MONOTONIC, &current_time);
      double elapsed_ms =
          (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
          (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
      print_progress((long long)total_downloaded, (long long)file_size,
                     elapsed_ms);
    }
  }
  // libssh2_sftp_read 返回负值是错误；读到 0 才是 EOF
  if (n < 0) {
    log_error("SFTP read error on %s: %ld", path.c_str(), (long)n);
    return -1;
  }

  if (nullptr != file_buf) {
    *file_buf = oss.str();
    log_debug("sftp get file buf: %s", file_buf->c_str());
  } else {
    clock_gettime(CLOCK_MONOTONIC, &current_time);
    double elapsed_ms =
        (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
        (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
    print_progress((long long)total_downloaded, (long long)file_size,
                   elapsed_ms);
    cout << "" << endl;
    local_file.close();
    if (!local_file) {
      log_error("Failed to flush local file: %s", file_name.c_str());
      return -1;
    }
  }

  if (file_size != total_downloaded) {
    log_error("Failed to download file %s: got %llu of %llu bytes", path.c_str(),
              (unsigned long long)total_downloaded,
              (unsigned long long)file_size);
    return -1;
  }
  handle.reset(nullptr);
  log_info("Download completed.");
  log_debug("get file %s ok", path.c_str());
  return (int64_t)total_downloaded;
}

std::streamsize get_file_size(const std::string& file_path) {
  std::ifstream file_stream(file_path, std::ios::binary | std::ios::ate);
  if (!file_stream.is_open()) {
    log_error("Failed to open file: %s", file_path.c_str());
    return -1;
  }
  std::streamsize file_size = file_stream.tellg();
  file_stream.close();
  log_debug("file %s, size %ld", file_path.c_str(), file_size);
  return file_size;
}

std::string get_current_time() {
  std::time_t t = std::time(nullptr);
  std::tm* tm_ptr = std::localtime(&t);
  std::ostringstream oss;
  oss << std::put_time(tm_ptr, "%Y_%m_%d_%H_%M_%S");
  return oss.str();
}

int64_t sftp_put_file(struct ServerInfo* server, string local_path,
                      string re_path) {
  string file_name = getFileNameFromPath(local_path.c_str());
  string cur_time = get_current_time();
  string remote_path =
      re_path + string("/") + cur_time + string("_") + file_name;

  log_info("sftp put file from %s -> sftp://%s:%d/%s", file_name.c_str(),
           server->host.c_str(), server->port, remote_path.c_str());

  SftpConn conn;
  std::string err;
  if (!conn.open(*server, (int)(connect_timeout * 1000), &err)) {
    log_error("sftp put file failed: %s", err.c_str());
    return -1;
  }

  SftpFileHandle handle(libssh2_sftp_open(
      conn.sftp(), remote_path.c_str(),
      LIBSSH2_FXF_WRITE | LIBSSH2_FXF_CREAT | LIBSSH2_FXF_TRUNC,
      LIBSSH2_SFTP_S_IRUSR | LIBSSH2_SFTP_S_IWUSR | LIBSSH2_SFTP_S_IRGRP |
          LIBSSH2_SFTP_S_IROTH));
  if (!handle) {
    log_error("Unable to open file with SFTP: %s (errno %d)",
              remote_path.c_str(), libssh2_sftp_last_error(conn.sftp()));
    return -1;
  }

  int64_t file_size = get_file_size(local_path);
  std::ifstream local_file(local_path, std::ios::binary);
  if (!local_file.is_open() || file_size < 0) {
    log_error("Failed to open local file for reading: %s", local_path.c_str());
    return -1;
  }

  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  int64_t total_upload = 0;
  std::vector<char> write_buf(1024 * 128);
  while (local_file.read(write_buf.data(), write_buf.size()) ||
         local_file.gcount() > 0) {
    ssize_t bytes_read = (ssize_t)local_file.gcount();
    if (local_file.bad()) {
      log_error("Read error on i/o operation.");
      return -1;
    }
    ssize_t bytes_written = 0;
    while (bytes_written < bytes_read) {
      ssize_t n = libssh2_sftp_write(handle.get(),
                                     write_buf.data() + bytes_written,
                                     (size_t)(bytes_read - bytes_written));
      if (n < 0) {
        log_error("SFTP write error: %ld", (long)n);
        return -1;
      }
      bytes_written += n;
    }
    total_upload += bytes_written;
    clock_gettime(CLOCK_MONOTONIC, &current_time);
    double elapsed_ms = (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
                        (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
    print_progress(total_upload, file_size, elapsed_ms);
  }
  clock_gettime(CLOCK_MONOTONIC, &current_time);
  double elapsed_ms = (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
                      (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
  print_progress(total_upload, file_size, elapsed_ms);
  cout << "" << endl;
  handle.reset(nullptr);

  if (total_upload != file_size) {
    log_error("Failed to upload file: %s", local_path.c_str());
    return -1;
  }
  log_info("Upload completed.");
  log_debug("put file %s ok", local_path.c_str());
  return total_upload;
}

// 探测服务器是否为 SFTP 服务。阶段 1 保持原语义：只做 TCP 连接 + SSH 握手，
// 不做认证与 sftp_init（是否加强由阶段 2 决定）。
bool is_sftp_service(ServerInfo* server_in) {
  log_debug("[%s] Determine if service is SFTP...", server_in->host.c_str());
  server_in->is_ok = false;
  SftpConn conn;
  std::string err;
  if (!conn.open(*server_in, (int)(connect_timeout * 1000), &err, true)) {
    log_debug("[%s] not a reachable sftp service: %s", server_in->host.c_str(),
              err.c_str());
    return false;
  }
  log_info("[%s] find sftp server", server_in->host.c_str());
  server_in->is_ok = true;
  return true;
}


void* sftp_server_and_speed(void* arg) {
  struct ThreadArgs* args = (struct ThreadArgs*)arg;
  pthread_t self_id = pthread_self();
  {
    pthread_mutex_lock(&cv_m);
    log_debug("sftp_server_and_speed thread id:0x%X is wait ready",
              (unsigned long)self_id);
    while (!cv_ready) {
      pthread_cond_wait(&cv, &cv_m);
    }
    pthread_mutex_unlock(&cv_m);
  }
  log_debug("sftp_server_and_speed thread id:0x%X start",
            (unsigned long)self_id);
  if (is_sftp_service(args->server_in) == false) {
    delete args;
    return NULL;
  }
  pthread_mutex_lock(&mtx_get_server);
  if (args->test_speed) {
    if (fast_server == nullptr) {
      sftp_test_speed(args->server_in);
      if (args->server_in->speed > (1024 * 1024 * 4)) {
        fast_server = args->server_in;
        log_debug("find 4MB/s server: %s:%d, kill other thread.",
                  fast_server->host.c_str(), fast_server->port);
        for (size_t i = 0; i < args->num_threads; ++i) {
          if (!pthread_equal(self_id, args->threads[i])) {
            pthread_cancel(args->threads[i]);
          }
        }
      }
    }
  } else {
    log_debug("find server no speed test: %s:%d, kill other thread.",
              args->server_in->host.c_str(), args->server_in->port);
    for (size_t i = 0; i < args->num_threads; ++i) {
      if (!pthread_equal(self_id, args->threads[i])) {
        pthread_cancel(args->threads[i]);
      }
    }
  }
  pthread_mutex_unlock(&mtx_get_server);
  delete args;
  return NULL;
}

struct ServerInfo* get_available_server(
    bool test_speed, std::vector<struct ServerInfo>& servers) {
  log_info(
      "get available server, It takes approximately 2 minutes... (speed test "
      "enable:%d)",
      test_speed);
  fast_server = nullptr;
  {
    pthread_mutex_lock(&cv_m);
    cv_ready = false;
    pthread_mutex_unlock(&cv_m);
  }
  {
    pthread_t* threads = new pthread_t[servers.size()];
    size_t num_threads = servers.size();

    for (size_t i = 0; i < num_threads; ++i) {
      struct ThreadArgs* args =
          new ThreadArgs{test_speed, &servers[i], threads, num_threads};
      if (pthread_create(&threads[i], NULL, sftp_server_and_speed, args) != 0) {
        log_error("Failed to create thread");
        delete args;
        threads[i] = 0;
      }
    }
    sleep(1);
    {
      pthread_mutex_lock(&cv_m);
      cv_ready = true;
      pthread_mutex_unlock(&cv_m);
    }
    pthread_cond_broadcast(&cv);

    for (size_t i = 0; i < num_threads; ++i) {
      if (threads[i] != 0) {
        pthread_join(threads[i], NULL);
      }
    }
    delete[] threads;
  }
  if (test_speed) {
    if (fast_server != nullptr) return fast_server;
    ServerInfo* max_index = nullptr;
    double max_speed = 0.0;
    for (ServerInfo& server : servers) {
      if (max_speed < server.speed) {
        max_speed = server.speed;
        max_index = &server;
      }
    }
    if (max_index == nullptr) {
      log_error("No available server found");
      return nullptr;
    } else {
      return max_index;
    }
  } else {
    for (ServerInfo& server : servers) {
      if (server.is_ok == true) {
        return &server;
      }
    }
  }
  log_error("No available server found");
  return nullptr;
}

bool get_file_open(string re_path) {
  log_info("get file from %s", re_path.c_str());
  ServerInfo* max_index = get_available_server(true, sdk_server_info);
  if (nullptr == max_index) {
    return false;
  }
  // >= 0 才是成功：0 字节文件是合法的下载结果
  return sftp_get_file(max_index, re_path) >= 0;
}

bool starts_with(const std::string& str, const std::string& prefix) {
  return str.size() >= prefix.size() &&
         str.compare(0, prefix.size(), prefix) == 0;
}

// 用户名会被拼进 system() 的 sftp 命令，限制为安全字符集，避免 shell 注入。
bool is_safe_username(const std::string& username) {
  for (char c : username) {
    if (!(isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '.' ||
          c == '-')) {
      return false;
    }
  }
  return !username.empty();
}

void sftp_login(string username) {
  if (!is_safe_username(username)) {
    log_error("invalid username: %s", username.c_str());
    return;
  }
  struct ServerInfo* login_info;
  if (starts_with(username, "sophgo") || starts_with(username, "h_s")) {
    log_info("%s sftp login hdk server", username.c_str());
    hdk_server_info.erase(
        std::remove_if(
            hdk_server_info.begin(), hdk_server_info.end(),
            [&](const ServerInfo& info) { return info.only_open == true; }),
        hdk_server_info.end());
    login_info = get_available_server(false, hdk_server_info);
  } else {
    log_info("%s sftp login sdk server", username.c_str());
    sdk_server_info.erase(
        std::remove_if(
            sdk_server_info.begin(), sdk_server_info.end(),
            [&](const ServerInfo& info) { return info.only_open == true; }),
        sdk_server_info.end());
    login_info = get_available_server(true, sdk_server_info);
  }
  if (nullptr == login_info) {
    log_error("cannot not find available server for login");
  } else {
    log_info("find available server: sftp://%s@%s:%d", username.c_str(),
             login_info->host.c_str(), login_info->port);
#ifdef WIN32
    const string command = "sftp.exe -P " + std::to_string(login_info->port) +
                           " " + username + "@" + login_info->host;
#else
    const string command = "sftp -P " + std::to_string(login_info->port) + " " +
                           username + "@" + login_info->host;
#endif
    log_debug("login cmd: %s", command.c_str());
    (void)system(command.c_str());
  }
}

bool get_file_dflag(string dflag) {
  log_debug("start to get file by dfalg: %s", dflag.c_str());
  string file_path;
  ServerInfo* server = get_available_server(true, sdk_server_info);
  if (server == nullptr) {
    return false;
  }
  std::string json_buf;
  if (sftp_get_file(server, "/.dfss_flags", &json_buf) < 0) {
    log_error("get json file error");
    return false;
  }
  try {
    json j = json::parse(json_buf);
    if (!j.contains(dflag) || j[dflag].is_null() ||
        !j[dflag].contains("filepath")) {
      log_error("dflag '%s' not found in index", dflag.c_str());
      return false;
    }
    std::string url = j[dflag.c_str()]["filepath"];
    log_info("from dflag %s get file %s", dflag.c_str(), url.c_str());
    file_path = url;
  } catch (json::exception& e) {
    log_error("JSON error: %s", e.what());
    return false;
  }
  return sftp_get_file(server, file_path) >= 0;
}

bool is_base64(unsigned char c) {
  return (isalnum(c) || (c == '+') || (c == '/'));
}

std::string base64_decode(const std::string& encoded_string) {
  int in_len = encoded_string.size();
  int i = 0;
  int j = 0;
  int in_ = 0;
  unsigned char char_array_4[4], char_array_3[3];
  static const std::string base64_chars =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
      "abcdefghijklmnopqrstuvwxyz"
      "0123456789+/";
  std::string decoded_string;

  while (in_len-- && (encoded_string[in_] != '=') &&
         is_base64(encoded_string[in_])) {
    char_array_4[i++] = encoded_string[in_];
    in_++;
    if (i == 4) {
      for (i = 0; i < 4; i++)
        char_array_4[i] = base64_chars.find(char_array_4[i]);

      char_array_3[0] =
          (char_array_4[0] << 2) + ((char_array_4[1] & 0x30) >> 4);
      char_array_3[1] =
          ((char_array_4[1] & 0xf) << 4) + ((char_array_4[2] & 0x3c) >> 2);
      char_array_3[2] = ((char_array_4[2] & 0x3) << 6) + char_array_4[3];

      for (i = 0; (i < 3); i++) decoded_string += char_array_3[i];
      i = 0;
    }
  }

  if (i) {
    for (j = i; j < 4; j++) char_array_4[j] = 0;

    for (j = 0; j < 4; j++)
      char_array_4[j] = base64_chars.find(char_array_4[j]);

    char_array_3[0] = (char_array_4[0] << 2) + ((char_array_4[1] & 0x30) >> 4);
    char_array_3[1] =
        ((char_array_4[1] & 0xf) << 4) + ((char_array_4[2] & 0x3c) >> 2);
    char_array_3[2] = ((char_array_4[2] & 0x3) << 6) + char_array_4[3];

    for (j = 0; (j < i - 1); j++) decoded_string += char_array_3[j];
  }

  return decoded_string;
}

bool sftp_upfile(std::string upflag, std::string upfile) {
  log_info("upfile %s -> upflag %s (%s)", upfile.c_str(), upflag.c_str(),
           base64_decode(upflag).c_str());
  sdk_server_info.erase(
      std::remove_if(
          sdk_server_info.begin(), sdk_server_info.end(),
          [&](const ServerInfo& info) { return info.only_open == true; }),
      sdk_server_info.end());
  ServerInfo* server = get_available_server(true, sdk_server_info);
  if (server == nullptr) {
    return false;
  }
  ServerInfo upload_server = *server;  // 使用副本，不修改全局服务器列表
  const char* upload_user = getenv("DFSS_UPLOAD_USER");
  const char* upload_pass = getenv("DFSS_UPLOAD_PASS");
  upload_server.user = upload_user ? upload_user : "customerUploadAccount";
  upload_server.pass = upload_pass ? upload_pass : "1QQHJONFflnI2BLsxUvA";
  if (sftp_put_file(&upload_server, upfile, base64_decode(upflag)) > 0) return true;
  return false;
}

std::string getExecutablePath() {
  static char buffer_in[1024];
  memset(buffer_in, 0, 1024);
#ifdef _WIN32
  GetModuleFileNameA(NULL, buffer_in, sizeof(buffer_in));
#elif defined(__APPLE__)
  uint32_t path_size = sizeof(buffer_in);
  if (_NSGetExecutablePath(buffer_in, &path_size) != 0) {
    return std::string();
  }
  // 解析符号链接，与 Linux /proc/self/exe 行为一致
  char resolved_path[PATH_MAX];
  if (realpath(buffer_in, resolved_path) != nullptr) {
    return std::string(resolved_path);
  }
  return std::string(buffer_in);
#else
  ssize_t len = readlink("/proc/self/exe", buffer_in, sizeof(buffer_in) - 1);
  if (len != -1) {
    buffer_in[len] = '\0';
  } else {
    return std::string();
  }
#endif
  return std::string(buffer_in);
}

void config_json_read() {
  fs::path executablePath = getExecutablePath();
  log_debug("get cur path:%s", executablePath.c_str());
  fs::path directoryPath = executablePath.parent_path();
  fs::path targetFilePath = directoryPath / string("dfss-config.json");
  std::ifstream inputFile(targetFilePath);
  if (!inputFile.is_open()) {
    log_debug("cannot find config json file: %s", targetFilePath.c_str());
  } else {
    log_debug("find and open config json file: %s", targetFilePath.c_str());
    // 读取阶段的任何异常（JSON 语法错误、字段类型不符）都不允许逃出：
    // 打印 warn 后回退到内置服务器列表（历史实现会直接崩溃）。
    try {
      json jsonData;
      inputFile >> jsonData;
      inputFile.close();
      if (!jsonData.is_object()) {
        throw std::runtime_error("config root is not a JSON object");
      }
      std::vector<ServerInfo> parsed_sdk;
      std::vector<ServerInfo> parsed_hdk;
      // 全部字段走 .value()：缺键取默认值，不再因为一个缺键就抛异常
      if (jsonData.contains("sdk")) {
        for (const auto& sdk : jsonData["sdk"]) {
          ServerInfo info;
          info.id = sdk.value("id", 0);
          info.host = sdk.value("host", std::string());
          info.port = sdk.value("port", 32022);
          info.user = sdk.value("user", std::string());
          info.pass = sdk.value("pass", std::string());
          info.only_open = sdk.value("only_open", false);
          info.is_ok = false;
          info.speed = 0.0;
          if (info.host.empty()) {
            log_warn("skip sdk server entry without host");
            continue;
          }
          parsed_sdk.push_back(info);
        }
      }
      if (jsonData.contains("hdk")) {
        for (const auto& hdk : jsonData["hdk"]) {
          ServerInfo info;
          info.id = hdk.value("id", 0);
          info.host = hdk.value("host", std::string());
          info.port = hdk.value("port", 32022);
          info.user = hdk.value("user", std::string());
          info.pass = hdk.value("pass", std::string());
          info.only_open = hdk.value("only_open", false);
          info.is_ok = false;
          info.speed = 0.0;
          if (info.host.empty()) {
            log_warn("skip hdk server entry without host");
            continue;
          }
          parsed_hdk.push_back(info);
        }
      }
      sdk_server_info = parsed_sdk;
      hdk_server_info = parsed_hdk;
      // 缺 connect_timeout 时保留默认值
      connect_timeout = jsonData.value("connect_timeout", connect_timeout);
    } catch (const std::exception& e) {
      log_warn("config json invalid (%s), fallback to built-in server list",
               e.what());
      sdk_server_info = kDefaultSdkServers;
      hdk_server_info = kDefaultHdkServers;
    }
  }
  for (auto& server : sdk_server_info) {
    log_debug("sdk server %s:%s@%s:%d", server.user.c_str(),
              server.pass.c_str(), server.host.c_str(), server.port);
  }
  for (auto& server : hdk_server_info) {
    log_debug("hdk server %s:%d", server.host.c_str(), server.port);
  }
  log_debug("sftp session timeout: %llds", (long long)connect_timeout);
}

int main(int argc, char* argv[]) {
#ifdef WIN32
  WSADATA wsadata;
  int err;
  err = WSAStartup(MAKEWORD(2, 0), &wsadata);
  if (err != 0) {
    log_error("WSAStartup failed with error: %d", err);
    exit(-1);
  }
#endif
  log_info("dfss cpp tool, version: (%s)[%s]", GIT_COMMIT_HASH,
           GIT_COMMIT_DATE);
  libssh2_init(0);
  cxxopts::Options options(
      "dfss-cpp", "About: a tool can download file from sophgo sftp server");
  options.add_options("url get file")("url", "url to get sftp file",
                                      cxxopts::value<std::string>());
  options.add_options("user login")("user", "username to login sftp",
                                    cxxopts::value<std::string>());
  options.add_options("dflag get file")("dflag",
                                        "using download flag to get file",
                                        cxxopts::value<std::string>());
  options.add_options("user up file")("upflag",
                                      "flag of need upload file, need upfile",
                                      cxxopts::value<std::string>())(
      "upfile", "need to upload file, need upflag",
      cxxopts::value<std::string>());
  options.add_options("connect option")(
      "connect_timeout", "sftp session timeout in seconds",
      cxxopts::value<uint64_t>());
  options.add_options("debug info mode")("debug", "open debug info print mode");
  options.add_options("config json")("no_json", "do not use json config");
  options.add_options("list server info")("list", "list server info");
  options.add_options("force specify a server link")(
      "force_server", "force specify a server link",
      cxxopts::value<uint64_t>());
  options.add_options("help info")("help", "print help info");

  // cxxopts 的解析异常必须自己接住：默认会 uncaught throw 并 abort。
  // 未知选项和非法数值都走这里。
  cxxopts::ParseResult parser;
  try {
    parser = options.parse(argc, argv);
  } catch (const cxxopts::exceptions::exception& e) {
    log_error("invalid argument: %s", e.what());
    std::cerr << "ERROR: " << e.what() << std::endl;
    std::cerr << options.help() << std::endl;
    libssh2_exit();
#ifdef WIN32
    WSACleanup();
#endif
    return 1;
  }

  if (parser.count("help")) {
    std::cout << options.help() << std::endl;
    libssh2_exit();
#ifdef WIN32
    WSACleanup();
#endif
    return 0;
  }
  log_set_lock(Lk_mux, NULL);
  if (parser.count("debug")) {
    log_set_level(LOG_TRACE);
    log_info("DEBUG MODE OPEN");
  } else {
    log_set_level(LOG_INFO);
  }

  if (!parser.count("no_json")) config_json_read();
  if (parser.count("connect_timeout")) {
    connect_timeout = parser["connect_timeout"].as<uint64_t>();
    if (connect_timeout == 0) {
      log_warn("connect_timeout=0 is invalid, fallback to 5s");
      connect_timeout = 5;
    }
    log_info("config sftp session timeout %llds", (long long)connect_timeout);
  }
  ret_flag = 0;
  if (parser.count("force_server")) {
    uint64_t force_server_id = parser["force_server"].as<uint64_t>();
    remove_some_server_info(sdk_server_info, false, force_server_id);
    remove_some_server_info(hdk_server_info, false, force_server_id);
  }
  do {
    if (parser.count("url")) {
      std::string url = parser["url"].as<std::string>();
      if (starts_with(url, "open@sophgo.com:")) {
        std::string file_path = url.substr(strlen("open@sophgo.com:"));
        ret_flag = -1;
        for (int i = 0; i < 3; ++i) {
          if (get_file_open(file_path)) {
            ret_flag = 0;
            break;
          }
          log_info("Download attempt %d", i);
        }
        if (ret_flag != 0)
          log_error("Cannot download %s from open@sophgo.com",
                    file_path.c_str());
        break;
      } else {
        log_error("Please download from open@sophgo.com");
        ret_flag = -1;
        break;
      }
    } else if (parser.count("user")) {
      string username = parser["user"].as<std::string>();
      log_info("use user: %s", username.c_str());
      sftp_login(username);
    } else if (parser.count("dflag")) {
      std::string dflag = parser["dflag"].as<std::string>();
      std::cout << "dflag: " << dflag << std::endl;
      ret_flag = -1;
      for (int i = 0; i < 3; i++) {
        if (true == get_file_dflag(dflag)) {
          ret_flag = 0;
          break;
        }
      }
      if (ret_flag != 0) log_error("dflag error");
      break;
    } else if (parser.count("upflag") && parser.count("upfile")) {
      std::string upflag = parser["upflag"].as<std::string>();
      std::string upfile = parser["upfile"].as<std::string>();
      log_info("upflag: %s, upfile: %s", upflag.c_str(), upfile.c_str());
      ret_flag = -1;
      for (int i = 0; i < 3; i++) {
        if (true == sftp_upfile(upflag, upfile)) {
          ret_flag = 0;
          break;
        }
      }
      if (ret_flag != 0) log_error("upflag error");
      break;
    } else if (parser.count("list")) {
      log_info("SDK server: ");
      print_server_info(sdk_server_info);
      log_info("HDK server: ");
      print_server_info(hdk_server_info);
      break;
    } else {
      std::cout << options.help() << std::endl;
      ret_flag = -1;
      break;
    }
  } while (0);
  libssh2_exit();
#ifdef WIN32
  WSACleanup();
#endif
  return ret_flag;
}