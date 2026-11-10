#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
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

#ifdef _WIN32
// replace_file 需要 MoveFileExA；windows.h 有 include guard，重复包含无副作用。
#include <windows.h>
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

// 下载/上传会话的 libssh2 超时（秒）。配置键 connect_timeout，默认 60。
static uint64_t connect_timeout = 60;
// 单台服务器探测（TCP 连接 + 握手 + 认证 + sftp_init）的时间上界（秒）。
// 配置键 probe_timeout，默认 5。命令行 --probe_timeout 可覆盖。
static uint64_t probe_timeout = 5;
// 失败切换的最大轮数：一轮 = 完整探测一次 + 依次尝试候选列表。
static const int kMaxRounds = 3;
// 测速上限：2s 或 8MiB，先到者为准；任一服务器达到 4MiB/s 即提前结束。
static const long long kSpeedTestMaxMs = 2000;
static const uint64_t kSpeedTestMaxBytes = 8ULL * 1024 * 1024;
static const double kSpeedTestFastEnough = 4.0 * 1024 * 1024;
// --dflag 会把索引文件读进内存，超过这个长度直接判定失败
static const uint64_t kMaxBufferDownload = 4ULL * 1024 * 1024;
// --no_resume：忽略已有的 part/meta，强制从 0 开始
static bool no_resume = false;

static int ret_flag = 0;

// SIGINT/SIGTERM 置位后跳出下载循环：保留 part/meta 供续传，不再切换服务器。
static volatile sig_atomic_t g_interrupted = 0;
static void on_terminate_signal(int) { g_interrupted = 1; }

pthread_mutex_t log_mtx = PTHREAD_MUTEX_INITIALIZER;
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

static long long elapsed_ms_since(std::chrono::steady_clock::time_point begin) {
  return (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - begin)
      .count();
}

// 进度条按固定节奏刷新（至少间隔 kProgressIntervalMs），否则每读一块就写一次，
// 日志会被进度条淹没（续传用例要在日志里找 resume from 行）。
static const long long kProgressIntervalMs = 200;
static long long g_last_progress_ms = -1;

static bool progress_due(long long elapsed_ms, bool force) {
  if (force || g_last_progress_ms < 0 ||
      elapsed_ms - g_last_progress_ms >= kProgressIntervalMs) {
    g_last_progress_ms = elapsed_ms;
    return true;
  }
  return false;
}

// 每次传输开始时重置节流状态：否则失败切换后的新会话要等到超过上一次
// 会话的耗时才会再次刷新进度条。
static void progress_reset() { g_last_progress_ms = -1; }

// 进度条：总量 = 已续传偏移 + 本次会话下载量；速度与 ETA 只按本次会话的字节算，
// 否则续传时会把历史字节算进速度，ETA 失真。
void print_progress(uint64_t session_bytes, uint64_t offset, uint64_t file_size,
                    double elapsed_ms) {
  int bar_width = 20;
  uint64_t total_done = offset + session_bytes;
  double progress = file_size > 0 ? (double)total_done / (double)file_size : 1.0;
  if (progress > 1.0) progress = 1.0;
  int pos = (int)(bar_width * progress);
  double speed =
      elapsed_ms > 0 ? (double)session_bytes * 1000.0 / elapsed_ms : 0.0;
  double remaining_data =
      file_size > total_done ? (double)(file_size - total_done) : 0.0;
  double remaining_time = speed > 0 ? remaining_data / speed : 0.0;  // seconds

  printf("[%s] %3d%% [", file_size_h(total_done).c_str(),
         (int)(progress * 100));
  for (int i = 0; i < bar_width; ++i) {
    if (i < pos)
      printf("=");
    else if (i == pos)
      printf(">");
    else
      printf(" ");
  }
  printf("] %s/s, ETA: %s   \r", file_size_h((uint64_t)speed).c_str(),
         format_duration((int)remaining_time).c_str());
  fflush(stdout);
}

