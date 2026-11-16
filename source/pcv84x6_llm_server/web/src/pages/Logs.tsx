import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api, fmtBytes, type AuditPage, type AuditQuery, type LogLine, type LogPage, type LogQuery, type LogSource,
} from '../api'

/** 日志: the service's own logs (platform, one per model worker, one per agent)
 *  and the management audit trail. Backend: docs/logs.md (MYS-2674). */

type Tab = 'logs' | 'audit'

const RANGES: [string, string][] = [
  ['', '全部时间'],
  ['-30m', '最近 30 分钟'],
  ['-2h', '最近 2 小时'],
  ['-24h', '最近 24 小时'],
  ['-7d', '最近 7 天'],
]

const LEVELS: [string, string][] = [
  ['', '全部级别'],
  ['info', 'INFO 及以上'],
  ['warning', 'WARNING 及以上'],
  ['error', 'ERROR 及以上'],
]

export default function Logs() {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('logs.tab') === 'audit' ? 'audit' : 'logs'))
  const pick = (t: Tab) => { setTab(t); localStorage.setItem('logs.tab', t) }
  return (
    <>
      <h1>日志</h1>
      <p className="sub">
        {tab === 'logs'
          ? '平台、各模型推理服务与 Agent 的运行日志：按时间、级别、关键字筛选，可下载。'
          : '管理端的每一次变更操作与登录：谁、从哪里、对什么、结果如何。不记录密码与密钥。'}
      </p>
      <div className="tabs" role="tablist" aria-label="日志类型" data-testid="logs-tabs">
        <button role="tab" aria-selected={tab === 'logs'} className={tab === 'logs' ? 'active' : ''}
                onClick={() => pick('logs')} data-testid="logs-tab-logs">运行日志</button>
        <button role="tab" aria-selected={tab === 'audit'} className={tab === 'audit' ? 'active' : ''}
                onClick={() => pick('audit')} data-testid="logs-tab-audit">操作审计</button>
      </div>
      {tab === 'logs' ? <LogView /> : <AuditView />}
    </>
  )
}

// --------------------------------------------------------------------------
// Run logs
// --------------------------------------------------------------------------

const GROUPS: [string, string][] = [['platform', '平台'], ['worker', '推理服务'], ['agent', 'Agent']]

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id) }, [value, ms])
  return v
}

