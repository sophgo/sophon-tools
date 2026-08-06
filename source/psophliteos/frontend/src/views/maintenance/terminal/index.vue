<template>
  <div class="p-4">
    <div class="mb-2 flex items-center" style="gap: 8px">
      <a-tag :color="statusColor">{{ statusText }}</a-tag>
      <a-button v-if="status !== 'connected'" size="small" @click="connect">
        {{ t('maintenance.terminal.connect') }}
      </a-button>
      <a-button v-else size="small" danger @click="disconnect">
        {{ t('maintenance.terminal.disconnect') }}
      </a-button>
    </div>
    <div ref="termRef" class="term-container"></div>
  </div>
</template>

<script lang="ts" setup>
  import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue';
  import { Terminal } from '@xterm/xterm';
  import { FitAddon } from '@xterm/addon-fit';
  import { WebLinksAddon } from '@xterm/addon-web-links';
  import { useUserStore } from '/@/store/modules/user';
  import { useI18n } from '/@/hooks/web/useI18n';
  import '@xterm/xterm/css/xterm.css';

  const { t } = useI18n();
  const termRef = ref<HTMLElement>();
  const status = ref<'disconnected' | 'connecting' | 'connected'>('disconnected');
  const userStore = useUserStore();

  let term: Terminal | null = null;
  let fit: FitAddon | null = null;
  let ws: WebSocket | null = null;
  let resizeObserver: ResizeObserver | null = null;

  const statusText = computed(() => {
    switch (status.value) {
      case 'connected':
        return t('maintenance.terminal.connected');
      case 'connecting':
        return t('maintenance.terminal.connecting');
      default:
        return t('maintenance.terminal.disconnected');
    }
  });
  const statusColor = computed(() =>
    status.value === 'connected' ? 'green' : status.value === 'connecting' ? 'orange' : 'red',
  );

  async function connect() {
    if (status.value === 'connected' || status.value === 'connecting') return;
    status.value = 'connecting';
    await nextTick();
    if (term) {
      term.dispose();
      term = null;
    }
    term = new Terminal({
      fontSize: 14,
      theme: { background: '#1e1e1e' },
      cursorBlink: true,
    });
    fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    if (termRef.value) {
      term.open(termRef.value);
      try {
        fit.fit();
      } catch (e) {
        /* ignore */
      }
    }

    const token = userStore.getToken;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/api/v1/hardware/terminal?token=${token}`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      status.value = 'connected';
      sendResize();
    };
    ws.onmessage = (e) => {
      if (term) {
        // 二进制帧按字节写；文本帧（如后端错误/提示）转 UTF-8 写入，避免静默丢弃。
        if (e.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(e.data));
        } else if (typeof e.data === 'string') {
          term.write(e.data);
        } else if (e.data && e.data.byteLength !== undefined) {
          // Blob 等二进制对象
          e.data.arrayBuffer().then((buf: ArrayBuffer) => term.write(new Uint8Array(buf)));
        }
      }
    };
    ws.onclose = () => {
      status.value = 'disconnected';
    };
    ws.onerror = () => {
      status.value = 'disconnected';
    };

    term.onData((d) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(d);
      }
    });
    term.onResize(({ cols, rows }) => sendResize(cols, rows));

    // 重新连接前断开旧的 observer，避免多次 connect 累积多个观察器（内存泄漏 + fit 重复触发）
    if (resizeObserver) {
      resizeObserver.disconnect();
    }
    resizeObserver = new ResizeObserver(() => {
      try {
        fit?.fit();
      } catch (e) {
        /* ignore */
      }
    });
    if (termRef.value) resizeObserver.observe(termRef.value);
  }

  function sendResize(cols?: number, rows?: number) {
    if (!term || !ws || ws.readyState !== WebSocket.OPEN) return;
    const c = cols ?? term.cols;
    const r = rows ?? term.rows;
    if (c > 0 && r > 0) {
      const buf = new ArrayBuffer(5);
      const view = new DataView(buf);
      view.setUint8(0, 0x01); // resize 控制字节
      view.setUint16(1, c, true);
      view.setUint16(3, r, true);
      ws.send(buf);
    }
  }

  function disconnect() {
    if (ws) {
      ws.onclose = null;
      ws.close();
      ws = null;
    }
    status.value = 'disconnected';
  }

  onMounted(() => {
    connect();
  });

  onUnmounted(() => {
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    if (ws) {
      ws.onclose = null;
      ws.close();
      ws = null;
    }
    if (term) {
      term.dispose();
      term = null;
    }
  });
</script>

<style lang="less" scoped>
  .term-container {
    height: 70vh;
    background: #1e1e1e;
    border-radius: 4px;
    padding: 8px;
    overflow: hidden;
  }
  :deep(.xterm) {
    height: 100%;
  }
</style>