// 按节奏刷新的进度条包装：节流逻辑只影响显示，不影响下载。
static void print_progress_due(uint64_t session_bytes, uint64_t offset,
                               uint64_t file_size, double elapsed_ms,
                               bool force = false) {
  if (!progress_due((long long)elapsed_ms, force)) return;
  print_progress(session_bytes, offset, file_size, elapsed_ms);
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

// ============================ 阶段 A/B：探测 ============================

// 一台服务器的探测结果。ok 且未被取用的 conn 保持打开，供测速与下载复用，
// 免去「探测、测速、下载各握手一次」的三次握手。
struct ProbeEntry {
  ServerInfo server;
  bool ok = false;
  std::string error;        // ok == false 时的失败原因
  long long latency_ms = 0;  // 连接 + 握手（+ 认证 + sftp_init）耗时
  bool speed_tested = false;
  double speed = 0.0;  // Byte/s，测速失败为 0
  std::unique_ptr<SftpConn> conn;
};

// 阶段 A 的工作线程：只做连接，不做测速，必须 join，禁止 pthread_cancel。
static void* probe_worker(void* arg) {
  ProbeEntry* entry = static_cast<ProbeEntry*>(arg);
  auto begin = std::chrono::steady_clock::now();
  // 配置里没有账号的服务器（HDK 列表）没有可认证的凭据，只做连接 + 握手，
  // 与阶段 1 之前 is_sftp_service 的语义一致；配了账号的做完整 open。
  const bool handshake_only =
      entry->server.user.empty() && entry->server.pass.empty();
  std::unique_ptr<SftpConn> conn(new SftpConn());
  std::string err;
  if (conn->open(entry->server, (int)(probe_timeout * 1000), &err,
                 handshake_only)) {
    entry->ok = true;
    entry->latency_ms = elapsed_ms_since(begin);
    entry->conn = std::move(conn);
  } else {
    entry->error = err.empty() ? "unknown error" : err;
  }
  return NULL;
}

// 阶段 B：在已打开的连接上读 /.sophgo_speed，上限 2s 或 8MiB。
// 测速失败只记录，不淘汰服务器（历史 bug：speed 为 0 时整台服务器被丢弃）。
static void probe_speed(ProbeEntry* entry) {
  entry->speed_tested = true;
  entry->speed = 0.0;
  if (!entry->conn) return;
  // 只做握手的条目（HDK 列表没有账号）没有 sftp 子系统，不能测速。
  // 不判空就调 libssh2_sftp_open 只是碰巧被 libssh2 内部的空指针检查兜住，
  // 属于未定义行为；这类服务器保持「未测速」，表格里 speed 列显示 '-'，
  // 排名按 latency 排。
  if (entry->conn->sftp() == nullptr) {
    entry->speed_tested = false;
    log_debug("[%s:%d] handshake-only connection, skip speed test",
              entry->server.host.c_str(), entry->server.port);
    return;
  }
  const std::string host = entry->server.host;
  log_info("speed test server %s:%d ...", host.c_str(), entry->server.port);
  // 测速阶段的读写上界收紧到 2s；测速结束（或失败）后由下载路径改回
  // connect_timeout。
  entry->conn->set_io_timeout((int)kSpeedTestMaxMs);
  SftpFileHandle handle(libssh2_sftp_open(entry->conn->sftp(), "/.sophgo_speed",
                                          LIBSSH2_FXF_READ, 0));
  if (!handle) {
    log_warn("speed test on %s:%d failed: cannot open /.sophgo_speed (errno %d);"
             " server kept as candidate",
             host.c_str(), entry->server.port,
             libssh2_sftp_last_error(entry->conn->sftp()));
    return;
  }

  std::vector<char> buf(64 * 1024);
  uint64_t total_bytes = 0;
  auto begin = std::chrono::steady_clock::now();
  ssize_t n = 0;
  while ((n = libssh2_sftp_read(handle.get(), buf.data(), buf.size())) > 0) {
    total_bytes += (uint64_t)n;
    if (total_bytes >= kSpeedTestMaxBytes) break;
    if (elapsed_ms_since(begin) >= kSpeedTestMaxMs) break;
  }
  long long elapsed_ms = elapsed_ms_since(begin);
  if (n < 0) {
    // 会话可能已经进入错误状态：关掉连接，下载时再重连。
    // 必须先释放文件句柄再关连接：句柄挂在 sftp 会话上，会话释放后再
    // libssh2_sftp_close 就是 use-after-free（会段错误）。
    log_warn("speed test on %s:%d read error (%ld); server kept as candidate",
             host.c_str(), entry->server.port, (long)n);
    handle.reset(nullptr);
    entry->conn->close();
    entry->conn.reset();
    return;
  }
  if (elapsed_ms <= 0) elapsed_ms = 1;
  entry->speed = (double)total_bytes * 1000.0 / (double)elapsed_ms;
  log_info("server %s:%d speed %s/s (%llu bytes in %lldms)", host.c_str(),
           entry->server.port, file_size_h((uint64_t)entry->speed).c_str(),
           (unsigned long long)total_bytes, elapsed_ms);
}

// 排名：已测到速度的按速度降序在前；测速失败或未测速的按 latency 升序在后。
//
// 两个刻意的实现选择，都是为了二进制体积（armbi 是体积最紧的架构，
// stdout_filter 上每多 10KB 就会顶破 v1.10.10 的上限）：
//   1. 排的是下标而不是 ProbeEntry：ProbeEntry 带 std::string 和 unique_ptr，
//      直接排序会实例化一整套 swap/merge/rotate 模板。
//   2. 手写插入排序而不是 std::stable_sort：服务器数量是个位数到几十，
//      插入排序足够，且天然稳定，不引入任何模板实例。
static bool candidate_ranks_before(const ProbeEntry& a, const ProbeEntry& b) {
  const bool a_has = a.speed_tested && a.speed > 0.0;
  const bool b_has = b.speed_tested && b.speed > 0.0;
  if (a_has != b_has) return a_has;
  if (a_has) return a.speed > b.speed;
  return a.latency_ms < b.latency_ms;
}

static void sort_candidates(std::vector<ProbeEntry>& entries) {
  for (size_t i = 1; i < entries.size(); ++i) {
    // 只在严格优先时前移，「相等不动」等价于 stable_sort
    ProbeEntry moving = std::move(entries[i]);
    size_t j = i;
    while (j > 0 && candidate_ranks_before(moving, entries[j - 1])) {
      entries[j] = std::move(entries[j - 1]);
      --j;
    }
    entries[j] = std::move(moving);
  }
}

// 探测一组服务器，返回候选列表：成功的按排名在前，失败的附在后面（供 --probe
// 展示失败原因）。test_speed 为 false 时只排 latency（--user 登录路径）。
static std::vector<ProbeEntry> probe_servers(
    std::vector<struct ServerInfo>& servers, bool test_speed) {
  std::vector<ProbeEntry> results;
  if (servers.empty()) {
    log_warn("no server configured for probing");
    return results;
  }
  log_info("probing %d server(s) in parallel, probe timeout %llds%s",
           (int)servers.size(), (long long)probe_timeout,
           test_speed ? ", speed test enabled" : "");

  std::vector<ProbeEntry> entries(servers.size());
  for (size_t i = 0; i < servers.size(); ++i) {
    entries[i].server = servers[i];
  }
  std::vector<pthread_t> tids(servers.size());
  std::vector<char> started(servers.size(), 0);
  for (size_t i = 0; i < entries.size(); ++i) {
    if (pthread_create(&tids[i], NULL, probe_worker, &entries[i]) == 0) {
      started[i] = 1;
    } else {
      entries[i].ok = false;
      entries[i].error = "cannot create probe thread";
    }
  }
  // 全部 join：没有 pthread_cancel，也没有 sleep(1) 的启动 barrier
  for (size_t i = 0; i < entries.size(); ++i) {
    if (started[i]) pthread_join(tids[i], NULL);
  }

  std::vector<ProbeEntry> ok_entries;
  std::vector<ProbeEntry> failed_entries;
  for (auto& entry : entries) {
    if (!entry.ok) {
      log_warn("server %s:%d unreachable: %s", entry.server.host.c_str(),
               entry.server.port, entry.error.c_str());
    }
    if (entry.ok)
      ok_entries.push_back(std::move(entry));
    else
      failed_entries.push_back(std::move(entry));
  }

  if (test_speed && !ok_entries.empty()) {
    // 按 latency 升序逐台串行测速；有一台够快就停
    std::vector<size_t> by_latency(ok_entries.size());
    for (size_t i = 0; i < ok_entries.size(); ++i) by_latency[i] = i;
    std::stable_sort(by_latency.begin(), by_latency.end(),
                     [&](size_t a, size_t b) {
                       return ok_entries[a].latency_ms <
                              ok_entries[b].latency_ms;
                     });
    for (size_t idx : by_latency) {
      if (g_interrupted) break;
      probe_speed(&ok_entries[idx]);
      if (ok_entries[idx].speed >= kSpeedTestFastEnough) {
        log_info("server %s:%d reaches %s/s, skip remaining speed tests",
                 ok_entries[idx].server.host.c_str(),
                 ok_entries[idx].server.port,
                 file_size_h((uint64_t)ok_entries[idx].speed).c_str());
        break;
      }
    }
  }

  sort_candidates(ok_entries);

  int rank = 0;
  for (auto& entry : ok_entries) {
    ++rank;
    log_info("candidate #%d: %s:%d latency %lldms%s%s", rank,
             entry.server.host.c_str(), entry.server.port, entry.latency_ms,
             entry.speed_tested ? ", speed " : "",
             entry.speed_tested
                 ? file_size_h((uint64_t)entry.speed).c_str()
                 : "");
    results.push_back(std::move(entry));
  }
  for (auto& entry : failed_entries) {
    results.push_back(std::move(entry));
  }
  return results;
}

// 取一个可用于数据传输的连接：优先复用探测时已经握手的连接，
// 探测连接不可用（例如测速时读出错已关闭）时重连一次。
static std::unique_ptr<SftpConn> acquire_conn(ProbeEntry& entry,
                                              std::string* err) {
  if (entry.conn) {
    entry.conn->set_io_timeout((int)(connect_timeout * 1000));
    return std::move(entry.conn);
  }
  std::unique_ptr<SftpConn> conn(new SftpConn());
  if (!conn->open(entry.server, (int)(connect_timeout * 1000), err)) {
    return nullptr;
  }
  return conn;
}

// ============================ 断点续传 ============================

struct RemoteStat {
  uint64_t size = 0;
  long long mtime = 0;
};

// 续传元数据：<文件名>.dfss.meta，内容 {"v":1,"remote_path":...,"size":...,"mtime":...}
struct ResumeMeta {
  std::string remote_path;
  uint64_t size = 0;
  long long mtime = 0;
};

static bool remote_stat(SftpConn& conn, const std::string& path, RemoteStat* out,
                        std::string* err) {
  LIBSSH2_SFTP_ATTRIBUTES attrs;
  memset(&attrs, 0, sizeof(attrs));
  if (libssh2_sftp_stat(conn.sftp(), path.c_str(), &attrs) != 0) {
    if (err) {
      *err = "stat failed (errno " +
             std::to_string((int)libssh2_sftp_last_error(conn.sftp())) + ")";
    }
    return false;
  }
  if ((attrs.flags & LIBSSH2_SFTP_ATTR_SIZE) == 0) {
    if (err) *err = "stat did not report file size";
    return false;
  }
  out->size = (uint64_t)attrs.filesize;
  out->mtime = (attrs.flags & LIBSSH2_SFTP_ATTR_ACMODTIME)
                   ? (long long)attrs.mtime
                   : 0LL;
  return true;
}

static bool read_meta(const std::string& meta_path, ResumeMeta* out) {
  std::ifstream in(meta_path, std::ios::binary);
  if (!in.is_open()) return false;
  try {
    json j;
    in >> j;
    if (!j.is_object()) return false;
    if (j.value("v", 0) != 1) return false;
    out->remote_path = j.value("remote_path", std::string());
    out->size = j.value("size", (uint64_t)0);
    out->mtime = j.value("mtime", (long long)0);
    return !out->remote_path.empty();
  } catch (const std::exception&) {
    return false;
  }
}

// meta 的格式是固定的三个标量字段，手写比走 nlohmann 的 serializer 便宜得多
// （nlohmann 的 dump 在 armbi 上要占约 4.5KB，而 armbi 的二进制体积上限很紧）。
// remote_path 里可能含引号或反斜杠，这里按 JSON 规则转义。
static std::string json_escape(const std::string& in) {
  std::string out;
  out.reserve(in.size() + 8);
  for (char c : in) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if ((unsigned char)c < 0x20) {
          char buf[8];
          snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)c);
          out += buf;
        } else {
          out += c;
        }
    }
  }
  return out;
}

