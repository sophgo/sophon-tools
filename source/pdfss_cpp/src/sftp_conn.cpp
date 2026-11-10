#include "sftp_conn.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
// windows.h 必须在 winsock2.h 之后
#include <windows.h>
#else
#include <arpa/inet.h>
#include <arpa/nameser.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <resolv.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include <chrono>
#include <string>
#include <vector>
#include <utility>
#ifndef _WIN32
#include <fstream>
#include <sstream>
#include <strings.h>
#endif

extern "C" {
#include "log.h"
}

void dfss_close_socket(long long sock) {
#ifdef _WIN32
  if (sock == (long long)INVALID_SOCKET) return;
  closesocket((SOCKET)sock);
#else
  if (sock < 0) return;
  close((int)sock);
#endif
}

namespace {

#ifdef _WIN32
// Windows 的 SOCKET 是 UINT_PTR（64 位上 8 字节），不能用 int/store 判空；
// 这里统一用 SOCKET 类型持有，避免 -1 与 INVALID_SOCKET 的溢出告警。
typedef SOCKET socket_t;
const socket_t kInvalidSocket = INVALID_SOCKET;
#else
typedef int socket_t;
const socket_t kInvalidSocket = -1;
#endif

// sock_ 的「无效」哨兵：统一用 long long 表示，屏蔽 Windows SOCKET 的宽度差异。
const long long kInvalidSocketLong = (long long)kInvalidSocket;

int last_socket_error() {
#ifdef _WIN32
  return WSAGetLastError();
#else
  return errno;
#endif
}

// 连接进行中（非阻塞 connect 的正常返回）
bool is_in_progress(int err) {
#ifdef _WIN32
  return err == WSAEWOULDBLOCK || err == WSAEINPROGRESS;
#else
  return err == EINPROGRESS || err == EWOULDBLOCK;
#endif
}

std::string socket_error_string(int err) {
#ifdef _WIN32
  char buf[256] = {0};
  FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                 NULL, (DWORD)err, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
                 buf, sizeof(buf) - 1, NULL);
  std::string s(buf);
  while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
  if (s.empty()) return "wsa error " + std::to_string(err);
  return s + " (" + std::to_string(err) + ")";
#else
  return std::string(strerror(err)) + " (" + std::to_string(err) + ")";
#endif
}

bool set_nonblocking(socket_t sock, bool nonblocking, int* err_out) {
#ifdef _WIN32
  u_long mode = nonblocking ? 1 : 0;
  if (ioctlsocket(sock, FIONBIO, &mode) != 0) {
    if (err_out) *err_out = WSAGetLastError();
    return false;
  }
  return true;
#else
  int flags = fcntl(sock, F_GETFL, 0);
  if (flags < 0) {
    if (err_out) *err_out = errno;
    return false;
  }
  if (nonblocking)
    flags |= O_NONBLOCK;
  else
    flags &= ~O_NONBLOCK;
  if (fcntl(sock, F_SETFL, flags) < 0) {
    if (err_out) *err_out = errno;
    return false;
  }
  return true;
#endif
}

// 连接成功后设置收发超时（原 config_socket_timeout 的等价实现）
void config_socket_timeout(socket_t sock, int timeout_ms) {
#ifdef _WIN32
  DWORD tv = (DWORD)timeout_ms;
  setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#else
  struct timeval tv;
  tv.tv_sec = timeout_ms / 1000;
  tv.tv_usec = (timeout_ms % 1000) * 1000;
  setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#endif
}

