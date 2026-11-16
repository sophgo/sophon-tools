import { useCallback, useEffect, useState } from 'react'
import { SkeletonLines } from '../components/Skeleton'
import {
  api, anyAgentBusy, fmtBytes, OPERATION_POLL_MS, operationElapsed,
  type Agent, type AgentAction, type AgentPatch,
} from '../api'

/** How an agent's state reads on the card. `failed` is not "stopped": the
 *  supervisor gave up restarting it, so the reason is worth showing.
 *
 *  An agent that is starting reports `status: 'stopped'` (there is no ready
 *  process to point at) plus `operation: 'starting'`, so the label is built
 *  from both. */
const STATUS_LABEL: Record<Agent['status'], string> = {
  not_installed: '未安装',
  stopped: '已停止',
  running: '运行中',
  failed: '失败',
}

const STATUS_CLASS: Record<Agent['status'], string> = {
  not_installed: '',
  stopped: '',
  running: 'ok',
  failed: 'err',
}

/** The pill's text: the operation wins while one is in flight.
 *
 *  `pending` is this page's own request, sent but not yet answered -- the
 *  backend has not reported the operation yet, and showing the stale "已停止"
 *  during a 30 s start would invite exactly the second click the backend then
 *  refuses. It is only a bridge until the first poll carries the real value. */
function statusText(a: Agent, pending?: string): string {
  if (a.operation && a.operation_label) return `${a.operation_label}中`
  if (pending) return `${pending}中`
  // A surviving process this service could not take over: `status` is "failed"
  // (it is not running and never became healthy here), but "失败" alone reads
  // like a crashed start. There is a live pid and one way out of it.
  if (a.orphan_pid !== null) return '进程待接管'
  return STATUS_LABEL[a.status]
}

function statusClass(a: Agent, pending?: string): string {
  if (a.operation || pending) return 'warn'
  return STATUS_CLASS[a.status]
}

/** The Chinese label for the action this page just sent. */
const PENDING_LABEL: Partial<Record<AgentAction, string>> = {
  start: '启动', stop: '停止', restart: '重启', reset: '重置',
  uninstall: '卸载', sync: '同步配置',
}

function fmtUptime(s: number | null): string {
  if (!s) return '—'
  if (s < 90) return `${Math.round(s)} 秒`
  if (s < 5400) return `${Math.round(s / 60)} 分钟`
  return `${(s / 3600).toFixed(1)} 小时`
}