static bool write_meta(const std::string& meta_path, const ResumeMeta& meta) {
  // 必须用可变长拼接，不能 snprintf 进定长缓冲区：模型文件的 remote_path 可长
  // 达 129 字符（/.dfss_flags 里 88 条目有 37 条超过 68 字符），定长缓冲会截断
  // 出非法 JSON，下次 read_meta 解析失败就退化成从 0 重下——而需要续传的恰恰
  // 是这些 20GB 级的大模型文件。
  std::string body;
  body.reserve(meta.remote_path.size() + 96);
  body += "{\"v\":1,\"remote_path\":\"";
  body += json_escape(meta.remote_path);
  body += "\",\"size\":";
  body += std::to_string((unsigned long long)meta.size);
  body += ",\"mtime\":";
  body += std::to_string(meta.mtime);
  body += "}";
  std::ofstream out(meta_path, std::ios::binary | std::ios::trunc);
  if (!out.is_open()) return false;
  out << body;
  out.flush();
  return out.good();
}

static bool fs_file_size(const std::string& path, uint64_t* size) {
  std::error_code ec;
  if (!fs::is_regular_file(path, ec) || ec) return false;
  uintmax_t sz = fs::file_size(path, ec);
  if (ec) return false;
  *size = (uint64_t)sz;
  return true;
}

