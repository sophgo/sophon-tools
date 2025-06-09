#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
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
#include "libssh2.h"
#include "libssh2_sftp.h"

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

static char buffer[1024 * 128];
static bool http_open_get_enable = false;
static uint64_t connect_timeout = 5;
static int ret_flag = 0;
struct ServerInfo {
  int id;
  string host;
  int port;
  string user;
  string pass;
  bool only_open;
  bool is_ok;
  double speed;
};

struct ServerInfo* fast_server = NULL;
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

static std::vector<struct ServerInfo> sdk_server_info = {
    {0, "172.26.175.10", 32022, "oponIn", "oponIn", false, false, 0.0},
    {1, "172.24.12.77", 32022, "open", "open", true, false, 0.0},
    {2, "172.26.13.184", 32022, "oponIn", "oponIn", false, false, 0.0},
    {3, "172.26.166.66", 32022, "oponIn", "oponIn", false, false, 0.0},
    {4, "106.38.208.114", 32022, "open", "open", false, false, 0.0},
    {5, "103.68.183.114", 32022, "open", "open", false, false, 0.0},
};

static std::vector<struct ServerInfo> hdk_server_info = {
    {100, "219.142.246.77", 18822, "", "", false, false, 0.0},
    {101, "172.29.128.15", 8822, "", "", false, false, 0.0},
};

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

