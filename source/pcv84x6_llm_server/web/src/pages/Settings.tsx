import { useCallback, useEffect, useRef, useState } from 'react'
import PageSkeleton from '../components/Skeleton'
import {
  api, fmtBytes, fmtMb,
  type AppliedModel, type Model, type MoveJob, type SaveSettingsResult, type Settings,
  type SettingsPatch, type StorageInfo,
} from '../api'

/** One row of the form: a numeric input plus the sentence that explains what
 *  the number actually trades off. The hints are not decoration -- the backend
 *  clamps every field, and an operator who does not know why 3 is the ceiling
 *  or why 0 turns a feature off reads the clamped result as a bug. */
/** The numeric limits this page edits inline. The inference-record switch and
 *  its retention pair live in their own card below (`RecordSettings`), because
 *  they are saved and applied without a worker to push them to. */
type NumericSetting =
  | 'max_concurrent_per_model' | 'prefix_cache_entries'
  | 'prefix_cache_ttl_min' | 'max_queue' | 'prefill_exact_tail'

type Field = {
  key: NumericSetting
  label: string
  hint: string
  min: number
  max: number
  unit: string
}

const FIELDS: Field[] = [
  {
    key: 'max_concurrent_per_model', label: '每模型并发上限',
    hint: 'NPU 一次只算一个 token，超过 3 路只会让每路更慢。',
    min: 1, max: 3, unit: '路',
  },
  {
    key: 'max_queue', label: '排队上限',
    hint: '并发占满后最多排队的请求数，再多返回 429。',
    min: 0, max: 256, unit: '个',
  },
  {
    key: 'prefix_cache_ttl_min', label: '缓存保留时间',
    hint: '超过这段时间没被复用的快照会被释放；0 = 不过期。',
    min: 0, max: 10080, unit: '分钟',
  },
  {
    key: 'prefix_cache_entries', label: '缓存条目上限',
    hint: '最多保存多少份快照，满了按最久未用淘汰。',
    min: 1, max: 256, unit: '条',
  },
  {
    key: 'prefill_exact_tail', label: 'prompt 精确尾部',
    hint: '2048 token 以上的 prompt，最后这么多 token 改走解码图逐个计算（预填充图的专家 MoE 在 CV84X6 上有误差），每 token 约 40 ms；更短的 prompt 固定最多 16 个，防止不作答；0 = 全部关闭（不建议）。',
    min: 0, max: 1024, unit: 'token',
  },
]

/** Form state keeps strings so a half-typed or cleared box never turns into
 *  NaN; parsing happens once, on save. */
type Draft = Record<NumericSetting, string>

function toDraft(s: Settings): Draft {
  return {
    max_concurrent_per_model: String(s.max_concurrent_per_model),
    max_queue: String(s.max_queue),
    prefix_cache_ttl_min: String(s.prefix_cache_ttl_min),
    prefix_cache_entries: String(s.prefix_cache_entries),
    prefill_exact_tail: String(s.prefill_exact_tail),
  }
}

