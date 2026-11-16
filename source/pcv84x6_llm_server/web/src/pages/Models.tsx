import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api, anyModelBusy, fmtBytes, kindOf, OPERATION_POLL_MS, operationElapsed,
  type CatalogModel, type DownloadJob, type Model,
} from '../api'
import { KIND_LABEL, KIND_ROUTE, KIND_TABS, tabOfModel, type KindTab } from '../components/kinds'
import ModelSettings from '../components/ModelSettings'

const TAB_KEY = 'cv84x6.models.tab'

function initialTab(): KindTab {
  const saved = sessionStorage.getItem(TAB_KEY)
  return KIND_TABS.some((t) => t.id === saved) ? (saved as KindTab) : 'chat'
}

/** The rows of a model card's spec table that mean something for its kind.
 *  `context_length` is a different limit per kind (a chat window, an input
 *  cap, the OCR detector's side), so its label says which. */
function specRows(m: Model): [string, string][] {
  const kind = kindOf(m)
  const ctx = m.context_length
  switch (kind) {
    case 'chat':
      return [['上下文', ctx ? `${ctx} token` : '未知']]
    case 'embedding':
      return [
        ['单条最长', ctx ? `${ctx} token` : '未知'],
        ['向量维度', m.hidden_size ? String(m.hidden_size) : m.loaded ? '未知' : '加载后可知'],
      ]
    case 'rerank':
      return [['每对最长', ctx ? `${ctx} token（查询 + 文档）` : '未知']]
    case 'asr':
      return [['单段音频', '≤ 30 秒，长音频自动切段']]
    case 'ocr':
      return [['网络文件', `${m.bmodel_files?.length ?? 1} 个（检测 + 识别）`]]
    case 'ocr_vl':
      return [['上下文', ctx ? `${ctx} token` : '未知']]
  }
}

/** Independent operations can overlap (two models may load at once, and a
 *  download is a third thing), so "something is busy" is per-model rather than
 *  one page-wide flag. The lock lives on the server; `localAct` only keeps the
 *  clicked button from firing twice before the first poll lands. */
function modelBusy(m: Model): boolean {
  return m.operation !== null
}

/** Names of the model directories a download job is still writing. */
function activeNames(jobs: DownloadJob[]): Set<string> {
  return new Set(jobs.filter((j) => j.state === 'running' || j.state === 'pending').map((j) => j.name))
}

/** The load/unload button's text, driven by the backend operation. */
function actionLabel(m: Model, pending: boolean): string {
  if (m.operation === 'loading') {
    return `加载中… ${operationElapsed(m.operation_since)}`.trimEnd()
  }
  if (m.operation === 'unloading') {
    return `卸载中… ${operationElapsed(m.operation_since)}`.trimEnd()
  }
  if (pending) return m.loaded || m.conflict ? '停止中…' : '加载中…'
  // The button offered for a conflicted model is 卸载 (see the card): the
  // process exists but nothing answers, so "stop it" is what it does.
  return m.loaded || m.conflict ? '卸载' : '加载'
}

/** How often the page re-reads the model list when nothing is in flight. */
const BACKGROUND_POLL_MS = 10_000

/** "3 分钟前" for an epoch-seconds instant in the past. */
function agoText(epoch: number): string {
  const s = Math.max(0, Date.now() / 1000 - epoch)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`
  return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分钟前`
}

/** "约 7 分钟后" for an epoch-seconds deadline; "即将" once it is due. */
function untilText(epoch: number): string {
  const s = epoch - Date.now() / 1000
  if (s <= 60) return '即将'
  if (s < 3600) return `约 ${Math.ceil(s / 60)} 分钟后`
  return `约 ${Math.floor(s / 3600)} 小时 ${Math.ceil((s % 3600) / 60)} 分钟后`
}

