#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#if defined(__GNUC__) && !defined(__clang__)
#if (__GNUC__ > 4) && (__GNUC__ < 8)
#include <experimental/filesystem>
#else
#include <filesystem>
#endif
#endif

#include "cxxopts.hpp"
#include "httplib.h"
#include "json.hpp"
#define LIBSSH_STATIC 1
#include <libssh/libssh.h>
#include <libssh/sftp.h>

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
#if (__GNUC__ > 4) && (__GNUC__ < 8)
namespace fs = std::experimental::filesystem;
#else
namespace fs = std::filesystem;
#endif

/* 数据传输缓存区 */
static char buffer[1024 * 128];
/* 是否启用HTTP协议 */
static bool http_open_get_enable = false;
/* 链接超时 */
static long connect_timeout = 5;
/* LIBSSH日志等级 */
int verbosity = SSH_LOG_WARNING;

/* 多线程检测服务阶段线程共享变量 */
std::mutex mtx;
std::mutex mtx_get_server;
std::condition_variable cv;
std::mutex cv_m;
bool cv_ready = false;
void Lk_mux(bool lock, void*) {
  if (lock)
    mtx.lock();
  else
    mtx.unlock();
}

/* SFTP服务器信息 */
struct ServerInfo {
  string host;
  int port;
  string user;
  string pass;
  bool is_ok;
  double speed;
};

struct ServerInfo* fast_server = NULL;

/* 默认的SFTP链路 */
static std::vector<struct ServerInfo> sdk_server_info = {
    {"172.26.175.10", 32022, "oponIn", "oponIn", false, 0.0},
    {"172.26.13.184", 32022, "oponIn", "oponIn", false, 0.0},

    {"106.38.208.114", 32022, "open", "open", false, 0.0},
    {"103.68.183.114", 32022, "open", "open", false, 0.0},
};

static std::vector<struct ServerInfo> hdk_server_info = {
    {"219.142.246.77", 18822, "", "", false, 0.0},
    {"172.29.128.15", 8822, "", "", false, 0.0},
};

/* 从路径获取文件名 */
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

/* 数据大小可读化 */
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

/* 时间格式规整 */
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

/* 下载进度条 */
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

/* 配置socket的超时 */
void config_socket_timeout(int sockfd, int timeout_ms) {
#ifdef _WIN32
  setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, (char*)&timeout_ms,
             sizeof(timeout_ms));
  setsockopt(sockfd, SOL_SOCKET, SO_SNDTIMEO, (char*)&timeout_ms,
             sizeof(timeout_ms));
#else
  struct timeval tv;
  tv.tv_sec = timeout_ms / 1000;            // 将毫秒转换为秒
  tv.tv_usec = (timeout_ms % 1000) * 1000;  // 将剩余的毫秒转换为微秒
  setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(sockfd, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#endif
}

/* HTTP模式测速 */
void http_test_speed(struct ServerInfo* server) {
  log_info("start test server %s speed...", server->host.c_str());
  if (server->is_ok == false) {
    server->speed = 0.0;
    return;
  }
  string url = string("http://") + server->host + string(":") +
               std::to_string(server->port);
  httplib::Client cli(url);
  cli.set_basic_auth("open", "open");
  cli.set_read_timeout(connect_timeout, 0);
  cli.set_write_timeout(connect_timeout, 0);
  size_t total_bytes_downloaded = 0;
  auto start = std::chrono::high_resolution_clock::now();
  auto res =
      cli.Get("/.sophgo_speed", [&](const char* data, size_t data_length) {
        total_bytes_downloaded += data_length;
        if (std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::high_resolution_clock::now() - start)
                .count() > 5000)
          return false;
        return true;
      });
  auto end = std::chrono::high_resolution_clock::now();
  auto duration =
      std::chrono::duration_cast<std::chrono::milliseconds>(end - start)
          .count();
  double speed =
      duration == 0 ? 0 : (total_bytes_downloaded / (duration / 1000.0));
  log_info("server %s speed %s/s", server->host.c_str(),
           file_size_h(speed).c_str());
  server->speed = speed;
}