// 非阻塞 connect + select 等待超时。成功返回 true，timeout 时为 "timed out"。
bool connect_with_timeout(socket_t sock, const struct sockaddr* addr,
                          socklen_t addr_len, int timeout_ms,
                          std::string* err) {
  int sock_err = 0;
  if (!set_nonblocking(sock, true, &sock_err)) {
    if (err) *err = "cannot set socket non-blocking: " + socket_error_string(sock_err);
    return false;
  }

  int rc = connect(sock, addr, addr_len);
  if (rc != 0) {
    int cerr = last_socket_error();
    if (!is_in_progress(cerr)) {
      if (err) *err = "connect failed: " + socket_error_string(cerr);
      return false;
    }
    // 连接进行中：用 select 等待可写（或异常）
    fd_set wfds, efds;
    FD_ZERO(&wfds);
    FD_SET(sock, &wfds);
    FD_ZERO(&efds);
    FD_SET(sock, &efds);
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
#ifdef _WIN32
    int sel = select(0, NULL, &wfds, &efds, &tv);
#else
    int sel = select(sock + 1, NULL, &wfds, &efds, &tv);
#endif
    if (sel == 0) {
      if (err) *err = "connect timed out";
      return false;
    }
    if (sel < 0) {
      if (err) *err = "select failed: " + socket_error_string(last_socket_error());
      return false;
    }
    // 无论可写还是异常，都用 SO_ERROR 判定最终结果
    int so_error = 0;
    socklen_t so_len = sizeof(so_error);
    if (getsockopt(sock, SOL_SOCKET, SO_ERROR, (char*)&so_error, &so_len) != 0) {
      if (err) *err = "getsockopt failed: " + socket_error_string(last_socket_error());
      return false;
    }
    if (so_error != 0) {
      if (err) *err = "connect failed: " + socket_error_string(so_error);
      return false;
    }
  }

  // 连接成功后恢复阻塞模式，交给 libssh2 做同步收发
  if (!set_nonblocking(sock, false, &sock_err)) {
    if (err) *err = "cannot restore blocking mode: " + socket_error_string(sock_err);
    return false;
  }
  config_socket_timeout(sock, timeout_ms);
  return true;
}

#ifndef _WIN32
// 主机名解析（仅 POSIX）。
//
// 为什么不直接 getaddrinfo：dfss 的 Linux 产物是 `-static` 全静态链接，
// 而 glibc 的 getaddrinfo 依赖运行时动态加载的 NSS 模块（libnss_files/
// libnss_dns）。目标机上的 glibc 版本一旦与构建镜像（Ubuntu 20.04, glibc
// 2.31）不同，静态二进制调用 getaddrinfo 解析任何非纯数字主机名都会
// SIGSEGV（已在 13.24 的 glibc 2.44 上复现）。同理 __nss_configure_lookup
// 与 dlopen 也救不了。
//
// 因此这里自己做：IP 字面量直接 inet_pton，其余走 /etc/hosts + res_query
// （libresolv 可以静态链接，不依赖 NSS）。IPv4 必须可用；DNS 返回的 AAAA
// 记录也一并支持。
bool parse_ip_literal(const std::string& host, struct sockaddr_storage* out,
                      socklen_t* out_len) {
  struct sockaddr_in v4;
  memset(&v4, 0, sizeof(v4));
  v4.sin_family = AF_INET;
  if (inet_pton(AF_INET, host.c_str(), &v4.sin_addr) == 1) {
    memcpy(out, &v4, sizeof(v4));
    *out_len = sizeof(v4);
    return true;
  }
  struct sockaddr_in6 v6;
  memset(&v6, 0, sizeof(v6));
  v6.sin6_family = AF_INET6;
  if (inet_pton(AF_INET6, host.c_str(), &v6.sin6_addr) == 1) {
    memcpy(out, &v6, sizeof(v6));
    *out_len = sizeof(v6);
    return true;
  }
  return false;
}

// 从 /etc/hosts 查（静态二进制下这就是解析 localhost 的唯一途径）
bool lookup_etc_hosts(const std::string& host, std::vector<struct sockaddr_storage>* out,
                      std::vector<socklen_t>* lens) {
  std::ifstream hosts_file("/etc/hosts");
  if (!hosts_file.is_open()) return false;
  std::string line;
  while (std::getline(hosts_file, line)) {
    size_t hash = line.find('#');
    if (hash != std::string::npos) line = line.substr(0, hash);
    std::istringstream iss(line);
    std::string ip;
    if (!(iss >> ip)) continue;
    std::string name;
    bool matched = false;
    while (iss >> name) {
      if (strcasecmp(name.c_str(), host.c_str()) == 0) {
        matched = true;
        break;
      }
    }
    if (!matched) continue;
    struct sockaddr_storage ss;
    socklen_t sl = 0;
    if (parse_ip_literal(ip, &ss, &sl)) {
      out->push_back(ss);
      lens->push_back(sl);
    }
  }
  return !out->empty();
}

