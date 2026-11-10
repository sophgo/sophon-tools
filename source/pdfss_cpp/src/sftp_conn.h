#ifndef DFSS_SFTP_CONN_H
#define DFSS_SFTP_CONN_H

#include <string>

#include "libssh2.h"
#include "libssh2_sftp.h"

// 服务器链路信息
struct ServerInfo {
  int id;
  std::string host;
  int port;
  std::string user;
  std::string pass;
  bool only_open;
  bool is_ok;
  double speed;
};

// SFTP 连接的 RAII 封装：持有 socket、LIBSSH2_SESSION* 和 LIBSSH2_SFTP*，
// 析构时按打开的逆序释放，调用方不再需要写八段重复的清理代码。
class SftpConn {
 public:
  SftpConn();
  ~SftpConn();

  SftpConn(const SftpConn&) = delete;
  SftpConn& operator=(const SftpConn&) = delete;
  SftpConn(SftpConn&& other) noexcept;
  SftpConn& operator=(SftpConn&& other) noexcept;

  // 依次完成：TCP 连接（非阻塞 connect + select 超时）、SSH 握手、密码认证、
  // sftp_init。handshake_only 为 true 时只做 TCP 连接 + 握手（保留原有
  // is_sftp_service 的语义）。timeout_ms 同时用于连接超时和会话收发超时。
  bool open(const ServerInfo& server, int timeout_ms, std::string* err,
            bool handshake_only = false);

  // 按逆序释放 sftp / session / socket，可重复调用。
  void close();

  // 调整已打开连接的收发超时（socket SO_RCVTIMEO/SO_SNDTIMEO + libssh2 会话
  // 超时）。探测阶段用 probe_timeout 给握手设上界，测速时缩到剩余预算，
  // 真正下载前再放宽到 connect_timeout，因此需要在不重连的前提下改这个值。
  void set_io_timeout(int timeout_ms);

  bool is_open() const { return session_ != nullptr; }

  LIBSSH2_SESSION* session() const { return session_; }
  LIBSSH2_SFTP* sftp() const { return sftp_; }

 private:
  // 用足够宽的整型存 socket：Windows 的 SOCKET 在 64 位上是 UINT_PTR，
  // 直接放 int 会与 INVALID_SOCKET 产生溢出与符号比较问题。
  long long sock_;
  LIBSSH2_SESSION* session_;
  LIBSSH2_SFTP* sftp_;
  // 握手成功后才能调用 libssh2_session_disconnect
  bool handshaked_;
};

// 关闭 socket 的平台差异封装，供 .cpp 内部使用。
void dfss_close_socket(long long sock);

#endif  // DFSS_SFTP_CONN_H