function LogView() {
  const [sources, setSources] = useState<LogSource[]>([])
  const [source, setSource] = useState(() => localStorage.getItem('logs.source') ?? 'platform')
  const [level, setLevel] = useState('')
  const [range, setRange] = useState('')
  const [text, setText] = useState('')
  const q = useDebounced(text.trim(), 350)
  const [live, setLive] = useState(true)
  const [page, setPage] = useState<LogPage | null>(null)
  const [older, setOlder] = useState<LogLine[]>([])     // pages loaded with "加载更早"
  const [olderCursor, setOlderCursor] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement | null>(null)
  const pinned = useRef(true)                          // follow the tail while scrolled to the bottom

  useEffect(() => {
    api.logSources().then((r) => {
      setSources(r.sources)
      if (!r.sources.some((s) => s.id === source) && r.sources.length) setSource(r.sources[0].id)
    }).catch((e) => setErr(e instanceof Error ? e.message : '读取日志源失败'))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const query: LogQuery = useMemo(() => ({ level: level || undefined, since: range || undefined, q: q || undefined, limit: 300 }),
    [level, range, q])

  const refresh = useCallback(async () => {
    try {
      const p = await api.logs(source, query)
      setPage(p)
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取日志失败')
    }
  }, [source, query])

  // New source or filter: start again from the newest lines.
  useEffect(() => {
    setOlder([]); setOlderCursor(null); setPage(null); pinned.current = true
    localStorage.setItem('logs.source', source)
    void refresh()
  }, [source, query, refresh])

  // Live tail: re-read the newest page every 3 s, only while following the end.
  useEffect(() => {
    if (!live) return
    const id = setInterval(() => { if (pinned.current) void refresh() }, 3000)
    return () => clearInterval(id)
  }, [live, refresh])

  // Keep the view at the bottom when following.
  useEffect(() => {
    const el = box.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [page])

  const loadOlder = async () => {
    const cursor = olderCursor ?? page?.cursor
    if (!cursor) return
    setBusy(true)
    try {
      const el = box.current
      const before = el ? el.scrollHeight - el.scrollTop : 0
      const p = await api.logs(source, { ...query, cursor })
      setOlder((o) => [...p.lines, ...o])
      setOlderCursor(p.cursor ?? '')
      // Keep the line the reader was looking at in place.
      requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - before })
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取更早的日志失败')
    } finally {
      setBusy(false)
    }
  }

  const cur = sources.find((s) => s.id === source)
  const lines = [...older, ...(page?.lines ?? [])]
  const moreCursor = olderCursor === null ? page?.cursor : olderCursor || null
  const filtered = Boolean(level || range || q)

  return (
    <>
      <div className="toolbar" data-testid="logs-toolbar">
          <label className="field" style={{ minWidth: 220 }}>
            日志源
            <select value={source} onChange={(e) => setSource(e.target.value)} data-testid="logs-source">
              {GROUPS.map(([k, label]) => {
                const of = sources.filter((s) => (s.kind === k) || (k === 'platform' && !['worker', 'agent'].includes(s.kind)))
                return of.length > 0 && (
                  <optgroup key={k} label={label}>
                    {of.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                  </optgroup>
                )
              })}
            </select>
          </label>
          <label className="field" style={{ width: 150 }}>
            级别
            <select value={level} onChange={(e) => setLevel(e.target.value)} data-testid="logs-level">
              {LEVELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field" style={{ width: 150 }}>
            时间
            <select value={range} onChange={(e) => setRange(e.target.value)} data-testid="logs-range">
              {RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field grow" style={{ minWidth: 180 }}>
            关键字
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="按内容筛选，例如 error、模型名"
                   data-testid="logs-q" />
          </label>
          <div className="toolbar-end">
            <label className="field inline" title="停在底部时每 3 秒刷新">
              <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} data-testid="logs-live" />
              实时跟随
            </label>
            <a className="btn ghost" href={api.logDownloadUrl(source, query)} data-testid="logs-download"
               title={filtered ? '下载当前筛选结果（纯文本）' : '下载完整日志（含轮转的旧文件，zip）'}>
              {filtered ? '下载筛选结果' : '下载全部'}
            </a>
          </div>
      </div>

      {err && <p className="err-text" data-testid="logs-error">{err}</p>}

      <div className="card log-card">
        <div className="row log-head">
          <span className="metric-label" style={{ margin: 0 }}>{cur?.label ?? source}</span>
          <span className="note">
            {cur ? `${fmtBytes(cur.size_bytes)}${cur.updated_at_iso ? ` · 更新于 ${fmtTime(cur.updated_at_iso)}` : ''}` : ''}
          </span>
          <div className="spacer" />
          <span className="note">
            {page ? `显示 ${lines.length} 行${filtered ? '（已筛选）' : ''}` : ''}
          </span>
        </div>
        <div className="log-view" ref={box} data-testid="log-view"
             onScroll={(e) => {
               const el = e.currentTarget
               pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
             }}>
          {moreCursor && (
            <div className="log-more">
              <button className="btn ghost sm" onClick={() => void loadOlder()} disabled={busy} data-testid="logs-older">
                {busy ? '读取中…' : '加载更早的日志'}
              </button>
            </div>
          )}
          {!page ? (
            <div className="empty"><span className="spin" /> 正在读取…</div>
          ) : lines.length === 0 ? (
            <div className="empty">
              <strong>{filtered ? '没有符合条件的日志' : '这个日志还是空的'}</strong>
              {filtered ? '放宽级别、时间或关键字再试。' : ''}
            </div>
          ) : (
            lines.map((l, i) => <LogRow key={i} line={l} q={q} />)
          )}
        </div>
      </div>
    </>
  )
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function levelClass(level: string | null): string {
  const l = (level ?? '').toUpperCase()
  if (l === 'ERROR' || l === 'CRITICAL' || l === 'FATAL') return 'err'
  if (l === 'WARNING' || l === 'WARN') return 'warn'
  return ''
}

function LogRow({ line, q }: { line: LogLine; q: string }) {
  const cls = levelClass(line.level)
  return (
    <div className={`log-line${cls ? ` ${cls}` : ''}`}>
      <span className="log-ts" title={line.ts ?? ''}>{line.ts ? fmtTime(line.ts).slice(5) : ''}</span>
      <span className={`log-lv${cls ? ` ${cls}` : ''}`}>{line.level ?? ''}</span>
      <span className="log-msg">
        {line.logger && <span className="log-logger">{line.logger} </span>}
        <Highlight text={line.message} q={q} />
      </span>
    </div>
  )
}

function Highlight({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>
  const parts: React.ReactNode[] = []
  const lower = text.toLowerCase()
  const needle = q.toLowerCase()
  let i = 0
  for (;;) {
    const j = lower.indexOf(needle, i)
    if (j < 0) { parts.push(text.slice(i)); break }
    parts.push(text.slice(i, j), <mark key={j}>{text.slice(j, j + q.length)}</mark>)
    i = j + q.length
  }
  return <>{parts}</>
}

// --------------------------------------------------------------------------
// Audit trail
// --------------------------------------------------------------------------

const PAGE = 50

const METHOD_LABEL: Record<string, string> = { POST: '执行', PUT: '修改', PATCH: '修改', DELETE: '删除' }

/** What an audited request *did*, in words. Matched on method + path shape;
 *  anything not listed falls back to the method so a new endpoint still reads. */
const ACTIONS: [string, RegExp, string][] = [
  ['POST', /^\/api\/login$/, '登录'],
  ['POST', /^\/api\/logout$/, '登出'],
  ['POST', /^\/api\/password$/, '修改管理口令'],
  ['POST', /^\/api\/models\/[^/]+\/load$/, '加载模型'],
  ['POST', /^\/api\/models\/[^/]+\/unload$/, '卸载模型'],
  ['POST', /^\/api\/models\/[^/]+\/update$/, '更新模型'],
  ['DELETE', /^\/api\/models\/[^/]+$/, '删除模型'],
  ['POST', /^\/api\/downloads$/, '下载模型'],
  ['POST', /^\/api\/downloads\/[^/]+\/cancel$/, '取消下载'],
  ['POST', /^\/api\/settings$/, '修改设置'],
  ['POST', /^\/api\/keys$/, '创建 API Key'],
  ['POST', /^\/api\/keys\/[^/]+\/revoke$/, '吊销 API Key'],
  ['DELETE', /^\/api\/keys\/[^/]+$/, '删除 API Key'],
  ['POST', /^\/api\/agents\/[^/]+\/install$/, '安装 Agent'],
  ['POST', /^\/api\/agents\/[^/]+\/start$/, '启动 Agent'],
  ['POST', /^\/api\/agents\/[^/]+\/stop$/, '停止 Agent'],
  ['POST', /^\/api\/agents\/[^/]+\/restart$/, '重启 Agent'],
  ['POST', /^\/api\/agents\/[^/]+\/reset$/, '重置 Agent'],
  ['POST', /^\/api\/agents\/[^/]+\/uninstall$/, '卸载 Agent'],
  ['POST', /^\/api\/agents\/[^/]+\/sync$/, '同步 Agent 配置'],
  ['POST', /^\/api\/agents\/[^/]+\/[^/]+$/, 'Agent 操作'],
  ['PATCH', /^\/api\/agents\/[^/]+$/, '修改 Agent 设置'],
  ['POST', /^\/api\/storage\/move$/, '迁移数据目录'],
  ['POST', /^\/api\/inference-records\/clear$/, '清空推理记录'],
  ['POST', /^\/api\/apps\/kb$/, '新建知识库'],
  ['DELETE', /^\/api\/apps\/kb\/[^/]+$/, '删除知识库'],
  ['POST', /^\/api\/apps\/kb\/[^/]+\/docs$/, '上传知识库文档'],
  ['DELETE', /^\/api\/apps\/kb\/[^/]+\/docs\/[^/]+$/, '删除知识库文档'],
  ['POST', /^\/api\/apps\/kb\/[^/]+\/reindex$/, '重建知识库索引'],
]

function actionLabel(method: string, path: string): string {
  const hit = ACTIONS.find(([m, re]) => m === method && re.test(path))
  return hit ? hit[2] : (METHOD_LABEL[method] ?? method)
}

function AuditView() {
  const [range, setRange] = useState('-7d')
  const [actor, setActor] = useState('')
  const [action, setAction] = useState('')
  const [status, setStatus] = useState('')
  const [text, setText] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<AuditPage | null>(null)
  const [err, setErr] = useState('')
  const dActor = useDebounced(actor.trim(), 350)
  const dAction = useDebounced(action.trim(), 350)
  const dText = useDebounced(text.trim(), 350)

  const query: AuditQuery = useMemo(() => ({
    since: range || undefined, actor: dActor || undefined, action: dAction || undefined,
    status: status || undefined, q: dText || undefined, limit: PAGE,
  }), [range, dActor, dAction, status, dText])

  useEffect(() => { setOffset(0) }, [query])
  useEffect(() => {
    let alive = true
    api.audit({ ...query, offset }).then((p) => { if (alive) { setPage(p); setErr('') } })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : '读取审计失败') })
    return () => { alive = false }
  }, [query, offset])

  const total = page?.total ?? 0
  return (
    <>
      <div className="toolbar" data-testid="audit-toolbar">
          <label className="field" style={{ width: 150 }}>
            时间
            <select value={range} onChange={(e) => setRange(e.target.value)} data-testid="audit-range">
              {RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field" style={{ width: 130 }}>
            结果
            <select value={status} onChange={(e) => setStatus(e.target.value)} data-testid="audit-status">
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="failure">失败</option>
            </select>
          </label>
          <label className="field" style={{ width: 150 }}>
            操作者
            <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="admin 或 key 名" data-testid="audit-actor" />
          </label>
          <label className="field" style={{ width: 200 }}>
            操作
            <input value={action} onChange={(e) => setAction(e.target.value)} placeholder="如 POST /api/models" data-testid="audit-action" />
          </label>
          <label className="field grow" style={{ minWidth: 160 }}>
            关键字
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="目标、摘要、IP…" data-testid="audit-q" />
          </label>
          <div className="toolbar-end">
            <a className="btn ghost" href={api.auditExportUrl(query)} data-testid="audit-export"
               title="按当前筛选导出 CSV（Excel 可直接打开）">导出 CSV</a>
          </div>
      </div>

      {err && <p className="err-text">{err}</p>}

      <div className="card" data-testid="audit-table">
        {!page ? (
          <div className="empty"><span className="spin" /> 正在读取…</div>
        ) : page.items.length === 0 ? (
          <div className="empty"><strong>没有符合条件的操作</strong>换一个时间范围或清空筛选再试。</div>
        ) : (
          <div className="table-wrap">
            <table className="audit">
              <thead>
                <tr>
                  <th>时间</th><th>操作者</th><th>操作</th><th>目标 / 摘要</th><th>结果</th><th className="num">耗时</th><th>来源</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((it) => (
                  <tr key={it.id}>
                    <td className="nowrap mono">{fmtTime(it.ts_iso)}</td>
                    <td className="nowrap">
                      {it.actor_name ?? '—'}
                      <span className="note"> {it.actor_type === 'api_key' ? 'API Key' : it.actor_type === 'console' ? '控制台' : '未登录'}</span>
                    </td>
                    <td>
                      {actionLabel(it.method, it.path)}
                      <div className="note mono">{it.method} {it.path}</div>
                    </td>
                    <td>
                      {it.target && <span className="mono">{it.target}</span>}
                      {it.target && it.summary && <br />}
                      {it.summary && <span>{it.summary}</span>}
                      {!it.target && !it.summary && <span className="note">—</span>}
                    </td>
                    <td className="nowrap">
                      <span className={`pill ${it.ok ? 'ok' : 'err'}`}>{it.ok ? '成功' : '失败'} · {it.status}</span>
                    </td>
                    <td className="num nowrap">{it.duration_ms === null ? '—' : `${it.duration_ms < 1000 ? it.duration_ms.toFixed(0) + ' ms' : (it.duration_ms / 1000).toFixed(1) + ' s'}`}</td>
                    <td className="nowrap mono" title={it.user_agent ?? ''}>{it.ip ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page && (
          <div className="row pager" style={{ marginTop: 'var(--s-3)' }}>
            <span className="note">
              共 {total} 条{total ? ` · 第 ${offset + 1}–${Math.min(offset + PAGE, total)} 条` : ''} · 保留 {page.retention_days} 天（可在「设置」中修改）
            </span>
            <div className="spacer" />
            <button className="btn ghost sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
                    data-testid="audit-prev">上一页</button>
            <button className="btn ghost sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}
                    data-testid="audit-next">下一页</button>
          </div>
        )}
      </div>
    </>
  )
}