// 把 part 重命名为最终文件；目标已存在时必须覆盖。
// Windows 下 fs::rename 不会覆盖已存在的目标，用 MoveFileExA。
static bool replace_file(const std::string& from, const std::string& to) {
#ifdef _WIN32
  if (MoveFileExA(from.c_str(), to.c_str(), MOVEFILE_REPLACE_EXISTING)) {
    return true;
  }
  log_error("replace %s -> %s failed (GetLastError=%lu)", from.c_str(),
            to.c_str(), (unsigned long)GetLastError());
  return false;
#else
  std::error_code ec;
  fs::rename(from, to, ec);
  if (ec) {
    log_error("rename %s -> %s failed: %s", from.c_str(), to.c_str(),
              ec.message().c_str());
    return false;
  }
  return true;
#endif
}

// 在已打开的连接上下载 path 到本地，支持续传与失败保留。
//
// 续传判定：part 与 meta 都存在，remote_path、size、mtime 三者完全一致，
// 且 part 大小 <= size，则从 part 大小处续传；其它情况一律截断 part 从 0 开始
// 并重写 meta。因为各镜像上同名文件的 size/mtime 一致，同一套条件也覆盖
// 「换服务器续传」。
//
// 返回值：true 表示最终文件已经就位；false 表示失败（part/meta 保留）。
static bool download_file(SftpConn& conn, const std::string& path) {
  const std::string file_name = getFileNameFromPath(path);
  if (file_name.empty()) {
    log_error("invalid remote path: %s", path.c_str());
    return false;
  }
  const std::string final_path = file_name;
  const std::string part_path = file_name + ".dfss.part";
  const std::string meta_path = file_name + ".dfss.meta";

  conn.set_io_timeout((int)(connect_timeout * 1000));

  RemoteStat stat;
  std::string err;
  if (!remote_stat(conn, path, &stat, &err)) {
    log_error("stat %s failed: %s", path.c_str(), err.c_str());
    return false;
  }
  log_info("remote %s size %llu mtime %lld", path.c_str(),
           (unsigned long long)stat.size, stat.mtime);

  // ---- 续传判定 ----
  uint64_t offset = 0;
  uint64_t part_size = 0;
  bool have_part = fs_file_size(part_path, &part_size);
  if (no_resume) {
    if (have_part) log_info("--no_resume: discard %s, restart from 0", part_path.c_str());
  } else if (have_part) {
    ResumeMeta old_meta;
    if (!read_meta(meta_path, &old_meta)) {
      log_info("no valid meta for %s, restart from 0", part_path.c_str());
    } else if (old_meta.remote_path != path) {
      log_info("meta remote_path mismatch (%s != %s), restart from 0",
               old_meta.remote_path.c_str(), path.c_str());
    } else if (old_meta.size != stat.size || old_meta.mtime != stat.mtime) {
      log_info("meta size/mtime mismatch (meta %llu/%lld, remote %llu/%lld), "
               "restart from 0",
               (unsigned long long)old_meta.size, old_meta.mtime,
               (unsigned long long)stat.size, stat.mtime);
    } else if (part_size > stat.size) {
      log_info("part size %llu > remote size %llu, restart from 0",
               (unsigned long long)part_size,
               (unsigned long long)stat.size);
    } else {
      offset = part_size;
    }
  }

  // 从 0 开始时先把残留的 part 清掉，再写 meta：顺序反过来会出现「meta 已是新
  // 版本、part 还是旧的」这种自相矛盾的组合，续传判断会把它当成可续传。
  if (offset == 0 && have_part) {
    std::error_code ec;
    fs::remove(part_path, ec);
  }

  ResumeMeta meta;
  meta.remote_path = path;
  meta.size = stat.size;
  meta.mtime = stat.mtime;
  if (!write_meta(meta_path, meta)) {
    log_error("cannot write meta file %s", meta_path.c_str());
    return false;
  }

  if (offset > 0) {
    log_info("resume from %llu/%llu", (unsigned long long)offset,
             (unsigned long long)stat.size);
  } else {
    log_info("download from 0/%llu", (unsigned long long)stat.size);
  }

  // part 已经等于远端大小：只差改名（上一次下载完成但没来得及 rename）
  if (offset == stat.size && offset > 0) {
    log_info("part file %s already complete", part_path.c_str());
    if (!replace_file(part_path, final_path)) return false;
    std::error_code ec;
    fs::remove(meta_path, ec);
    log_info("Download completed.");
    return true;
  }

  // ---- 打开远端文件并定位 ----
  SftpFileHandle handle(
      libssh2_sftp_open(conn.sftp(), path.c_str(), LIBSSH2_FXF_READ, 0));
  if (!handle) {
    log_error("Unable to open file with SFTP: %s (errno %d)", path.c_str(),
              libssh2_sftp_last_error(conn.sftp()));
    return false;
  }
  if (offset > 0) libssh2_sftp_seek64(handle.get(), (libssh2_uint64_t)offset);

  // ---- 打开本地 part（续传用追加，否则截断） ----
  std::ios::openmode mode = std::ios::binary;
  mode |= (offset > 0) ? std::ios::app : std::ios::trunc;
  std::ofstream local_file(part_path, mode);
  if (!local_file.is_open()) {
    log_error("Failed to open file for writing: %s", part_path.c_str());
    return false;
  }

  auto begin = std::chrono::steady_clock::now();
  progress_reset();
  uint64_t session_bytes = 0;
  std::vector<char> read_buf(1024 * 128);
  ssize_t n = 0;
  while ((n = libssh2_sftp_read(handle.get(), read_buf.data(),
                                read_buf.size())) > 0) {
    session_bytes += (uint64_t)n;
    local_file.write(read_buf.data(), n);
    if (!local_file.good()) {
      log_error("Failed to write local file: %s", part_path.c_str());
      local_file.close();
      return false;
    }
    print_progress_due(session_bytes, offset, stat.size,
                       (double)elapsed_ms_since(begin));
    if (g_interrupted) {
      log_warn("interrupted, keep %s (%llu/%llu) for resume",
               part_path.c_str(),
               (unsigned long long)(offset + session_bytes),
               (unsigned long long)stat.size);
      local_file.close();
      return false;
    }
  }
  print_progress_due(session_bytes, offset, stat.size,
                     (double)elapsed_ms_since(begin), true);
  cout << "" << endl;

  if (n < 0) {
    // libssh2_sftp_read 返回负值是错误；读到 0 才是 EOF
    log_error("SFTP read error on %s: %ld (keep %s for resume)", path.c_str(),
              (long)n, part_path.c_str());
    local_file.close();
    return false;
  }
  local_file.close();
  if (!local_file) {
    log_error("Failed to flush local file: %s", part_path.c_str());
    return false;
  }
  handle.reset(nullptr);

  const uint64_t total_downloaded = offset + session_bytes;
  if (total_downloaded != stat.size) {
    log_error("Failed to download file %s: got %llu of %llu bytes", path.c_str(),
              (unsigned long long)total_downloaded,
              (unsigned long long)stat.size);
    return false;
  }

  // ---- 校验通过：rename 成最终文件（覆盖同名文件），再删 meta ----
  // 先 rename 后删 meta（设计里写的是「删 meta，再 rename」）：两者顺序对成功
  // 路径没有区别，但 rename 失败时保留 meta 才符合「失败时保留 part 和 meta」——
  // 否则 part 没有 meta 就再也续传不了。
  if (!replace_file(part_path, final_path)) return false;
  std::error_code ec;
  fs::remove(meta_path, ec);
  log_info("Download completed: %s (%llu bytes)", final_path.c_str(),
           (unsigned long long)total_downloaded);
  log_debug("get file %s ok", path.c_str());
  return true;
}