static void print_server_info(std::vector<struct ServerInfo> server_infos) {
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

uint64_t sftp_get_file(struct ServerInfo* server, string path) {
  const string hostname = server->host;
  const string username = server->user;
  const string password = server->pass;
  const int port = server->port;
  int rc;
  int sock;
  struct sockaddr_in sin;
  string file_name = getFileNameFromPath(path.c_str());
  LIBSSH2_SESSION* session;
  LIBSSH2_SFTP* sftp_session;
  LIBSSH2_SFTP_HANDLE* sftp_handle;

  log_info("sftp get file from sftp://%s:%d -> %s", server->host.c_str(),
           server->port, file_name.c_str());

  sock = socket(AF_INET, SOCK_STREAM, 0);
  sin.sin_family = AF_INET;
  sin.sin_port = htons(port);
  sin.sin_addr.s_addr = inet_addr(hostname.c_str());
  config_socket_timeout(sock, connect_timeout * 1000);
  if (connect(sock, (struct sockaddr*)(&sin), sizeof(sin)) != 0) {
    log_error("Failed to connect!");
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }

  session = libssh2_session_init();
  libssh2_session_set_timeout(session, connect_timeout * 1000);
  libssh2_session_flag(session, LIBSSH2_FLAG_COMPRESS, 1);
  libssh2_session_method_pref(session, LIBSSH2_METHOD_COMP_CS, "zlib,none");
  libssh2_session_method_pref(session, LIBSSH2_METHOD_COMP_SC, "zlib,none");
  if (libssh2_session_handshake(session, sock)) {
    log_error("Failure establishing SSH session");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }

  char* support_auth =
      libssh2_userauth_list(session, username.c_str(), username.length());
  if (support_auth != NULL) {
    log_info("server support auth list: %s", support_auth);
  }

  if (libssh2_userauth_password(session, username.c_str(), password.c_str())) {
    log_error("Authentication by password failed.");
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }

  char* banner_s = (char*)calloc(0, 1024 * 512);
  rc = libssh2_userauth_banner(session, &banner_s);
  if (rc == LIBSSH2_ERROR_NONE) {
    log_info(
        "SFTP server banner:\n--------------------\n%s\n--------------------",
        banner_s);
  }

  const char* comp = libssh2_session_methods(session, LIBSSH2_METHOD_COMP_CS);
  log_info("Compression algorithm: %s", comp);

  sftp_session = libssh2_sftp_init(session);
  if (!sftp_session) {
    log_error("Unable to init SFTP session");
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }

  sftp_handle =
      libssh2_sftp_open(sftp_session, path.c_str(), LIBSSH2_FXF_READ, 0);
  if (!sftp_handle) {
    log_error("Unable to open file with SFTP");
    libssh2_sftp_close(sftp_handle);
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }

  LIBSSH2_SFTP_ATTRIBUTES attributes;
  rc = libssh2_sftp_stat(sftp_session, path.c_str(), &attributes);
  if (rc != 0) {
    log_error("Failed to get file attributes: %d", rc);
    libssh2_sftp_close(sftp_handle);
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }
  uint64_t file_size = attributes.filesize;

  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  std::ofstream local_file(file_name, std::ios::binary);
  if (!local_file.is_open()) {
    log_error("Failed to open file for writing: %s", file_name.c_str());
    libssh2_sftp_close(sftp_handle);
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return 0;
  }
  ssize_t n;
  uint64_t total_downloaded = 0;
  while ((n = libssh2_sftp_read(sftp_handle, buffer, sizeof(buffer))) > 0) {
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

  libssh2_sftp_close(sftp_handle);
  libssh2_sftp_shutdown(sftp_session);
  libssh2_session_disconnect(session, "Normal Shutdown");
  libssh2_session_free(session);
#ifdef WIN32
  closesocket(sock);
#else
  close(sock);
#endif
  if (file_size == total_downloaded) {
    log_debug("get file %s ok", path.c_str());
    return total_downloaded;
  } else {
    log_error("Failed to download file: %s", path.c_str());
    return 0;
  }
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
  const string hostname = server->host;
  const string username = server->user;
  const string password = server->pass;
  const int port = server->port;
  int sock, rc;
  struct sockaddr_in sin;
  string file_name = getFileNameFromPath(local_path.c_str());
  string cur_time = get_current_time();
  string remote_path =
      re_path + string("/") + cur_time + string("_") + file_name;
  LIBSSH2_SESSION* session;
  LIBSSH2_SFTP* sftp_session;
  LIBSSH2_SFTP_HANDLE* sftp_handle;

  log_info("sftp put file from %s -> sftp://%s:%d/%s", file_name.c_str(),
           server->host.c_str(), server->port, remote_path.c_str());

  sock = socket(AF_INET, SOCK_STREAM, 0);
  sin.sin_family = AF_INET;
  sin.sin_port = htons(port);
  sin.sin_addr.s_addr = inet_addr(hostname.c_str());
  config_socket_timeout(sock, connect_timeout * 1000);
  if (connect(sock, (struct sockaddr*)(&sin), sizeof(sin)) != 0) {
    log_error("Failed to connect!");
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return -1;
  }

  session = libssh2_session_init();
  libssh2_session_set_timeout(session, connect_timeout * 1000);
  libssh2_session_flag(session, LIBSSH2_FLAG_COMPRESS, 1);
  libssh2_session_method_pref(session, LIBSSH2_METHOD_COMP_CS, "zlib,none");
  libssh2_session_method_pref(session, LIBSSH2_METHOD_COMP_SC, "zlib,none");
  if (libssh2_session_handshake(session, sock)) {
    log_error("Failure establishing SSH session");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return -1;
  }

  char* support_auth =
      libssh2_userauth_list(session, username.c_str(), username.length());
  if (support_auth != NULL) {
    log_info("server support auth list: %s", support_auth);
  }

  if (libssh2_userauth_password(session, username.c_str(), password.c_str())) {
    log_error("Authentication by password failed.");
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return -1;
  }

  char* banner_s = (char*)calloc(0, 1024 * 512);
  rc = libssh2_userauth_banner(session, &banner_s);
  if (rc == LIBSSH2_ERROR_NONE) {
    log_info(
        "SFTP server banner:\n--------------------\n%s\n--------------------",
        banner_s);
  }

  const char* comp = libssh2_session_methods(session, LIBSSH2_METHOD_COMP_CS);
  log_info("Compression algorithm: %s", comp);

  sftp_session = libssh2_sftp_init(session);
  if (!sftp_session) {
    log_error("Unable to init SFTP session");
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return -1;
  }

  sftp_handle = libssh2_sftp_open(
      sftp_session, (remote_path).c_str(),
      LIBSSH2_FXF_WRITE | LIBSSH2_FXF_CREAT | LIBSSH2_FXF_TRUNC,
      LIBSSH2_SFTP_S_IRUSR | LIBSSH2_SFTP_S_IWUSR | LIBSSH2_SFTP_S_IRGRP |
          LIBSSH2_SFTP_S_IROTH);
  if (!sftp_handle) {
    log_error("Unable to open file with SFTP: %s", remote_path);
    libssh2_sftp_close(sftp_handle);
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return -1;
  }

  struct timespec start_time, current_time;
  clock_gettime(CLOCK_MONOTONIC, &start_time);
  int64_t file_size = get_file_size(local_path);
  std::ifstream local_file(local_path, std::ios::binary);
  if (!local_file.is_open() || file_size < 0) {
    log_error("Failed to open local file for reading: %s", local_path.c_str());
    libssh2_sftp_close(sftp_handle);
    libssh2_sftp_shutdown(sftp_session);
    libssh2_session_disconnect(session, "Normal Shutdown");
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
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
      libssh2_sftp_close(sftp_handle);
      libssh2_sftp_shutdown(sftp_session);
      libssh2_session_disconnect(session, "Normal Shutdown");
      libssh2_session_free(session);
#ifdef WIN32
      closesocket(sock);
#else
      close(sock);
#endif
    }
    local_file.read(buffer, sizeof(buffer));
    bytes_read = local_file.gcount();
    bytes_written = 0;
    while (bytes_written != bytes_read) {
      bytes_written += libssh2_sftp_write(sftp_handle, buffer + bytes_written,
                                          bytes_read - bytes_written);
    }
    if (bytes_written != bytes_read) {
      log_error(
          "Failed to write to remote file, bytes_written:%d,bytes_read:%d",
          bytes_written, bytes_read);
      libssh2_sftp_close(sftp_handle);
      libssh2_sftp_shutdown(sftp_session);
      libssh2_session_disconnect(session, "Normal Shutdown");
      libssh2_session_free(session);
#ifdef WIN32
      closesocket(sock);
#else
      close(sock);
#endif
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

  libssh2_sftp_close(sftp_handle);
  libssh2_sftp_shutdown(sftp_session);
  libssh2_session_disconnect(session, "Normal Shutdown");
  libssh2_session_free(session);
#ifdef WIN32
  closesocket(sock);
#else
  close(sock);
#endif
  return total_upload;
  if (file_size == total_upload) {
    log_debug("put file %s ok", local_path.c_str());
    return total_upload;
  } else {
    log_error("Failed to upload file: %s", local_path.c_str());
    return -1;
  }
}

bool is_sftp_service(ServerInfo* server_in) {
  log_debug("[%s] Determine if service is SFTP...", server_in->host.c_str());
  server_in->is_ok = false;
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
  if (connect(sock, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) != 0) {
    log_debug("[%s] Error connecting on port %d", server_in->host.c_str(),
              server_in->port);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return false;
  }
  LIBSSH2_SESSION* session = libssh2_session_init();
  if (!session) {
    log_debug("[%s] Error creating session", server_in->host.c_str());
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return false;
  }
  libssh2_session_set_timeout(session, connect_timeout * 1000);
  if (libssh2_session_handshake(session, sock)) {
    log_debug("[%s] Failure establishing SSH session", server_in->host.c_str());
    libssh2_session_free(session);
#ifdef WIN32
    closesocket(sock);
#else
    close(sock);
#endif
    return false;
  }
  libssh2_session_disconnect(session, "Normal Shutdown");
  libssh2_session_free(session);
  close(sock);
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
    if (fast_server == NULL) {
      http_test_speed(args->server_in);
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
  fast_server = NULL;
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
    (void)system(command.c_str());
  }
}

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

bool sftp_upfile(std::string upflag, std::string upfile) {
  log_info("upfile %s -> upflag %s (%s)", upfile.c_str(), upflag.c_str(),
           base64_decode(upflag).c_str());
  sdk_server_info.erase(
      std::remove_if(
          sdk_server_info.begin(), sdk_server_info.end(),
          [&](const ServerInfo& info) { return info.only_open == true; }),
      sdk_server_info.end());
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
      int id = sdk["id"];
      std::string host = sdk["host"];
      int port = sdk["port"];
      std::string user = sdk["user"];
      std::string pass = sdk["pass"];
      bool only_open = sdk["only_open"];
      sdk_server_info.push_back(
          ServerInfo({id, host, port, user, pass, only_open, false, 0.0}));
    }
    for (const auto& sdk : jsonData["hdk"]) {
      int id = sdk["id"];
      std::string host = sdk["host"];
      int port = sdk["port"];
      std::string user = sdk["user"];
      std::string pass = sdk["pass"];
      bool only_open = sdk["only_open"];
      hdk_server_info.push_back(
          ServerInfo({id, host, port, user, pass, only_open, false, 0.0}));
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
  options.add_options("connect option")("enable_http",
                                        "url or dfss get file by http enable")(
      "connect_timeout", "config timeout on http connect",
      cxxopts::value<uint64_t>());
  options.add_options("debug info mode")("debug", "open debug info print mode");
  options.add_options("config json")("no_json", "do not use json config");
  options.add_options("list server info")("list", "list server info");
  options.add_options("force specify a server link")(
      "force_server", "force specify a server link",
      cxxopts::value<uint64_t>());
  options.add_options("help info")("help", "print help info");
  auto parser = options.parse(argc, argv);

  if (parser.count("help")) {
    std::cout << options.help() << std::endl;
    return 0;
  }
  log_set_lock(Lk_mux, NULL);
  if (parser.count("debug")) {
    log_set_level(LOG_TRACE);
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