export default function Models() {
  const [models, setModels] = useState<Model[]>([])
  const [err, setErr] = useState('')
  // Which row the operator just clicked. Cleared as soon as the backend
  // reports the operation, or when the request settles -- never the source of
  // truth for "is this model busy", only a guard against a double click.
  const [localAct, setLocalAct] = useState<string | null>(null)
  const [logFor, setLogFor] = useState<string | null>(null)
  const [logText, setLogText] = useState('')
  const [jobs, setJobs] = useState<DownloadJob[]>([])
  const [orphanBytes, setOrphanBytes] = useState(0)
  const [dlKind, setDlKind] = useState<'url' | 'dfss'>('url')
  const [dlUrl, setDlUrl] = useState('')
  const [dlName, setDlName] = useState('')
  const [catalog, setCatalog] = useState<CatalogModel[]>([])
  // Whether "用到时自动加载" is true for an idle-unloaded card: off by default,
  // and without it the next request gets 409 rather than a reload.
  const [autoLoad, setAutoLoad] = useState(false)
  // Which card has its settings form open (one at a time).
  const [settingsFor, setSettingsFor] = useState<string | null>(null)
  const [tab, setTabState] = useState<KindTab>(initialTab)
  const tabsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    tabsRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [tab])
  const setTab = (t: KindTab) => {
    setTabState(t)
    sessionStorage.setItem(TAB_KEY, t)
  }
  // A refresh counter, so the elapsed-time label ticks even between polls.
  const [, setTick] = useState(0)
  const modelsRef = useRef<Model[]>([])
  modelsRef.current = models
  // Model directories a download job is still writing. Kept so the page can
  // notice a job ending and rescan: the finished model unlocks without a click.
  const activeDlRef = useRef<Set<string>>(new Set())

  const refresh = useCallback(async () => {
    try {
      const r = await api.models()
      setModels(r.models)
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取失败')
    }
  }, [])

  const refreshDownloads = useCallback(async () => {
    try {
      const r = await api.downloads()
      setJobs(r.jobs)
      setOrphanBytes(r.orphans.bytes)
      const active = activeNames(r.jobs)
      const prev = activeDlRef.current
      activeDlRef.current = active
      if (active.size !== prev.size || [...prev].some((n) => !active.has(n))) void refresh()
    } catch { /* transient; the list simply stays as-is */ }
  }, [refresh])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    api.catalog().then((r) => setCatalog(r.models)).catch(() => { /* older server */ })
  }, [models])
  useEffect(() => {
    api.getSettings().then((s) => setAutoLoad(Boolean(s.aux_auto_load)))
      .catch(() => { /* older server: no idle unload either */ })
  }, [])

  // Poll while any model has an operation in flight. The condition comes from
  // the server, so a page reloaded mid-load keeps polling on its own -- it does
  // not need the click that started the load to still be in memory.
  const busy = anyModelBusy(models)
  // The server's flag plus the job list this page already polls every 1.5 s:
  // the job list is the fresher of the two while a download is starting.
  const dlActive = activeNames(jobs)
  const isDownloading = (m: Model) => Boolean(m.downloading) || dlActive.has(m.id)
  // A click whose request has not returned yet is worth polling for too: the
  // row still shows the pre-click state until the response arrives, and that
  // gap is when a second click would look reasonable to the operator.
  const inFlight = localAct !== null
  useEffect(() => {
    if (!busy && !inFlight) return
    const id = setInterval(() => void refresh(), OPERATION_POLL_MS)
    return () => clearInterval(id)
  }, [busy, inFlight, refresh])

  // A slow background poll as well: auxiliary models are now unloaded by the
  // idle sweep and loaded on demand by API / knowledge-base / MCP traffic, so
  // a card can change state with nobody clicking on this page. It also keeps
  // the "最近使用 / 空闲自动卸载" times current.
  useEffect(() => {
    if (busy || inFlight) return
    const id = setInterval(() => void refresh(), BACKGROUND_POLL_MS)
    return () => clearInterval(id)
  }, [busy, inFlight, refresh])

  // While busy, re-render once a second so "加载中… 42 秒" advances without
  // another request.
  useEffect(() => {
    if (!busy) return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [busy])

  useEffect(() => {
    void refreshDownloads()
    const anyActive = jobs.some((j) => j.state === 'running' || j.state === 'pending')
    if (!anyActive) return
    const id = setInterval(() => void refreshDownloads(), 1500)
    return () => clearInterval(id)
  }, [jobs, refreshDownloads])

  const startDownload = async () => {
    if (!dlUrl.trim() || !dlName.trim()) return
    setErr('')
    try {
      await api.startDownload({ url: dlUrl.trim(), name: dlName.trim(), kind: dlKind })
      setDlUrl('')
      setDlName('')
      await refreshDownloads()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '下载启动失败')
    }
  }

  // One click: the dfss path from sophon-demo's download script, into a
  // directory named after the catalog id. The service ships the tokenizer
  // config, so the bare .bmodel is a complete model.
  const downloadCatalog = async (c: CatalogModel) => {
    if (!c.dfss) return
    setErr('')
    try {
      await api.startDownload({ url: c.dfss, name: c.id, kind: 'dfss', expected_bytes: c.size_bytes })
      await refreshDownloads()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '下载启动失败')
    }
  }

  // A newer build behind the model's download tag: download it and replace
  // the installed bmodel (server side). Shown as a download job meanwhile.
  const updateCatalog = async (c: CatalogModel) => {
    setErr('')
    try {
      await api.updateModel(c.id)
      await refreshDownloads()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '更新启动失败')
    }
  }

  const removeModel = async (m: Model) => {
    if (!window.confirm(`删除磁盘上的模型「${m.display_name}」？此操作不可恢复。`)) return
    setErr('')
    try {
      await api.deleteModel(m.id)
      await refresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '删除失败')
    }
  }

  const act = async (id: string, action: 'load' | 'unload') => {
    // Refuse a click the backend would also refuse: the operation is already
    // in flight (this browser, another tab, or another operator).
    const target = modelsRef.current.find((m) => m.id === id)
    if (target?.operation) return
    setLocalAct(id)
    setErr('')
    try {
      if (action === 'load') await api.loadModel(id)
      else await api.unloadModel(id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '操作失败')
    } finally {
      // Read the row's real state rather than assuming the click decided it:
      // a 409 means someone else's operation is what the operator is seeing.
      setLocalAct(null)
      await refresh()
    }
  }

  const showLog = async (id: string) => {
    try {
      const r = await api.modelLog(id)
      setLogText(r.log || '(空)')
      setLogFor(id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取日志失败')
    }
  }

  const totalModels = models.reduce((a, m) => a + m.size_bytes, 0)
  const loadedCount = models.filter((m) => m.loaded).length

  const current = KIND_TABS.find((t) => t.id === tab) ?? KIND_TABS[0]
  const inTab = (m: { kind?: string | null }) => tabOfModel(m) === tab
  const tabModels = models.filter(inTab)
  const tabCatalog = catalog.filter(inTab)
  // A job is shown on the tab of the catalogue entry it downloads. A URL
  // download has no entry, and its kind is only known once the file lands, so
  // it is shown on every tab rather than on none.
  const catalogTab = new Map(catalog.map((c) => [c.id, tabOfModel(c)]))
  const tabJobs = jobs.filter((j) => (catalogTab.get(j.name) ?? tab) === tab)
  const isChat = tab === 'chat'

  return (
    <>
      <h1>模型</h1>
      <p className="sub">
        从模型目录扫描到 {models.length} 个模型，共 {fmtBytes(totalModels)}；已加载 {loadedCount} 个。
        加载会把权重映射进设备内存（NPU 与 VPP）：加载前按两个堆的剩余量和最大连续块检查，放不下会说明差多少；每个模型还可以在「设置」里配置内存上限。
      </p>

      {/* One tab per family. The badge is the loaded count -- the number an
          operator scans for -- and a spinner marks a tab with work in flight,
          so a download started on one tab is not lost behind another. */}
      <div className="tabs" role="tablist" aria-label="模型类型" data-testid="model-tabs" ref={tabsRef}>
        {KIND_TABS.map((t) => {
          const of = models.filter((m) => tabOfModel(m) === t.id)
          const online = of.filter((m) => m.loaded).length
          const working = of.some((m) => m.operation || isDownloading(m))
            || jobs.some((j) => (j.state === 'running' || j.state === 'pending')
              && catalogTab.get(j.name) === t.id)
          return (
            <button key={t.id} role="tab" aria-selected={tab === t.id}
                    className={tab === t.id ? 'active' : ''}
                    data-testid={`model-tab-${t.id}`}
                    title={`磁盘上 ${of.length} 个，已加载 ${online} 个`}
                    onClick={() => setTab(t.id)}>
              {t.label}
              {working
                ? <span className="spin" aria-label="有进行中的操作" />
                : online > 0 && (
                  <span className="tab-badge" aria-label={`已加载 ${online} 个`}
                        data-testid={`model-tab-loaded-${t.id}`}>
                    <span className="dot" />{online}
                  </span>
                )}
            </button>
          )
        })}
      </div>
      <p className="note" style={{ marginBottom: 'var(--s-4)' }} data-testid="model-tab-blurb">
        {current.blurb}
      </p>

      {err && <p className="err-text">{err}</p>}

      <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
        <div className="row" style={{ marginBottom: 'var(--s-2)' }}>
          <h2 style={{ margin: 0 }}>获取模型</h2>
          <div className="spacer" />
          <button className="btn ghost sm" onClick={() => void refresh()}>重新扫描目录</button>
        </div>
        <p className="note" style={{ marginBottom: 'var(--s-3)' }}>
          设备平时离线，下载需要临时连通。dfss 是 sophon-demo 使用的官方分发通道；
          内网制品服务器请选 URL。
        </p>
        {tabCatalog.length > 0 ? (
          <div className="table-wrap" style={{ marginBottom: 'var(--s-3)' }}>
          <table className="catalog" data-testid="catalog-table">
            {isChat ? (
              <thead><tr><th>本版本支持的模型</th><th className="num">上下文</th><th>前缀缓存</th><th className="num">大小</th><th>视觉</th><th></th></tr></thead>
            ) : (
              <thead><tr><th>本版本支持的模型</th><th>接口</th><th className="num">大小</th><th></th></tr></thead>
            )}
            <tbody>
              {tabCatalog.map((c) => (
                <tr key={c.id} data-testid={`catalog-row-${c.id}`}>
                  <td>
                    {c.title}
                    {!c.verified && <span className="note" style={{ display: 'inline' }}>（同结构，未在板上实测）</span>}
                  </td>
                  {isChat ? (
                    <>
                      <td className="num">{c.context ?? '—'}</td>
                      <td>{c.prefix_cache ? '支持' : '—'}</td>
                      <td className="num" style={{ whiteSpace: 'nowrap' }}>{c.size_bytes ? fmtBytes(c.size_bytes) : '—'}</td>
                      <td>{c.vision ? '支持' : '—'}</td>
                    </>
                  ) : (
                    <>
                      <td className="mono" style={{ whiteSpace: 'nowrap' }}>{KIND_ROUTE[kindOf(c)]}</td>
                      <td className="num" style={{ whiteSpace: 'nowrap' }}>{c.size_bytes ? fmtBytes(c.size_bytes) : '—'}</td>
                    </>
                  )}
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {/* Acquiring a model is a different task from running one,
                        so its per-row action is secondary: the only filled
                        button on this page belongs to a model's own card
                        (§2.8.a). Four solid buttons in one viewport was the
                        loud version of a table of ordinary rows. */}
                    {c.downloading || dlActive.has(c.id)
                      ? <span className="muted">下载中</span>
                      : c.installed && c.update_available
                      ? (() => {
                          const live = models.find((m) => m.id === c.id)
                          const busy = !!live && (live.loaded || !!live.operation)
                          return (
                            <span className="row" style={{ gap: 'var(--s-2)', flexWrap: 'nowrap' }}
                                  data-testid={`catalog-update-${c.id}`}>
                              <span className="pill warn" title={c.latest_file ? `最新文件：${c.latest_file}` : undefined}>
                                <span className="dot" />有新版本
                              </span>
                              <button className="btn ghost sm" onClick={() => void updateCatalog(c)} disabled={busy}
                                      title={busy ? '模型正在运行，先卸载再更新' : '下载新版本并替换磁盘上的旧文件'}>
                                更新</button>
                            </span>
                          )
                        })()
                      : c.installed
                      ? <span className="muted">已在磁盘</span>
                      : !c.dfss
                      ? <span className="muted" title="尚未发布到 dfss；可用 URL 直链或手动放入 models/ 目录">待发布</span>
                      : <button className="btn ghost sm" onClick={() => void downloadCatalog(c)}
                                disabled={dlActive.has(c.id)}>
                          dfss 下载</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : (
          <p className="note" style={{ marginBottom: 'var(--s-3)' }}>
            本版本还没有可一键下载的{current.label}模型，可以用下面的 URL / dfss 地址下载。
          </p>
        )}
        <div className="row">
          <select value={dlKind} onChange={(e) => setDlKind(e.target.value as 'url' | 'dfss')}
                  aria-label="下载方式" style={{ maxWidth: 128 }}>
            <option value="url">URL 直链</option>
            <option value="dfss">dfss</option>
          </select>
          <input
            placeholder={dlKind === 'dfss'
              ? 'open@sophgo.com:/ext_model_information/LLM/LLM-TPU/xxx.bmodel'
              : 'http://192.168.1.10/models/xxx.bmodel'}
            value={dlUrl}
            onChange={(e) => setDlUrl(e.target.value)}
            aria-label="模型地址"
            style={{ flex: '1 1 288px' }}
          />
          <input placeholder="模型名（建同名目录）" value={dlName}
                 onChange={(e) => setDlName(e.target.value)}
                 aria-label="模型名" style={{ maxWidth: 224 }} />
          <button className="btn" onClick={() => void startDownload()}
                  disabled={!dlUrl.trim() || !dlName.trim()}>开始下载</button>
        </div>
        <p className="note" style={{ marginTop: 'var(--s-2)' }}>
          模型类型由 bmodel 文件名自动识别，下载完成后出现在对应的页签里。
        </p>
        {orphanBytes > 0 && (
          <p className="note" style={{ marginTop: 'var(--s-3)' }}>
            发现 {fmtBytes(orphanBytes)} 的未完成下载残留（<code>.part</code>），可以手动删除。
          </p>
        )}
      </div>

      {tabJobs.length > 0 && (
        <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
          <h2>下载任务</h2>
          <div className="table-wrap">
          <table>
            <thead>
              <tr><th>模型</th><th>方式</th><th>进度</th><th>状态</th><th></th></tr>
            </thead>
            <tbody>
              {tabJobs.map((j) => (
                <tr key={j.id}>
                  <td>{j.name}</td>
                  <td className="muted">{j.kind}</td>
                  <td style={{ minWidth: 160 }}>
                    <div className="bar"><span style={{ width: `${j.percent}%` }} /></div>
                    <span className="note">
                      {j.percent.toFixed(0)}%
                      {j.total_bytes ? ` · ${fmtBytes(j.done_bytes)} / ${fmtBytes(j.total_bytes)}` : ''}
                    </span>
                  </td>
                  <td>
                    {j.state === 'done' && <span className="pill ok">完成</span>}
                    {j.state === 'running' && <span className="pill warn">下载中</span>}
                    {j.state === 'pending' && <span className="pill">等待</span>}
                    {j.state === 'error' && <span className="pill err">失败</span>}
                    {j.state === 'cancelled' && <span className="pill">已取消</span>}
                    {j.message && <div className="note">{j.message}</div>}
                  </td>
                  <td className="num">
                    {(j.state === 'running' || j.state === 'pending') && (
                      <button className="btn ghost sm"
                              onClick={async () => { await api.cancelDownload(j.id); await refreshDownloads() }}>
                        取消
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {tabModels.length === 0 ? (
        <div className="card" data-testid="model-empty">
          <div className="empty">
            <strong>{models.length === 0 ? '模型目录里还没有模型' : `还没有${current.label}模型`}</strong>
            {tabCatalog.some((c) => c.dfss)
              ? <>点上面目录里的「dfss 下载」一键获取；也可以把 bmodel 放到 <code>models/&lt;模型名&gt;/</code> 下，再点「重新扫描目录」。</>
              : <>把 bmodel 和它的 config 目录放到 <code>models/&lt;模型名&gt;/</code> 下，然后点「重新扫描目录」。</>}
          </div>
        </div>
      ) : (
        <div className="grid c2" data-testid="model-grid">
          {tabModels.map((m) => {
            const downloading = isDownloading(m)
            return (
            <div className="card" key={m.id} data-testid={`model-card-${m.id}`}
                 data-operation={m.operation ?? (downloading ? 'downloading' : 'idle')}
                 data-loaded={m.loaded ? 'true' : 'false'}>
              <div className="row" style={{ marginBottom: 'var(--s-2)' }}>
                {/* The model's name is the card's tier 1 (§2.1): body size but
                    emphasised by weight, not pushed up a size step. */}
                <h3 style={{ margin: 0, fontSize: 'var(--t-md)' }}>{m.display_name}</h3>
                {/* The pill is the single place a reloaded page learns what the
                    model is doing: "在线" is only true once the worker is usable. */}
                <span className={`pill ${m.loaded ? 'ok' : m.operation || downloading ? 'warn' : ''}`}
                      data-testid={`model-status-${m.id}`}>
                  <span className={m.operation || downloading ? 'spin' : 'dot'} />
                  {m.operation === 'loading' ? '加载中'
                    : m.operation === 'unloading' ? '卸载中'
                    : m.loaded ? '在线' : m.conflict ? '进程冲突'
                    : downloading ? '下载中'
                    : m.unloaded_reason === 'idle' ? '空闲已卸载' : '未加载'}
                </span>
                {!m.loaded && !m.operation && m.unloaded_reason === 'idle' && autoLoad && (
                  <span className="note" data-testid={`model-idle-note-${m.id}`}>用到时自动加载</span>
                )}
                {m.operation_since && (
                  <span className="note">已 {operationElapsed(m.operation_since)}</span>
                )}
                {m.supports_vision && kindOf(m) === 'chat' && <span className="pill">VLM</span>}
                {kindOf(m) === 'ocr_vl' && <span className="pill">{KIND_LABEL.ocr_vl}</span>}
              </div>

              <table className="kv">
                <tbody>
                  <tr><th>大小</th><td className="num">{fmtBytes(m.size_bytes)}</td></tr>
                  {specRows(m).map(([k, v]) => (
                    <tr key={k}><th>{k}</th><td className="num">{v}</td></tr>
                  ))}
                  <tr><th>接口</th><td className="num mono">{KIND_ROUTE[kindOf(m)]}</td></tr>
                  <tr><th>配置</th><td className="num">{m.has_config ? '有 config/' : <span className="err-text">缺 config/</span>}</td></tr>
                  {m.loaded && m.port && <tr><th>worker 端口</th><td className="num mono">{m.port}</td></tr>}
                  {m.load_seconds !== null && <tr><th>加载耗时</th><td className="num">{m.load_seconds}s</td></tr>}
                  {m.loaded && m.last_used_at && (
                    <tr><th>最近使用</th><td className="num">{agoText(m.last_used_at)}</td></tr>
                  )}
                  {m.loaded && m.idle_unload_at && (
                    <tr data-testid={`model-idle-at-${m.id}`}>
                      <th>空闲自动卸载</th>
                      <td className="num" title="期间有请求会重新计时">{untilText(m.idle_unload_at)}</td>
                    </tr>
                  )}
                  {m.effective && <MemRow m={m} />}
                  {m.effective && (
                    <tr data-testid={`model-policy-${m.id}`}>
                      <th>卸载 / 加载</th>
                      <td className="num">
                        {m.effective.idle_unload_min ? `空闲 ${m.effective.idle_unload_min} 分钟卸载` : '不自动卸载'}
                        {' · '}
                        {m.effective.auto_load ? '按需加载' : '不自动加载'}
                        {m.settings && (m.settings.idle_unload_min !== null || m.settings.auto_load !== null
                          || m.settings.mem_limit_mb !== null) && <span className="pill tiny">单独设置</span>}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

              {m.load_error && (
                <pre className="log" style={{ marginTop: 'var(--s-3)' }}>{m.load_error}</pre>
              )}

              {/* A surviving worker this service could not take over: online is
                  wrong (nothing answers) and idle is wrong (its NPU heap is
                  allocated, and a load would start a second one). The backend
                  refuses the load; this says why and names the one action that
                  works. */}
              {m.conflict && (
                <pre className="log" style={{ marginTop: 'var(--s-3)' }}
                     data-testid={`model-conflict-${m.id}`}>{m.conflict}</pre>
              )}

              <div className="row card-actions">
                {/* A conflicted model offers 卸载, not 加载: the process is real
                    and holds NPU memory, so stopping it is the only move the
                    backend will accept (it refuses a load with 409). */}
                {m.loaded || m.conflict ? (
                  <button className="btn danger sm" data-testid={`model-unload-${m.id}`}
                          disabled={modelBusy(m) || localAct === m.id}
                          onClick={() => void act(m.id, 'unload')}>
                    {actionLabel(m, localAct === m.id)}
                  </button>
                ) : (
                  <button className="btn sm" data-testid={`model-load-${m.id}`}
                          disabled={modelBusy(m) || localAct === m.id || !m.has_config || downloading}
                          onClick={() => void act(m.id, 'load')}>
                    {modelBusy(m) || localAct === m.id
                      ? <><span className="spin" /> {actionLabel(m, localAct === m.id)}</>
                      : '加载'}
                  </button>
                )}
                <button className="btn ghost sm" data-testid={`model-log-${m.id}`}
                        onClick={() => void showLog(m.id)}>查看日志</button>
                {m.effective && (
                  <button className="btn ghost sm" data-testid={`model-settings-btn-${m.id}`}
                          aria-expanded={settingsFor === m.id}
                          disabled={modelBusy(m)}
                          onClick={() => setSettingsFor(settingsFor === m.id ? null : m.id)}>设置</button>
                )}
                {/* Deleting a model mid-load would pull the .bmodel out from
                    under a worker that is mapping it; the backend refuses it,
                    and the button must not offer it. A conflicted model is the
                    same case: its worker still has the file open. */}
                {!m.loaded && !m.conflict && (
                  <button className="btn danger sm" data-testid={`model-delete-${m.id}`}
                          disabled={modelBusy(m) || downloading}
                          onClick={() => void removeModel(m)}>删除</button>
                )}
                {/* A conflict (another client already operating this model) is
                    reported by the backend; say what to do about it. */}
                {m.operation && (
                  <span className="note"
                        data-testid={`model-operation-${m.id}`}>
                    {m.operation === 'loading'
                      ? '正在加载，完成后自动解锁'
                      : '正在卸载，完成后自动解锁'}
                  </span>
                )}
                {/* The .bmodel is still being written: loading would map a
                    truncated file, and deleting it would pull the directory
                    out from under dfss. Cancel the job to remove it. */}
                {!m.operation && downloading && (
                  <span className="note" data-testid={`model-downloading-${m.id}`}>
                    正在下载，完成后才能加载
                  </span>
                )}
              </div>
              {!m.has_config && (
                <p className="note" style={{ marginTop: 'var(--s-3)' }}>
                  缺少配置目录（tokenizer / 预处理配置），无法加载。
                </p>
              )}
              {settingsFor === m.id && (
                <ModelSettings id={m.id} onSaved={() => void refresh()} onClose={() => setSettingsFor(null)} />
              )}
            </div>
            )
          })}
        </div>
      )}

      {logFor && (
        <div className="card" style={{ marginTop: 'var(--s-4)' }}>
          <div className="row" style={{ marginBottom: 'var(--s-3)' }}>
            <h2 style={{ margin: 0 }}>{logFor} 的 worker 日志</h2>
            <div className="spacer" />
            <button className="btn ghost sm" onClick={() => setLogFor(null)}>关闭</button>
          </div>
          <pre className="log">{logText}</pre>
        </div>
      )}
    </>
  )
}

/** Device memory for one model: used against its own ceiling when loaded (a
 *  thin bar, static part darker than the session/cache part), the ceiling and
 *  static size otherwise. */
function MemRow({ m }: { m: Model }) {
  const limit = m.effective?.mem_limit_bytes ?? null
  const isDefault = m.settings?.mem_limit_mb === null || m.settings?.mem_limit_mb === undefined
  const used = m.mem_used_bytes ?? null
  const st = m.mem_static_bytes ?? null
  const pct = (v: number | null) => (limit && v !== null ? Math.min(100, (v / limit) * 100) : 0)
  return (
    <tr data-testid={`model-mem-${m.id}`}>
      <th>设备内存</th>
      <td className="num">
        {m.loaded && used !== null
          ? <>{fmtBytes(used)} <span className="note">/ 上限 {fmtBytes(limit)}{isDefault ? '（默认）' : ''}</span></>
          : <>上限 {fmtBytes(limit)}{isDefault ? '（默认）' : ''}<span className="note">{st ? ` · 静态 ${fmtBytes(st)}` : ''}</span></>}
        {m.loaded && limit && used !== null && (
          <div className="mem-bar" title={`静态 ${fmtBytes(st)} · 会话与缓存 ${fmtBytes(Math.max(0, used - (st ?? 0)))}`}>
            <span className="mem-static" style={{ width: `${pct(st)}%` }} />
            <span className="mem-run" style={{ width: `${Math.max(0, pct(used) - pct(st))}%` }} />
          </div>
        )}
      </td>
    </tr>
  )
}
