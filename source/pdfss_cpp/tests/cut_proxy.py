#!/usr/bin/env python3
"""TCP 转发代理，转发 N 字节后断开（用于验证断流与换服务器续传）。

用法:
    python3 cut_proxy.py --listen 127.0.0.1:32022 \
        --target 106.38.208.114:32022 --budget 4194304 [--mode all|first]

行为:
  - 监听 listen 端口（写 0 端口时由内核分配，实际端口写进 --ready-file），
    接受连接后连到 target，双向转发；
  - 累计「客户端 -> 服务器」和「服务器 -> 客户端」的字节总和达到 budget 后，
    关闭这条连接（模拟网络中断）；
  - --mode all: 之后的所有连接都不再转发，连上即断（每一次下载都在同一位置断掉）；
  - --mode first: 只让第一条连接断开，之后的连接正常转发（用来让测速失败、
    而下载成功）。
"""
import argparse
import os
import socket
import sys
import threading


def parse_endpoint(text: str):
    host, _, port = text.rpartition(":")
    if not host or not port:
        raise argparse.ArgumentTypeError("expected host:port, got %r" % text)
    return host, int(port)


def pump(src, dst, state, lock):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            with lock:
                if state["cut"]:
                    # 这条连接已被判定超预算: 不再转发, 直接断链
                    break
                state["total"] += len(data)
                if state["total"] >= state["budget"]:
                    state["cut"] = True
                    break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(client, addr, target_endpoint, state, lock):
    with lock:
        state["conns"] += 1
        conn_id = state["conns"]
        # mode=first 时只有第一条连接受预算约束，之后的连接不限量转发
        unlimited = state["mode"] == "first" and conn_id > 1
        if unlimited:
            conn_state = dict(state)
            conn_state["budget"] = 1 << 62
            conn_state["cut"] = False
    try:
        upstream = socket.create_connection(target_endpoint, timeout=10)
    except OSError as e:
        print("cut_proxy: cannot connect upstream: %s" % e, file=sys.stderr)
        client.close()
        return
    print("cut_proxy: conn #%d from %s:%d%s"
          % (conn_id, addr[0], addr[1], " (unlimited)" if unlimited else ""),
          file=sys.stderr)
    cs = conn_state if unlimited else state
    t1 = threading.Thread(target=pump, args=(client, upstream, cs, lock))
    t2 = threading.Thread(target=pump, args=(upstream, client, cs, lock))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    client.close()
    upstream.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=parse_endpoint, required=True)
    ap.add_argument("--target", type=parse_endpoint, required=True)
    ap.add_argument("--budget", type=int, default=4 * 1024 * 1024,
                    help="bytes to forward before cutting the connection")
    ap.add_argument("--mode", choices=("all", "first"), default="all",
                    help="all: cut every connection; first: cut only the first")
    ap.add_argument("--ready-file", default=None)
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(args.listen)
    srv.listen(16)
    if args.ready_file:
        with open(args.ready_file, "w") as f:
            f.write("%d\n" % srv.getsockname()[1])
    print("cut_proxy: listening on %s:%d -> %s:%d, budget %d bytes, mode %s"
          % (args.listen[0], srv.getsockname()[1],
             args.target[0], args.target[1], args.budget, args.mode),
          file=sys.stderr)

    state = {"total": 0, "budget": args.budget, "conns": 0, "cut": False,
             "mode": args.mode}
    lock = threading.Lock()
    try:
        while True:
            client, addr = srv.accept()
            threading.Thread(target=handle,
                             args=(client, addr, args.target, state, lock),
                             daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if args.ready_file and os.path.exists(args.ready_file):
            os.remove(args.ready_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