// DNS 查询（A 优先，其次 AAAA）。失败返回空。
bool lookup_dns(const std::string& host,
                std::vector<struct sockaddr_storage>* out,
                std::vector<socklen_t>* lens) {
  res_init();
  const int kMaxAnswers = 16;
  unsigned char answer[2048];
  int len = res_query(host.c_str(), ns_c_in, ns_t_a, answer, sizeof(answer));
  if (len > 0) {
    ns_msg msg;
    if (ns_initparse(answer, len, &msg) == 0) {
      int count = ns_msg_count(msg, ns_s_an);
      for (int i = 0; i < count && (int)out->size() < kMaxAnswers; ++i) {
        ns_rr rr;
        if (ns_parserr(&msg, ns_s_an, i, &rr) != 0) continue;
        if (ns_rr_type(rr) != ns_t_a || ns_rr_rdlen(rr) != 4) continue;
        const unsigned char* rdata = ns_rr_rdata(rr);
        struct sockaddr_in v4;
        memset(&v4, 0, sizeof(v4));
        v4.sin_family = AF_INET;
        memcpy(&v4.sin_addr, rdata, 4);
        struct sockaddr_storage ss;
        memcpy(&ss, &v4, sizeof(v4));
        out->push_back(ss);
        lens->push_back(sizeof(v4));
      }
    }
  }
  if (!out->empty()) return true;

  len = res_query(host.c_str(), ns_c_in, ns_t_aaaa, answer, sizeof(answer));
  if (len > 0) {
    ns_msg msg;
    if (ns_initparse(answer, len, &msg) == 0) {
      int count = ns_msg_count(msg, ns_s_an);
      for (int i = 0; i < count && (int)out->size() < kMaxAnswers; ++i) {
        ns_rr rr;
        if (ns_parserr(&msg, ns_s_an, i, &rr) != 0) continue;
        if (ns_rr_type(rr) != ns_t_aaaa || ns_rr_rdlen(rr) != 16) continue;
        struct sockaddr_in6 v6;
        memset(&v6, 0, sizeof(v6));
        v6.sin6_family = AF_INET6;
        memcpy(&v6.sin6_addr, ns_rr_rdata(rr), 16);
        struct sockaddr_storage ss;
        memcpy(&ss, &v6, sizeof(v6));
        out->push_back(ss);
        lens->push_back(sizeof(v6));
      }
    }
  }
  return !out->empty();
}

// 把 host 解析成一组候选地址。返回 false 表示解析失败（err 里写原因）。
bool resolve_host(const std::string& host, std::vector<struct sockaddr_storage>* out,
                  std::vector<socklen_t>* lens, std::string* err) {
  struct sockaddr_storage ss;
  socklen_t sl = 0;
  if (parse_ip_literal(host, &ss, &sl)) {
    out->push_back(ss);
    lens->push_back(sl);
    return true;
  }
  if (lookup_etc_hosts(host, out, lens)) return true;
  if (lookup_dns(host, out, lens)) return true;
  if (err) {
    *err = "cannot resolve host " + host +
           " (not an IP literal, not in /etc/hosts, DNS lookup failed)";
  }
  return false;
}

#endif  // !_WIN32
}  // namespace

SftpConn::SftpConn()
    : sock_(kInvalidSocketLong), session_(nullptr), sftp_(nullptr), handshaked_(false) {}

SftpConn::~SftpConn() { close(); }

SftpConn::SftpConn(SftpConn&& other) noexcept
    : sock_(other.sock_),
      session_(other.session_),
      sftp_(other.sftp_),
      handshaked_(other.handshaked_) {
  other.sock_ = kInvalidSocketLong;
  other.session_ = nullptr;
  other.sftp_ = nullptr;
  other.handshaked_ = false;
}

