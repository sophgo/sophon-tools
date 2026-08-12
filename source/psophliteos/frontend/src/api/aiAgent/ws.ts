/**
 * Reasonix WebSocket 客户端（sophliteos 原生接入，PicoWS 的 TS 移植）。
 *
 * 职责：
 *   - 建立与 Reasonix agentproxy 的 WS 连接：ws://<host>:18990/agent/ws
 *   - 用子协议 token.<forward_key> 认证（浏览器无法设 Header，对齐 agentproxy ws.go）
 *   - 发送 message.send / session.list / session.history，接收 message.create /
 *     message.update / typing.* / session.create / error 等帧
 *   - 断线自动重连（3s 退避）
 */

const REASONIX_DEFAULT_PORT = 18990;
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
    if (this.ready && this.ws && this.ws.readyState === WebSocket.OPEN && !o.queued) {
      this.ws.send(value);
      return true;
    }
    if (o.queued) {
      this.queue.push(JSON.parse(value));
    }
    return false;
  }

  reconnect(): void {
    this.close();
    this.connect();
  }

  close(): void {
    this.closed = true;
    this.queue = [];
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

export function defaultReasonixWsUrl(hostname: string, port?: number): string {
  const p = port || REASONIX_DEFAULT_PORT;
  return `ws://${hostname}:${p}${REASONIX_WS_PATH}`;
}