// 把远端文件读进内存（用于 .dfss_flags 索引）。不做续传。
static bool download_to_buffer(SftpConn& conn, const std::string& path,
                               std::string* out) {
  conn.set_io_timeout((int)(connect_timeout * 1000));
  SftpFileHandle handle(
      libssh2_sftp_open(conn.sftp(), path.c_str(), LIBSSH2_FXF_READ, 0));
  if (!handle) {
    log_error("Unable to open file with SFTP: %s (errno %d)", path.c_str(),
              libssh2_sftp_last_error(conn.sftp()));
    return false;
  }
  std::ostringstream oss;
  std::vector<char> read_buf(1024 * 128);
  uint64_t total = 0;
  ssize_t n = 0;
  while ((n = libssh2_sftp_read(handle.get(), read_buf.data(),
                                read_buf.size())) > 0) {
    total += (uint64_t)n;
    if (total > kMaxBufferDownload) {
      log_error("get file to buf, size bigger %llu",
                (unsigned long long)kMaxBufferDownload);
      return false;
    }
    oss.write(read_buf.data(), n);
  }
  if (n < 0) {
    log_error("SFTP read error on %s: %ld", path.c_str(), (long)n);
    return false;
  }
  *out = oss.str();
  return true;
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

// 在指定服务器上上传文件（上传不做续传）。
// 注意：上传使用独立的 customerUploadAccount 凭据，与探测连接（open/oponIn）
// 的认证身份不同，因此不能复用探测连接，必须重新握手登录。
static bool sftp_put_file(const ServerInfo& server, string local_path,
                          string re_path) {
  string file_name = getFileNameFromPath(local_path.c_str());
  string cur_time = get_current_time();
  string remote_path =
      re_path + string("/") + cur_time + string("_") + file_name;

  log_info("sftp put file from %s -> sftp://%s:%d/%s", file_name.c_str(),
           server.host.c_str(), server.port, remote_path.c_str());

  std::string err;
  SftpConn conn;
  if (!conn.open(server, (int)(connect_timeout * 1000), &err)) {
    log_error("sftp put file failed: %s", err.c_str());
    return false;
  }

  SftpFileHandle handle(libssh2_sftp_open(
      conn.sftp(), remote_path.c_str(),
      LIBSSH2_FXF_WRITE | LIBSSH2_FXF_CREAT | LIBSSH2_FXF_TRUNC,
      LIBSSH2_SFTP_S_IRUSR | LIBSSH2_SFTP_S_IWUSR | LIBSSH2_SFTP_S_IRGRP |
          LIBSSH2_SFTP_S_IROTH));
  if (!handle) {
    log_error("Unable to open file with SFTP: %s (errno %d)",
              remote_path.c_str(), libssh2_sftp_last_error(conn.sftp()));
    return false;
  }

  int64_t file_size = get_file_size(local_path);
  std::ifstream local_file(local_path, std::ios::binary);
  if (!local_file.is_open() || file_size < 0) {
    log_error("Failed to open local file for reading: %s", local_path.c_str());
    return false;
  }

  auto begin = std::chrono::steady_clock::now();
  progress_reset();
  int64_t total_upload = 0;
  std::vector<char> write_buf(1024 * 128);
  while (local_file.read(write_buf.data(), write_buf.size()) ||
         local_file.gcount() > 0) {
    ssize_t bytes_read = (ssize_t)local_file.gcount();
    if (local_file.bad()) {
      log_error("Read error on i/o operation.");
      return false;
    }
    ssize_t bytes_written = 0;
    while (bytes_written < bytes_read) {
      ssize_t n = libssh2_sftp_write(handle.get(),
                                     write_buf.data() + bytes_written,
                                     (size_t)(bytes_read - bytes_written));
      if (n < 0) {
        log_error("SFTP write error: %ld", (long)n);
        return false;
      }
      bytes_written += n;
    }
    total_upload += bytes_written;
    print_progress_due((uint64_t)total_upload, 0, (uint64_t)file_size,
                       (double)elapsed_ms_since(begin));
    if (g_interrupted) {
      log_warn("interrupted during upload");
      return false;
    }
  }
  print_progress_due((uint64_t)total_upload, 0, (uint64_t)file_size,
                     (double)elapsed_ms_since(begin), true);
  cout << "" << endl;
  handle.reset(nullptr);

  if (total_upload != file_size) {
    log_error("Failed to upload file: %s", local_path.c_str());
    return false;
  }
  log_info("Upload completed.");
  log_debug("put file %s ok", local_path.c_str());
  return true;
}

// ============================ 下载编排 ============================

// 按候选列表顺序下载一个远端文件：任何错误都切到下一台并从已下载偏移续传；
// 列表用尽后重新完整探测一轮，最多 kMaxRounds 轮。
static bool download_with_failover(const std::string& remote_path) {
  for (int round = 1; round <= kMaxRounds; ++round) {
    if (g_interrupted) break;
    if (round > 1) log_info("download round %d/%d, re-probing", round, kMaxRounds);
    std::vector<ProbeEntry> candidates = probe_servers(sdk_server_info, true);
    bool any_ok = false;
    for (auto& entry : candidates) {
      if (!entry.ok) continue;
      any_ok = true;
      if (g_interrupted) break;
      std::string err;
      std::unique_ptr<SftpConn> conn = acquire_conn(entry, &err);
      if (!conn) {
        log_warn("connect %s:%d for download failed: %s, switching to next "
                 "server",
                 entry.server.host.c_str(), entry.server.port, err.c_str());
        continue;
      }
      log_info("downloading %s from %s:%d", remote_path.c_str(),
               entry.server.host.c_str(), entry.server.port);
      if (download_file(*conn, remote_path)) return true;
      if (g_interrupted) break;
      log_warn("download from %s:%d failed, switching to next server",
               entry.server.host.c_str(), entry.server.port);
    }
    if (g_interrupted) break;
    if (!any_ok) {
      log_error("no candidate server available in round %d/%d", round,
                kMaxRounds);
    }
  }
  return false;
}

// --dflag：先从候选服务器取索引（内存，不续传），再按候选顺序下载目标文件。
// 取到索引的那台服务器把连接交接出来，继续用它下载目标文件，不再二次握手
// （与「首选直接复用探测连接」保持一致）。
static bool download_dflag(const std::string& dflag) {
  for (int round = 1; round <= kMaxRounds; ++round) {
    if (g_interrupted) break;
    if (round > 1) log_info("dflag round %d/%d, re-probing", round, kMaxRounds);
    std::vector<ProbeEntry> candidates = probe_servers(sdk_server_info, true);

    // ---- 取索引 ----
    std::string json_buf;
    bool got_index = false;
    std::unique_ptr<SftpConn> index_conn;  // 取到索引的那个连接，稍后复用
    size_t index_entry = 0;
    for (size_t i = 0; i < candidates.size(); ++i) {
      ProbeEntry& entry = candidates[i];
      if (!entry.ok) continue;
      std::string err;
      std::unique_ptr<SftpConn> conn = acquire_conn(entry, &err);
      if (!conn) {
        log_warn("connect %s:%d for index failed: %s, switching to next server",
                 entry.server.host.c_str(), entry.server.port, err.c_str());
        continue;
      }
      if (download_to_buffer(*conn, "/.dfss_flags", &json_buf)) {
        got_index = true;
        index_entry = i;
        index_conn = std::move(conn);
        break;
      }
      conn->close();
      log_warn("get /.dfss_flags from %s:%d failed, switching to next server",
               entry.server.host.c_str(), entry.server.port);
    }
    if (!got_index) {
      log_error("cannot fetch /.dfss_flags in round %d/%d", round, kMaxRounds);
      continue;
    }

    // ---- 解析 ----
    std::string file_path;
    try {
      json j = json::parse(json_buf);
      if (!j.contains(dflag) || j[dflag].is_null() ||
          !j[dflag].contains("filepath")) {
        log_error("dflag '%s' not found in index", dflag.c_str());
        return false;  // 索引里没有这个 flag：重试没有意义
      }
      file_path = j[dflag.c_str()]["filepath"].get<std::string>();
      log_info("from dflag %s get file %s", dflag.c_str(), file_path.c_str());
    } catch (const json::exception& e) {
      log_error("JSON error: %s", e.what());
      return false;
    }

    // ---- 下载目标文件：先试刚取过索引的那台（连接已在手），再按排名试其余 ----
    for (size_t i = 0; i < candidates.size(); ++i) {
      ProbeEntry& entry = candidates[i];
      if (!entry.ok) continue;
      if (g_interrupted) break;
      std::unique_ptr<SftpConn> conn;
      if (i == index_entry && index_conn) {
        conn = std::move(index_conn);  // 复用，不再握手
      } else {
        std::string err;
        conn = acquire_conn(entry, &err);
        if (!conn) {
          log_warn("connect %s:%d for download failed: %s, switching to next "
                   "server",
                   entry.server.host.c_str(), entry.server.port, err.c_str());
          continue;
        }
      }
      log_info("downloading %s from %s:%d", file_path.c_str(),
               entry.server.host.c_str(), entry.server.port);
      if (download_file(*conn, file_path)) return true;
      if (g_interrupted) break;
      log_warn("download from %s:%d failed, switching to next server",
               entry.server.host.c_str(), entry.server.port);
    }
    if (g_interrupted) break;
  }
  return false;
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
  struct ServerInfo* login_info = nullptr;
  std::vector<ProbeEntry> candidates;
  if (starts_with(username, "sophgo") || starts_with(username, "h_s")) {
    log_info("%s sftp login hdk server", username.c_str());
    hdk_server_info.erase(
        std::remove_if(
            hdk_server_info.begin(), hdk_server_info.end(),
            [&](const ServerInfo& info) { return info.only_open == true; }),
        hdk_server_info.end());
    // 登录只需要一台可达的服务器：不测速，只按 latency 排序
    candidates = probe_servers(hdk_server_info, false);
  } else {
    log_info("%s sftp login sdk server", username.c_str());
    sdk_server_info.erase(
        std::remove_if(
            sdk_server_info.begin(), sdk_server_info.end(),
            [&](const ServerInfo& info) { return info.only_open == true; }),
        sdk_server_info.end());
    candidates = probe_servers(sdk_server_info, false);
  }
  for (auto& entry : candidates) {
    if (entry.ok) {
      login_info = &entry.server;
      break;
    }
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

// 上传：探测出候选列表后按顺序尝试，失败切下一台（不做续传）。
bool sftp_upfile(std::string upflag, std::string upfile) {
  log_info("upfile %s -> upflag %s (%s)", upfile.c_str(), upflag.c_str(),
           base64_decode(upflag).c_str());
  sdk_server_info.erase(
      std::remove_if(
          sdk_server_info.begin(), sdk_server_info.end(),
          [&](const ServerInfo& info) { return info.only_open == true; }),
      sdk_server_info.end());

  const char* upload_user = getenv("DFSS_UPLOAD_USER");
  const char* upload_pass = getenv("DFSS_UPLOAD_PASS");
  const std::string remote_dir = base64_decode(upflag);

  for (int round = 1; round <= kMaxRounds; ++round) {
    if (g_interrupted) break;
    if (round > 1) log_info("upload round %d/%d, re-probing", round, kMaxRounds);
    std::vector<ProbeEntry> candidates = probe_servers(sdk_server_info, true);
    for (auto& entry : candidates) {
      if (!entry.ok || g_interrupted) continue;
      // 上传用独立的上传账号，不复用探测连接
      ServerInfo upload_server = entry.server;
      upload_server.user = upload_user ? upload_user : "customerUploadAccount";
      upload_server.pass = upload_pass ? upload_pass : "1QQHJONFflnI2BLsxUvA";
      if (sftp_put_file(upload_server, upfile, remote_dir)) return true;
      if (g_interrupted) break;
      log_warn("upload to %s:%d failed, switching to next server",
               entry.server.host.c_str(), entry.server.port);
    }
  }
  return false;
}

// --probe：对 SDK 和 HDK 两个列表执行阶段 A 和阶段 B，打印表格。
// 至少一台 ok 时返回 true。
static bool run_probe_report() {
  bool any_ok = false;
  struct Report {
    const char* title;
    std::vector<struct ServerInfo>* servers;
  };
  Report reports[2] = {{"SDK", &sdk_server_info}, {"HDK", &hdk_server_info}};

  for (int r = 0; r < 2; ++r) {
    std::vector<ProbeEntry> entries =
        probe_servers(*reports[r].servers, true);
    printf("\n[%s] server probe result\n", reports[r].title);
    printf("%-4s %-5s %-24s %-8s %-10s %-12s %s\n", "rank", "id", "host:port",
           "status", "latency", "speed", "error");
    int rank = 0;
    for (auto& entry : entries) {
      char endpoint[128];
      snprintf(endpoint, sizeof(endpoint), "%s:%d", entry.server.host.c_str(),
               entry.server.port);
      if (entry.ok) {
        ++rank;
        any_ok = true;
        std::string latency = std::to_string(entry.latency_ms) + "ms";
        std::string speed = entry.speed_tested
                                ? file_size_h((uint64_t)entry.speed) + "/s"
                                : std::string("-");
        printf("%-4d %-5d %-24s %-8s %-10s %-12s %s\n", rank, entry.server.id,
               endpoint, "ok", latency.c_str(), speed.c_str(), "");
      } else {
        printf("%-4s %-5d %-24s %-8s %-10s %-12s %s\n", "-", entry.server.id,
               endpoint, "fail", "-", "-", entry.error.c_str());
      }
    }
    if (entries.empty()) {
      printf("(no server configured)\n");
    }
    fflush(stdout);
  }
  return any_ok;
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
      // 缺 key 时保留默认值
      connect_timeout = jsonData.value("connect_timeout", connect_timeout);
      probe_timeout = jsonData.value("probe_timeout", probe_timeout);
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
  log_debug("sftp session timeout: %llds, probe timeout: %llds",
            (long long)connect_timeout, (long long)probe_timeout);
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
  options.add_options("probe option")(
      "probe_timeout",
      "per-server probe timeout in seconds (default from config, 5)",
      cxxopts::value<uint64_t>());
  options.add_options("resume option")(
      "no_resume",
      "ignore existing .dfss.part/.dfss.meta and download from 0");
  options.add_options("probe server")(
      "probe",
      "probe all servers (connectivity + speed) and print the ranking table");
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

  // Ctrl-C / SIGTERM 时保留 part/meta 供续传，而不是把进程直接打断
  signal(SIGINT, on_terminate_signal);
  signal(SIGTERM, on_terminate_signal);

  if (!parser.count("no_json")) config_json_read();
  if (parser.count("connect_timeout")) {
    connect_timeout = parser["connect_timeout"].as<uint64_t>();
    if (connect_timeout == 0) {
      log_warn("connect_timeout=0 is invalid, fallback to 60s");
      connect_timeout = 60;
    }
    log_info("config sftp session timeout %llds", (long long)connect_timeout);
  }
  if (parser.count("probe_timeout")) {
    probe_timeout = parser["probe_timeout"].as<uint64_t>();
    if (probe_timeout == 0) {
      log_warn("probe_timeout=0 is invalid, fallback to 5s");
      probe_timeout = 5;
    }
    log_info("config probe timeout %llds", (long long)probe_timeout);
  }
  if (parser.count("no_resume")) no_resume = true;

  ret_flag = 0;
  if (parser.count("force_server")) {
    uint64_t force_server_id = parser["force_server"].as<uint64_t>();
    remove_some_server_info(sdk_server_info, false, force_server_id);
    remove_some_server_info(hdk_server_info, false, force_server_id);
  }
  do {
    if (parser.count("probe")) {
      ret_flag = run_probe_report() ? 0 : -1;
      if (ret_flag != 0) log_error("no reachable server found");
      break;
    } else if (parser.count("url")) {
      std::string url = parser["url"].as<std::string>();
      if (starts_with(url, "open@sophgo.com:")) {
        std::string file_path = url.substr(strlen("open@sophgo.com:"));
        ret_flag = download_with_failover(file_path) ? 0 : -1;
        if (ret_flag != 0) {
          if (g_interrupted)
            log_error("Interrupted, run again to resume");
          else
            log_error("Cannot download %s from open@sophgo.com",
                      file_path.c_str());
        }
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
      ret_flag = download_dflag(dflag) ? 0 : -1;
      if (ret_flag != 0) log_error("dflag error");
      break;
    } else if (parser.count("upflag") && parser.count("upfile")) {
      std::string upflag = parser["upflag"].as<std::string>();
      std::string upfile = parser["upfile"].as<std::string>();
      log_info("upflag: %s, upfile: %s", upflag.c_str(), upfile.c_str());
      ret_flag = sftp_upfile(upflag, upfile) ? 0 : -1;
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