SftpConn& SftpConn::operator=(SftpConn&& other) noexcept {
  if (this != &other) {
    close();
    sock_ = other.sock_;
    session_ = other.session_;
    sftp_ = other.sftp_;
    handshaked_ = other.handshaked_;
    other.sock_ = kInvalidSocketLong;
    other.session_ = nullptr;
    other.sftp_ = nullptr;
    other.handshaked_ = false;
  }
  return *this;
}

void SftpConn::close() {
  // 逆序释放：sftp -> session -> socket
  if (sftp_ != nullptr) {
    libssh2_sftp_shutdown(sftp_);
    sftp_ = nullptr;
  }
  if (session_ != nullptr) {
    if (handshaked_) libssh2_session_disconnect(session_, "Normal Shutdown");
    libssh2_session_free(session_);
    session_ = nullptr;
  }
  handshaked_ = false;
  if (sock_ != kInvalidSocketLong) {
    dfss_close_socket(sock_);
    sock_ = kInvalidSocketLong;
  }
}

// 调整已打开连接的收发超时。探测、测速、下载三个阶段对同一个连接用不同的
// 上界，因此这里允许在不重连的前提下改超时：socket 的收发超时和 libssh2 的
// 会话超时都跟着改，否则 libssh2 内部的阻塞读会无视 socket 层超时。
void SftpConn::set_io_timeout(int timeout_ms) {
  if (timeout_ms <= 0) timeout_ms = 1;
  if (session_ != nullptr) libssh2_session_set_timeout(session_, (long)timeout_ms);
  if (sock_ != kInvalidSocketLong) config_socket_timeout((socket_t)sock_, timeout_ms);
}