export default function Agents() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  // Only a guard against a double click before the first poll lands; the
  // backend's `operation` is what actually locks the card.
  const [busy, setBusy] = useState<string | null>(null)
  const [embed, setEmbed] = useState<Agent | null>(null)
  const [logFor, setLogFor] = useState<string | null>(null)
  const [logText, setLogText] = useState('')

  const refresh = useCallback(async () => {
    try {
      const r = await api.agents()
      setAgents(r.agents)
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取失败')
    }
  }, [])

  // Poll whenever the backend reports an operation in flight -- an install, a
  // start, a stop, a restart. It is the server's answer, not a flag this page
  // set, so a refresh mid-install resumes polling by itself.
  const live = anyAgentBusy(agents)
  const downloading = agents.some(
    (a) => a.job && (a.job.state === 'running' || a.job.state === 'pending'))
  // A request this page sent is also worth polling for: `start` does not return
  // until the agent is healthy, so between the click and the response the card
  // still shows the old state -- and it is exactly during that window that the
  // operator would click again. `busy` closes it; the backend's `operation`
  // takes over as soon as the first poll lands.
  const inFlight = busy !== null
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!live && !downloading && !inFlight) return
    const id = setInterval(() => void refresh(), OPERATION_POLL_MS)
    return () => clearInterval(id)
  }, [live, downloading, inFlight, refresh])
  // Keep the elapsed-time label moving between polls.
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!live) return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [live])

  const run = async (a: Agent, action: AgentAction) => {
    const confirmText: Partial<Record<AgentAction, string>> = {
      reset: `重置「${a.name}」？会停止它并清空配置、会话数据与缓存（保留程序和 workspace 里的文件），`
             + '并换发新的 API Key 和登录密码。',
      uninstall: `卸载「${a.name}」？会删除它的全部文件（包括 workspace 里由它生成的文件）并吊销它的 API Key。`,
    }
    const ask = confirmText[action]
    if (ask && !window.confirm(ask)) return
    setBusy(`${a.id}:${action}`)
    setErr('')
    setNotice('')
    try {
      const next = await api.agentAct(a.id, action)
      setAgents((prev) => prev.map((x) => (x.id === next.id ? next : x)))
      if (embed?.id === next.id && !next.running) setEmbed(null)
      const done: Partial<Record<AgentAction, string>> = {
        start: '已启动', stop: '已停止', restart: '已重启',
        reset: '已重置', uninstall: '已卸载', sync: '配置已重写',
      }
      if (done[action]) setNotice(`${a.name}：${done[action]}`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '操作失败')
      // A 409 means another client's operation is what the operator is looking
      // at; re-read so the card shows that, not the intent of this click.
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  const install = async (a: Agent) => {
    setBusy(`${a.id}:install`)
    setErr('')
    setNotice('')
    try {
      const { job } = await api.agentInstall(a.id)
      setAgents((prev) => prev.map((x) => (x.id === a.id ? { ...x, job } : x)))
      setNotice(`${a.name}：安装已开始`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '安装失败')
    } finally {
      setBusy(null)
    }
  }

  const patch = async (a: Agent, p: AgentPatch) => {
    setBusy(`${a.id}:patch`)
    setErr('')
    setNotice('')
    try {
      const next = await api.agentPatch(a.id, p)
      setAgents((prev) => prev.map((x) => (x.id === next.id ? next : x)))
      if (a.running) setNotice(`${a.name}：设置已保存，已按新配置重启`)
      else setNotice(`${a.name}：设置已保存，下次启动生效`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败')
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  const toggleLog = async (a: Agent) => {
    if (logFor === a.id) { setLogFor(null); return }
    setLogFor(a.id)
    setLogText('加载中…')
    try {
      const r = await api.agentLogs(a.id, 200)
      setLogText(r.log || '（暂无日志）')
    } catch (e) {
      setLogText(e instanceof Error ? e.message : '读取日志失败')
    }
  }

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setNotice(`${label}已复制`)
    } catch {
      // Over plain http the clipboard API is unavailable in most browsers, so
      // this is the common case rather than the exception. The values below
      // are on screen in selectable inputs, so the fallback is an instruction,
      // not a dead end -- and nothing is masked, so selecting by hand works.
      setErr('浏览器不允许写剪贴板；下面账号和密码都是明文，可直接选中复制')
    }
  }

  return (
    <>
      <h1>Agent</h1>
      <p className="sub">
        一键安装、配置、启停开源 agent，让它用本机的模型干活。
        每个 agent 的文件都在数据目录的 <code>agents/&lt;id&gt;/</code> 下，不碰系统目录。
      </p>
      {err && <p className="err-text">{err}</p>}
      {notice && <p className="ok-text">{notice}</p>}

      {agents.length === 0 && !err && (
        <div className="card skel-card" role="status" aria-label="正在读取…">
          <span className="skel skel-title" />
          <SkeletonLines lines={3} />
        </div>
      )}

      <div className="grid" style={{ gap: 'var(--s-4)' }}>
        {agents.map((a) => {
          const job = a.job
          const installing = a.operation === 'installing'
          // Any operation on this agent locks its whole control set: a second
          // start, a reset mid-stop, or a port change during a restart would
          // each race the operation in flight.
          const locked = a.operation !== null
          const anyBusy = busy?.startsWith(`${a.id}:`) ?? false
          // The action this page just sent, until the backend reports it.
          const pending = busy?.startsWith(`${a.id}:`)
            ? PENDING_LABEL[busy.slice(a.id.length + 1) as AgentAction]
            : undefined
          return (
            <div className="card" key={a.id} data-testid={`agent-card-${a.id}`}
                 data-operation={a.operation ?? 'idle'}
                 data-pending={pending ?? ''}
                 data-status={a.status}
                 data-running={a.running ? 'true' : 'false'}>
              <div className="row" style={{ alignItems: 'baseline', gap: 'var(--s-2)' }}>
                <h3 style={{ margin: 0 }}>{a.name}</h3>
                <span className={`pill ${statusClass(a, pending)}`}
                      data-testid={`agent-status-${a.id}`}>
                  <span className={a.operation || pending ? 'spin' : 'dot'} />
                  {' '}{statusText(a, pending)}
                </span>
                {a.operation_since && (
                  <span className="note">已 {operationElapsed(a.operation_since)}</span>
                )}
                <span className="note">v{a.version}</span>
                {a.autostart && <span className="pill">开机自启</span>}
                {/* A process that survived a restart and was attached to, rather
                    than spawned: worth showing, because "running seconds after
                    boot" otherwise looks like a bug. */}
                {a.adopted && (
                  <span className="pill" data-testid={`agent-adopted-${a.id}`}
                        title="接管了服务重启前就在运行的进程，没有重复启动">
                    已接管
                  </span>
                )}
                {/* A survivor that matched this agent but never answered /health:
                    its port and memory are real, but it is not usable. The start
                    is refused until it is stopped, so this is the pointer. */}
                {a.orphan_pid !== null && (
                  <span className="pill warn" data-testid={`agent-orphan-${a.id}`}>
                    残留进程 pid {a.orphan_pid}
                  </span>
                )}
                <div className="spacer" />
                {a.running && (
                  <span className="note">已运行 {fmtUptime(a.uptime_s)}</span>
                )}
              </div>

              {a.status === 'failed' && a.last_error && (
                <p className="err-text" style={{ marginTop: 'var(--s-2)', marginBottom: 0 }}>{a.last_error}</p>
              )}
              {a.status !== 'failed' && a.last_error && (
                <p className="note tight">{a.last_error}</p>
              )}

              {installing && (
                <div style={{ marginTop: 'var(--s-3)' }}>
                  <div className="bar"><span style={{ width: `${job?.percent ?? 0}%` }} /></div>
                  <div className="note" style={{ marginTop: 'var(--s-1)' }}>
                    {job?.message || '正在安装'}
                    {job ? ` · ${job.percent.toFixed(0)}%` : ''}
                    {job?.total_bytes
                      ? `（${fmtBytes(job.done_bytes)} / ${fmtBytes(job.total_bytes)}）` : ''}
                  </div>
                </div>
              )}
              {job?.state === 'error' && !installing && (
                <p className="err-text" style={{ marginTop: 'var(--s-2)' }}>安装失败：{job.message}</p>
              )}

              <div className="grid c4 facts">
                <div>
                  <div className="metric-label">端口</div>
                  <div className="mono">{a.port}</div>
                </div>
                <div>
                  <div className="metric-label">内存 (RSS)</div>
                  <div className="mono">{a.running ? fmtBytes(a.rss_bytes) : '—'}</div>
                </div>
                <div>
                  <div className="metric-label">磁盘占用</div>
                  <div className="mono">{a.installed ? fmtBytes(a.disk_bytes) : '—'}</div>
                </div>
                <div>
                  <div className="metric-label">进程</div>
                  <div className="mono">{a.pid ?? '—'}</div>
                </div>
              </div>

              {a.installed && (
                <>
                  <div className="row" style={{ marginTop: 'var(--s-3)', gap: 'var(--s-2)' }}>
                    <button
                      className="btn sm" data-testid={`agent-start-${a.id}`}
                      disabled={locked || anyBusy || a.running}
                      onClick={() => void run(a, 'start')}
                    >{a.operation === 'starting' ? '启动中…' : '启动'}</button>
                    <button
                      className="btn ghost sm" data-testid={`agent-stop-${a.id}`}
                      disabled={locked || anyBusy || !a.running}
                      onClick={() => void run(a, 'stop')}
                    >{a.operation === 'stopping' ? '停止中…' : '停止'}</button>
                    <button
                      className="btn ghost sm" data-testid={`agent-restart-${a.id}`}
                      disabled={locked || anyBusy || !a.running}
                      onClick={() => void run(a, 'restart')}
                    >{a.operation === 'restarting' ? '重启中…' : '重启'}</button>
                    <button
                      className="btn ghost sm" data-testid={`agent-sync-${a.id}`}
                      disabled={locked || anyBusy || a.running}
                      onClick={() => void run(a, 'sync')}
                    >同步配置</button>
                    <button
                      className="btn ghost sm" data-testid={`agent-reset-${a.id}`}
                      disabled={locked || anyBusy}
                      onClick={() => void run(a, 'reset')}
                    >重置</button>
                    <button
                      className="btn ghost sm" data-testid={`agent-uninstall-${a.id}`}
                      disabled={locked || anyBusy || a.running}
                      onClick={() => void run(a, 'uninstall')}
                    >卸载</button>
                    <div className="spacer" />
                    {a.running && (
                      <>
                        <a
                          className="btn ghost sm" href={a.web_url} target="_blank" rel="noreferrer"
                          data-testid={`agent-open-${a.id}`}
                        >打开</a>
                        {a.embeddable && (
                          <button
                            className="btn ghost sm"
                            data-testid={`agent-embed-${a.id}`}
                            onClick={() => setEmbed(embed?.id === a.id ? null : a)}
                          >{embed?.id === a.id ? '关闭内嵌' : '内嵌'}</button>
                        )}
                      </>
                    )}
                    <button className="btn ghost sm" onClick={() => void toggleLog(a)}>
                      {logFor === a.id ? '收起日志' : '日志'}
                    </button>
                  </div>
                  {locked && (
                    <p className="note tight"
                       data-testid={`agent-operation-${a.id}`}>
                      正在{a.operation_label}，完成后自动解锁（刷新页面也会保持此状态）
                    </p>
                  )}

                  {a.running && (
                    <div style={{ marginTop: 'var(--s-3)' }}>
                      <div className="row" style={{ gap: 'var(--s-2)', alignItems: 'center' }}>
                        <span className="note">登录</span>
                        {a.web.username && (
                          <>
                            <span className="note">用户名</span>
                            <input
                              className="mono" readOnly value={a.web.username}
                              data-testid={`agent-username-${a.id}`}
                              onFocus={(e) => e.currentTarget.select()}
                              style={{ width: 120 }}
                            />
                          </>
                        )}
                        <span className="note">密码</span>
                        {/* Plain text, not dots: over plain http the clipboard
                            API is usually blocked, and a masked value cannot be
                            copied by hand either. readOnly + select-on-focus
                            makes it a copy target without being editable. */}
                        <input
                          className="mono" readOnly value={a.web.password || ''}
                          data-testid={`agent-password-${a.id}`}
                          onFocus={(e) => e.currentTarget.select()}
                          style={{ width: 200 }}
                        />
                        <button
                          className="btn ghost sm" data-testid={`agent-copy-${a.id}`}
                          onClick={() => void copy(
                            `${a.web.username ? `用户名：${a.web.username}\n` : ''}密码：${a.web.password}\n地址：${window.location.origin}${a.web_url}`,
                            '登录信息',
                          )}
                        >复制登录信息</button>
                      </div>
                      <p className="note tight">
                        「打开」和「内嵌」都走本站地址 {a.web_url}，不再按 agent 自己的端口访问；
                        已登录管理页时不用再输一次。
                      </p>
                    </div>
                  )}

                  <div className="row" style={{ marginTop: 'var(--s-4)', gap: 'var(--s-4)', alignItems: 'flex-end' }}>
                    <label>
                      <div className="metric-label">端口</div>
                      <input
                        type="number" style={{ width: 112 }}
                        defaultValue={a.port}
                        key={`${a.id}-port-${a.port}`}
                        data-testid={`agent-port-${a.id}`}
                        disabled={locked || anyBusy}
                        onBlur={(e) => {
                          const v = Number(e.target.value)
                          if (v && v !== a.port) void patch(a, { port: v })
                        }}
                      />
                    </label>
                    <label>
                      <div className="metric-label">默认模型</div>
                      <select
                        style={{ minWidth: 208 }}
                        value={a.default_model}
                        data-testid={`agent-model-${a.id}`}
                        disabled={locked || anyBusy || a.models.length === 0}
                        onChange={(e) => void patch(a, { default_model: e.target.value })}
                      >
                        {a.models.length === 0 && <option value="">（暂无模型）</option>}
                        {a.models.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.id}（{Math.round(m.context / 1024)}k{m.vision ? '，视觉' : ''}）
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="row" style={{ gap: 'var(--s-2)' }}>
                      <input
                        type="checkbox" checked={a.thinking}
                        data-testid={`agent-thinking-${a.id}`}
                        disabled={locked || anyBusy}
                        onChange={(e) => void patch(a, { thinking: e.target.checked })}
                      />
                      <span>默认思考</span>
                    </label>
                    <label className="row" style={{ gap: 'var(--s-2)' }}>
                      <input
                        type="checkbox" checked={a.autostart}
                        data-testid={`agent-autostart-${a.id}`}
                        disabled={locked || anyBusy}
                        onChange={(e) => void patch(a, { autostart: e.target.checked })}
                      />
                      <span>开机自启</span>
                    </label>
                  </div>
                  <p className="note tight agent-mcp" data-testid={`agent-mcp-${a.id}`}>
                    <span className="pill ok"><span className="dot" />MCP</span>
                    已接入本机工具：知识库检索与入库、OCR（图片 / PDF）、语音转写。
                    安装、重置、同步配置时自动写入，不影响你自己添加的其他 MCP。
                  </p>
                  {a.running && (
                    <p className="note tight">
                      改端口、模型或思考开关会让运行中的 agent 自动重启。
                    </p>
                  )}
                </>
              )}

              {!a.installed && !installing && (
                <div className="row" style={{ marginTop: 'var(--s-3)', gap: 'var(--s-2)' }}>
                  <button
                    className="btn sm" data-testid={`agent-install-${a.id}`}
                    disabled={locked || anyBusy}
                    onClick={() => void install(a)}
                  >{busy === `${a.id}:install` ? '正在开始…' : `安装 v${a.latest_version}`}</button>
                  <span className="note">安装到数据目录，自动生成配置和独立的 API Key</span>
                </div>
              )}

              {a.card_note && (
                <p className="note" style={{ marginTop: 'var(--s-3)' }}>
                  {a.card_note}
                </p>
              )}

              {logFor === a.id && (
                <pre className="code" style={{ marginTop: 'var(--s-3)', maxHeight: 320, overflow: 'auto' }}>
                  {logText}
                </pre>
              )}

              {embed?.id === a.id && (
                <div style={{ marginTop: 'var(--s-3)' }}>
                  <iframe
                    title={`${a.name} 内嵌界面`}
                    src={a.web_url}
                    style={{
                      width: '100%', height: '78vh', border: '1px solid var(--line)',
                      borderRadius: 'var(--radius)', background: '#fff',
                    }}
                  />
                  <p className="note tight">
                    内嵌页面与直接打开是同一个界面；宽度不够时点「打开」用整页。
                  </p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}
