/**
 * Reasonix WebSocket 客户端（sophliteos 原生接入，PicoWS 的 TS 移植）。
 *
 * 职责：
 *   - 建立与 Reasonix agentproxy 的 WS 连接：同源 ws(s)://<当前页面host>/agent/ws
 *     （默认同源入口，/agent/ws 由 sophliteos 反向代理转发到 bmssm 主服务；
 *     经端口转发/反代访问时自动跟随实际入口端口，不固定 8080）
 *   - 用子协议 token.<forward_key> 认证（浏览器无法设 Header，对齐 agentproxy ws.go）
 *   - 发送 message.send / session.list / session.history，接收 message.create /
 *     message.update / typing.* / session.create / error 等帧
 *   - 断线自动重连（3s 退避）
 */

const REASONIX_DEFAULT_PORT = 8080;
const REASONIX_WS_PATH = '/agent/ws';

export type WsState = 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface WsStatus {
  state: WsState;
  info?: { delay: number; count: number };
}

interface PicoWsOpts {
  url: string;
  token: string;
  onMessage: (msg: any) => void;
  onStatus?: (status: WsStatus) => void;
}

// 应用层心跳间隔（MYS-632 P0-2）：浏览器 WebSocket 无法主动发 control ping，
// 用 25s 一条 {type:'ping'} 帧保持服务端读空闲不超时；半开连接时客户端消息也
// 到不了服务端，服务端 3 分钟读超时关闭 → TCP 断开信号经 onclose 回到客户端。
const HEARTBEAT_INTERVAL = 25_000;

export class PicoWs {
  url: string;
  token: string;
  onMessage: (msg: any) => void;
  onStatus: (status: WsStatus) => void;

  private ws: WebSocket | null = null;
  ready = false;
  private closed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectCount = 0;
  private queue: any[] = [];
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  constructor(opts: PicoWsOpts) {
    this.url = opts.url;
    this.token = opts.token;
    this.onMessage = opts.onMessage;
    this.onStatus = opts.onStatus || (() => {});
  }

  connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    this.closed = false;
    this.bindNetworkEvents();
    this.emitStatus('connecting');
    try {
      this.ws = new WebSocket(this.url, ['token.' + this.token]);
    } catch (err) {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.ready = true;
      this.reconnectCount = 0;
      this.startHeartbeat();
      this.flushQueue();
      this.emitStatus('open');
    };

    this.ws.onmessage = (e: MessageEvent) => {
      const data = e.data;
      let msg: any;
      try {
        msg = typeof data === 'string' ? JSON.parse(data) : data;
      } catch (err) {
        return;
      }
      if (msg && this.onMessage) this.onMessage(msg);
    };

    this.ws.onclose = () => {
      const wasReady = this.ready;
      this.ready = false;
      this.stopHeartbeat();
      this.unbindNetworkEvents();
      if (wasReady) this.emitStatus('closed');
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose 会随后触发并处理重连
    };
  }

  send(sessionId?: string, content?: string, media?: string[]): void {
    if (!this.ready || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket 未连接，无法发送消息');
    }
    const frame = this.buildFrame(sessionId, content, media);
    this.ws.send(JSON.stringify(frame));
  }

  sendFrame(frame: any, opts?: { queued?: boolean }): boolean {
    const o = opts || {};
    const value = JSON.stringify(frame);
    // MYS-637 修复：优先发送——连接就绪时即使标记 queued 也直接发送，避免
    // 「入队后立刻被 next reconnect 清队」导致帧从不送达（session.delete 在线删除回归）。
    // queued 语义收敛为「仅未就绪时入队,等重连 flush」。
    if (this.ready && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(value);
      return true;
    }
    if (o.queued) {
      this.queue.push(JSON.parse(value));
    }
    return false;
  }

  reconnect(): void {
    this.close({ keepQueue: true }); // 跨重连保留未发送帧（断线期间的 delete 等）,onopen flush
    this.connect();
  }

  close(opts?: { keepQueue?: boolean }): void {
    this.closed = true;
    if (!opts?.keepQueue) this.queue = [];
    this.stopHeartbeat();
    this.unbindNetworkEvents();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch (e) {
        /* ignore */
      }
      this.ws = null;
    }
    this.ready = false;
  }

  // ---------- 心跳（MYS-632 P0-2） ----------
  // 浏览器 WebSocket 不允许发送 control ping，应用层 ping 帧让服务端保持读空闲
  // 不超时；半开连接时消息到不了服务端，服务端 3 分钟读超时关闭连接，触发本地
  // onclose → scheduleReconnect，从而结束「已连接但发消息无反应」的假死。
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      try {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      } catch (e) {
        // 发送抛异常说明连接已坏，交给 onclose/reconnect 恢复
      }
    }, HEARTBEAT_INTERVAL);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // ---------- 网络事件（MYS-632 P0-2） ----------
  // 页面切回前台 / 网络恢复：若连接已半开（ws.ready 仍 true 但实际已断），主动
  // reconnect 而非被动等 onclose；若连接已断开则恢复重连调度。
  private onVisibilityChange = () => {
    if (document.visibilityState !== 'visible') return;
    if (this.closed) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.reconnect();
    }
  };

  private onOnline = () => {
    if (this.closed) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.reconnect();
    }
  };

  private bindNetworkEvents(): void {
    if (typeof window === 'undefined') return;
    window.addEventListener('visibilitychange', this.onVisibilityChange);
    window.addEventListener('online', this.onOnline);
  }

  private unbindNetworkEvents(): void {
    if (typeof window === 'undefined') return;
    window.removeEventListener('visibilitychange', this.onVisibilityChange);
    window.removeEventListener('online', this.onOnline);
  }

  private buildFrame(sessionId?: string, content?: string, media?: string[]): any {
    const payload: any = { content: content || '' };
    if (media && media.length) payload.media = media;
    const frame: any = { type: 'message.send', payload };
    if (sessionId) frame.session_id = sessionId;
    return frame;
  }

  private flushQueue(): void {
    if (!this.ready || !this.ws) return;
    while (this.queue.length) {
      const frame = this.queue.shift();
      try {
        this.ws.send(JSON.stringify(frame));
      } catch (e) {
        /* ignore */
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.closed) return;
    if (this.reconnectTimer) return;
    this.reconnectCount += 1;
    this.emitStatus('reconnecting', { delay: 3000, count: this.reconnectCount });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 3000);
  }

  private emitStatus(state: WsState, info?: { delay: number; count: number }): void {
    this.onStatus({ state, info });
  }
}

/**
 * 构造 agent WS 地址。
 * 不传参数：同源模式——跟随当前页面的协议与 host（含端口），经端口转发/反向代理
 * 访问（如 socat 18080 引出）时 WS 与页面走同一入口，不再固定 8080。
 * 传 hostname（兼容旧调用）：默认 8080 端口，可由 port 覆盖。
 */
export function defaultReasonixWsUrl(hostname?: string, port?: number): string {
  if (!hostname && !port) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}${REASONIX_WS_PATH}`;
  }
  const p = port || REASONIX_DEFAULT_PORT;
  return `ws://${hostname}:${p}${REASONIX_WS_PATH}`;
}