/* HTTP模式下载文件 */
int64_t http_get_file(struct ServerInfo* server, const std::string& path,
                      std::string* file_buf = NULL) {
  string url = string("http://") + server->host + string(":") +
               std::to_string(server->port);
  string file_name = getFileNameFromPath(path.c_str());
  if (NULL == file_buf)
    log_info("http get file from %s -> %s", url.c_str(), file_name.c_str());
  else
    log_info("http get file from %s -> buffer", url.c_str());
  httplib::Client client(url);
  client.set_basic_auth("open", "open");
  client.set_read_timeout(connect_timeout, 0);
  client.set_write_timeout(connect_timeout, 0);
  int64_t total_downloaded = 0;
  int64_t total_size = -1;
  std::ostringstream oss;
  std::ofstream ofs;
  if (NULL == file_buf) {
    ofs.open(file_name, std::ios::binary);
    if (!ofs.is_open()) {
      log_error("Failed to open file for writing: %s", file_name.c_str());
      return -1;
    }
  }
  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  auto http_res =
      client.Get(("/" + path).c_str(),
                 [&](const char* data, size_t data_length) {
                   total_downloaded += data_length;
                   if (NULL != file_buf) {
                     oss.write(data, data_length);
                     if (total_downloaded > 1024 * 1024 * 4) {
                       log_error("get file to buf, size bigger 4M");
                       return false;
                     }
                   } else {
                     ofs.write(data, data_length);
                   }
                   return true;
                 },
                 [&](uint64_t current, uint64_t total) {
                   clock_gettime(CLOCK_MONOTONIC, &current_time);
                   double elapsed_ms =
                       (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
                       (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
                   print_progress(current, total, elapsed_ms);
                   total_size = total;
                   return true;
                 });
  clock_gettime(CLOCK_MONOTONIC, &current_time);
  std::cout << "" << std::endl;
  if (NULL != file_buf) {
    *file_buf = oss.str();
    log_debug("get file buf: %s", file_buf->c_str());
  } else {
    ofs.close();
  }

  if (total_size == total_downloaded) {
    log_debug("get file ok");
    return total_downloaded;
  } else {
    log_error("Failed to download file: %s", http_res.error());
    return -1;
  }
}

/* SFTP模式下载文件 */
int64_t sftp_get_file(struct ServerInfo* server, string path) {
  const string hostname = server->host;
  const string username = server->user;
  const string password = server->pass;
  const int port = server->port;
  int rc;
  int sock;
  bool ssh_options_file = false;
  struct sockaddr_in sin;
  string file_name = getFileNameFromPath(path.c_str());

  log_info("sftp get file from sftp://%s:%d -> %s", server->host.c_str(),
           server->port, file_name.c_str());
  ssh_session ssh_session = ssh_new();
  if (ssh_session == NULL) {
    log_error("Failed to creat ssh_session!");
    return -1;
  }

  sock = socket(AF_INET, SOCK_STREAM, 0);
  sin.sin_family = AF_INET;
  sin.sin_port = htons(port);
  sin.sin_addr.s_addr = inet_addr(hostname.c_str());
  config_socket_timeout(sock, connect_timeout * 1000);
  rc = connect(sock, (struct sockaddr*)(&sin), sizeof(sin));
#ifdef WIN32
  closesocket(sock);
#else
  close(sock);
#endif
  if (rc != 0) {
    log_error("Failed to connect!");
    ssh_free(ssh_session);
    return -1;
  }

  ssh_options_set(ssh_session, SSH_OPTIONS_HOST, server->host.c_str());
  ssh_options_set(ssh_session, SSH_OPTIONS_LOG_VERBOSITY, &verbosity);
  ssh_options_set(ssh_session, SSH_OPTIONS_PORT, &port);
  ssh_options_set(ssh_session, SSH_OPTIONS_TIMEOUT, &connect_timeout);
  ssh_options_set(ssh_session, SSH_OPTIONS_PROCESS_CONFIG, &ssh_options_file);
  if (ssh_connect(ssh_session) != SSH_OK) {
    log_error("Error connecting to server: %s\n", ssh_get_error(ssh_session));
    ssh_free(ssh_session);
    return -1;
  }

  if (ssh_userauth_password(ssh_session, username.c_str(), password.c_str()) !=
      SSH_AUTH_SUCCESS) {
    log_error("Error authenticating with password [%s:%s]: %s\n",
              username.c_str(), password.c_str(), ssh_get_error(ssh_session));
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  char* banner = ssh_get_issue_banner(ssh_session);
  if (ssh_session) {
    log_info(
        "sftp server "
        "banner:\n------------------------------\n%s\n-------------------------"
        "-----",
        banner);
    SSH_STRING_FREE_CHAR(banner);
    banner = NULL;
  }

  sftp_session sftp_session = sftp_new(ssh_session);
  if (sftp_session == NULL) {
    log_error("Failed to creat sftp_session: %s", ssh_get_error(ssh_session));
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  if (sftp_init(sftp_session) != SSH_OK) {
    log_error("Error initializing SFTP session: code %d.\n",
              sftp_get_error(sftp_session));
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  sftp_attributes file_attr = sftp_stat(sftp_session, path.c_str());
  if (file_attr == NULL) {
    log_error("Can't get file stat: %s\n", ssh_get_error(ssh_session));
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  sftp_file sfile;
  sfile = sftp_open(sftp_session, path.c_str(), O_RDONLY, 0);
  if (sfile == NULL) {
    log_error("Can't open file for reading: %s\n", ssh_get_error(ssh_session));
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }
  uint64_t file_size = file_attr->size;
  sftp_attributes_free(file_attr);

  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  std::ofstream local_file(file_name, std::ios::binary);
  if (!local_file.is_open()) {
    log_error("Failed to open file for writing: %s", file_name.c_str());
    sftp_close(sfile);
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }
  ssize_t n;
  uint64_t total_downloaded = 0;
  for (;;) {
    n = sftp_read(sfile, buffer, sizeof(buffer));
    if (n == 0) {
      break;  // EOF
    } else if (n < 0) {
      log_error("Error to get sftp file: %s", ssh_get_error(ssh_session));
      sftp_close(sfile);
      sftp_free(sftp_session);
      ssh_disconnect(ssh_session);
      ssh_free(ssh_session);
      return -1;
    }
    local_file.write(buffer, n);
    total_downloaded += n;
    clock_gettime(CLOCK_MONOTONIC, &current_time);
    double elapsed_ms = (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
                        (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
    print_progress(total_downloaded, file_size, elapsed_ms);
  }
  clock_gettime(CLOCK_MONOTONIC, &current_time);
  double elapsed_ms = (current_time.tv_sec - start_time.tv_sec) * 1000.0 +
                      (current_time.tv_nsec - start_time.tv_nsec) / 1000000.0;
  print_progress(total_downloaded, file_size, elapsed_ms);
  cout << "" << endl;
  log_info("Download completed.");

  sftp_close(sfile);
  sftp_free(sftp_session);
  ssh_disconnect(ssh_session);
  ssh_free(ssh_session);
  if (file_size == total_downloaded) {
    log_debug("get file %s ok", path.c_str());
    return total_downloaded;
  } else {
    log_error("Failed to download file: %s", path.c_str());
    return -1;
  }
}

/* 获取文件大小 */
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

/* 获取当前时间 */
std::string get_current_time() {
  std::time_t t = std::time(nullptr);
  std::tm* tm_ptr = std::localtime(&t);
  std::ostringstream oss;
  oss << std::put_time(tm_ptr, "%Y_%m_%d_%H_%M_%S");
  return oss.str();
}

/* SFTP模式上传文件 */
int64_t sftp_put_file(struct ServerInfo* server, string local_path,
                      string re_path) {
  const string hostname = server->host;
  const string username = server->user;
  const string password = server->pass;
  const int port = server->port;
  int sock, rc;

  bool ssh_options_file = false;
  struct sockaddr_in sin;
  string file_name = getFileNameFromPath(local_path.c_str());
  string cur_time = get_current_time();
  string remote_path =
      re_path + string("/") + cur_time + string("_") + file_name;
  log_info("sftp put file from %s -> sftp://%s:%d/%s", file_name.c_str(),
           server->host.c_str(), server->port, remote_path.c_str());
  ssh_session ssh_session = ssh_new();
  if (ssh_session == NULL) {
    log_error("Failed to creat ssh_session!");
    return -1;
  }

  sock = socket(AF_INET, SOCK_STREAM, 0);
  sin.sin_family = AF_INET;
  sin.sin_port = htons(port);
  sin.sin_addr.s_addr = inet_addr(hostname.c_str());
  config_socket_timeout(sock, connect_timeout * 1000);
  rc = connect(sock, (struct sockaddr*)(&sin), sizeof(sin));
#ifdef WIN32
  closesocket(sock);
#else
  close(sock);
#endif
  if (rc != 0) {
    log_error("Failed to connect!");
    ssh_free(ssh_session);
    return -1;
  }

  ssh_options_set(ssh_session, SSH_OPTIONS_HOST, server->host.c_str());
  ssh_options_set(ssh_session, SSH_OPTIONS_LOG_VERBOSITY, &verbosity);
  ssh_options_set(ssh_session, SSH_OPTIONS_PORT, &port);
  ssh_options_set(ssh_session, SSH_OPTIONS_TIMEOUT, &connect_timeout);
  ssh_options_set(ssh_session, SSH_OPTIONS_PROCESS_CONFIG, &ssh_options_file);
  if (ssh_connect(ssh_session) != SSH_OK) {
    log_error("Error connecting to server: %s\n", ssh_get_error(ssh_session));
    ssh_free(ssh_session);
    return -1;
  }

  if (ssh_userauth_password(ssh_session, username.c_str(), password.c_str()) !=
      SSH_AUTH_SUCCESS) {
    log_error("Error authenticating with password [%s:%s]: %s\n",
              username.c_str(), password.c_str(), ssh_get_error(ssh_session));
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  char* banner = ssh_get_issue_banner(ssh_session);
  if (ssh_session) {
    log_info(
        "sftp server "
        "banner:\n------------------------------\n%s\n-------------------------"
        "-----",
        banner);
    SSH_STRING_FREE_CHAR(banner);
    banner = NULL;
  }

  sftp_session sftp_session = sftp_new(ssh_session);
  if (sftp_session == NULL) {
    log_error("Failed to creat sftp_session: %s", ssh_get_error(ssh_session));
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  if (sftp_init(sftp_session) != SSH_OK) {
    log_error("Error initializing SFTP session: code %d.\n",
              sftp_get_error(sftp_session));
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  sftp_file sfile;
  sfile = sftp_open(sftp_session, (remote_path).c_str(),
                    O_WRONLY | O_CREAT | O_TRUNC, S_IRWXU);
  if (sfile == NULL) {
    log_error("Can't open file for writing: %s\n", ssh_get_error(ssh_session));
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }

  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  int64_t file_size = get_file_size(local_path);
  std::ifstream local_file(local_path, std::ios::binary);
  if (!local_file.is_open() || file_size < 0) {
    log_error("Failed to open local file for reading: %s", local_path.c_str());
    sftp_close(sfile);
    sftp_free(sftp_session);
    ssh_disconnect(ssh_session);
    ssh_free(ssh_session);
    return -1;
  }
  int64_t total_upload = 0;
  ssize_t bytes_written = 0;
  ssize_t bytes_read = 0;
  bool ef = false;
  while (!local_file.eof()) {
    if (local_file.eof()) {
      log_error("End of file reached.");
      ef = true;
    } else if (local_file.fail()) {
      log_error("Logical error on i/o operation.");
      ef = true;
    } else if (local_file.bad()) {
      log_error("Read error on i/o operation.");
      ef = true;
    }
    if (ef) {
      sftp_close(sfile);
      sftp_free(sftp_session);
      ssh_disconnect(ssh_session);
      ssh_free(ssh_session);
    }
    local_file.read(buffer, sizeof(buffer));
    bytes_read = local_file.gcount();
    bytes_written = 0;
    while (bytes_written != bytes_read) {
      bytes_written +=
          sftp_write(sfile, buffer + bytes_written, bytes_read - bytes_written);
    }
    if (bytes_written != bytes_read) {
      log_error(
          "Failed to write to remote file, bytes_written:%d,bytes_read:%d",
          bytes_written, bytes_read);
      sftp_close(sfile);
      sftp_free(sftp_session);
      ssh_disconnect(ssh_session);
      ssh_free(ssh_session);
      return -1;
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
  log_info("Upload completed.");

  sftp_close(sfile);
  sftp_free(sftp_session);
  ssh_disconnect(ssh_session);
  ssh_free(ssh_session);
  if (file_size == total_upload) {
    log_debug("put file %s ok", local_path.c_str());
    return total_upload;
  } else {
    log_error("Failed to upload file: %s", local_path.c_str());
    return -1;
  }
}

/* 判断是否是SFTP服务器 */
bool is_sftp_service(bool test_speed, ServerInfo* server_in) {
  int rc = 0, verbosity = SSH_LOG_NOLOG;
  log_debug("[%s] Determine if service is SFTP...", server_in->host.c_str());
  server_in->is_ok = false;
  ssh_session ssh_session = ssh_new();
  if (ssh_session == NULL) {
    log_error("Failed to creat ssh_session!");
    return false;
  }

  int sock = socket(AF_INET, SOCK_STREAM, 0);
  if (sock == -1) {
    log_debug("[%s] Error creating socket.", server_in->host.c_str());
    return false;
  }

  struct sockaddr_in serv_addr;
  std::memset(&serv_addr, 0, sizeof(serv_addr));
  serv_addr.sin_family = AF_INET;
  serv_addr.sin_addr.s_addr = inet_addr(server_in->host.c_str());
  serv_addr.sin_port = htons(server_in->port);
  config_socket_timeout(sock, connect_timeout * 1000);
  rc = connect(sock, (struct sockaddr*)&serv_addr, sizeof(serv_addr));
#ifdef WIN32
  closesocket(sock);
#else
  close(sock);
#endif
  if (rc != 0) {
    log_debug("[%s] Error connecting on port %d", server_in->host.c_str(),
              server_in->port);
    return false;
  }

  ssh_options_set(ssh_session, SSH_OPTIONS_HOST, server_in->host.c_str());
  ssh_options_set(ssh_session, SSH_OPTIONS_LOG_VERBOSITY, &verbosity);
  ssh_options_set(ssh_session, SSH_OPTIONS_PORT, &server_in->port);
  ssh_options_set(ssh_session, SSH_OPTIONS_TIMEOUT, &connect_timeout);
  if (ssh_connect(ssh_session) != SSH_OK) {
    log_error("Error connecting to server: %s\n", ssh_get_error(ssh_session));
    ssh_free(ssh_session);
    return false;
  }

  /* 考虑到需要兼容HDK的SFTP服务器 */
  if (test_speed) {
    if (ssh_userauth_password(ssh_session, server_in->user.c_str(),
                              server_in->pass.c_str()) != SSH_AUTH_SUCCESS) {
      log_error("Error authenticating with password [%s:%s]: %s\n",
                server_in->user.c_str(), server_in->pass.c_str(),
                ssh_get_error(ssh_session));
      ssh_disconnect(ssh_session);
      ssh_free(ssh_session);
      return -1;
    }

    sftp_session sftp_session = sftp_new(ssh_session);
    if (sftp_session == NULL) {
      log_error("Failed to creat sftp_session: %s", ssh_get_error(ssh_session));
      ssh_free(ssh_session);
      return false;
    }

    if (sftp_init(sftp_session) != SSH_OK) {
      log_error("Error initializing SFTP session: code %d.\n",
                sftp_get_error(sftp_session));
      sftp_free(sftp_session);
      ssh_disconnect(ssh_session);
      ssh_free(ssh_session);
      return -1;
    }

    sftp_free(sftp_session);
  }
  ssh_free(ssh_session);
  log_info("[%s] find sftp server", server_in->host.c_str());
  server_in->is_ok = true;
  return true;
}

/* 确定是否SFTP，并且测速 */
void sftp_server_and_speed(bool test_speed, ServerInfo* server_in,
                           std::vector<std::thread>* ths) {
  std::thread::id self_id = std::this_thread::get_id();
  {
    std::unique_lock<std::mutex> lk(cv_m);
    log_debug("sftp_server_and_speed thread id:0x%X is wait ready", self_id);
    cv.wait(lk, [&] { return cv_ready; });
  }
  log_debug("sftp_server_and_speed thread id:0x%X start", self_id);
  if (is_sftp_service(test_speed, server_in) == false) return;
  mtx_get_server.lock();
  if (test_speed) {
    if (fast_server == NULL) {
      http_test_speed(server_in);
      if (server_in->speed > (1024 * 1024 * 4)) {
        fast_server = server_in;
        log_debug("find 4MB/s server: %s:%d, kill other thread.",
                  fast_server->host.c_str(), fast_server->port);
        for (std::thread& th : *ths) {
          if (self_id != th.get_id())
            if (th.joinable()) {
              pthread_cancel(th.native_handle());
            }
        }
      }
    }
  } else {
    log_debug("find server no speed test: %s:%d, kill other thread.",
              server_in->host.c_str(), server_in->port);
    for (std::thread& th : *ths) {
      if (self_id != th.get_id())
        if (th.joinable()) {
          pthread_cancel(th.native_handle());
        }
    }
  }
  mtx_get_server.unlock();
}

/* 查找最快的服务器 */
struct ServerInfo* get_available_server(
    bool test_speed, std::vector<struct ServerInfo>& servers) {
  log_info(
      "get available server, It takes approximately 2 minutes... (speed test "
      "enable:%d)",
      test_speed);
  fast_server = NULL;
  {
    std::vector<std::thread> threads;
    for (ServerInfo& server : servers) {
      threads.emplace_back(sftp_server_and_speed, test_speed, &server,
                           &threads);
    }
    std::this_thread::sleep_for(std::chrono::seconds(1));
    {
      std::lock_guard<std::mutex> lk(cv_m);
      cv_ready = true;
    }
    cv.notify_all();

    for (auto& t : threads) {
      if (t.joinable()) t.join();
    }
  }
  if (test_speed == 1) {
    if (fast_server != NULL) return fast_server;
    ServerInfo* max_index = 0;
    int max_speed = 0;
    for (ServerInfo& server : servers) {
      if (max_speed < server.speed) {
        max_speed = server.speed;
        max_index = &server;
      }
    }
    if (max_speed == 0) {
      log_error("No available server found");
      return NULL;
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
  return NULL;
}

bool get_file_open(string re_path) {
  log_info("get file from %s", re_path.c_str());
  ServerInfo* max_index = get_available_server(true, sdk_server_info);
  if (NULL == max_index) {
    return false;
  }
  if (http_open_get_enable) {
    if (http_get_file(max_index, re_path) > 0) return true;
  } else {
    if (sftp_get_file(max_index, re_path) > 0) return true;
  }
  return false;
}

bool starts_with(const std::string& str, const std::string& prefix) {
  return str.size() >= prefix.size() &&
         str.compare(0, prefix.size(), prefix) == 0;
}

void sftp_login(string username) {
  struct ServerInfo* login_info;
  if (starts_with(username, "sophgo") || starts_with(username, "h_s")) {
    log_info("%s sftp login hdk server", username.c_str());
    login_info = get_available_server(false, hdk_server_info);
  } else {
    log_info("%s sftp login sdk server", username.c_str());
    login_info = get_available_server(true, sdk_server_info);
  }
  if (NULL == login_info) {
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
    system(command.c_str());
  }
}

/* 获取gflag文件并解析 */
bool get_file_dflag(string dflag) {
  log_debug("start to get file by dfalg: %s", dflag.c_str());
  string file_path;
  ServerInfo* server = get_available_server(true, sdk_server_info);
  if (server == NULL) {
    return false;
  }
  std::string json_buf;
  if (http_get_file(server, "/.dfss_flags", &json_buf) > 0) {
    try {
      json j = json::parse(json_buf);
      std::string url = j[dflag.c_str()]["filepath"];
      log_info("from dflag %s get file %s", dflag.c_str(), url.c_str());
      file_path = url;
    } catch (json::parse_error& e) {
      log_error("JSON parse error: %s", e.what());
      return false;
    }
  } else {
    log_error("get json file error");
    return false;
  }
  if (http_open_get_enable) {
    if (http_get_file(server, file_path) > 0) return true;
  } else {
    if (sftp_get_file(server, file_path) > 0) return true;
  }
  return false;
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

/* sftp上传文件 */
bool sftp_upfile(std::string upflag, std::string upfile) {
  log_info("upfile %s -> upflag %s (%s)", upfile.c_str(), upflag.c_str(),
           base64_decode(upflag).c_str());
  ServerInfo* server = get_available_server(true, sdk_server_info);
  if (server == NULL) {
    return false;
  }
  server->user = "customerUploadAccount";
  server->pass = "1QQHJONFflnI2BLsxUvA";
  if (sftp_put_file(server, upfile, base64_decode(upflag)) > 0) return true;
  return false;
}

std::string getExecutablePath() {
  static char buffer_in[1024];
  memset(buffer_in, 0, 1024);
#ifdef _WIN32
  GetModuleFileNameA(NULL, buffer, sizeof(buffer));
#else
  ssize_t len = readlink("/proc/self/exe", buffer, sizeof(buffer) - 1);
  if (len != -1) {
    buffer[len] = '\0';
  } else {
    return std::string();
  }
#endif
  return std::string(buffer);
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
    json jsonData;
    inputFile >> jsonData;
    inputFile.close();
    sdk_server_info.clear();
    hdk_server_info.clear();
    for (const auto& sdk : jsonData["sdk"]) {
      std::string host = sdk["host"];
      int port = sdk["port"];
      std::string user = sdk["user"];
      std::string pass = sdk["pass"];
      sdk_server_info.push_back(
          ServerInfo({host, port, user, pass, false, 0.0}));
    }
    for (const auto& sdk : jsonData["hdk"]) {
      std::string host = sdk["host"];
      int port = sdk["port"];
      std::string user = sdk["user"];
      std::string pass = sdk["pass"];
      hdk_server_info.push_back(
          ServerInfo({host, port, user, pass, false, 0.0}));
    }
    connect_timeout = jsonData["connect_timeout"];
  }
  for (auto& server : sdk_server_info) {
    log_debug("sdk server %s:%s@%s:%d", server.user.c_str(),
              server.pass.c_str(), server.host.c_str(), server.port);
  }
  for (auto& server : hdk_server_info) {
    log_debug("hdk server %s:%d", server.host.c_str(), server.port);
  }
  log_debug("http connect timeout: %ds", connect_timeout);
}

int main(int argc, char* argv[]) {
  int ret_flag = 0;
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
  options.add_options("connect option")("enable_http",
                                        "url or dfss get file by http enable")(
      "connect_timeout", "config timeout on http connect",
      cxxopts::value<uint64_t>());
  options.add_options("debug info mode")("debug", "open debug info print mode");
  options.add_options("config json")("no_json", "do not use json config");
  auto parser = options.parse(argc, argv);

  if (parser.count("help")) {
    std::cout << options.help() << std::endl;
    return 0;
  }
  log_set_lock(Lk_mux, NULL);
  if (parser.count("debug")) {
    log_set_level(LOG_TRACE);
    verbosity = SSH_LOG_PACKET;
    log_info("DEBUG MODE OPEN");
  } else {
    log_set_level(LOG_INFO);
  }

  if (parser.count("enable_http"))
    http_open_get_enable = true;
  else
    http_open_get_enable = false;

  if (!parser.count("no_json")) config_json_read();
  if (parser.count("connect_timeout")) {
    connect_timeout = parser["connect_timeout"].as<uint64_t>();
    log_info("config http connect timeout %ld s", connect_timeout);
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
      std::cout << "user: " << username << std::endl;
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
      std::cout << "upflag: " << upflag << "upfile: " << upfile << std::endl;
      ret_flag = -1;
      for (int i = 0; i < 3; i++) {
        if (true == sftp_upfile(upflag, upfile)) {
          ret_flag = 0;
          break;
        }
      }
      if (ret_flag != 0) log_error("upflag error");
      break;
    } else {
      std::cout << options.help() << std::endl;
      ret_flag = -1;
      break;
    }
  } while (0);
#ifdef WIN32
  WSACleanup();
#endif
  return ret_flag;
}