export default function SettingsPage() {
  const [draft, setDraft] = useState<Draft | null>(null)
  const [stored, setStored] = useState<Settings | null>(null)
  // What the last save asked for, kept so the page can point at the boxes the
  // server overrode instead of quietly replacing the operator's number.
  const [requested, setRequested] = useState<SettingsPatch | null>(null)
  const [applied, setApplied] = useState<Record<string, AppliedModel> | null>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  const [loadErr, setLoadErr] = useState('')
  const [saveErr, setSaveErr] = useState('')
  const [justSaved, setJustSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const s = await api.getSettings()
      setStored(s)
      setDraft(toDraft(s))
      setLoadErr('')
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : '读取失败')
    }
    // Display names only; a failure here just means we fall back to model ids.
    try {
      const r = await api.models()
      const m: Record<string, string> = {}
      for (const x of r.models as Model[]) m[x.id] = x.display_name
      setNames(m)
    } catch { /* not fatal */ }
  }, [])

  useEffect(() => { void load() }, [load])

  const save = async () => {
    if (!draft) return
    setBusy(true)
    setSaveErr('')
    setJustSaved(false)
    try {
      const patch: SettingsPatch = {}
      for (const f of FIELDS) {
        const raw = draft[f.key].trim()
        // An empty box keeps the stored value rather than silently writing 0,
        // which for the cache would mean "turn it off".
        if (raw === '') continue
        const n = Number(raw)
        if (!Number.isFinite(n)) throw new Error(`${f.label} 需要填整数`)
        patch[f.key] = Math.trunc(n)
      }
      const r: SaveSettingsResult = await api.saveSettings(patch)
      // Refill from the server's copy, not from the patch: the clamped values
      // are the whole point of showing the result.
      setRequested(patch)
      setStored(r.settings)
      setDraft(toDraft(r.settings))
      setApplied(r.applied)
      setJustSaved(true)
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  const revert = () => {
    if (!stored) return
    setDraft(toDraft(stored))
    setRequested(null)
    setSaveErr('')
    setJustSaved(false)
  }

  if (loadErr && !draft) {
    return <><h1>设置</h1><p className="err-text">读取设置失败：{loadErr}</p></>
  }
  if (!draft || !stored) return <PageSkeleton title="设置" blocks={3} label="正在读取设置…" />

  // Only count a box as edited when it parses -- a partially typed value is a
  // pending edit, not a change to save.
  const dirty = FIELDS.some((f) => {
    const raw = draft[f.key].trim()
    if (raw === '' || !Number.isFinite(Number(raw))) return false
    return Math.trunc(Number(raw)) !== (stored[f.key] as number)
  })
  const clampedFields = new Set<NumericSetting>(
    requested
      ? FIELDS.filter((f) => {
          const asked = requested[f.key]
          return asked !== undefined && asked !== (stored[f.key] as number)
        }).map((f) => f.key)
      : [],
  )
  const appliedIds = applied ? Object.keys(applied) : []

  return (
    <>
      <h1>设置</h1>
      <p className="sub">
        并发、排队与缓存保留策略。前缀缓存和会话共用各模型的内存额度，可在「模型 → 设置」调整内存上限。保存后立即对已加载的模型生效。
      </p>

      {saveErr && <p className="err-text">{saveErr}</p>}

      <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
        {/* Between-field space (--s-5) is larger than the label-to-input space
            (--s-1), so each label is unambiguously attached to its own box
            (§3.6.a #1). The hint sits in a second column rather than under the
            input, which keeps the form from stretching to 900px (§3.3.2). */}
        <div className="grid" style={{ gap: 'var(--s-5)' }}>
          {FIELDS.map((f) => (
            <div key={f.key} className="field-row">
              <div>
                <div className="metric-label" style={{ marginBottom: 'var(--s-1)' }}>
                  {f.label}
                  <span className="range">
                    {f.min}–{f.max} {f.unit}
                  </span>
                  {clampedFields.has(f.key) && (
                    <span className="pill warn" style={{ marginLeft: 'var(--s-2)' }}>已钳位</span>
                  )}
                </div>
                <input
                  type="number" value={draft[f.key]} min={f.min} max={f.max}
                  aria-label={f.label}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              </div>
              <p className="note" style={{ margin: 0 }}>{f.hint}</p>
            </div>
          ))}
        </div>

        <div className="row" style={{ marginTop: 'var(--s-5)' }}>
          <button className="btn" onClick={() => void save()} disabled={busy}>
            {busy ? '保存中…' : '保存'}
          </button>
          {dirty && <button className="btn ghost sm" onClick={revert} disabled={busy}>放弃修改</button>}
          {justSaved && <span className="ok-text">已保存</span>}
        </div>
        {clampedFields.size > 0 && (
          <p className="note" style={{ marginTop: 'var(--s-3)' }}>
            标「已钳位」的输入超出服务端允许范围，已按上限保存。
          </p>
        )}
      </div>

      <AuxIdleSettings onSaved={() => void load()} />

      <RecordSettings onSaved={() => void load()} />

      <DataDir />

      <div className="card">
        <h2>实际生效</h2>
        {applied === null ? (
          <div className="empty" style={{ padding: 'var(--s-3)' }}>
            保存后这里会显示每个已加载模型真正生效的上限。
          </div>
        ) : appliedIds.length === 0 ? (
          <div className="empty" style={{ padding: 'var(--s-3)' }}>
            没有已加载的模型。设置已保存，下次加载模型时生效。
          </div>
        ) : (
          <div className="grid" style={{ gap: 'var(--s-2)' }}>
            {appliedIds.map((id) => {
              const a = applied[id]
              const name = names[id] ?? id
              if (a.error) {
                return (
                  <div key={id} className="value">
                    <span className="mono">{name}</span>：<span className="err-text">{a.error}</span>
                  </div>
                )
              }
              return (
                <div key={id} className="value">
                  <span className="mono">{name}</span>：缓存实际上限 {fmtMb(a.cache_max_bytes)}
                  （NPU 可用 {fmtMb(a.cache_npu_cap_bytes ?? null)}）
                  <span className="muted">
                    {' · '}并发 {a.max_concurrent ?? '—'}
                    {' · '}排队 {a.max_queue ?? '—'}
                    {' · '}条目 {a.cache_entries ?? '—'}
                    {' · '}精确尾部 {a.exact_tail ?? '—'}
                    {a.kv_budget_bytes != null && <>{' · '}会话+缓存可用 {fmtMb(a.kv_budget_bytes)}</>}
                  </span>
                </div>
              )
            })}
          </div>
        )}
        {appliedIds.length > 0 && (
          <p className="note" style={{ marginTop: 'var(--s-3)' }}>
            缓存和会话共用「模型内存上限 − 静态占用」的额度，并受设备可用空间限制。会话运行时会优先回收缓存。
          </p>
        )}
      </div>
    </>
  )
}

/** Inference record settings (MYS-2496).
 *
 *  Its own card rather than two more rows in the form above: the switch and the
 *  retention pair are about *storing evidence*, not about serving tokens, and
 *  the save path is different -- these are persisted and applied to the live
 *  store immediately, with no worker to push them to. Keeping them here means
 *  one settings page, not a parallel entry point.
 */
/** Idle unload and on-demand load for the auxiliary models. Saved on its own
 *  because it is a service policy, not a limit pushed to each loaded worker. */
function AuxIdleSettings({ onSaved }: { onSaved: () => void }) {
  const [minutes, setMinutes] = useState('')
  const [limit, setLimit] = useState(1440)
  const [autoLoad, setAutoLoad] = useState<boolean | null>(null)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const fill = (s: Settings) => {
    setMinutes(String(s.aux_idle_unload_min ?? 0))
    setLimit(s.aux_idle_unload_limit_min ?? 1440)
    setAutoLoad(s.aux_auto_load ?? false)
  }

  useEffect(() => {
    api.getSettings().then(fill)
      .catch((e) => setErr(e instanceof Error ? e.message : '读取失败'))
  }, [])

  const save = async () => {
    setBusy(true)
    setErr('')
    setSaved(false)
    try {
      const patch: SettingsPatch = { aux_auto_load: autoLoad ?? false }
      if (minutes.trim() !== '') {
        const n = Number(minutes)
        if (!Number.isFinite(n)) throw new Error('空闲时间需要填整数')
        patch.aux_idle_unload_min = Math.trunc(n)
      }
      const r = await api.saveSettings(patch)
      fill(r.settings)
      setSaved(true)
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  const off = minutes.trim() === '0'
  return (
    <div className="card" style={{ marginBottom: 'var(--s-4)' }} data-testid="aux-idle-settings">
      <h2>辅助模型自动卸载</h2>
      <p className="sub" style={{ marginTop: 0 }}>
        {'Embedding、Reranker、语音识别、OCR 加载后一直占着 NPU 和内存（推理本身不会多占）。'
          + '开启后，空闲到时间就自动卸载，下次用到时再自动加载。大语言模型不受影响。'
          + '两项默认关闭，建议一起开启（例如 10 分钟 + 按需自动加载）。'
          + '这里是没有单独设置的辅助模型使用的默认值；每个模型（包括大模型）都可以在「模型」页的「设置」里单独配置。'}
      </p>

      {err && <p className="err-text">{err}</p>}

      {autoLoad === null ? (
        <div className="empty"><span className="spin" /> 正在读取…</div>
      ) : (
        <>
          <div className="grid" style={{ gap: 'var(--s-5)' }}>
            <div className="field-row">
              <div>
                <div className="metric-label" style={{ marginBottom: 'var(--s-1)' }}>
                  空闲多久后卸载<span className="range">0–{limit} 分钟</span>
                </div>
                <input
                  type="number" value={minutes} min={0} max={limit} aria-label="空闲多久后卸载"
                  data-testid="aux-idle-minutes"
                  onChange={(e) => setMinutes(e.target.value)}
                />
              </div>
              <p className="note" style={{ margin: 0 }}>
                {off ? '0 = 不自动卸载（默认），辅助模型一直保持加载，直到手动卸载。'
                  : '没有请求在处理、且超过这段时间没被用过，就卸载并释放 NPU 和内存；0 = 不自动卸载。'}
              </p>
            </div>
          </div>
          <div className="field inline" style={{ marginTop: 'var(--s-4)', flexWrap: 'wrap' }}>
            <input
              type="checkbox" id="aux-auto-load" checked={autoLoad} data-testid="aux-auto-load"
              onChange={(e) => setAutoLoad(e.target.checked)}
            />
            <label htmlFor="aux-auto-load" style={{ whiteSpace: 'nowrap' }}>按需自动加载</label>
            <span className="note" style={{ margin: 0, flex: '1 1 18rem' }}>
              API、知识库、MCP 用到未加载的辅助模型时自动加载（Embedding 约 4 秒）；关闭后返回「未加载」。
            </span>
          </div>

          {!off && minutes.trim() !== '' && !autoLoad && (
            <p className="note warn-note" style={{ marginTop: 'var(--s-3)' }} data-testid="aux-idle-warn">
              只开了自动卸载：卸载后的请求会返回「未加载」，需要手动加载。
            </p>
          )}

          <div className="row" style={{ marginTop: 'var(--s-5)' }}>
            <button className="btn" onClick={() => void save()} disabled={busy} data-testid="aux-idle-save">
              {busy ? '保存中…' : '保存'}
            </button>
            {saved && <span className="ok-text">已保存，立即生效</span>}
          </div>
        </>
      )}
    </div>
  )
}

function RecordSettings({ onSaved }: { onSaved: () => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [count, setCount] = useState('')
  const [days, setDays] = useState('')
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getSettings()
      .then((s) => {
        setEnabled(s.inference_logging_enabled)
        setCount(String(s.inference_log_retention_count))
        setDays(String(s.inference_log_retention_days))
      })
      .catch((e) => setErr(e instanceof Error ? e.message : '读取失败'))
  }, [])

  const save = async () => {
    setBusy(true)
    setErr('')
    setSaved(false)
    try {
      const patch: SettingsPatch = { inference_logging_enabled: enabled ?? true }
      // An empty box keeps the stored number rather than writing 0, which the
      // server would clamp to 1 anyway -- the operator would see a value they
      // never typed.
      if (count.trim() !== '') patch.inference_log_retention_count = Math.trunc(Number(count))
      if (days.trim() !== '') patch.inference_log_retention_days = Math.trunc(Number(days))
      const r = await api.saveSettings(patch)
      setEnabled(r.settings.inference_logging_enabled)
      setCount(String(r.settings.inference_log_retention_count))
      setDays(String(r.settings.inference_log_retention_days))
      setSaved(true)
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ marginBottom: 'var(--s-4)' }} data-testid="record-settings">
      <h2>推理记录</h2>
      <p className="sub" style={{ marginTop: 0 }}>
        每次推理落一条记录，用于事后定位异常输出。记录里是客户真实对话，
        默认明文保存在数据目录的 <span className="mono">state/inference_records.sqlite3</span>，
        仅管理员可查看；在「推理记录」页可以导出或全部清空。
      </p>

      {err && <p className="err-text">{err}</p>}

      {enabled === null ? (
        <div className="empty"><span className="spin" /> 正在读取…</div>
      ) : (
        <>
          <div className="field inline">
            <input
              type="checkbox" id="record-enabled" checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <label htmlFor="record-enabled">启用推理记录</label>
            <span className="note" style={{ margin: 0 }}>
              关闭后新的推理不再落盘，已有记录保留。
            </span>
          </div>

          <div className="grid" style={{ gap: 'var(--s-5)', marginTop: 'var(--s-4)' }}>
            <div className="field-row">
              <div>
                <div className="metric-label" style={{ marginBottom: 'var(--s-1)' }}>
                  保留条数<span className="range">1–100000 条</span>
                </div>
                <input
                  type="number" value={count} min={1} max={100000} aria-label="保留条数"
                  disabled={!enabled}
                  onChange={(e) => setCount(e.target.value)}
                />
              </div>
              <p className="note" style={{ margin: 0 }}>
                只保留最新的这么多条，更旧的记录在下一次写入时被删除。
              </p>
            </div>
            <div className="field-row">
              <div>
                <div className="metric-label" style={{ marginBottom: 'var(--s-1)' }}>
                  保留天数<span className="range">1–3650 天</span>
                </div>
                <input
                  type="number" value={days} min={1} max={3650} aria-label="保留天数"
                  disabled={!enabled}
                  onChange={(e) => setDays(e.target.value)}
                />
              </div>
              <p className="note" style={{ margin: 0 }}>
                超过这么多天的记录也会被删除。两条规则同时生效，保留更少的那一条说了算。
              </p>
            </div>
          </div>

          <div className="row" style={{ marginTop: 'var(--s-5)' }}>
            <button className="btn" onClick={() => void save()} disabled={busy}>
              {busy ? '保存中…' : '保存'}
            </button>
            {saved && <span className="ok-text">已保存，立即生效</span>}
          </div>
        </>
      )}
    </div>
  )
}

/** How each move state reads to an operator. `running` decides whether the
 *  page keeps polling; the wording is the progress the copy actually reports. */const MOVE_STATES: Record<MoveJob['state'], { label: string; running?: boolean }> = {
  idle: { label: '空闲' },
  checking: { label: '检查目标目录…', running: true },
  stopping: { label: '卸载模型、停止 agent…', running: true },
  copying: { label: '复制数据…', running: true },
  verifying: { label: '校验副本…', running: true },
  switching: { label: '切换数据目录…', running: true },
  done: { label: '完成' },
  failed: { label: '失败' },
}

/** The data directory: where it is, how full the disk is, and moving it.
 *
 *  A move unloads every model, copies 20+ GB and rewrites the service
 *  configuration, so the button asks for confirmation and the page then polls
 *  GET /api/storage/move once a second until the job settles.
 */
function DataDir() {
  const [info, setInfo] = useState<StorageInfo | null>(null)
  const [path, setPath] = useState('')
  const [job, setJob] = useState<MoveJob | null>(null)
  const [err, setErr] = useState('')
  const [starting, setStarting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const timer = useRef<number | null>(null)

  const load = useCallback(async (refresh = false) => {
    try {
      const s = await api.storage(refresh)
      setInfo(s)
      setPath((p) => (p === '' ? s.data_dir : p))
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取数据目录失败')
    }
  }, [])

  const stopPolling = useCallback(() => {
    if (timer.current !== null) { window.clearInterval(timer.current); timer.current = null }
  }, [])

  const poll = useCallback(async () => {
    try {
      const j = await api.moveStatus()
      setJob(j)
      if (MOVE_STATES[j.state]?.running) return
      stopPolling()
      if (j.state === 'done') {
        await load(true)
        setPath(j.new)
      }
    } catch (e) {
      stopPolling()
      setErr(e instanceof Error ? e.message : '读取迁移状态失败')
    }
  }, [load, stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    timer.current = window.setInterval(() => void poll(), 1000)
  }, [poll, stopPolling])

  useEffect(() => {
    void load()
    // A move started in another tab (or a page reload mid-copy) is picked up
    // here rather than being lost with the previous render.
    void api.moveStatus().then((j) => {
      setJob(j)
      if (MOVE_STATES[j.state]?.running) startPolling()
    }).catch(() => undefined)
    return stopPolling
  }, [load, startPolling, stopPolling])

  const move = async () => {
    setConfirming(false)
    setStarting(true)
    setErr('')
    try {
      await api.startMove(path.trim())
      startPolling()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '迁移失败')
    } finally {
      setStarting(false)
    }
  }

  const running = job !== null && MOVE_STATES[job.state]?.running === true
  const pct = job && job.total_bytes > 0
    ? Math.min(100, (job.copied_bytes / job.total_bytes) * 100)
    : null
  const fsPct = info && info.fs_total_bytes ? (info.fs_used_bytes / info.fs_total_bytes) * 100 : null

  return (
    <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
      <h2>数据目录</h2>
      <p className="sub" style={{ marginTop: 0 }}>
        模型、密钥、用量与日志都在这个目录里。换到别的盘会先卸载所有模型，再复制、校验、切换；
        失败时新目录会被清空，配置与运行中的路径都保持原样。
      </p>

      {err && <p className="err-text">{err}</p>}

      {info && (
        <>
          <div className="metric-label" style={{ marginBottom: 'var(--s-1)' }}>当前路径</div>
          <div className="mono" style={{ wordBreak: 'break-all', marginBottom: 'var(--s-3)', display: 'block' }}>
            {info.data_dir}
          </div>
          <div className={fsPct !== null && fsPct > 90 ? 'bar err' : fsPct !== null && fsPct > 70 ? 'bar warn' : 'bar'}>
            <span style={{ width: `${Math.min(100, fsPct ?? 0)}%` }} />
          </div>
          <div className="note tight">
            服务占用 {fmtBytes(info.dir_bytes)}（模型 {fmtBytes(info.parts.models)}） ·
            文件系统已用 {fmtBytes(info.fs_used_bytes)} / 共 {fmtBytes(info.fs_total_bytes)} ·
            可用 {fmtBytes(info.fs_free_bytes)}
          </div>
        </>
      )}

      <div className="row" style={{ marginTop: 'var(--s-4)', alignItems: 'flex-start' }}>
        <input
          type="text" value={path} aria-label="新的数据目录"
          placeholder="/data/cv84x6_llm_server"
          onChange={(e) => setPath(e.target.value)}
          disabled={running || starting}
          style={{ flex: 1, minWidth: 256, fontFamily: 'var(--mono)' }}
        />
        <button
          className="btn" disabled={running || starting || path.trim() === ''}
          onClick={() => setConfirming(true)}
        >
          {running ? '迁移中…' : starting ? '提交中…' : '迁移'}
        </button>
      </div>
      <p className="note" style={{ marginTop: 'var(--s-3)' }}>
        目标必须是不存在或空的绝对路径，可用空间要比当前占用多 1 GB。迁移期间模型全部卸载，
        推理请求会失败。
      </p>

      {confirming && (
        <div className="card confirm" data-testid="move-confirm">
          <p style={{ margin: 0 }}>
            把数据目录从 <span className="mono">{info?.data_dir}</span> 迁到{' '}
            <span className="mono">{path.trim()}</span>？
          </p>
          <p className="note tight">
            会先卸载所有模型、停止推理，然后复制并校验；成功后删除旧目录。
          </p>
          <div className="row" style={{ marginTop: 'var(--s-3)' }}>
            <button className="btn danger-solid sm" onClick={() => void move()}>确认迁移</button>
            <button className="btn ghost sm" onClick={() => setConfirming(false)}>取消</button>
          </div>
        </div>
      )}

      {job && job.state !== 'idle' && (
        <div style={{ marginTop: 'var(--s-4)' }}>
          <div className="row" style={{ alignItems: 'baseline' }}>
            <span className={job.state === 'failed' ? 'err-text' : job.state === 'done' ? 'ok-text' : ''}>
              {MOVE_STATES[job.state]?.label ?? job.state}
            </span>
            {job.total_bytes > 0 && (
              <span className="note">
                {fmtBytes(job.copied_bytes)} / {fmtBytes(job.total_bytes)}
                {pct !== null && <> · {pct.toFixed(0)}%</>}
              </span>
            )}
          </div>
          <div className={job.state === 'failed' ? 'bar err' : 'bar'}>
            <span style={{ width: `${job.state === 'done' ? 100 : (pct ?? (running ? 4 : 0))}%` }} />
          </div>
          {job.message && (
            <p className={job.state === 'failed' ? 'err-text' : 'note'} style={{ marginTop: 'var(--s-2)' }}>
              {job.message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
