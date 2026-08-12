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
              v-html="renderMarkdown(m.content)"
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
              v-html="renderMarkdown(m.content)"
            ></div>
          </div>
          <div v-else class="webchat-msg webchat-msg-assistant">
            <div class="webchat-bubble" v-html="renderMarkdown(m.content)"></div>
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
  import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue';
  import { PicoWs, defaultReasonixWsUrl } from '/@/api/aiAgent/ws';
  import { renderMarkdownToHtml as renderMarkdown } from './markdown';
  import { getAgentConfig } from '/@/api/aiAgent';

  interface ChatMsg {
    key?: string;
    role: 'user' | 'assistant';
    kind?: string;
    content: string;
    open?: boolean;
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
  // 当前流式「思考过程」折叠块的 key（同一逻辑思考常被后端拆成多个 message.create
  // thought-1/thought-2，累积到同一折叠块避免拆泡）。
  let openThoughtKey: string | null = null;

  function clearOpenThought() {
    openThoughtKey = null;
  }

  const activeSess = computed(() => sessions.value.find((s) => s.id === activeId.value) || null);
  const currentMessages = computed(() => activeSess.value?.messages || []);
  // 待处理的权限请求：取当前会话第一条未处理（permDone 为空）的 permission 消息。
  // 由消息状态派生，切换会话/允许/拒绝/回执后自动同步，与消息历史共享同一份 permDone。
  const pendingPerm = computed<ChatMsg | null>(() => {
    const msgs = activeSess.value?.messages || [];
    return msgs.find((m) => m.kind === 'permission' && !m.permDone) || null;
  });

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
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.value));
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
      return calls.map((c: any) => JSON.stringify(c, null, 2)).join('\n\n');
    }
    return payload.content || '';
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

  // 工具调用：从 formatToolCalls 生成的 JSON（多 call 以空行连接）逐个提取
  // function.name + 参数 JSON 扁平化简写，拼成「名称(参数…)、名称(参数…)」。
  function toolCallSummary(content: string): string {
    if (!content) return '';
    const parts: string[] = [];
    // 每个 call 非贪婪匹配到 name 与 arguments（arguments 可能缺失）
    const callRe =
      /"function"\s*:\s*\{[\s\S]*?"name"\s*:\s*"([^"]+)"[\s\S]*?(?:"arguments"\s*:\s*"((?:[^"\\]|\\.)*)")?\s*\}/g;
    let mm: RegExpExecArray | null;
    let guard = 0;
    while ((mm = callRe.exec(content)) && parts.length < 4 && guard++ < 20) {
      const name = mm[1];
      const rawArgs = mm[2] ? flattenArgs(mm[2]) : '';
      parts.push(rawArgs ? `${name}(${clampChars(rawArgs, 20)})` : name);
    }
    if (!parts.length) return clampChars(plainText(content), SUMMARY_LEN);
    return clampChars(parts.join('、'), SUMMARY_LEN);
  }

  // 把 arguments 的转义 JSON 压成「k=v, k=v」简写；解析失败时返回空串
  function flattenArgs(raw: string): string {
    try {
      const obj = JSON.parse(raw.replace(/\\n/g, '').replace(/\\"/g, '"').replace(/\\\\/g, '\\'));
      if (obj == null) return '';
      const pairs = Object.entries(obj).map(([k, v]) => {
        const val = v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v);
        return `${k}=${val}`;
      });
      return pairs.join(', ');
    } catch (e) {
      return '';
    }
  }

  function handleSessionList(payload: any) {
    const serverList = Array.isArray(payload.sessions) ? payload.sessions : [];
    const stored: Session[] = serverList.map((ss: any) => ({
      id: ss.id,
      title: ss.title || '新会话',
      messages: [],
      busy: !!ss.running, // 需求 2：服务端回合进行中 → 忙碌
    }));
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
    s.messages = raw.map((m: any) => ({
      key: 'his' + msgSeq++,
      role: m.role === 'user' ? 'user' : 'assistant',
      kind: m.kind || (m.role === 'user' ? '' : 'text'),
      content: m.content || '',
      open: false,
    }));
    if (payload.title && s.title !== payload.title) s.title = payload.title;
    s.busy = !!payload.running; // 需求 2：恢复会话时同步忙碌
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
  });

  onBeforeUnmount(() => {
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
