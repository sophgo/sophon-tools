<template>
  <!-- eslint-disable vue/no-v-html -- 内容一律经 renderMarkdown（marked + DOMPurify）消毒 -->
  <div class="webchat">
    <!-- 左侧：会话列表 -->
    <aside class="webchat-sidebar">
      <div class="webchat-sidebar-header">
        <span class="webchat-app-title">AI Agent</span>
      </div>
      <button class="webchat-new-chat" type="button" @click="newSession">＋ 新对话</button>
      <nav class="webchat-session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="webchat-session-item"
          :class="{ active: s.id === activeId }"
          @click="switchSession(s.id)"
        >
          <div class="webchat-session-title">{{ s.title || '新会话' }}</div>
          <!-- 需求 2：会话忙碌（仍在干活）时右侧转圈标记 -->
          <span v-if="s.busy" class="webchat-busy webchat-busy-dot" title="Agent 工作中"></span>
          <button
            class="webchat-session-del"
            type="button"
            title="删除会话"
            @click.stop="deleteSession(s.id)"
            >×</button
          >
        </div>
        <div v-if="!sessions.length" class="webchat-session-empty">暂无会话</div>
      </nav>
    </aside>

    <!-- 右侧：聊天区 -->
    <main class="webchat-main">
      <header class="webchat-header">
        <div class="webchat-header-title-wrap">
          <div
            v-if="!editingTitle"
            class="webchat-header-title"
            title="双击自定义标题"
            @dblclick="startEditTitle"
          >
            {{ activeSess?.title || '新会话' }}
          </div>
          <input
            v-else
            v-model="draftTitle"
            class="webchat-header-title-input"
            ref="titleInputEl"
            @keydown.enter="commitTitle"
            @keydown.esc="cancelEditTitle"
            @blur="commitTitle"
          />
          <!-- 需求 2：当前会话忙碌（agent 正在干活）时标题旁转圈 -->
          <span v-if="activeSess?.busy" class="webchat-busy" title="Agent 正在工作中"></span>
        </div>
        <div class="webchat-header-status" :class="statusClass">{{ statusText }}</div>
      </header>

      <div ref="messagesEl" class="webchat-messages" @scroll.passive="onMessagesScroll">
        <!-- 懒加载：上翻到头时提示还有更早历史，可点此逐批加载（底部滚动锚定不跳动） -->
        <button
          v-if="hasMoreOlder"
          class="webchat-load-older"
          type="button"
          :disabled="loadingOlder"
          @click="loadOlder"
          >{{ loadingOlder ? '加载中…' : '↥ 加载更早消息' }}</button
        >
        <template v-for="m in visibleMessages" :key="m.key">
          <div v-if="m.role === 'user'" class="webchat-msg webchat-msg-user">
            <div class="webchat-bubble">{{ m.content }}</div>
          </div>
          <div v-else-if="m.kind === 'thought'" class="webchat-collapse">
            <button class="webchat-collapse-header" type="button" @click="m.open = !m.open">
              <span class="webchat-collapse-arrow">{{ m.open ? '▾' : '▸' }}</span>
              <span class="webchat-collapse-label">思考过程</span>
              <span v-if="!m.open" class="webchat-collapse-summary"
                >· {{ thoughtSummary(m.content) }}</span
              >
            </button>
            <div
              v-show="m.open"
              class="webchat-collapse-body"
              v-html="m.html"
            ></div>
          </div>
          <div v-else-if="m.kind === 'tool_calls'" class="webchat-collapse">
            <button class="webchat-collapse-header" type="button" @click="m.open = !m.open">
              <span class="webchat-collapse-arrow">{{ m.open ? '▾' : '▸' }}</span>
              <span class="webchat-collapse-label">工具调用</span>
              <span v-if="!m.open" class="webchat-collapse-summary"
                >· {{ toolCallSummary(m.content) }}</span
              >
            </button>
            <div
              v-show="m.open"
              class="webchat-collapse-body"
              v-html="m.html"
            ></div>
          </div>
          <div v-else class="webchat-msg webchat-msg-assistant">
            <div class="webchat-bubble" v-html="m.html"></div>
          </div>
        </template>
        <div v-if="typing" class="webchat-msg webchat-msg-assistant">
          <div class="webchat-typing"><span></span><span></span><span></span></div>
        </div>
        <div v-if="errorMsg" class="webchat-msg webchat-msg-error">
          <div class="webchat-bubble">{{ errorMsg }}</div>
        </div>
        <!-- 需求(MYS-210)：上翻历史时出现的「跳到最底部」悬浮按钮 -->
        <Transition name="webchat-fade">
          <button
            v-if="showJumpBottom"
            class="webchat-jump-bottom"
            type="button"
            @click="scrollToBottom"
            aria-label="跳到最底部"
            >▼</button
          >
        </Transition>
      </div>

      <footer class="webchat-input-area">
        <div v-if="pendingPerm" class="webchat-msg webchat-msg-assistant">
          <div class="webchat-bubble webchat-perm">
            <div class="webchat-perm-label">需要确认：<strong>{{ pendingPerm.permTitle }}</strong></div>
            <div class="webchat-perm-hint">Agent 请求执行上述操作，是否允许？(60 秒未操作将自动拒绝)</div>
            <div class="webchat-perm-actions">
              <button class="webchat-perm-btn webchat-perm-allow" type="button" @click="respondPermission(pendingPerm.permReqId, true, pendingPerm)">允许</button>
              <button class="webchat-perm-btn webchat-perm-deny" type="button" @click="respondPermission(pendingPerm.permReqId, false, pendingPerm)">拒绝</button>
            </div>
          </div>
        </div>
        <div class="webchat-input-box">
          <!-- 需求(MYS-210)：输入框左侧 —— 自动审批 + 停止，与发送按钮同风格（高亮表示开启） -->
          <div class="webchat-input-tools">
            <button
              class="webchat-tool-btn"
              :class="{ on: autoApproveOn }"
              type="button"
              title="开启后，工具权限请求将自动允许（随本会话保存）；高亮=已开启"
              @click="autoApproveOn = !autoApproveOn"
              >自动审批</button
            >
            <button
              v-if="activeSess?.busy || typing"
              class="webchat-tool-btn"
              type="button"
              title="停止当前回合"
              @click="stopAgent"
              >停止</button
            >
          </div>
          <textarea
            ref="inputEl"
            v-model="draft"
            rows="1"
            placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
            @keydown="onKeydown"
            @input="autoGrow"
          ></textarea>
          <button
            class="webchat-send"
            type="button"
            :disabled="sending || !connected"
            @click="sendMessage"
            >发送</button
          >
        </div>
        <div class="webchat-input-hint">内容由 AI Agent 生成，请注意甄别</div>
      </footer>
    </main>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { ref, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue';
  import { PicoWs, defaultReasonixWsUrl } from '/@/api/aiAgent/ws';
  import { renderMarkdownToHtml } from './markdown';
  import { getAgentConfig } from '/@/api/aiAgent';

  interface ChatMsg {
    key?: string;
    role: 'user' | 'assistant';
    kind?: string;
    content: string;
    html?: string;
    open?: boolean;
    // 渲染竞态防护：每次异步渲染打上序号，仅最新序号落地结果
    __renderSeq?: number;
    // 权限审批卡片字段
    permReqId?: number;
    permTitle?: string;
    permDone?: boolean | null;
  }

  interface Session {
    id: string;
    title: string;
    messages: ChatMsg[];
    busy?: boolean;
    // 是否已绑定服务端会话 id（运行期派生态，不持久化）。
    // 用于会话隔离：绑定后不再把本会话 id 篡改为任意入帧的 session_id。
    serverBound?: boolean;
    // 需求(MYS-210)：自动审批开关，随会话保存（刷新/换浏览器后恢复）。
    autoApprove?: boolean;
  }

  const SESSIONS_KEY = 'sophon.ai-agent.sessions';
  const ACTIVE_KEY = 'sophon.ai-agent.active';

  const sessions = ref<Session[]>([]);
  const activeId = ref<string>('');
  const draft = ref('');
  const editingTitle = ref(false);
  const draftTitle = ref('');
  const titleInputEl = ref<HTMLElement | null>(null);
  const sending = ref(false);
  const typing = ref(false);
  const errorMsg = ref('');
  const connected = ref(false);
  const statusText = ref('连接中…');
  const statusClass = ref('');

  const messagesEl = ref<HTMLElement | null>(null);
  const inputEl = ref<HTMLTextAreaElement | null>(null);
  // 需求(MYS-210)：消息区是否可滚动（内容超出视口才显示「跳底」按钮）与是否贴近底部
  const canScroll = ref(false);
  const nearBottom = ref(true);
  const showJumpBottom = computed(() => canScroll.value && !nearBottom.value);

  let ws: PicoWs | null = null;
  let forwardKey = '';
  // P1-1：配置拉取重试句柄（失败 30s 内重试 3 次，成功后更新 token 供后续重连使用）
  let configRetryTimer: ReturnType<typeof setTimeout> | null = null;
  // P1-2：最近一次发送成功时间（sending 在途标记超时兜底用）
  let lastSendAt = 0;
  // 本地 message 渲染序号（避免重复 key）
  let msgSeq = 0;
  // 兜底：agent 回答完仍转圈的动画 BUG（MYS-199）。
  // 根因：服务端回合(consumeTurn)的唯一结束信号依赖 reasonix `session/prompt`
  // 响应帧到达才关 updates 通道并下发 typing.stop / session.busy=false；若该响应帧
  // 丢失/迟到/挂起，这两类停止事件不送达，前端 typing 与 busy 会卡死一直转。
  // 兜底1：收到 text 最终答案内容即本地清 typing（服务端 protocol.go 在首 chunk 也发
  //        typing.stop，此处为防丢包/时序残留的冗余）。
  // 兜底2：busy 超时复位——busy 会话长期收不到任何 ws 帧即视为回合已停，强制清 busy
  //        （覆盖「回合永不结束 → busy=false 永不发」的根因路径）。
  // 兜底3：error 事件除清 typing 外同步清当前会话 busy。
  // 兜底4（需求 4）：刷新/换浏览器后恢复型 busy 一次性校准——恢复的 busy 若短时间内收不到
  //        任何新活动帧，判定为服务端 running 残留（回合已完成/卡死），复位为空闲。
  const BUSY_STALL_TIMEOUT = 120_000; // busy 无任何活动帧超过此值即判定停摆
  const BUSY_CALIBRATE_WINDOW = 8_000; // 恢复型 busy 的校准窗口：窗口内无新帧即复位
  const BUSY_SCAN_INTERVAL = 10_000; // 兜底扫描周期
  // 会话最后一次收到 ws 帧的时间（key=sessionId）。仅用于 busy 超时判定，不入持久化。
  const sessionLastWsAt: Record<string, number> = {};
  // 恢复型 busy 的校准截止时间（key=sessionId）；到点后若仍无新帧则复位 busy。
  const busyCalibAt: Record<string, number> = {};
  // 兜底扫描定时器句柄
  let busyStallTimer: ReturnType<typeof setInterval> | null = null;
  // 当前流式「思考过程」折叠块的 key（同一逻辑思考常被后端拆成多个 message.create
  // thought-1/thought-2，累积到同一折叠块避免拆泡）。
  let openThoughtKey: string | null = null;

  function clearOpenThought() {
    openThoughtKey = null;
  }

  const activeSess = computed(() => sessions.value.find((s) => s.id === activeId.value) || null);
  // 展示列表：权限审批卡（kind==='permission'）只以输入框上方的 pendingPerm 呈现，
  // 不在消息流里渲染成气泡（需求 2：允许/拒绝后不再出现空白气泡）。
  const rawMessages = computed(() => activeSess.value?.messages || []);
  const currentMessages = computed(() => rawMessages.value.filter((m) => m.kind !== 'permission'));
  // ---------- 懒加载（长会话动态渲染）----------
  // 长会话消息成百上千条，一次性全量渲染 DOM + markdown 会卡死。方案：只渲染
  // 「尾部窗口」内的可见消息（默认最近 INITIAL_RENDER 条），用户上翻时逐批
  // loadCount 增大、动态补载更早消息（滚动锚定，不跳动）；窗口外的历史保持原始
  // 文本、不占 DOM、不渲染 markdown。既解决点开长会话卡顿，也解决初始 DOM 爆炸。
  const INITIAL_RENDER = 40;
  const LOAD_BATCH = 60;
  // 从尾部向前渲染多少条。0 = 尚未初始化（新会话/未加载历史）。
  const loadCount = ref(0);
  const loadingOlder = ref(false);
  // 可见窗口：始终锚定在消息尾部（slice 负索引），最新消息必然可见；
  // 新的流式消息追加到尾部，窗口自动跟随，无需额外处理。
  const visibleMessages = computed(() => {
    const all = currentMessages.value;
    if (!all.length) return all;
    const n = Math.max(1, Math.min(loadCount.value || INITIAL_RENDER, all.length));
    return all.slice(all.length - n);
  });
  // 是否还有更早历史未渲染（显示「加载更早消息」按钮；配合滚动到底部自动补载）。
  const hasMoreOlder = computed(
    () => (loadCount.value || INITIAL_RENDER) < currentMessages.value.length
  );
  // 切换/加载会话时重置渲染窗口：默认只渲染尾部 INITIAL_RENDER 条。
  function resetRenderWindow() {
    const total = currentMessages.value.length;
    loadCount.value = Math.min(total, INITIAL_RENDER);
  }
  // 滚动事件：接近窗口顶部且有更早历史时，自动补载一批（滚动锚定保持位置不跳）。
  function loadOlder() {
    if (loadingOlder.value) return;
    const el = messagesEl.value;
    const prevHeight = el ? el.scrollHeight : 0;
    const prevScrollTop = el ? el.scrollTop : 0;
    const anchor = prevHeight - prevScrollTop; // 相对底部的距离（补载后保持不变）
    const total = currentMessages.value.length;
    if ((loadCount.value || INITIAL_RENDER) >= total) return; // 已全部渲染
    loadingOlder.value = true;
    loadCount.value = Math.min(total, (loadCount.value || INITIAL_RENDER) + LOAD_BATCH);
    nextTick(() => {
      if (el) el.scrollTop = Math.max(0, el.scrollHeight - anchor);
      refreshScrollState();
      loadingOlder.value = false;
    });
  }
  // 待处理的权限请求：取当前会话第一条未处理（permDone 为空）的 permission 消息。
  // 由消息状态派生，切换会话/允许/拒绝/回执后自动同步，与消息历史共享同一份 permDone。
  const pendingPerm = computed<ChatMsg | null>(() => {
    const msgs = activeSess.value?.messages || [];
    // permDone === null: 仍在等待用户处理；true=已允许，false=已拒绝/取消（均视为已解决，不再作为待办卡片）。
    return msgs.find((m) => m.kind === 'permission' && m.permDone === null) || null;
  });
  // 需求(MYS-210)：自动审批开关。绑定当前会话的 autoApprove 字段，
  // 随 Session 一起持久化（saveSessions / loadSessions + 同步到 bmssm 后端），
  // 刷新或换浏览器后恢复、各会话独立。切换会话/无会话时回退 false。
  const autoApproveOn = computed<boolean>({
    get: () => !!activeSess.value?.autoApprove,
    set: (v: boolean) => {
      const s = activeSess.value;
      if (s) {
        s.autoApprove = v;
        saveSessions();
        // 同步到 bmssm（跨浏览器/设备持久化），session.list/history 据此恢复。
        if (ws && ws.ready) {
          ws.sendFrame({ type: 'session.autoapprove', session_id: s.id,
            payload: { session_id: s.id, autoApprove: v } });
        }
      }
    },
  });

  // 需求(MYS-210)：停止当前回合。向服务端发 session.cancel（agentproxy ws.go 已支持
  // 该帧 → module.CancelTurn 取消在途回合），本地同步清 typing/busy，避免残留转圈。
  function stopAgent() {
    const s = activeSess.value;
    if (ws && ws.ready && s?.id) {
      ws.sendFrame({ type: 'session.cancel', session_id: s.id });
    }
    typing.value = false;
    sending.value = false;
    if (s) {
      s.busy = false;
      delete busyCalibAt[s.id];
    }
  }

  // 异步渲染 markdown → 安全 HTML。消息内容流式累积，用版本号避免旧结果的竞态覆盖。
  let renderSeq = 0;
  function renderMsgHtml(m: ChatMsg) {
    const mark = ++renderSeq;
    m.__renderSeq = mark;
    const key = m.key;
    const sessionId = activeSess.value?.id;
    renderMarkdownToHtml(m.content)
      .then((html) => {
        // 仅当消息仍在当前会话、且无更新渲染时应用结果（避免竞态写回错误内容）
        const stillActive =
          key && sessionId && activeId.value === sessionId && activeSess.value?.messages.some((x) => x.key === key);
        if (stillActive && m.__renderSeq === mark) {
          m.html = html;
          scheduleSave(); // 渲染结果写回,流式期间高频 → 防抖合并
        }
      })
      .catch(() => {
        /* renderMarkdownToHtml 内部已有兜底，无需处理 */
      });
  }
  function bumpRender(m: ChatMsg) {
    m.__renderSeq = 0;
    renderMsgHtml(m);
  }

  // 消息内容流式变化时，对需要 markdown 渲染的 assistant 消息做防抖重渲染。
  // 用深度 watch 覆盖所有内容变更入口（handleCreate/handleUpdate/历史恢复等），避免遗漏。
  // 性能优化（长会话卡顿）：watch 的 source 同时带出「上一份 key:content」映射，
  // 重渲染只针对内容实际变化过的 assistant 消息——避免长会话下任何一点内容变化都
  // 触发全量 markdown 重渲染（marked+DOMPurify+高亮+katex/mermaid 开销大）。
  let renderTimer: ReturnType<typeof setTimeout> | null = null;
  const msgContentSnapshot = (msgs: ChatMsg[]) =>
    msgs.map((m) => m.key + ':' + m.content).join('');
  watch(
    () => msgContentSnapshot(visibleMessages.value),
    (now, prev) => {
      if (renderTimer) clearTimeout(renderTimer);
      renderTimer = setTimeout(() => {
        const msgs = visibleMessages.value || [];
        // 解析上一份 key:content 快照为 Map
        const prevMap = new Map<string, string>();
        if (prev) {
          for (const line of prev.split('')) {
            const i = line.indexOf(':');
            if (i > 0) prevMap.set(line.slice(0, i), line.slice(i + 1));
          }
        }
        for (const m of msgs) {
          if (m.role !== 'assistant' || m.kind === 'permission' || !m.content) continue;
          // 旧持久化的工具调用可能是裸 JSON，渲染前规整为可读文本（幂等，自动修复历史）
          if (m.kind === 'tool_calls') m.content = displayToolCalls(m.content);
          // 内容未变且已有渲染结果 → 跳过（长会话历史不重复渲染，降低卡顿）
          const prevContent = prevMap.get(m.key);
          if (m.html && prevContent != null && prevContent === m.content) continue;
          bumpRender(m);
        }
      }, 150);
      // 内容渲染后刷新消息区滚动状态
      nextTick(refreshScrollState);
    }
  );

  function uuid(): string {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function loadSessions(): Session[] {
    try {
      const raw = localStorage.getItem(SESSIONS_KEY);
      const list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function saveSessions() {
    try {
      // html / __renderSeq 是从 content 派生的渲染缓存，不持久化（向后兼容、避免存储膨胀）
      // busy 是运行期派生态（需求 4）：不持久化，避免刷新后错误沿用旧的「正在工作」标记；
      // 恢复时以服务端 running + 一次性校准为准。
      const snap = sessions.value.map((s) => {
        const { busy: _b, ...rest } = s as Session;
        return {
          ...rest,
          messages: rest.messages.map((m) => {
            const { html: _h, __renderSeq: _r, ...mrest } = m as ChatMsg;
            return mrest;
          }),
        };
      });
      const serialized = JSON.stringify(snap);
      localStorage.setItem(SESSIONS_KEY, serialized);
    } catch (e: any) {
      // MYS-635 P1-4：写入失败(通常 QuotaExceeded)不再静默吞掉——提示一次,避免
      // 用户以为已持久化实际刷新即丢。仅在阈值外提示,防长回话说一句刷屏。
      if (e && (e.name === 'QuotaExceededError' || e.code === 22 || e.code === 1014)) {
        const now = Date.now();
        if (now - (lastStorageQuotaWarnAt || 0) > 60_000) {
          lastStorageQuotaWarnAt = now;
          console.warn('[sophon-webchat] localStorage 容量超限,会话本地持久化失效(服务端仍在线,刷新后历史由 session.history 恢复)', e);
        }
      }
    }
  }

  // MYS-635 P1-4：流式写入防抖——每个流式 chunk 都 saveSessions() 全量序列化所有会话,
  // 长会话下每 chunk 都写 localStorage 拖慢 UI。结构性操作(新建/删除/切换/绑定/权限)仍
  // 调 saveSessions() 立即落盘;高频流式(handleCreate/handleUpdate)改走本函数 500ms 合并,
  // 一轮连发多个 chunk 只写一次。
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let lastStorageQuotaWarnAt = 0;
  function scheduleSave() {
    if (saveTimer) return;
    saveTimer = setTimeout(() => {
      saveTimer = null;
      saveSessions();
    }, 500);
  }
  // 组件卸载时冲刷防抖缓冲,避免「刷新/关闭瞬间丢失最后一段内容」。
  function flushScheduleSave() {
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
      saveSessions();
    }
  }

  function saveActive() {
    try {
      if (activeId.value) localStorage.setItem(ACTIVE_KEY, activeId.value);
      else localStorage.removeItem(ACTIVE_KEY);
    } catch (e) {
      /* ignore */
    }
  }

  function ensureSession(): Session {
    const s = activeSess.value;
    if (s) return s;
    return newSession();
  }

  function newSession(): Session {
    const s: Session = { id: uuid(), title: '新会话', messages: [], busy: false, serverBound: false };
    sessions.value.unshift(s);
    activeId.value = s.id;
    saveSessions();
    saveActive();
    draft.value = '';
    errorMsg.value = '';
    clearOpenThought();
    resetRenderWindow(); // 懒加载：新会话为空，渲染窗口归零
    resetConnection();
    return s;
  }

  function switchSession(id: string) {
    if (!sessions.value.some((s) => s.id === id)) return;
    activeId.value = id;
    saveActive();
    clearOpenThought();
    resetRenderWindow(); // 懒加载：切换会话时重置渲染窗口，只渲染尾部 INITIAL_RENDER 条
    resetConnection();
  }

  function deleteSession(id: string) {
    // 先同步到服务端真实删除（此前只做本地移除，重连后 session.list 会把服务端仍在的
    // 会话拉回来 → 点击消失又复现）。后端 handleSessionDeleteLocked 会删除服务端会话
    // 并解绑本连接对该会话的 byACP 订阅，此后重连 session.list 不再返回它。
    // MYS-635 P1-3：queued:true —— 断线期间删除入队,重连后 flush 真正送达服务端,
    // 避免「删了又复活」(旧行为仅本地移除,断线删除静默失败,重连拉回)。
    if (ws) {
      ws.sendFrame({ type: 'session.delete', session_id: id, payload: { session_id: id } }, { queued: true });
    }
    sessions.value = sessions.value.filter((s) => s.id !== id);
    if (activeId.value === id) {
      activeId.value = sessions.value.length ? sessions.value[0].id : '';
    }
    saveSessions();
    saveActive();
    if (!activeId.value) newSession();
    else resetConnection();
  }

  function resetConnection() {
    if (ws) ws.reconnect();
  }

  // ---------- WS ----------
  // 内容类帧（消息、审批、回合终态）：仅当帧属于当前展示会话时才写入聊天区渲染，
  // 属于其他会话（后台并行回合 / 时序残留）只更新其 busy，绝不写入当前 view——
  // 根治「切换会话后新历史不刷新、追加在旧历史后」：上一个会话在途帧不会覆盖当前。
  const CONTENT_FRAMES = new Set(['message.create', 'message.update', 'permission.request',
    'turn.error', 'typing.start', 'typing.stop']);
  function frameBelongsToActive(frameSid: string | undefined, payloadSid: string | undefined): boolean {
    const sid = frameSid || payloadSid;
    if (!sid) return true; // 无会话归属的帧（连接级）始终处理
    return sid === activeId.value;
  }
  function handleMessage(msg: any) {
    if (!msg || !msg.type) return;
    const type = msg.type;
    const payload = msg.payload || {};
    if (msg.session_id) bindServerSession(msg.session_id);
    // 记录该会话最后活动帧时间（busy 超时兜底用）：该会话收到任何帧即视为仍在运转
    if (msg.session_id) sessionLastWsAt[msg.session_id] = Date.now();
    const frameSid = msg.session_id || payload.session_id;

    // 会话隔离：内容/回合类帧只作用于当前展示会话；后台会话帧仅更新 busy，不渲染。
    // 这样其它 worker 会话的流式输出不会污染当前聊天区，也不会把消息 push 错会话。
    // 注：session.busy 是会话级帧，不在此隔离（下方 switch 统一按帧 session_id 更新对应会话）。
    if (CONTENT_FRAMES.has(type) && !frameBelongsToActive(msg.session_id, payload.session_id)) {
      return; // 后台会话内容帧直接丢弃，切回时由 session.history 补齐
    }

    switch (type) {
      case 'message.create':
        handleCreate(payload);
        break;
      case 'message.update':
        handleUpdate(payload);
        break;
      case 'typing.start':
        typing.value = true;
        break;
      case 'typing.stop':
        typing.value = false;
        // MYS-632 P1-2：typing.stop 在首个内容 chunk 到达时也会下发一次
        // （protocol.go messageChunk 停打字指示器），并非只对应回合结束——不能在此
        // 复位 sending，否则快速连发两条仍会让第二条 StartTurn 取消第一条。
        // sending 仅在 busy=false / error / turn.error 时复位（见对应分支）。
        // 回合结束：思考已结束，后续新思考应另起折叠块
        clearOpenThought();
        break;
      case 'session.list':
        handleSessionList(payload);
        break;
      case 'session.history':
        handleSessionHistory(payload);
        break;
      case 'session.busy':
        // 需求 2：会话忙碌状态（agent 正在干活）的转圈标记
        {
          const bsid = msg.session_id || payload.session_id;
          const wasBusy = !!sessions.value.find((x) => x.id === bsid)?.busy;
          setSessionBusy(bsid, !!payload.busy);
          if (!payload.busy) {
            // 回合结束：允许下一条消息（MYS-632 P1-2）
            sending.value = false;
            // MYS-632 P0-1：回合可能在重连/切会话期间结束，本回合 assistant 只在
            // 服务端回合结束才落库，若流式帧因重连丢失，本地看不到答案。收到
            // busy=false 对该会话补拉一次 history reconcile（mergeHistory 幂等）。
            if (wasBusy && bsid) pullHistory(bsid);
          }
        }
        break;
      case 'session.updated':
        // 需求 3：自定义标题后的回执 + 自动审批开关跨浏览器同步回执
        applyTitle(msg.session_id, payload.title);
        if (typeof payload.autoApprove === 'boolean') applyAutoApprove(msg.session_id, payload.autoApprove);
        break;
      case 'permission.request':
        handlePermissionRequest(msg.session_id, payload);
        break;
      case 'permission.responded':
        markPermissionDone(payload.request_id, !!payload.allow);
        break;
      case 'turn.error':
        // MYS-632 P1-2：回合错误与 error 同语义，终止在途标记（否则 sending 卡死）
        errorMsg.value = payload.message || '发生错误';
        sending.value = false;
        typing.value = false;
        setSessionBusy(msg.session_id || activeId.value, false);
        break;
      case 'error':
        errorMsg.value = payload.message || '发生错误';
        sending.value = false;
        typing.value = false;
        // 兜底3：出错即回合终止，同步复位当前会话 busy（避免异常后仍转圈）
        setSessionBusy(msg.session_id || activeId.value, false);
        break;
    }
  }

  /** permission.request：Agent 触发需用户批准的工具调用 → 在活跃会话插入审批卡片。
       reasonix 已移除模型侧 ask 工具（MYS-212）：本端收到的 permission.request 只含
       命令审批（Allow/allow_always/Reject），不再有真实候选选项的选择题 ask。因此
       自动审批直接全部放行（回 allow），无需区分 ask vs 命令审批。 */
  function handlePermissionRequest(sessionId: string | undefined, payload: any) {
    const reqId = payload?.request_id;
    const toolCall = payload?.tool_call || {};
    if (reqId == null) return;
    const s = ensureSession();
    const makePermMsg = (done: boolean | null) => ({
      key: 'perm' + msgSeq++,
      role: 'assistant',
      kind: 'permission',
      content: '',
      permReqId: reqId,
      permTitle: (toolCall.title as string) || '工具调用',
      permDone: done,
      open: false,
    });
    // 开启自动审批 → 命令审批直接自动放行（allow=true 对应 allow_once 本次放行）。
    if (s.autoApprove) {
      if (ws && ws.ready) {
        ws.sendFrame({
          type: 'permission.respond',
          session_id: s.id,
          payload: { session_id: s.id, request_id: reqId, allow: true },
        });
      }
      s.messages.push(makePermMsg(true));
      saveSessions();
      return;
    }
    s.messages.push(makePermMsg(null));
    saveSessions();
    scrollToBottom();
  }

  /** 用户点击 允许/拒绝 → 回传 permission.respond。 */
  function respondPermission(reqId: number, allow: boolean, m: ChatMsg) {
    const sid = activeSess.value?.id;
    if (ws && ws.ready) {
      ws.sendFrame({
        type: 'permission.respond',
        session_id: sid,
        payload: { session_id: sid, request_id: reqId, allow },
      });
    }
    m.permDone = allow;
    saveSessions();
  }

  /** permission.responded 回执：把对应审批卡片置为已处理（幂等）。 */
  function markPermissionDone(reqId: number, allow: boolean) {
    const s = activeSess.value;
    if (!s) return;
    const m = s.messages.find((x) => x.permReqId === reqId);
    if (m) {
      m.permDone = allow;
      saveSessions();
    }
  }

  function setSessionBusy(sid: string | undefined, busy: boolean) {
    if (!sid) return;
    const s = sessions.value.find((x) => x.id === sid);
    if (s) s.busy = busy;
  }

  // 恢复型 busy（需求 4）：刷新/换浏览器时由服务端 session.list/history 的 running 恢复。
  // 服务端 running 仅进程内存（HasTurn），若某回合的 prompt 响应帧丢失/挂起，turn 的
  // done 通道永不关闭，running 会一直为 true → 刷新后误显示「正在工作」。这里对该恢复的
  // busy 做一次性校准：记基线时刻，校准窗口内若无任何新 ws 帧（真在跑会持续发
  // tool_call/text），判定为误恢复的空闲会话并复位。
  function restoreBusy(sid: string | undefined, busy: boolean) {
    if (!sid) return;
    const s = sessions.value.find((x) => x.id === sid);
    if (!s) return;
    s.busy = !!busy;
    if (busy) {
      sessionLastWsAt[sid] = Date.now(); // 恢复基线：真在跑会有新帧刷新这里
      busyCalibAt[sid] = Date.now() + BUSY_CALIBRATE_WINDOW;
    } else {
      delete busyCalibAt[sid];
    }
  }

  // 兜底4校准扫描：在每个兜底周期内，检查恢复型 busy 是否过窗且无新活动帧。
  function calibrateRestoredBusy() {
    const now = Date.now();
    sessions.value.forEach((s) => {
      const due = busyCalibAt[s.id];
      if (!due) return;
      if (now < due) return; // 窗口内：保持，等真在跑的任务发帧刷新基线
      delete busyCalibAt[s.id];
      if (s.busy && now - (sessionLastWsAt[s.id] || 0) >= BUSY_CALIBRATE_WINDOW) {
        s.busy = false;
        // 复位 busy 同步复位发送/输入态：终结态帧丢失时用户仍可继续发消息（MYS-632 P1-2）
        if (s.id === activeId.value) {
          sending.value = false;
          typing.value = false;
        }
        // MYS-632 P0-1：校准复位可能是回合已完成但终态帧丢失，补拉 reconcile 幂等
        if (ws && ws.ready) pullHistory(s.id, true);
      }
    });
  }

  // 兜底2：busy 超时复位。服务端 session.busy=false 仅在回合(consumeTurn)正常结束时
  // 下发；若回合永不结束（reasonix prompt 响应帧丢失/挂起），busy=false 永不送达，
  // busy 转圈会一直转。此定时器兜底：busy 会话长期收不到任何 ws 帧即视为回合已停，
  // 强制复位 busy（不改动服务端协议，纯前端保险；tool_call_update 等活动帧会刷新
  // sessionLastWsAt，正常长任务不会被误清）。
  function clearStalledBusy() {
    const now = Date.now();
    sessions.value.forEach((s) => {
      if (!s.busy) return;
      if (now - (sessionLastWsAt[s.id] || 0) > BUSY_STALL_TIMEOUT) {
        s.busy = false;
        // 复位 busy 同步复位发送/输入态：终结态帧丢失时用户仍可继续发消息（MYS-632 P1-2）
        if (s.id === activeId.value) {
          sending.value = false;
          typing.value = false;
        }
        // MYS-632 P0-1：回合实际结束但终态帧丢失的兜底——补拉历史把落库答案
        // reconcile 回本地；mergeHistory 幂等，可安全重复。
        if (ws && ws.ready) pullHistory(s.id, true);
      }
    });
  }

  function applyTitle(sid: string | undefined, title: string | undefined) {
    if (!sid || !title) return;
    const s = sessions.value.find((x) => x.id === sid);
    if (s) s.title = title;
  }

  // 自动审批开关跨浏览器/设备同步回执（session.updated 的 autoApprove）。
  function applyAutoApprove(sid: string | undefined, on: boolean) {
    if (!sid) return;
    const s = sessions.value.find((x) => x.id === sid);
    if (s) s.autoApprove = !!on;
  }

  function bindServerSession(serverId: string) {
    const s = activeSess.value;
    if (!s || !serverId) return;
    // 仅当本会话尚无服务端 id（fresh 本地临时 uuid，尚未收到任何服务端确认帧）时绑定一次。
    // 绝不把已稳定绑定的会话 id 篡改为任意入帧的 session_id —— 后端所有业务帧的
    // session_id 都是本会话初始的本地 uuid，本应恒等；一旦出现不等于当前 id 的帧
    // （历史遗留/极端时序），篡改 id 会把两个会话的历史相互覆盖/追加，造成
    // 「切换会话后新历史不刷新、旧历史残留」的串扰 bug。
    if (s.serverBound) return;
    if (serverId) {
      s.serverBound = true;
      if (s.id !== serverId) {
        s.id = serverId;
        activeId.value = serverId;
      }
      saveSessions();
      saveActive();
    }
  }

  function handleCreate(payload: any) {
    const s = ensureSession();
    const messageId = payload.message_id || '';
    const kind = payload.kind || 'text';
    const content = payload.content || '';

    if (kind === 'text') {
      // 连续 text 合并到同一条 assistant 文本气泡（修复拆泡）。
      // reasonix 常把一句话拆成多个不同 message_id 的 text（text-1/text-2…），
      // 期间还可能夹入 thought / tool_calls（内部思考、工具调用/审批）——这些不应把
      // text 切成两泡。因此从后向前找「最近一条纯文本 assistant 气泡，二者之间没有
      // user 消息」，把后续 text 续接到它上面；中间可跳过 thought/tool_calls。
      clearOpenThought();
      // 兜底1：最终答案内容开始输出即本地清 typing（需求：收到 text 首条置 false；
      // 服务端首 chunk 本应发 typing.stop，此处防丢包/切会话时序导致的残留）
      typing.value = false;
      const me = messageId;
      const existingById = me ? s.messages.find((m) => m.key === me) : null;
      if (existingById && (existingById.kind === 'text' || !existingById.kind)) {
        existingById.content = existingById.content + content;
        return;
      }
      // 从后向前找最近的纯文本 assistant 气泡（可跳过中间的 thought），
      // 只要中间没有 user 消息且没有 tool_calls（工具调用为合并边界），
      // 就把本次 text 续接上去（保持同一气泡）。
      let target: ChatMsg | null = null;
      for (let i = s.messages.length - 1; i >= 0; i--) {
        const m = s.messages[i];
        if (m.role === 'user') break; // 遇 user：跨轮，不再回退合并
        if (m.kind === 'tool_calls') break; // 遇工具调用：不跨工具合并（各自成泡）
        if (m.role === 'assistant' && !m.kind) {
          target = m;
          break; // 找到最近的纯 text 气泡
        }
        // thought：跳过继续向前找
      }
      if (target) {
        target.content += content;
        return;
      }
      s.messages.push({
        key: messageId || 'msg' + msgSeq++,
        role: 'assistant',
        content,
        open: false,
      });
    } else if (kind === 'thought') {
      // 同一逻辑思考常被后端拆成多个 message.create（thought-1/thought-2）：
      // 累积到当前打开的思考折叠块，避免同一段思考被拆成两个「思考过程」气泡。
      const existing = messageId
        ? s.messages.find((m) => m.key === messageId && m.kind === 'thought')
        : null;
      if (existing) {
        existing.content = accumulate(existing.content, content);
        openThoughtKey = existing.key as string;
      } else if (openThoughtKey) {
        const target = s.messages.find((m) => m.key === openThoughtKey);
        if (target && target.kind === 'thought') {
          target.content += content;
        } else {
          openThoughtKey = null;
          pushThought(messageId, content);
        }
      } else {
        pushThought(messageId, content);
      }
    } else if (kind === 'tool_calls') {
      // 思考结束进入工具调用：后续新思考应另起折叠块
      clearOpenThought();
      const text = formatToolCalls(payload);
      s.messages.push({
        key: messageId || 'msg' + msgSeq++,
        role: 'assistant',
        kind,
        content: text,
        open: false,
      });
    }
    scheduleSave(); // 流式创建,高频 → 防抖合并(MYS-635 P1-4)
    scrollToBottom();
  }

  function pushThought(messageId: string, content: string) {
    const s = activeSess.value;
    if (!s) return;
    const key = messageId || 'msg' + msgSeq++;
    s.messages.push({ key, role: 'assistant', kind: 'thought', content, open: false });
    openThoughtKey = key;
  }

  function handleUpdate(payload: any) {
    const s = activeSess.value;
    if (!s) return;
    const messageId = payload.message_id || '';
    const content = payload.content || '';
    const kind = payload.kind || '';
    const targetByKey = messageId ? s.messages.find((m) => m.key === messageId) : null;
    if (targetByKey) {
      targetByKey.content = accumulate(targetByKey.content, content);
      // thought 增量更新到达时，把它作为当前打开的思考块累积目标
      if (kind === 'thought' && targetByKey.kind === 'thought')
        openThoughtKey = targetByKey.key as string;
    } else if (kind === 'thought' && openThoughtKey) {
      // 未跟踪的 thought 增量 → 累积到当前打开的思考块
      const t = s.messages.find((m) => m.key === openThoughtKey);
      if (t && t.kind === 'thought') t.content = accumulate(t.content, content);
    } else if (kind !== 'thought') {
      // 未跟踪的 text/tool 增量：追加到最近一条同类消息
      const last = s.messages[s.messages.length - 1];
      if (last && last.role === 'assistant') last.content = accumulate(last.content, content);
    } else {
      const last = s.messages[s.messages.length - 1];
      if (last && last.role === 'assistant' && last.kind === 'thought')
        last.content = accumulate(last.content, content);
    }
    scheduleSave(); // 每个流式 chunk 高频 → 防抖合并,一轮只写一次 localStorage (MYS-635 P1-4)
    scrollToBottom();
  }

  function accumulate(current: string, incoming: string): string {
    if (!incoming) return current;
    if (!current) return incoming;
    if (incoming.length >= current.length && incoming.indexOf(current) === 0) return incoming;
    if (incoming.length > current.length) return incoming;
    return current + incoming;
  }

  function formatToolCalls(payload: any): string {
    const calls = payload.tool_calls;
    if (Array.isArray(calls) && calls.length) {
      return calls.map((c: any) => toolCallLine(c)).filter(Boolean).join('\n');
    }
    // 拿不到结构化 tool_calls：回退 payload.content（message.create 已带后端可读摘要）或空
    return payload.content || '';
  }

  // 把一条工具调用规整为可读的「工具名: 内容」（需求：工具名 + 执行的命令/编辑的文件路径）。
  // 兼容两种载荷形态：
  //   - pico/旧形态：{function:{name,arguments}} → 「工具名: 参数主内容」
  //   - ACP 现代形态 ToolCallState：{toolCallId,title,kind,status,rawInput,locations}
  //     → 「工具名: 命令/路径」（rawInput/locations 优先，与后端 toolCallSummary 一致）。
  function toolCallLine(c: any): string {
    if (c == null) return '';
    if (typeof c !== 'object') return String(c);
    if (c.function && typeof c.function === 'object') {
      const name = c.function.name || '';
      const body = extractArgs(c.function.arguments);
      return [name, body].filter((x) => x).join(': ').trim();
    }
    const name = c.title || c.toolCallId || '';
    const detail = extractToolDetail(c);
    if (detail) return [name, detail].filter((x) => x).join(': ').trim();
    const bits: string[] = [];
    if (c.title) bits.push(c.title);
    else if (c.toolCallId) bits.push(c.toolCallId);
    if (c.kind) bits.push(c.kind);
    if (typeof c.status === 'string' && c.status) bits.push(c.status);
    return bits.join(' · ');
  }

  // 从 ACP 现代形态 ToolCallState 提取「命令/文件路径」：locations 优先，其次 rawInput JSON。
  function extractToolDetail(c: any): string {
    if (Array.isArray(c.locations) && c.locations.length && c.locations[0]) {
      const p = String(c.locations[0]);
      if (p.trim()) return p.trim();
    }
    if (c.rawInput == null) return '';
    if (typeof c.rawInput === 'object') return extractArgs(c.rawInput);
    let text = String(c.rawInput).trim();
    if (!text || text === '{}' || text === 'null') return '';
    try {
      const obj = JSON.parse(text);
      if (obj && typeof obj === 'object') return extractArgs(obj);
    } catch (e) {
      /* 非 JSON，按原文返回 */
    }
    return text;
  }

  // 从工具调用的 arguments/参数中提取主参数文本（命令、文件路径优先）。
  // arguments 可能是字符串（含转义 JSON）或已是对象；解析失败回退原文。
  function extractArgs(raw: any): string {
    if (raw == null) return '';
    const primaryOf = (o: any): string => {
      if (o == null) return '';
      const k = o.command ?? o.path ?? o.file ?? o.paths ?? o.src ?? o.content ?? o.cmd;
      if (k != null) return typeof k === 'object' ? JSON.stringify(k) : String(k);
      try {
        return Object.entries(o)
          .map(([kk, v]) => `${kk}=${String(v)}`)
          .join(', ');
      } catch (e) {
        return '';
      }
    };
    if (typeof raw !== 'object') {
      let text = String(raw);
      // 转义 JSON（pico 会把 arguments 转义成字符串）→ 尝试解引用一次
      try {
        const obj = JSON.parse(text.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\'));
        if (obj && typeof obj === 'object') return primaryOf(obj);
      } catch (e) {
        /* 非 JSON，按原文返回 */
      }
      return text.trim();
    }
    return primaryOf(raw);
  }

  // 兼容旧持久化的工具调用内容：旧版可能是原始 JSON（pico function 或 ToolCallState 序列化），
  // 检测到则规整为可读文本；已经是可读行则原样返回（幂等）。
  function displayToolCalls(content: string): string {
    if (!content) return '';
    const t = content.trim();
    const looksReadable =
      !t.startsWith('[') && !t.includes('"function"') && !/^\{"toolCallId\b/.test(t);
    if (looksReadable) return content;
    try {
      let calls: any[] | null = null;
      if (t.startsWith('[')) {
        const arr = JSON.parse(t);
        if (Array.isArray(arr)) calls = arr;
      } else {
        calls = [JSON.parse(t)];
      }
      if (calls) {
        const rebuilt = calls.map((c) => toolCallLine(c)).filter(Boolean).join('\n');
        if (rebuilt) return rebuilt;
      }
    } catch (e) {
      /* 解析失败，保持原文 */
    }
    return content;
  }

  // ---------- 折叠块收起时的单行摘要 ----------
  // 摘要在渲染期从 m.content 实时计算，不改变已持久化的消息结构（向后兼容）。
  const SUMMARY_LEN = 30;

  function clampChars(text: string, n: number): string {
    const chars = Array.from(text);
    const sliced = chars.slice(0, n).join('');
    return sliced + (chars.length > n ? '…' : '');
  }

  // 剥掉常见 markdown 标记，得到可读纯文本（避免摘要里出现 # * 等符号）
  function plainText(text: string): string {
    return (text || '')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/[#>*`_~]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // 思考过程：内容前 SUMMARY_LEN 个文字
  function thoughtSummary(content: string): string {
    return clampChars(plainText(content), SUMMARY_LEN);
  }

  // 工具调用折叠块收起时的单行摘要：内容已是可读行（或旧 JSON），取首条「工具名: 内容」截断。
  function toolCallSummary(content: string): string {
    if (!content) return '';
    const normalized = displayToolCalls(content);
    const firstLine = (normalized || '').split('\n')[0] || '';
    return clampChars(plainText(firstLine), SUMMARY_LEN);
  }

  // 历史合并（需求 3）：服务端历史为权威完整基线（原样保留顺序，允许跨轮次同内容消息
  // 重复存在），仅追加本地尚未被服务端覆盖的消息（在途流式内容、权限审批记录——
  // 服务端不回放 permission）。这样既不丢失历史，也不会因去重把不同轮次的相同内容合并掉。
  function mergeHistory(local: ChatMsg[], server: ChatMsg[]): ChatMsg[] {
    // keyOf 对 assistant 纯文本做 kind 归一化（MYS-774）：本地流式 text 消息不存 kind
    // （handleCreate 只记录 role/content），服务端 session.history 落库的 text 消息带
    // kind='text'。若直接拼 kind，同一回复在「流式接收 + 回合结束 pullHistory 合并」时
    // 会因 kind 不一致各保留一份 → 页面渲染出两条重复回复。归一化把 kind 为空或 text
    // 的 assistant 消息视为同一类，新旧数据（含 localStorage 旧缓存）均可正确去重。
    const keyOf = (m: ChatMsg) => {
      let k = m.kind || '';
      if (m.role === 'assistant' && (k === '' || k === 'text')) k = 'text';
      return m.role + '|' + k + '|' + (m.content || '');
    };
    const serverKeys = new Set(server.map(keyOf));
    return server.concat(local.filter((m) => !serverKeys.has(keyOf(m))));
  }

  function handleSessionList(payload: any) {
    const serverList = Array.isArray(payload.sessions) ? payload.sessions : [];
    const stored: Session[] = serverList.map((ss: any) => {
      // 服务端列表不含消息；保留本地已缓存消息作为兜底，等 session.history 确认后再刷新
      const existing = sessions.value.find((x) => x.id === ss.id);
      return {
        id: ss.id,
        title: ss.title || '新会话',
        messages: existing ? existing.messages : [],
        busy: false,
        // 服务端返回的会话其 id 已是稳定 server id，标记已绑定避免后续被误篡改
        serverBound: true,
        // 自动审批开关以 bmssm 服务端为准（跨浏览器/设备同步）；本地缓存的兜底
        autoApprove: typeof ss.autoApprove === 'boolean' ? ss.autoApprove : existing ? !!existing.autoApprove : false,
      };
    });
    // 保留本地尚未同步到服务端的会话——仅未绑定(serverBound=false)的本地临时新会话。
    // 已绑定且服务端不存在的本地会话视为「已被删除(另一标签页/清库)」,同步移除,
    // 避免「删了又复活」与长期幽灵会话(MYS-635 P1-3)。
    const storedIds = new Set(stored.map((s) => s.id));
    sessions.value.forEach((s) => {
      if (!storedIds.has(s.id) && !s.serverBound) stored.push(s);
    });
    sessions.value = stored;
    if (!sessions.value.some((s) => s.id === activeId.value)) {
      activeId.value = sessions.value.length ? sessions.value[0].id : '';
    }
    saveSessions();
    saveActive();
    // 同步忙碌指示（需求 2/4）：服务端 running 为真相，恢复型 busy 走一次性校准
    sessions.value.forEach((s) => restoreBusy(s.id, !!serverList.find((ss: any) => ss.id === s.id)?.running));
    if (activeId.value) {
      pullHistory(activeId.value);
    } else {
      newSession();
    }
  }

  // 校准/超时复位引发的 history 补拉：只合并消息做 reconcile，不恢复 busy。
  // 若恢复 busy，服务端 running=true 又会重设校准窗口 → 复位 → 再补拉 → 无限循环。
  const reconcileOnly = new Set<string>();

  function handleSessionHistory(payload: any) {
    const sid = payload.session_id;
    const raw = Array.isArray(payload.messages) ? payload.messages : [];
    const s = sessions.value.find((x) => x.id === sid);
    if (!s) return;
    const onlyReconcile = reconcileOnly.delete(sid); // 在合并前消费标记
    // history 里会出现成段的相邻 text 小片段（agent 一条完整回答被切成 text-1..text-N），
    // 且一句话中间可能夹 thought / tool_calls（内部思考、工具调用）。若这些把 text
    // 切断成多泡，会把「同一条连续回答」显示成碎片。故加载历史时，把相邻的 assistant
    // 纯文本合并；合并允许跳过中间的 thought/tool_calls（它们不阻断正文，只是正文中的
    // 阶段动作），但遇 user 消息即止（不跨轮次合并）。thought/tool_calls 各自成泡。
    const serverMsgs: ChatMsg[] = [];
    for (const m of raw) {
      const role = m.role === 'user' ? 'user' : 'assistant';
      const kind = m.kind || (m.role === 'user' ? '' : 'text');
      const content =
        m.content && m.kind === 'tool_calls' ? displayToolCalls(m.content) : m.content || '';
      const isPlainText = role === 'assistant' && kind !== 'thought' && kind !== 'tool_calls';
      // 纯文本空内容无信息量（源是流式片段，可能为空白），跳过避免空泡
      if (isPlainText && !content) continue;
      if (isPlainText) {
        // 从后向前找 serverMsgs 里最近的纯文本 assistant 气泡（可跳过中间的 thought，
        // 但遇 tool_calls 即止——工具调用为合并边界，调用两侧文本各自成泡）
        let prevPlain: ChatMsg | null = null;
        for (let i = serverMsgs.length - 1; i >= 0; i--) {
          const pm = serverMsgs[i];
          if (pm.role === 'user') break;
          if (pm.kind === 'tool_calls') break;
          if (pm.role === 'assistant' && !pm.kind) {
            prevPlain = pm;
            break;
          }
          // thought 跳过
        }
        if (prevPlain) {
          prevPlain.content += content;
          continue;
        }
      }
      serverMsgs.push({ key: 'his' + msgSeq++, role, kind, content, open: false });
    }
    // 请求 3：以服务端历史为权威基线，并合并本地尚未同步到的消息（在途内容、权限审批记录），
    // 避免刷新/换浏览器后历史缺失；同内容按 role+kind+content 去重，防止重复。
    s.serverBound = true; // 收到 history 即本会话已绑定稳定 server id
    s.messages = mergeHistory(s.messages, serverMsgs);
    if (payload.title && s.title !== payload.title) s.title = payload.title;
    // 自动审批开关跨浏览器同步：以 bmssm 服务端为准
    if (typeof payload.autoApprove === 'boolean') s.autoApprove = payload.autoApprove;
    if (!onlyReconcile) {
      restoreBusy(s.id, !!payload.running); // 需求 4：恢复 busy 时走一次性校准
    }
    clearOpenThought();
    saveSessions();
    resetRenderWindow(); // 懒加载：历史到达后只渲染尾部窗口，避免一次性渲染全部导致卡顿
    scrollToBottom();
  }

  function syncFromServer() {
    if (!ws || !ws.ready) return;
    ws.sendFrame({ type: 'session.list' }, { queued: true });
  }

  function pullHistory(sessionId: string, onlyReconcile = false) {
    if (!ws || !ws.ready || !sessionId) return;
    if (onlyReconcile) reconcileOnly.add(sessionId);
    ws.sendFrame({ type: 'session.history', session_id: sessionId }, { queued: true });
  }

  // ---------- 发送 ----------
  function sendMessage() {
    const s = ensureSession();
    const content = draft.value.trim();
    if (!content) return;
    if (sending.value) return;
    if (!ws || !ws.ready) {
      errorMsg.value = '连接未就绪，请稍后再试';
      return;
    }
    sending.value = true;
    errorMsg.value = '';
    clearOpenThought();

    // 用户消息入本地
    s.messages.push({ key: 'msg' + msgSeq++, role: 'user', content });
    // 需求 3：默认标题用第一条用户消息前 20 个字（本地即时更新，服务端 EnsureTitle 亦会设）
    if (!s.title || s.title === '新会话') {
      s.title = defaultTitleFromText(content);
    }
    const serverId = s.id;
    saveSessions();
    draft.value = '';
    // 需求：清空输入后重算高度（autoGrow 内部 nextTick 等 Vue 把空内容渲染进 textarea，
    // 否则残留长文本 scrollHeight，高度收不回默认 40px）
    autoGrow();
    scrollToBottom();

    try {
      ws.send(serverId, content, []);
      lastSendAt = Date.now();
      // 在途标记：保持 sending=true 直到本轮回合结束信号（session.busy=false /
      // turn.error / error）到达，期间用户再 Enter 会被 sendMessage 顶部的
      // `if (sending.value) return` 拦下，避免第二条 StartTurn 取消第一条的回答
      // （MYS-632 P1-2）。
    } catch (err: any) {
      sending.value = false;
      errorMsg.value = err.message || '发送失败，请检查连接';
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ---------- 需求 3：自定义标题 ----------
  function defaultTitleFromText(text: string): string {
    const t = text.trim().replace(/\s+/g, ' ');
    if (!t) return '新会话';
    return Array.from(t).slice(0, 20).join('') || '新会话';
  }
  function startEditTitle() {
    const s = activeSess.value;
    if (!s) return;
    draftTitle.value = s.title || '新会话';
    editingTitle.value = true;
    nextTick(() => {
      if (titleInputEl.value) titleInputEl.value.focus();
    });
  }

  function commitTitle() {
    editingTitle.value = false;
    if (!ws || !ws.ready) return;
    const s = activeSess.value;
    const t = draftTitle.value.trim();
    if (!s || !t) return;
    // 本地立即更新 + 服务端持久化
    s.title = t;
    saveSessions();
    ws.sendFrame({ type: 'session.rename', session_id: s.id, payload: { title: t } });
  }

  function cancelEditTitle() {
    editingTitle.value = false;
  }

  function autoGrow() {
    const el = inputEl.value;
    if (!el) return;
    el.style.height = 'auto';
    // 需求：等本轮 Vue 渲染（清空输入后 DOM 才真正变短）再读 scrollHeight，
    // 否则读到的是旧长文本高度，导致发送后输入框收不回默认 40px。
    nextTick(() => {
      const h = Math.max(40, Math.min(el.scrollHeight, 160));
      el.style.height = h + 'px';
    });
  }

  function scrollToBottom() {
    nextTick(() => {
      if (messagesEl.value) {
        messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
        refreshScrollState();
      }
    });
  }

  // 需求(MYS-210)：刷新「可滚动 / 贴近底部」状态（跳底按钮显隐依据）。
  function refreshScrollState() {
    const el = messagesEl.value;
    if (!el) {
      canScroll.value = false;
      nearBottom.value = true;
      return;
    }
    const can = el.scrollHeight > el.clientHeight + 1;
    canScroll.value = can;
    nearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight <= 40;
  }

  function onMessagesScroll() {
    refreshScrollState();
    // 懒加载：上翻接近窗口顶部且还有更早历史时，自动补载下一批（滚动锚定）。
    const el = messagesEl.value;
    if (el && hasMoreOlder.value && el.scrollTop <= 150) {
      loadOlder();
    }
  }

  // ---------- 连接 ----------
  // P1-1：配置拉取短退避周期重试（30s 内最多重试 3 次，累计 ~3s/10s/25s）。
  // 服务端 /agent/ws 自 MYS-379 起不再校验子协议 key，配置失败不阻塞建连；
  // 重试成功后更新 forwardKey，供后续重建连接时携带子协议 token（兼容回显）。
  async function refreshAgentConfig(retries: number): Promise<void> {
    const cfg = await getAgentConfig();
    if (cfg?.forwardKey) {
      forwardKey = cfg.forwardKey;
      if (ws) ws.token = cfg.forwardKey;
      return;
    }
    if (retries >= 3) return;
    const delays = [3000, 7000, 15000];
    configRetryTimer = setTimeout(() => refreshAgentConfig(retries + 1), delays[retries]);
  }

  async function connect() {
    if (!forwardKey) {
      // 异步读取配置（首个尝试等快速失败），拿到失败/超时结果前直接建连——
      // 非 admin / bmssm 刚启动配置未就绪的场景也能立即进入对话页。
      void refreshAgentConfig(0);
    }
    if (ws) {
      ws.close();
      ws = null;
    }
    // 同源：跟随当前访问的协议/host（含端口），经 socat 等端口转发访问时
    // WS 与页面同一入口，不再固定 8080（此前 18080 引出访问时 WS 连
    // <host>:8080 失败，页面一直"重连中"）。
    const url = defaultReasonixWsUrl();
    ws = new PicoWs({
      url,
      token: forwardKey,
      onMessage: handleMessage,
      onStatus: (st) => {
        const map: Record<string, string> = {
          connecting: '连接中…',
          open: '已连接',
          reconnecting: '重连中…',
          closed: '已断开',
        };
        connected.value = st.state === 'open';
        statusText.value = map[st.state] || st.state;
        statusClass.value = st.state === 'open' ? 'ok' : st.state === 'closed' ? 'bad' : 'warn';
        if (st.state === 'open') syncFromServer();
      },
    });
    ws.connect();
  }

  onMounted(() => {
    sessions.value = loadSessions();
    const saved = localStorage.getItem(ACTIVE_KEY);
    if (saved && sessions.value.some((s) => s.id === saved)) activeId.value = saved;
    if (!activeSess.value) newSession();
    connect();
    nextTick(refreshScrollState);
    // 兜底2/4：启动忙状态扫描（防回合永不结束致 busy 卡死 + 恢复型 busy 一次性校准）
    busyStallTimer = setInterval(() => {
      clearStalledBusy();
      calibrateRestoredBusy();
      // P1-2 兜底：sending 在途标记长期不落位（终态帧丢失/回合卡死）会阻塞后续
      // 发送，超时后复位（busy 走 BUSY_STALL_TIMEOUT 同一阈值）。
      if (sending.value && Date.now() - lastSendAt > BUSY_STALL_TIMEOUT) {
        sending.value = false;
      }
    }, BUSY_SCAN_INTERVAL);
  });

  onBeforeUnmount(() => {
    if (busyStallTimer) {
      clearInterval(busyStallTimer);
      busyStallTimer = null;
    }
    if (configRetryTimer) {
      clearTimeout(configRetryTimer);
      configRetryTimer = null;
    }
    if (renderTimer) clearTimeout(renderTimer);
    flushScheduleSave(); // 冲刷防抖缓冲,退出页面前最后落盘一次 (MYS-635 P1-4)
    if (ws) ws.close();
  });
</script>

<style lang="less" scoped>
  .webchat {
    display: flex;
    height: calc(100vh - 110px);
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    overflow: hidden;
    background: #fff;
  }

  .webchat-sidebar {
    width: 240px;
    flex-shrink: 0;
    border-right: 1px solid #e5e7eb;
    display: flex;
    flex-direction: column;
    background: #fafafa;
  }

  .webchat-sidebar-header {
    padding: 14px 16px;
    font-size: 15px;
    font-weight: 600;
    border-bottom: 1px solid #eee;
  }

  .webchat-new-chat {
    margin: 12px;
    padding: 8px;
    border: 1px dashed #d9d9d9;
    border-radius: 6px;
    background: #fff;
    cursor: pointer;
    font-size: 13px;
    color: #333;
  }
  .webchat-new-chat:hover {
    border-color: #1a73e8;
    color: #1a73e8;
  }

  .webchat-session-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 8px;
  }

  .webchat-session-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    color: #333;
  }
  .webchat-session-item:hover {
    background: #f0f2f5;
  }
  .webchat-session-item.active {
    background: #e8f0fe;
    color: #1a73e8;
  }

  .webchat-session-title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .webchat-session-del {
    border: none;
    background: transparent;
    color: #999;
    cursor: pointer;
    font-size: 15px;
    padding: 0 4px;
  }
  .webchat-session-del:hover {
    color: #e33;
  }

  .webchat-session-empty {
    padding: 20px;
    text-align: center;
    color: #bbb;
    font-size: 13px;
  }

  .webchat-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .webchat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid #eee;
  }

  .webchat-header-title {
    font-size: 14px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .webchat-header-status {
    font-size: 12px;
    color: #888;
  }
  .webchat-header-status.ok {
    color: #52c41a;
  }
  .webchat-header-status.bad {
    color: #ff4d4f;
  }
  .webchat-header-status.warn {
    color: #faad14;
  }

  .webchat-header-title-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
  }

  .webchat-header-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: text;
  }

  .webchat-header-title-input {
    width: 240px;
    border: 1px solid #1a73e8;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 14px;
    outline: none;
  }

  /* 需求 2：agent 正在干活的转圈动画 */
  .webchat-busy {
    flex-shrink: 0;
    width: 14px;
    height: 14px;
    border: 2px solid #1a73e8;
    border-top-color: transparent;
    border-radius: 50%;
    animation: webchat-spin 0.8s linear infinite;
  }
  .webchat-busy-dot {
    width: 10px;
    height: 10px;
  }
  @keyframes webchat-spin {
    to {
      transform: rotate(360deg);
    }
  }

  .webchat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    position: relative; /* 供「跳到最底部」悬浮按钮定位 */
  }

  /* 懒加载：历史有更早内容时的「加载更早消息」按钮（置顶居中，浅色小按钮） */
  .webchat-load-older {
    display: block;
    margin: 0 auto 12px;
    border: 1px solid #d9d9d9;
    background: #fafafa;
    color: #666;
    border-radius: 14px;
    padding: 4px 14px;
    font-size: 12px;
    cursor: pointer;
  }
  .webchat-load-older:hover {
    border-color: #1a73e8;
    color: #1a73e8;
    background: #e8f0fe;
  }
  .webchat-load-older:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  /* 需求(MYS-210)：上翻历史时出现的「跳到最底部」悬浮按钮 */
  .webchat-jump-bottom {
    position: sticky;
    bottom: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    border: 1px solid #d9d9d9;
    background: rgba(255, 255, 255, 0.92);
    color: #1a73e8;
    border-radius: 50%;
    width: 34px;
    height: 34px;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  }
  .webchat-jump-bottom:hover {
    color: #fff;
    background: #1a73e8;
    border-color: #1a73e8;
  }
  .webchat-fade-enter-active,
  .webchat-fade-leave-active {
    transition: opacity 0.2s ease;
  }
  .webchat-fade-enter-from,
  .webchat-fade-leave-to {
    opacity: 0;
  }

  .webchat-msg {
    margin-bottom: 12px;
    display: flex;
  }
  .webchat-msg-user {
    justify-content: flex-start;
  }
  .webchat-msg-assistant {
    justify-content: flex-start;
  }

  .webchat-bubble {
    max-width: 80%;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 14px;
    line-height: 1.6;
    word-break: break-word;
  }
  .webchat-msg-user .webchat-bubble {
    background: #1a73e8;
    color: #fff;
  }
  .webchat-msg-assistant .webchat-bubble {
    background: #f5f5f5;
    color: #333;
  }
  .webchat-msg-error .webchat-bubble {
    background: #fff1f0;
    color: #ff4d4f;
  }

  /* ===== AI markdown 内容样式（MYS-206）：WindiCSS Preflight 重置了列表/表格，需补回 ===== */
  .webchat-bubble,
  .webchat-collapse-body {
    overscroll-behavior: contain;
  }
  /* 列表点位与编号 */
  .webchat-bubble :deep(ul),
  .webchat-collapse-body :deep(ul) {
    list-style: disc;
    padding-left: 1.5em;
    margin: 0.5em 0;
  }
  .webchat-bubble :deep(ol),
  .webchat-collapse-body :deep(ol) {
    list-style: decimal;
    padding-left: 1.5em;
    margin: 0.5em 0;
  }
  .webchat-bubble :deep(li),
  .webchat-collapse-body :deep(li) {
    margin: 0.15em 0;
  }
  /* 表格格子线 */
  .webchat-bubble :deep(table),
  .webchat-collapse-body :deep(table) {
    border-collapse: collapse;
    margin: 0.5em 0;
    width: 100%;
    display: block;
    overflow-x: auto;
  }
  .webchat-bubble :deep(th),
  .webchat-bubble :deep(td),
  .webchat-collapse-body :deep(th),
  .webchat-collapse-body :deep(td) {
    border: 1px solid #d9d9d9;
    padding: 6px 10px;
    text-align: left;
  }
  .webchat-bubble :deep(th),
  .webchat-collapse-body :deep(th) {
    background: #f0f0f0;
    font-weight: 600;
  }
  /* 标题 */
  .webchat-bubble :deep(h1),
  .webchat-collapse-body :deep(h1) {
    font-size: 1.5em;
    margin: 0.6em 0 0.4em;
  }
  .webchat-bubble :deep(h2),
  .webchat-collapse-body :deep(h2) {
    font-size: 1.3em;
    margin: 0.6em 0 0.4em;
  }
  .webchat-bubble :deep(h3),
  .webchat-collapse-body :deep(h3) {
    font-size: 1.15em;
    margin: 0.5em 0 0.35em;
  }
  .webchat-bubble :deep(h4),
  .webchat-bubble :deep(h5),
  .webchat-bubble :deep(h6),
  .webchat-collapse-body :deep(h4),
  .webchat-collapse-body :deep(h5),
  .webchat-collapse-body :deep(h6) {
    font-size: 1em;
    margin: 0.5em 0 0.3em;
  }
  /* 段落 */
  .webchat-bubble :deep(p),
  .webchat-collapse-body :deep(p) {
    margin: 0.4em 0;
  }
  /* 代码块（代码高亮 / mermaid 回退共用）。
     需求(MYS-209)：由深底（#282c34/#abb2bf）改为浅色易读风格——浅灰底 + 深色正文，
     与 hljs 的 github（浅色）高亮主题 token 颜色（深色系）搭配，保证在浅色气泡内可读。
     暗色模式（html.dark）下气泡为深色，为避免浅色 token 撞深底，代码块保持浅色卡片
     （github 浅色主题的 token 恒为深色），随页面暗色切换不冲突。 */
  .webchat-bubble :deep(.webchat-codeblock),
  .webchat-collapse-body :deep(.webchat-codeblock) {
    margin: 0.5em 0;
    padding: 10px 12px;
    background: #f6f8fa;
    color: #24292e;
    border-radius: 6px;
    font-size: 13px;
    line-height: 1.5;
    overflow-x: auto;
  }
  .webchat-bubble :deep(.webchat-codeblock code),
  .webchat-collapse-body :deep(.webchat-codeblock code) {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    white-space: pre;
    word-break: normal;
    background: transparent;
  }
  /* 暗色页面下代码块保持浅色卡片：hljs 用的是 github(浅色)主题，token 恒为深色，
     深色页面上若让代码块随背景变深会致 token 撞底不可读，故恒保浅底。 */
  .dark .webchat-bubble :deep(.webchat-codeblock),
  .dark .webchat-collapse-body :deep(.webchat-codeblock) {
    background: #f6f8fa;
    color: #24292e;
  }
  /* 行内代码 */
  .webchat-bubble :deep(code:not(.webchat-codeblock code)),
  .webchat-collapse-body :deep(code:not(.webchat-codeblock code)) {
    background: rgba(27, 31, 35, 0.08);
    padding: 0.15em 0.35em;
    border-radius: 4px;
    font-size: 0.9em;
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  }
  /* 引用 */
  .webchat-bubble :deep(blockquote),
  .webchat-collapse-body :deep(blockquote) {
    margin: 0.5em 0;
    padding: 4px 12px;
    border-left: 3px solid #d9d9d9;
    color: #666;
    background: rgba(0, 0, 0, 0.03);
  }
  /* mermaid 图表容器 */
  .webchat-bubble :deep(.webchat-mermaid),
  .webchat-collapse-body :deep(.webchat-mermaid) {
    margin: 0.5em 0;
    overflow-x: auto;
    background: #fff;
    border-radius: 6px;
    padding: 8px;
  }

  /* 权限审批卡片（需求 197：从消息区移到输入框上方，宽度与输入框对齐） */
  .webchat-input-area .webchat-msg {
    margin-bottom: 10px;
    margin-right: 68px; /* 与发送按钮+间距同宽，使卡片右边缘贴齐输入框 */
  }
  .webchat-input-area .webchat-bubble {
    max-width: none;
    width: 100%;
    box-sizing: border-box;
  }
  .webchat-input-area .webchat-perm {
    border: 1px solid #d9d9d9;
    background: #fafafa;
  }
  .webchat-perm-label {
    font-size: 14px;
    color: #333;
  }
  .webchat-perm-label strong {
    color: #1a73e8;
  }
  .webchat-perm-hint {
    margin-top: 4px;
    font-size: 12px;
    color: #999;
  }
  .webchat-perm-actions {
    display: flex;
    gap: 8px;
    margin-top: 10px;
  }
  .webchat-perm-btn {
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 13px;
    cursor: pointer;
  }
  .webchat-perm-allow {
    background: #1a73e8;
    color: #fff;
  }
  .webchat-perm-deny {
    background: #f0f2f5;
    color: #333;
    border: 1px solid #d9d9d9;
  }
  .webchat-perm-done {
    margin-top: 10px;
    font-size: 12.5px;
    font-weight: 600;
    color: #666;
  }

  /* 需求：折叠块（思考过程/工具调用）高度紧凑，上下紧挨 */
  .webchat-collapse {
    margin: 0 0 2px;
  }
  .webchat-collapse-header {
    display: flex;
    align-items: center;
    gap: 4px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 12px;
    color: #888;
    padding: 2px 0;
    width: 100%;
    text-align: left;
  }
  .webchat-collapse-summary {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #999;
  }
  .webchat-collapse-arrow {
    display: inline-block;
    width: 14px;
  }
  .webchat-collapse-body {
    padding: 8px 12px;
    background: #fafafa;
    border-radius: 6px;
    font-size: 13px;
    color: #555;
    word-break: break-word;
    white-space: pre-wrap;
  }

  .webchat-typing span {
    display: inline-block;
    width: 6px;
    height: 6px;
    margin-right: 4px;
    border-radius: 50%;
    background: #bbb;
    animation: webchat-blink 1.2s infinite both;
  }
  .webchat-typing span:nth-child(2) {
    animation-delay: 0.2s;
  }
  .webchat-typing span:nth-child(3) {
    animation-delay: 0.4s;
  }
  @keyframes webchat-blink {
    0%,
    80%,
    100% {
      opacity: 0.3;
    }
    40% {
      opacity: 1;
    }
  }

  .webchat-input-area {
    border-top: 1px solid #eee;
    padding: 12px 16px 8px;
  }
  .webchat-input-box {
    display: flex;
    align-items: flex-end;
    gap: 8px;
  }
  /* 需求：输入框左侧工具区（自动审批 + 停止）+ 输入框 + 发送，统一 40px 高度 */
  .webchat-input-tools {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  /* 自动审批 / 停止：与「发送」按钮同风格（蓝底白字圆角），高度统一 40px */
  .webchat-tool-btn {
    box-sizing: border-box;
    height: 40px;
    border: 1px solid #1a73e8;
    background: #fff;
    color: #1a73e8;
    border-radius: 6px;
    padding: 0 12px;
    cursor: pointer;
    font-size: 12px;
    line-height: 1;
    white-space: nowrap;
  }
  .webchat-tool-btn:hover {
    background: #e8f0fe;
  }
  /* 自动审批开启 → 高亮（实心品牌蓝） */
  .webchat-tool-btn.on {
    background: #1a73e8;
    color: #fff;
  }
  .webchat-tool-btn.on:hover {
    background: #1663c5;
  }
  .webchat-input-box textarea {
    box-sizing: border-box;
    flex: 1;
    height: 40px;
    min-height: 40px;
    max-height: 160px;
    resize: none;
    border: 1px solid #d9d9d9;
    border-radius: 6px;
    padding: 10px 10px;
    font-size: 14px;
    line-height: 1.4;
    outline: none;
  }
  .webchat-input-box textarea:focus {
    border-color: #1a73e8;
  }
  .webchat-send {
    box-sizing: border-box;
    height: 40px;
    border: none;
    background: #1a73e8;
    color: #fff;
    border-radius: 6px;
    padding: 0 16px;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
  }
  .webchat-send:disabled {
    background: #ccc;
    cursor: not-allowed;
  }
  .webchat-input-hint {
    margin-top: 6px;
    font-size: 12px;
    color: #bbb;
    text-align: center;
  }
</style>
