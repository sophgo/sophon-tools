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

      <div ref="messagesEl" class="webchat-messages">
        <template v-for="m in currentMessages" :key="m.key">
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
      </div>

      <footer class="webchat-input-area">
        <div v-if="pendingPerm" class="webchat-msg webchat-msg-assistant">
          <div class="webchat-bubble webchat-perm">
            <div class="webchat-perm-label">需要批准：<strong>{{ pendingPerm.permTitle }}</strong></div>
            <div class="webchat-perm-hint">Agent 请求执行上述操作，是否允许？(60 秒未操作将自动拒绝)</div>
            <div class="webchat-perm-actions">
              <button class="webchat-perm-btn webchat-perm-allow" type="button" @click="respondPermission(pendingPerm.permReqId, true, pendingPerm)">允许</button>
              <button class="webchat-perm-btn webchat-perm-deny" type="button" @click="respondPermission(pendingPerm.permReqId, false, pendingPerm)">拒绝</button>
            </div>
          </div>
        </div>
        <div class="webchat-input-box">
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

  let ws: PicoWs | null = null;
  let forwardKey = '';
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
  // 待处理的权限请求：取当前会话第一条未处理（permDone 为空）的 permission 消息。
  // 由消息状态派生，切换会话/允许/拒绝/回执后自动同步，与消息历史共享同一份 permDone。
  const pendingPerm = computed<ChatMsg | null>(() => {
    const msgs = activeSess.value?.messages || [];
    return msgs.find((m) => m.kind === 'permission' && !m.permDone) || null;
  });

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
          saveSessions();
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
  let renderTimer: ReturnType<typeof setTimeout> | null = null;
  watch(
    () => currentMessages.value.map((m) => m.key + ':' + m.content),
    () => {
      if (renderTimer) clearTimeout(renderTimer);
      renderTimer = setTimeout(() => {
        const msgs = currentMessages.value || [];
        for (const m of msgs) {
          // user/error/permission 内容不渲染 markdown；assistant 文本/思考/工具调用渲染
          if (m.role === 'assistant' && m.kind !== 'permission' && m.content) {
            // 旧持久化的工具调用可能是裸 JSON，渲染前规整为可读文本（幂等，自动修复历史）
            if (m.kind === 'tool_calls') m.content = displayToolCalls(m.content);
            bumpRender(m);
          }
        }
      }, 150);
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
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(snap));
    } catch (e) {
      /* ignore */
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
    const s: Session = { id: uuid(), title: '新会话', messages: [], busy: false };
    sessions.value.unshift(s);
    activeId.value = s.id;
    saveSessions();
    saveActive();
    draft.value = '';
    errorMsg.value = '';
    clearOpenThought();
    resetConnection();
    return s;
  }

  function switchSession(id: string) {
    if (!sessions.value.some((s) => s.id === id)) return;
    activeId.value = id;
    saveActive();
    clearOpenThought();
    resetConnection();
  }

  function deleteSession(id: string) {
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
  function handleMessage(msg: any) {
    if (!msg || !msg.type) return;
    const type = msg.type;
    const payload = msg.payload || {};
    if (msg.session_id) bindServerSession(msg.session_id);
    // 记录该会话最后活动帧时间（busy 超时兜底用）：该会话收到任何帧即视为仍在运转
    if (msg.session_id) sessionLastWsAt[msg.session_id] = Date.now();

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
        setSessionBusy(msg.session_id || payload.session_id, !!payload.busy);
        break;
      case 'session.updated':
        // 需求 3：自定义标题后的回执
        applyTitle(msg.session_id, payload.title);
        break;
      case 'permission.request':
        handlePermissionRequest(msg.session_id, payload);
        break;
      case 'permission.responded':
        markPermissionDone(payload.request_id, !!payload.allow);
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

  /** permission.request：Agent 触发需用户批准的工具调用 → 在活跃会话插入审批卡片。 */
  function handlePermissionRequest(sessionId: string | undefined, payload: any) {
    const reqId = payload?.request_id;
    const toolCall = payload?.tool_call || {};
    if (reqId == null) return;
    const s = ensureSession();
    s.messages.push({
      key: 'perm' + msgSeq++,
      role: 'assistant',
      kind: 'permission',
      content: '',
      permReqId: reqId,
      permTitle: (toolCall.title as string) || '工具调用',
      permDone: null,
      open: false,
    });
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
      }
    });
  }

  function applyTitle(sid: string | undefined, title: string | undefined) {
    if (!sid || !title) return;
    const s = sessions.value.find((x) => x.id === sid);
    if (s) s.title = title;
  }

  function bindServerSession(serverId: string) {
    const s = activeSess.value;
    if (!s || !serverId) return;
    if (s.id !== serverId) {
      s.id = serverId;
      activeId.value = serverId;
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
      // 连续 text 合并到最近一条 assistant 文本（修复拆泡）
      clearOpenThought();
      // 兜底1：最终答案内容开始输出即本地清 typing（需求：收到 text 首条置 false；
      // 服务端首 chunk 本应发 typing.stop，此处防丢包/切会话时序导致的残留）
      typing.value = false;
      const last = s.messages[s.messages.length - 1];
      if (
        last &&
        last.role === 'assistant' &&
        !last.kind &&
        !s.messages.some((m) => m.key === messageId)
      ) {
        last.content += content;
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
    saveSessions();
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
    saveSessions();
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

  // 把一条工具调用规整为可读的「工具名: 内容」（需求：不再显示裸 JSON）。
  // 兼容两种载荷形态：
  //   - pico/旧形态：{function:{name,arguments}} → 「工具名: 参数主内容」
  //   - ACP 现代形态 ToolCallState：{toolCallId,title,kind,status} → 与后端
  //     toolCallSummary 同格式（title · kind · status），保证前端实时内容与后端
  //     持久化 history 一致，历史合并去重时不产生重复。
  function toolCallLine(c: any): string {
    if (c == null) return '';
    if (typeof c !== 'object') return String(c);
    if (c.function && typeof c.function === 'object') {
      const name = c.function.name || '';
      const body = extractArgs(c.function.arguments);
      return [name, body].filter((x) => x).join(': ').trim();
    }
    const bits: string[] = [];
    if (c.title) bits.push(c.title);
    else if (c.toolCallId) bits.push(c.toolCallId);
    if (c.kind) bits.push(c.kind);
    if (typeof c.status === 'string' && c.status) bits.push(c.status);
    return bits.join(' · ');
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
    const keyOf = (m: ChatMsg) => m.role + '|' + (m.kind || '') + '|' + (m.content || '');
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
      };
    });
    // 保留本地尚未同步到服务端的会话
    const storedIds = new Set(stored.map((s) => s.id));
    sessions.value.forEach((s) => {
      if (!storedIds.has(s.id)) stored.push(s);
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

  function handleSessionHistory(payload: any) {
    const sid = payload.session_id;
    const raw = Array.isArray(payload.messages) ? payload.messages : [];
    const s = sessions.value.find((x) => x.id === sid);
    if (!s) return;
    // 需求(MYS-209)：后端一轮回答会按 message_id 拆成多条 message.create，落库后
    // history 里会出现成段的相邻 text 小片段（agent 一条完整回答被切成 text-1..text-N）。
    // 若逐条各自成泡会把「同一段连续输出」显示成一串碎气泡。故在加载历史时把
    // 相邻的 assistant 纯文本（非 thought/tool_calls）累积合并为一个气泡；
    // 遇 user / thought / tool_calls 则视为新气泡（正确开新泡，不跨逻辑段错误合并）。
    const serverMsgs: ChatMsg[] = [];
    for (const m of raw) {
      const role = m.role === 'user' ? 'user' : 'assistant';
      const kind = m.kind || (m.role === 'user' ? '' : 'text');
      const content =
        m.content && m.kind === 'tool_calls' ? displayToolCalls(m.content) : m.content || '';
      const isPlainText = role === 'assistant' && kind !== 'thought' && kind !== 'tool_calls';
      // 纯文本空内容无信息量（源是流式片段，可能为空白），跳过避免空泡
      if (isPlainText && !content) continue;
      const prev = serverMsgs[serverMsgs.length - 1];
      if (isPlainText && prev && prev.role === 'assistant' && !prev.kind) {
        prev.content += content;
      } else {
        serverMsgs.push({ key: 'his' + msgSeq++, role, kind, content, open: false });
      }
    }
    // 请求 3：以服务端历史为权威基线，并合并本地尚未同步到的消息（在途内容、权限审批记录），
    // 避免刷新/换浏览器后历史缺失；同内容按 role+kind+content 去重，防止重复。
    s.messages = mergeHistory(s.messages, serverMsgs);
    if (payload.title && s.title !== payload.title) s.title = payload.title;
    restoreBusy(s.id, !!payload.running); // 需求 4：恢复 busy 时走一次性校准
    clearOpenThought();
    saveSessions();
    scrollToBottom();
  }

  function syncFromServer() {
    if (!ws || !ws.ready) return;
    ws.sendFrame({ type: 'session.list' }, { queued: true });
  }

  function pullHistory(sessionId: string) {
    if (!ws || !ws.ready || !sessionId) return;
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
    // 需求 3：默认标题用第一条用户消息前 8 个字（本地即时更新，服务端 EnsureTitle 亦会设）
    if (!s.title || s.title === '新会话') {
      s.title = defaultTitleFromText(content);
    }
    const serverId = s.id;
    saveSessions();
    draft.value = '';
    autoGrow();
    scrollToBottom();

    try {
      ws.send(serverId, content, []);
      sending.value = false;
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
    return Array.from(t).slice(0, 8).join('') || '新会话';
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
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  function scrollToBottom() {
    nextTick(() => {
      if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
    });
  }

  // ---------- 连接 ----------
  async function connect() {
    if (!forwardKey) {
      const cfg = await getAgentConfig();
      forwardKey = cfg?.forwardKey || '';
    }
    if (ws) {
      ws.close();
      ws = null;
    }
    const url = defaultReasonixWsUrl(window.location.hostname);
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
    // 兜底2/4：启动忙状态扫描（防回合永不结束致 busy 卡死 + 恢复型 busy 一次性校准）
    busyStallTimer = setInterval(() => {
      clearStalledBusy();
      calibrateRestoredBusy();
    }, BUSY_SCAN_INTERVAL);
  });

  onBeforeUnmount(() => {
    if (busyStallTimer) {
      clearInterval(busyStallTimer);
      busyStallTimer = null;
    }
    if (renderTimer) clearTimeout(renderTimer);
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

  .webchat-collapse {
    margin-bottom: 8px;
  }
  .webchat-collapse-header {
    display: flex;
    align-items: center;
    gap: 4px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 13px;
    color: #666;
    padding: 4px 0;
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
  .webchat-input-box textarea {
    flex: 1;
    resize: none;
    border: 1px solid #d9d9d9;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 14px;
    line-height: 1.5;
    outline: none;
  }
  .webchat-input-box textarea:focus {
    border-color: #1a73e8;
  }
  .webchat-send {
    border: none;
    background: #1a73e8;
    color: #fff;
    border-radius: 6px;
    padding: 8px 16px;
    cursor: pointer;
    font-size: 14px;
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