bool SftpConn::open(const ServerInfo& server, int timeout_ms, std::string* err,
                    bool handshake_only) {
  close();
  if (timeout_ms <= 0) timeout_ms = 1;

  // ---- 1. 地址解析（支持主机名，IPv4 必须、IPv6 尽力） ----
  std::vector<struct sockaddr_storage> addrs;
  std::vector<socklen_t> addr_lens;
#ifdef _WIN32
  {
    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo* res = nullptr;
    const std::string port_str = std::to_string(server.port);
    int gai = getaddrinfo(server.host.c_str(), port_str.c_str(), &hints, &res);
    if (gai != 0 || res == nullptr) {
      if (err)
        *err = "cannot resolve host " + server.host + ": " + std::to_string(gai);
      return false;
    }
    for (struct addrinfo* ai = res; ai != nullptr; ai = ai->ai_next) {
      struct sockaddr_storage ss;
      memset(&ss, 0, sizeof(ss));
      memcpy(&ss, ai->ai_addr, ai->ai_addrlen);
      addrs.push_back(ss);
      addr_lens.push_back((socklen_t)ai->ai_addrlen);
    }
    freeaddrinfo(res);
  }
#else
  if (!resolve_host(server.host, &addrs, &addr_lens, err)) return false;
#endif

  // ---- 2. TCP 连接（非阻塞 connect + select，总预算 timeout_ms） ----
  std::string last_err = "no usable address";
  bool connected = false;
  auto deadline = std::chrono::steady_clock::now() +
                  std::chrono::milliseconds(timeout_ms);
  for (size_t i = 0; i < addrs.size(); ++i) {
    auto now = std::chrono::steady_clock::now();
    int remain_ms = (int)std::chrono::duration_cast<std::chrono::milliseconds>(
                        deadline - now)
                        .count();
    if (remain_ms <= 0) {
      last_err = "connect timed out";
      break;
    }
    struct sockaddr_storage ss = addrs[i];
    if (ss.ss_family == AF_INET) {
      ((struct sockaddr_in*)&ss)->sin_port = htons((unsigned short)server.port);
    } else if (ss.ss_family == AF_INET6) {
      ((struct sockaddr_in6*)&ss)->sin6_port =
          htons((unsigned short)server.port);
    }
    socket_t s = socket(ss.ss_family, SOCK_STREAM, 0);
    if (s == kInvalidSocket) {
      last_err = "socket failed: " + socket_error_string(last_socket_error());
      continue;
    }
    std::string one_err;
    if (connect_with_timeout(s, (const struct sockaddr*)&ss, addr_lens[i],
                             remain_ms, &one_err)) {
      sock_ = (long long)s;
      connected = true;
      break;
    }
    dfss_close_socket((long long)s);
    last_err = one_err;
    // 超时后不必再尝试其它地址：总预算已耗尽
    if (one_err.find("timed out") != std::string::npos) break;
  }
  if (!connected) {
    if (err) *err = last_err;
    return false;
  }

  // ---- 3. SSH 会话与握手 ----
  // timeout_ms 是整段 open() 的总预算，不是每一跳各自的预算：握手耗时后，
  // 认证与 sftp_init 只能共用剩余时间。否则「连接 5s + 握手 5s + 认证 5s」
  // 会让 probe_timeout 名不副实（验收要求探测时间有上界）。
  session_ = libssh2_session_init();
  if (session_ == nullptr) {
    if (err) *err = "libssh2_session_init failed";
    close();
    return false;
  }
  auto remaining_ms = [&]() -> int {
    int64_t left = std::chrono::duration_cast<std::chrono::milliseconds>(
                       deadline - std::chrono::steady_clock::now())
                       .count();
    if (left <= 0) left = 1;  // 不传 0/负数：libssh2 会当成无限等待
    return (int)left;
  };
  libssh2_session_set_timeout(session_, (long)remaining_ms());
  // socket 层超时同样收敛到剩余预算：libssh2 内部有部分读会直接落到 socket 上
  config_socket_timeout((socket_t)sock_, remaining_ms());
  libssh2_session_flag(session_, LIBSSH2_FLAG_COMPRESS, 1);
  libssh2_session_method_pref(session_, LIBSSH2_METHOD_COMP_CS, "zlib,none");
  libssh2_session_method_pref(session_, LIBSSH2_METHOD_COMP_SC, "zlib,none");
  int rc = libssh2_session_handshake(session_, (libssh2_socket_t)sock_);
  if (rc != 0) {
    if (err) *err = "SSH handshake failed: " + std::to_string(rc);
    close();
    return false;
  }
  handshaked_ = true;
  if (handshake_only) return true;

  // ---- 4. 密码认证 ----
  // 诊断信息必须在认证之前取：认证后 libssh2_userauth_list/banner 会破坏会话状态。
  char* support_auth =
      libssh2_userauth_list(session_, server.user.c_str(),
                            (unsigned int)server.user.length());
  if (support_auth != nullptr) {
    log_info("server support auth list: %s", support_auth);
  }
  char* banner_s = nullptr;
  if (libssh2_userauth_banner(session_, &banner_s) == LIBSSH2_ERROR_NONE &&
      banner_s != nullptr) {
    log_info(
        "SFTP server banner:\n--------------------\n%s\n--------------------",
        banner_s);
  }

  libssh2_session_set_timeout(session_, (long)remaining_ms());
  config_socket_timeout((socket_t)sock_, remaining_ms());
  rc = libssh2_userauth_password(session_, server.user.c_str(),
                                 server.pass.c_str());
  if (rc != 0) {
    if (err) *err = "password authentication failed: " + std::to_string(rc);
    close();
    return false;
  }

  const char* comp = libssh2_session_methods(session_, LIBSSH2_METHOD_COMP_CS);
  if (comp != nullptr) log_info("Compression algorithm: %s", comp);

  // ---- 5. SFTP 子系统 ----
  libssh2_session_set_timeout(session_, (long)remaining_ms());
  config_socket_timeout((socket_t)sock_, remaining_ms());
  sftp_ = libssh2_sftp_init(session_);
  if (sftp_ == nullptr) {
    if (err) *err = "sftp_init failed: " + std::to_string(libssh2_session_last_errno(session_));
    close();
    return false;
  }
  return true;
}
