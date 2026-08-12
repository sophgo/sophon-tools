/**
 * chat.js — 聊天核心逻辑（T2）
 *
 * 职责：
 *   - WebSocket 对接：初始化 PicoWS，接收消息分发
 *   - 消息渲染：按 message_id 创建/更新气泡，流式打字机效果
 *   - 折叠块：thought / tool_calls 按 kind 折叠展示
 *   - 会话管理：新建/切换/删除会话，localStorage 持久化
 *   - 发送逻辑：Enter 发送 / Shift+Enter 换行，图片 FileReader → base64 → media
 *   - typing.start/stop 显示「输入中…」
 *
 * 依赖：ws.js（PicoWS）、markdown.js（T3，Markdown 渲染）、settings.js（T3，设置面板）。
 * 渲染策略：增量 DOM 操作（按消息到达顺序 append），message_id 去重与累积。
 */
(function () {
  'use strict';

  var SETTINGS_KEY = 'pico-web-chat.settings';
  var SESSIONS_KEY = 'pico-web-chat.sessions';
  var ACTIVE_KEY = 'pico-web-chat.active-session';

  // ---------- 工具函数 ----------

  /** 部署层注入配置（T6）：ws.js 提供 PicoConfig.injected()；缺失时视为无注入 */
  function injectedConfig() {
    if (window.PicoConfig && typeof window.PicoConfig.injected === 'function') {
      try { return window.PicoConfig.injected(); } catch (e) { return null; }
    }
    return null;
  }

  /** 默认 Reasonix WS 地址：注入配置优先，否则当前主机 + 默认端口 */
  function defaultReasonixWsUrl() {
    var inj = injectedConfig();
    if (inj && inj.wsUrl) return inj.wsUrl;
    return 'ws://' + window.location.hostname + ':18990/agent/ws';
  }

  function getSettings() {
    var inj = injectedConfig();
    var defaults = {
      wsUrl: defaultReasonixWsUrl(),
      token: inj && inj.token ? inj.token : '',
      model: 'DeepSeek-V4-Flash-0731'
    };
    try {
      var raw = localStorage.getItem(SETTINGS_KEY);
      var s = raw ? JSON.parse(raw) : {};
      s = Object.assign({}, defaults, s);
      // T2 阶段设置面板保存逻辑由 T3 实现；localStorage 无值时回退读设置面板当前值
      if (!s.token || !s.wsUrl) {
        var tokenEl = document.getElementById('setting-token');
        var wsEl = document.getElementById('setting-ws');
        if (tokenEl && tokenEl.value) s.token = tokenEl.value;
        if (wsEl && wsEl.value) s.wsUrl = wsEl.value;
      }
      // 开箱即用（T6）：localStorage 未显式保存（或已清除）时，用注入配置兜底
      if (!s.token && inj && inj.token) s.token = inj.token;
      return s;
    } catch (e) {
      return defaults;
    }
  }

  function uuid() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    // 兜底：Math.random 生成 v4 风格 UUID
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function timeStr(ts) {
    var d = ts ? new Date(ts) : new Date();
    var hh = ('0' + d.getHours()).slice(-2);
    var mm = ('0' + d.getMinutes()).slice(-2);
    return hh + ':' + mm;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** Markdown 渲染：交给 markdown.js（含 DOMPurify 消毒）；库缺失时降级纯文本 */
  function renderMarkdown(content) {
    if (window.Markdown && typeof window.Markdown.renderMarkdown === 'function') {
      try {
        return window.Markdown.renderMarkdown(content);
      } catch (e) {
        return '<p>' + escapeHtml(content) + '</p>';
      }
    }
    return '<p>' + escapeHtml(content) + '</p>';
  }

  // ---------- 状态 ----------

  var state = {
    ws: null,
    settings: getSettings(),
    sessions: loadSessions(),
    activeId: null,   // 在下方单独赋值（见 loadActive 调用）
    messagesEl: null,
    inputEl: null,
    // message_id -> { el, content, kind, model }
    live: {},
    typingEl: null,
    sending: false,
    pendingSendSessionId: null,   // 最近一次发送消息的前端会话 id，用于正确绑定服务端 session_id
    // 合并状态：一轮无用户打断的连续 text 归并到同一气泡（修复连续信息拆泡问题）。
    // 服务端（agentproxy）可能把同一回复拆成多个 text message_id（如 text-1/text-2），
    // 若逐条 create 会各建泡。用该状态把相邻 text create 累积到同一个气泡。
    merge: null   // { id, el, content, model }
  };
  state.activeId = loadActiveId(state.sessions);

  function loadSessions() {
    try {
      var raw = localStorage.getItem(SESSIONS_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function loadActiveId(sessions) {
    var id = localStorage.getItem(ACTIVE_KEY);
    if (id && sessions.some(function (s) { return s.id === id; })) return id;
    return null;
  }

  function saveSessions() {
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(state.sessions));
    } catch (e) { /* 存储满等忽略 */ }
  }

  function saveActive() {
    try {
      if (state.activeId) localStorage.setItem(ACTIVE_KEY, state.activeId);
      else localStorage.removeItem(ACTIVE_KEY);
    } catch (e) { /* 忽略 */ }
  }

  function getActiveSession() {
    return state.sessions.find(function (s) { return s.id === state.activeId; }) || null;
  }

  // ---------- 会话管理 ----------

  /**
   * 切换/新建会话后重开连接。
   * 协议约束（实测）：服务端会话绑定连接生命周期，跨连接不可恢复——
   * 旧连接创建的 session_id 在新连接上会被忽略。因此切换会话必须重开
   * 连接，让服务端「忘记」上一个会话，当前会话首次空 sid 发送时才能建独立会话。
   */
  function resetConnection() {
    if (state.ws) state.ws.reconnect();
  }

  function newSession() {
    var s = {
      id: uuid(),
      title: '新会话',
      createdAt: Date.now(),
      messages: []
    };
    state.sessions.unshift(s);
    state.activeId = s.id;
    saveSessions();
    saveActive();
    renderSessionList();
    renderChat();
    clearInput();
    resetConnection();
    return s;
  }

  function switchSession(id) {
    if (!state.sessions.some(function (s) { return s.id === id; })) return;
    state.activeId = id;
    saveActive();
    renderSessionList();
    renderChat();
    resetConnection();
  }

  function deleteSession(id) {
    state.sessions = state.sessions.filter(function (s) { return s.id !== id; });
    if (state.activeId === id) {
      state.activeId = state.sessions.length ? state.sessions[0].id : null;
    }
    saveSessions();
    saveActive();
    renderSessionList();
    renderChat();
    resetConnection();
  }

  function ensureSession() {
    if (!getActiveSession()) return newSession();
    return getActiveSession();
  }

  /**
   * 绑定服务端返回的 webchat session_id 到本地会话（跨浏览器持久主键）。
   * session.create 回传的 id 是服务端 agent_session 主键，跨设备一致；
   * 用它替换本地临时 uuid，作为持久主键。
   */
  function bindServerSession(serverSessionId) {
    if (!serverSessionId) return;
    var targetId = state.pendingSendSessionId || state.activeId;
    var s = state.sessions.find(function (x) { return x.id === targetId; });
    if (!s) return;
    if (s.id !== serverSessionId) {
      var idx = state.sessions.findIndex(function (x) { return x.id === s.id; });
      if (idx >= 0) state.sessions[idx].id = serverSessionId;
      if (state.activeId === s.id) state.activeId = serverSessionId;
      s.id = serverSessionId;
    }
    s.serverSessionId = serverSessionId;
    state.pendingSendSessionId = null;
    saveSessions();
    saveActive();
    renderSessionList();
  }

  /** 把一条消息追加到当前会话并持久化 */
  function appendToSession(msg) {
    var s = ensureSession();
    s.messages.push(msg);
    var titleChanged = false;
    // 首条用户消息作为标题
    if (msg.role === 'user' && (s.title === '新会话' || !s.title)) {
      s.title = (msg.content || '').replace(/\s+/g, ' ').slice(0, 20) || '新会话';
      titleChanged = true;
    }
    saveSessions();
    renderSessionList();
    // 顶部标题同步（首条消息生成标题后，右侧聊天区标题不再显示「新会话」）
    if (titleChanged) {
      var titleEl = $('.chat-title');
      if (titleEl) titleEl.textContent = s.title;
    }
  }

  // ---------- 用户消息渲染 ----------

  function renderUserMessage(content, media, opts) {
    if (!opts || opts.persist !== false) {
      appendToSession({ role: 'user', content: content, media: media || [], time: Date.now() });
    }

    // 用户消息打断 AI text 流：之后到达的 text 应另起气泡，清除合并上下文
    clearMerge();

    var wrap = document.createElement('div');
    wrap.className = 'msg msg-user';

    // 文本内容
    var bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.textContent = content;
    wrap.appendChild(bubble);

    // 图片预览
    if (media && media.length) {
      var imgWrap = document.createElement('div');
      imgWrap.className = 'msg-images';
      media.forEach(function (dataUrl) {
        var img = document.createElement('img');
        img.src = dataUrl;
        img.alt = '上传的图片';
        img.className = 'msg-image';
        imgWrap.appendChild(img);
      });
      wrap.insertBefore(imgWrap, bubble);
    }

    state.messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  // ---------- AI 消息渲染 ----------

  /** 清除 AI text 合并上下文。会话切换/新建、用户发消息时调用。 */
  function clearMerge() {
    state.merge = null;
  }

  /**
   * 处理 message.create：首次创建消息气泡。
   * 同一 message_id 重复 create → 视为更新（幂等）。
   */
  function handleCreate(payload) {
    var messageId = payload.message_id;
    var kind = payload.kind || 'text';
    var content = payload.content || '';
    var model = payload.model_name || '';

    if (messageId && state.live[messageId]) {
      // 重复 create：更新已有气泡
      updateBubble(messageId, content, kind);
      return;
    }

    // 正文不带 model_name 时沿用会话最近出现的模型名（thought 块通常带）
    if (!model) {
      var sess = getActiveSession();
      if (sess && sess.messages.length) {
        for (var i = sess.messages.length - 1; i >= 0; i--) {
          if (sess.messages[i].role === 'assistant' && sess.messages[i].model) {
            model = sess.messages[i].model;
            break;
          }
        }
      }
      if (!model) model = state.settings.model || 'AI';
    }

    // 合并策略：一段连续 assistant 输出可能被服务端拆成多个 text message_id
    //（如 text-1/text-2，中间无用户消息）。这种情况下追加到上一个 text 气泡，
    // 避免同一轮回复被拆进不同气泡。
    if (kind === 'text' && state.merge && state.merge.el) {
      var mergedContent = state.merge.content + content;
      state.merge.content = mergedContent;
      // 更新合并根气泡 DOM 内容
      var mergedBubble = state.merge.el.querySelector('.msg-bubble');
      if (mergedBubble) mergedBubble.innerHTML = renderMarkdown(mergedContent);
      // 根条目 content 同步为合并后全量（后续 update 都在此累积）
      var rootEntry = state.live[state.merge.id];
      if (rootEntry) rootEntry.content = mergedContent;
      // 新 message_id 也映射到同一根气泡，便于后续 update/create 命中
      state.live[messageId] = {
        el: state.merge.el,
        content: mergedContent,
        kind: 'text',
        model: model,
        messageIdKey: messageId,
        sessionId: state.activeId,
        mergeRootId: state.merge.id,   // 本条目是合并别名：指向根气泡
        mergeAlias: true
      };
      // 同步与会话历史里该 assistant text 消息（累加）
      mergePersistToSession(mergedContent, model);
      scrollToBottom();
      return;
    }

    var el;
    if (kind === 'thought') {
      el = buildCollapse('思考过程', content);
      // 折叠块（思考/工具）打断连续正文：其后新 text 另起一组
      clearMerge();
    } else if (kind === 'tool_calls') {
      el = buildCollapse('工具调用', formatToolCalls(payload));
      // 工具调用片段不应与正文合并
      clearMerge();
    } else {
      el = buildTextMessage(content, model);
      // 记录 text 气泡为后续合并目标（thought/tool_calls 不参与合并）
      state.merge = { id: messageId, el: el, content: content, model: model };
    }

    state.live[messageId] = {
      el: el,
      content: content,
      kind: kind,
      model: model,
      messageIdKey: messageId,
      // 记录该消息归属的会话（thought 与正文可能同会话，这里存当前活动会话）
      sessionId: state.activeId
    };

    state.messagesEl.appendChild(el);
    scrollToBottom();

    // 持久化到当前会话
    if (kind !== 'text') {
      // thought / tool_calls 直接持久化
      appendToSession({
        role: 'assistant',
        kind: kind,
        content: content,
        model: model,
        message_id: messageId,
        time: Date.now()
      });
    } else {
      // 正文：记录待持久化状态，避免后续 update 重复写
      var s = getActiveSession();
      if (s) {
        var found = s.messages.some(function (m) {
          return m.message_id && m.message_id === messageId;
        });
        if (!found) {
          appendToSession({
            role: 'assistant',
            content: content,
            model: model,
            message_id: messageId,
            time: Date.now()
          });
        }
      }
    }
  }

  /**
   * 合并 text 后把最新完整内容写回会话历史（合并到该 assistant 最近一条 text 消息）。
   */
  function mergePersistToSession(content, model) {
    var s = getActiveSession();
    if (!s) return;
    for (var i = s.messages.length - 1; i >= 0; i--) {
      var m = s.messages[i];
      if (m.role === 'assistant' && (m.kind || 'text') === 'text') {
        m.content = content;
        if (model) m.model = model;
        saveSessions();
        return;
      }
    }
  }

  /**
   * 处理 message.update：更新同一 message_id 的气泡内容。
   * 兼容两种语义：
   *   - 全量扩展：update.content 是当前内容的前缀扩展 → 直接替换
   *   - 增量：update.content 是追加片段 → 累积
   */
  function handleUpdate(payload) {
    var messageId = payload.message_id;
    var entry = messageId ? state.live[messageId] : null;

    // 合并别名：同轮连续 text 归并到同一根气泡后，其余 message_id 的 update
    // 也应对根气泡累积，避免只更新别名本条造成内容割裂。
    if (entry && entry.mergeRootId && state.merge && state.merge.content !== undefined) {
      var rootEntry = state.live[entry.mergeRootId];
      if (rootEntry) {
        var mNext = accumulate(state.merge.content, payload.content || '');
        state.merge.content = mNext;
        rootEntry.content = mNext;
        updateBubbleContent(rootEntry.el, 'text', mNext, rootEntry.model);
        persistAssistantUpdate(rootEntry, mNext);
        scrollToBottom();
        return;
      }
    }

    if (!messageId || !entry) {
      // 未跟踪的 update：当作 create 兜底
      handleCreate(payload);
      return;
    }
    var next = accumulate(entry.content, payload.content || '');
    entry.content = next;
    // 若命中当前合并根气泡，同步合并累积值
    if (state.merge && state.merge.id === messageId) state.merge.content = next;
    updateBubbleContent(entry.el, entry.kind, next, entry.model);
    // 同步持久化消息内容（流式 update 结束后刷新历史仍是最新内容）
    persistAssistantUpdate(entry, next);
    scrollToBottom();
  }

  /** 把 AI 消息的最新内容写回会话历史 */
  function persistAssistantUpdate(entry, content) {
    var s = getActiveSession();
    if (!s) return;
    var msg = s.messages.find(function (m) {
      return m.role === 'assistant' && m.kind === entry.kind && m.message_id === entry.messageIdKey;
    });
    // 若无 message_id 匹配（正文按顺序最后一条），更新同 kind 的最近一条
    if (!msg) {
      for (var i = s.messages.length - 1; i >= 0; i--) {
        if (s.messages[i].role === 'assistant' && (s.messages[i].kind || 'text') === entry.kind) {
          msg = s.messages[i];
          break;
        }
      }
    }
    if (msg) {
      msg.content = content;
      saveSessions();
    }
  }

  function accumulate(current, incoming) {
    if (!incoming) return current;
    if (!current) return incoming;
    // 全量语义：incoming 以 current 为前缀（或更长）
    if (incoming.length >= current.length && incoming.indexOf(current) === 0) {
      return incoming;
    }
    // 仍是全量但非前缀（罕见）：取更长者
    if (incoming.length > current.length) {
      return incoming;
    }
    // 增量语义：追加
    return current + incoming;
  }

  function buildTextMessage(content, model) {
    var wrap = document.createElement('div');
    wrap.className = 'msg msg-assistant';

    var meta = document.createElement('div');
    meta.className = 'msg-meta';
    var time = document.createElement('span');
    time.className = 'msg-time';
    time.textContent = timeStr();
    meta.appendChild(time);
    wrap.appendChild(meta);

    var bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    // AI 内容不可信：Markdown 渲染 + DOMPurify 消毒（降级为纯文本）
    bubble.innerHTML = renderMarkdown(content);
    wrap.appendChild(bubble);

    return wrap;
  }

  function updateBubbleContent(el, kind, content, model) {
    if (kind === 'thought' || kind === 'tool_calls') {
      var body = el.querySelector('.collapse-body');
      if (body) body.innerHTML = renderMarkdown(content);
    } else {
      var bubble = el.querySelector('.msg-bubble');
      if (bubble) bubble.innerHTML = renderMarkdown(content);
      var modelSpan = el.querySelector('.msg-model');
      if (modelSpan && model) modelSpan.textContent = model;
    }
  }

  function updateBubble(messageId, content, kind) {
    var entry = state.live[messageId];
    if (!entry) return;
    var next = accumulate(entry.content, content);
    entry.content = next;
    updateBubbleContent(entry.el, entry.kind, next, entry.model);
    scrollToBottom();
  }

  /** 折叠块：thought / tool_calls（点击事件由 init 的 document 委托统一处理） */
  function buildCollapse(label, content) {
    var wrap = document.createElement('div');
    wrap.className = 'collapse';

    var header = document.createElement('button');
    header.className = 'collapse-header';
    header.type = 'button';
    header.setAttribute('aria-expanded', 'false');
    header.innerHTML =
      '<span class="collapse-arrow">▸</span>' +
      '<span class="collapse-label">' + escapeHtml(label) + '</span>';

    var body = document.createElement('div');
    body.className = 'collapse-body';
    body.hidden = true;
    // AI 内容不可信：body 内容一律 renderMarkdown 过 DOMPurify
    body.innerHTML = renderMarkdown(content);

    wrap.appendChild(header);
    wrap.appendChild(body);
    return wrap;
  }

  function formatToolCalls(payload) {
    // 优先用具备结构化的 tool_calls 数组；否则用 content
    var calls = payload.tool_calls;
    if (Array.isArray(calls) && calls.length) {
      return calls.map(function (c) {
        return JSON.stringify(c, null, 2);
      }).join('\n\n');
    }
    return payload.content || '';
  }

  // ---------- typing 指示器 ----------

  function showTyping() {
    if (state.typingEl) return;
    var wrap = document.createElement('div');
    wrap.className = 'msg msg-assistant';
    var typing = document.createElement('div');
    typing.className = 'typing';
    typing.setAttribute('aria-label', '正在输入');
    var span;
    for (var i = 0; i < 3; i++) {
      span = document.createElement('span');
      typing.appendChild(span);
    }
    wrap.appendChild(typing);
    state.messagesEl.appendChild(wrap);
    state.typingEl = wrap;
    scrollToBottom();
  }

  function hideTyping() {
    if (!state.typingEl) return;
    if (state.typingEl.parentNode) state.typingEl.parentNode.removeChild(state.typingEl);
    state.typingEl = null;
  }

  // ---------- 消息分发 ----------

  function handleMessage(msg) {
    if (!msg || !msg.type) return;
    var type = msg.type;
    var payload = msg.payload || {};

    // 服务端回包带 session_id：绑定到当前活动会话（首次不带 session_id 发送后服务端自动建会话）
    if (msg.session_id) {
      bindServerSession(msg.session_id);
    }

    switch (type) {
      case 'message.create':
        handleCreate(payload);
        break;
      case 'message.update':
        handleUpdate(payload);
        break;
      case 'typing.start':
        showTyping();
        break;
      case 'typing.stop':
        hideTyping();
        break;
      case 'session.list':
        handleSessionList(payload);
        break;
      case 'session.history':
        handleSessionHistory(payload);
        break;
      case 'permission.request':
        handlePermissionRequest(msg.session_id, payload);
        break;
      case 'permission.responded':
        handlePermissionResponded(payload);
        break;
      case 'error':
        handleError(payload);
        break;
      default:
        // 未知消息类型：忽略
        break;
    }
  }

  function handleError(payload) {
    var message = payload.message || '发生错误';
    var code = payload.code ? ' (' + payload.code + ')' : '';
    hideTyping();
    var wrap = document.createElement('div');
    wrap.className = 'msg msg-assistant msg-error';
    var bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.textContent = '错误' + code + '：' + message;
    wrap.appendChild(bubble);
    state.messagesEl.appendChild(wrap);
    state.sending = false;
    setSendEnabled(true);
    scrollToBottom();
  }

  // ---------- 工具权限审批（permission.request / permission.responded） ----------

  /** 工具权限审批卡片：Agent 触发需要用户批准的工具调用（如 bash）。
   *  权限决策在服务器端已配 60s 超时自动拒绝；这里仅纯展示 + 回执。 */
  function handlePermissionRequest(sessionId, payload) {
    if (!state.messagesEl || !payload) return;
    if (payload.request_id == null) return;

    var toolCall = payload.tool_call || {};
    var title = toolCall.title || '工具调用';
    var wrap = document.createElement('div');
    wrap.className = 'msg msg-assistant msg-permission';
    wrap.setAttribute('data-perm-request', payload.request_id);

    var body = document.createElement('div');
    body.className = 'msg-bubble msg-permission-body';
    var label = document.createElement('div');
    label.className = 'msg-permission-label';
    label.innerHTML = '需要批准：<strong>' + escapeHtml(title) + '</strong>';
    body.appendChild(label);

    var hint = document.createElement('div');
    hint.className = 'msg-permission-hint';
    hint.textContent = 'Agent 请求执行上述操作，是否允许？(60 秒未操作将自动拒绝)';
    body.appendChild(hint);

    var actions = document.createElement('div');
    actions.className = 'msg-permission-actions';

    var allowBtn = document.createElement('button');
    allowBtn.type = 'button';
    allowBtn.className = 'btn btn-primary';
    allowBtn.textContent = '允许';
    allowBtn.addEventListener('click', function () {
      respondPermission(sessionId, payload.request_id, true, wrap);
    });
    actions.appendChild(allowBtn);

    var denyBtn = document.createElement('button');
    denyBtn.type = 'button';
    denyBtn.className = 'btn btn-ghost';
    denyBtn.textContent = '拒绝';
    denyBtn.addEventListener('click', function () {
      respondPermission(sessionId, payload.request_id, false, wrap);
    });
    actions.appendChild(denyBtn);

    body.appendChild(actions);
    wrap.appendChild(body);
    state.messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  /** 审批回执：向前端发送 permission.respond，并把卡片标记为已处理。 */
  function respondPermission(sessionId, requestId, allow, wrap) {
    if (state.ws && state.ws.ready) {
      state.ws.sendFrame({
        type: 'permission.respond',
        session_id: sessionId,
        payload: { session_id: sessionId, request_id: requestId, allow: allow }
      });
    }
    markPermissionDone(wrap, allow ? '已允许' : '已拒绝');
  }

  /** 服务端回执 permission.responded：更新对应卡片为已处理（幂等）。 */
  function handlePermissionResponded(payload) {
    if (!payload || payload.request_id == null) return;
    var wrap = state.messagesEl.querySelector('[data-perm-request="' + payload.request_id + '"]');
    if (wrap) {
      markPermissionDone(wrap, payload.allow ? '已允许' : '已拒绝');
    }
  }

  /** 把审批卡片置为已处理（禁用按钮并显示结果）。 */
  function markPermissionDone(wrap, text) {
    var actions = wrap.querySelector('.msg-permission-actions');
    if (!actions) return;
    actions.innerHTML = '';
    var done = document.createElement('span');
    done.className = 'msg-permission-done';
    done.textContent = text;
    actions.appendChild(done);
  }

  // ---------- 服务端会话回读（跨浏览器/跨设备恢复） ----------

  /** 连接就绪后拉取服务端会话列表，覆盖本地列表（跨设备恢复）。 */
  function syncFromServer() {
    if (!state.ws || !state.ws.ready) return;
    state.ws.sendFrame({ type: 'session.list' }, { queued: true });
  }

  /** 主动拉取某会话的历史消息。 */
  function pullHistory(sessionId) {
    if (!state.ws || !state.ws.ready || !sessionId) return;
    state.ws.sendFrame({ type: 'session.history', session_id: sessionId }, { queued: true });
  }

  /** session.list 下行：用服务端会话列表重建前端列表（本地未同步的新会话另起）。 */
  function handleSessionList(payload) {
    var serverList = payload && Array.isArray(payload.sessions) ? payload.sessions : [];
    var byId = {};
    state.sessions.forEach(function (s) { byId[s.id] = s; });

    var stored = serverList.map(function (ss) {
      var existing = byId[ss.id] || byId[ss.serverSessionId];
      if (existing) {
        existing.serverSessionId = ss.id;
        if (existing.id !== ss.id) existing.id = ss.id;
        if (!existing.loaded) existing.loaded = false;
        // 用服务端 updatedAt 排序（若本地更旧则刷新 preview，消息稍后按需拉取）
        existing.localTitle = existing.title;
        existing.title = existing.title && existing.title !== '新会话' ? existing.title : (ss.title || '新会话');
        return existing;
      }
      return {
        id: ss.id,
        serverSessionId: ss.id,
        title: ss.title || '新会话',
        messages: [],
        loaded: false
      };
    });

    // 合并仍是本地的、但服务端还没有的（离线兜底 / 尚未同步的新会话）
    var storedIds = {};
    stored.forEach(function (s) { storedIds[s.id] = true; });
    state.sessions.forEach(function (s) {
      if (!storedIds[s.id]) stored.push(s);
    });

    state.sessions = stored;
    if (!state.sessions.some(function (s) { return s.id === state.activeId; })) {
      state.activeId = state.sessions.length ? state.sessions[0].id : null;
    }
    saveSessions();
    saveActive();
    renderSessionList();
    renderChat();
    // 活动会话若是服务端已有但未加载历史，立即拉取
    var act = getActiveSession();
    if (act && act.serverSessionId && !act.loaded) pullHistory(act.serverSessionId);
  }

  /** session.history 下行：回放服务端全量消息。 */
  function handleSessionHistory(payload) {
    var sid = payload.session_id;
    var raw = Array.isArray(payload.messages) ? payload.messages : [];
    var s = state.sessions.find(function (x) { return x.id === sid || x.serverSessionId === sid; });
    if (!s) return;
    s.messages = raw.map(function (m) {
      return {
        role: m.role,
        kind: m.kind || 'text',
        content: m.content || '',
        model: m.model || '',
        message_id: m.id || m.message_id || '',
        time: null
      };
    });
    s.loaded = true;
    saveSessions();
    if (state.activeId === s.id) renderChat();
  }

  // ---------- 发送逻辑 ----------

  function sendMessage() {
    var s = ensureSession();
    var content = state.inputEl.value.trim();
    var files = state.pendingFiles || [];
    if (!content && !files.length) return;
    if (state.sending) return;

    state.sending = true;
    setSendEnabled(false);

    var finish = function (media) {
      var mediaList = media || [];
      renderUserMessage(content, mediaList);
      state.inputEl.value = '';
      state.pendingFiles = [];
      clearPreview();
      autoGrow();
      try {
        // 记录本次请求归属的会话，供回包绑定 serverSessionId
        state.pendingSendSessionId = s.id;
        // 携带服务端 webchat id 续聊（跨浏览器/跨设备恢复同一会话）；
        // 未绑定服务端 id（新会话）时发空 sid，服务端自动建独立会话。
        var sendId = s.serverSessionId ? s.serverSessionId : '';
        state.ws.send(sendId, content, mediaList);
        state.sending = false;
        setSendEnabled(true);
      } catch (err) {
        state.pendingSendSessionId = null;
        state.sending = false;
        setSendEnabled(true);
        handleError({ message: err.message || '发送失败，请检查连接' });
      }
    };

    if (files.length) {
      // 逐张 FileReader → base64 data URL
      var results = [];
      var idx = 0;
      var readNext = function () {
        if (idx >= files.length) {
          finish(results);
          return;
        }
        var file = files[idx++];
        if (!/^image\//.test(file.type)) {
          readNext();
          return;
        }
        var reader = new FileReader();
        reader.onload = function (e) {
          results.push(e.target.result);
          readNext();
        };
        reader.onerror = function () {
          readNext();
        };
        reader.readAsDataURL(file);
      };
      readNext();
    } else {
      finish([]);
    }
  }

  // ---------- 图片上传 UI ----------

  /**
   * 隐藏图片上传按钮并禁用图片发送（Reasonix 无 VLM 能力，T3 已确认
   * promptCapabilities.image=false）。Reasonix 为唯一后端，按钮恒定隐藏，
   * 且清空未提交的待发图片，避免用户消息夹带 media 字段。
   */
  function applyUploadVisibility() {
    var btn = $(UPLOAD_BTN_SEL);
    if (!btn) return;
    btn.style.display = 'none';
    state.pendingFiles = [];
    clearPreview();
  }

  function setupUpload() {
    var fileEl = document.createElement('input');
    fileEl.type = 'file';
    fileEl.accept = 'image/*';
    fileEl.multiple = true;
    fileEl.style.display = 'none';
    document.body.appendChild(fileEl);
    state.fileEl = fileEl;
    state.pendingFiles = [];

    // 图片上传按钮点击不触发文件选择（Reasonix 无图片能力）
    $(UPLOAD_BTN_SEL).addEventListener('click', function () {
      return;
    });

    fileEl.addEventListener('change', function () {
      state.pendingFiles = Array.prototype.slice.call(fileEl.files || []);
      renderPreview();
      fileEl.value = '';
    });

    // 恒定隐藏上传按钮
    applyUploadVisibility();
  }

  function renderPreview() {
    clearPreview();
    var files = state.pendingFiles || [];
    if (!files.length) return;
    var container = document.createElement('div');
    container.className = 'preview-bar';
    container.id = PREVIEW_ID;
    files.forEach(function (file) {
      var chip = document.createElement('span');
      chip.className = 'preview-chip';
      chip.textContent = file.name;
      var url = file.type && /^image\//.test(file.type) ? URL.createObjectURL(file) : null;
      if (url) {
        var img = document.createElement('img');
        img.src = url;
        img.className = 'preview-thumb';
        chip.insertBefore(img, chip.firstChild);
      }
      container.appendChild(chip);
    });
    var hint = document.createElement('span');
    hint.className = 'preview-count';
    hint.textContent = files.length + ' 张图片';
    container.appendChild(hint);
    state.inputArea.insertBefore(container, state.inputBox);
  }

  function clearPreview() {
    var el = document.getElementById(PREVIEW_ID);
    if (el) el.parentNode.removeChild(el);
  }

  // ---------- 会话列表渲染 ----------

  function renderSessionList() {
    var listEl = $(SESSION_LIST_SEL);
    if (!listEl) return;
    listEl.innerHTML = '';
    state.sessions.forEach(function (s) {
      var item = document.createElement('div');
      item.className = 'session-item' + (s.id === state.activeId ? ' active' : '');
      item.dataset.id = s.id;

      var icon = document.createElement('div');
      icon.className = 'session-icon';
      icon.textContent = '💬';
      item.appendChild(icon);

      var meta = document.createElement('div');
      meta.className = 'session-meta';
      var title = document.createElement('div');
      title.className = 'session-title';
      title.textContent = s.title || '新会话';
      var preview = document.createElement('div');
      preview.className = 'session-preview';
      var last = s.messages[s.messages.length - 1];
      preview.textContent = last ? (last.content || '').replace(/\s+/g, ' ').slice(0, 30) : '暂无消息';
      meta.appendChild(title);
      meta.appendChild(preview);
      item.appendChild(meta);

      // 删除按钮
      var del = document.createElement('button');
      del.className = 'session-del';
      del.type = 'button';
      del.title = '删除会话';
      del.textContent = '×';
      del.addEventListener('click', function (e) {
        e.stopPropagation();
        if (confirm('确定删除该会话？')) deleteSession(s.id);
      });
      item.appendChild(del);

      item.addEventListener('click', function () {
        switchSession(s.id);
      });

      listEl.appendChild(item);
    });
  }

  // ---------- 聊天区渲染 ----------

  function renderChat() {
    var s = getActiveSession();
    state.messagesEl.innerHTML = '';
    state.live = {};
    state.typingEl = null;
    clearMerge();

    // 标题
    var titleEl = $('.chat-title');
    if (titleEl) titleEl.textContent = s ? s.title : '新会话';

    if (!s) return;

    // 服务端已有但本端未加载历史的会话：拉取历史（跨设备首次打开某会话）
    if (s.serverSessionId && !s.loaded) {
      pullHistory(s.serverSessionId);
    }

    // 重放会话历史
    s.messages.forEach(function (msg) {
      if (msg.role === 'user') {
        renderUserMessage(msg.content, msg.media, { persist: false });
      } else if (msg.kind === 'thought') {
        state.messagesEl.appendChild(buildCollapse('思考过程', msg.content));
      } else if (msg.kind === 'tool_calls') {
        state.messagesEl.appendChild(buildCollapse('工具调用', msg.content));
      } else {
        state.messagesEl.appendChild(buildTextMessage(msg.content, msg.model));
      }
    });
    scrollToBottom();
  }

  // ---------- 滚动 ----------

  function scrollToBottom() {
    if (state.messagesEl) state.messagesEl.scrollTop = state.messagesEl.scrollHeight;
  }

  // ---------- 输入框 ----------

  function autoGrow() {
    var el = state.inputEl;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  function clearInput() {
    if (state.inputEl) {
      state.inputEl.value = '';
      state.inputEl.style.height = 'auto';
    }
  }

  function setSendEnabled(enabled) {
    var btn = $(SEND_BTN_SEL);
    if (btn) btn.disabled = !enabled;
  }

  // ---------- 连接状态 ----------

  function onWsStatus(status) {
    var sub = $('.chat-subtitle');
    if (!sub) return;
    var map = {
      connecting: '连接中…',
      open: 'AI Agent · 已连接',
      reconnecting: '重连中…',
      closed: '已断开'
    };
    sub.textContent = map[status.state] || status.state;
    // 连接就绪后从服务端回读会话列表（跨浏览器/跨设备恢复）
    if (status.state === 'open') syncFromServer();
  }

  // ---------- 初始化 ----------

  var SESSION_LIST_SEL = '#session-list';
  var UPLOAD_BTN_SEL = '#upload-btn';
  var SEND_BTN_SEL = '#send-btn';
  var PREVIEW_ID = 'img-preview';

  function init() {
    // 归一到 DOM id（若存在）
    state.messagesEl = $('#messages');
    state.inputEl = $('#input');
    state.inputArea = $('.input-area');
    state.inputBox = $('.input-box');

    // 新对话按钮
    var newBtn = $('#new-chat-btn');
    if (newBtn) newBtn.addEventListener('click', newSession);

    // 输入框：Enter 发送 / Shift+Enter 换行
    state.inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    state.inputEl.addEventListener('input', autoGrow);

    // 发送按钮
    var sendBtn = $(SEND_BTN_SEL);
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);

    // 图片上传
    setupUpload();

    // 折叠块交互（T1 内联脚本已移除，这里统一接管）
    document.addEventListener('click', function (e) {
      var header = e.target.closest('.collapse-header');
      if (!header) return;
      var expanded = header.getAttribute('aria-expanded') === 'true';
      header.setAttribute('aria-expanded', String(!expanded));
      var body = header.nextElementSibling;
      if (body) body.hidden = expanded;
    });

    // 会话列表渲染
    renderSessionList();

    // 无会话则建一个
    if (!getActiveSession()) newSession();
    else renderChat();

    // WebSocket
    connect();
  }

  function connect() {
    var s = getSettings();
    state.settings = s;
    if (!s.token) {
      onWsStatus({ state: 'closed' });
      return;
    }
    state.ws = new PicoWS({
      url: s.wsUrl,
      token: s.token,
      onMessage: handleMessage,
      onStatus: onWsStatus
    });
    state.ws.connect();
  }

  /**
   * 设置面板保存回调（T3 settings.js 调用）。
   * 用新配置重建 WebSocket 连接：token/wsUrl 变更时关闭旧连接并用新配置建新连接。
   */
  function onSettingsSave(next) {
    var s = next || getSettings();
    var tokenChanged = s.token !== state.settings.token;
    var urlChanged = s.wsUrl !== state.settings.wsUrl;
    state.settings = s;

    if (!tokenChanged && !urlChanged) return;

    // 旧连接的待发队列（重建后 flush 用）
    var queued = [];
    if (state.ws) {
      try { queued = state.ws._queue.slice() || []; } catch (e) { /* 忽略 */ }
      try { state.ws.close(); } catch (e) { /* 忽略 */ }
      state.ws = null;
    }

    if (!s.token) {
      onWsStatus({ state: 'closed' });
      return;
    }

    state.ws = new PicoWS({
      url: s.wsUrl,
      token: s.token,
      onMessage: handleMessage,
      onStatus: onWsStatus
    });
    state.ws.connect();
    queued.forEach(function (f) {
      if (f && f.payload && f.payload.content) {
        state.ws.sendQueued(f.session_id, f.payload.content, f.payload.media || []);
      }
    });
  }

  // 立即初始化（脚本在 body 末尾加载，DOM 已就绪）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 暴露接口，供 T3 / 调试使用
  window.ChatApp = {
    handleMessage: handleMessage,
    newSession: newSession,
    switchSession: switchSession,
    deleteSession: deleteSession,
    sendMessage: sendMessage,
    connect: connect,
    getSettings: getSettings,
    onSettingsSave: onSettingsSave,
    getState: function () { return state; }
  };
})();