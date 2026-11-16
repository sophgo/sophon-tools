import { useEffect, useState } from 'react'
import { api, fmtBytes, type ModelSettingsView } from '../api'

/** One model's own settings (MYS-2675): idle unload, on-demand load and the
 *  device-memory ceiling. Each field is either "跟随默认" (saved as null) or a
 *  value the operator chose, and the form says which default it would follow,
 *  so an operator never has to guess what null means. docs/model-settings.md. */

const AUX = ['embedding', 'rerank', 'asr', 'ocr']

type IdleMode = 'default' | 'off' | 'custom'
type LoadMode = 'default' | 'on' | 'off'
type MemMode = 'default' | 'custom'

export default function ModelSettings({ id, onSaved, onClose }: {
  id: string
  onSaved: () => void
  onClose: () => void
}) {
  const [view, setView] = useState<ModelSettingsView | null>(null)
  const [globals, setGlobals] = useState<{ idle: number; auto: boolean } | null>(null)
  const [idleMode, setIdleMode] = useState<IdleMode>('default')
  const [idleMin, setIdleMin] = useState('10')
  const [loadMode, setLoadMode] = useState<LoadMode>('default')
  const [memMode, setMemMode] = useState<MemMode>('default')
  const [memMb, setMemMb] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const fill = (v: ModelSettingsView) => {
    setView(v)
    const s = v.settings
    if (s.idle_unload_min === null) setIdleMode('default')
    else if (s.idle_unload_min === 0) setIdleMode('off')
    else { setIdleMode('custom'); setIdleMin(String(s.idle_unload_min)) }
    setLoadMode(s.auto_load === null ? 'default' : s.auto_load ? 'on' : 'off')
    if (s.mem_limit_mb === null) {
      setMemMode('default')
      setMemMb(v.mem_limit_default_bytes ? String(Math.round(v.mem_limit_default_bytes / 2 ** 20)) : '')
    } else { setMemMode('custom'); setMemMb(String(s.mem_limit_mb)) }
  }

  useEffect(() => {
    api.modelSettings(id).then(fill).catch((e) => setErr(e instanceof Error ? e.message : '读取失败'))
    api.getSettings().then((s) => setGlobals({ idle: s.aux_idle_unload_min ?? 0, auto: Boolean(s.aux_auto_load) }))
      .catch(() => undefined)
  }, [id])

  if (!view) {
    return <div className="model-settings">{err ? <p className="err-text">{err}</p> : <span className="spin" />}</div>
  }

  const aux = AUX.includes(view.kind)
  // What "跟随默认" resolves to for this kind: the global values only reach the
  // auxiliary kinds; chat and OCR-VL default to off whatever they say.
  const dIdle = aux ? (globals?.idle ?? 0) : 0
  const dAuto = aux ? Boolean(globals?.auto) : false
  const dMem = view.mem_limit_default_bytes
  const lim = view.limits

  const save = async () => {
    setBusy(true)
    setErr('')
    try {
      const body: { idle_unload_min: number | null; auto_load: boolean | null; mem_limit_mb: number | null } = {
        idle_unload_min: idleMode === 'default' ? null : idleMode === 'off' ? 0 : Math.trunc(Number(idleMin)),
        auto_load: loadMode === 'default' ? null : loadMode === 'on',
        mem_limit_mb: memMode === 'default' ? null : Math.trunc(Number(memMb)),
      }
      if (idleMode === 'custom' && !(body.idle_unload_min! >= 1 && body.idle_unload_min! <= lim.idle_unload_min_max)) {
        throw new Error(`空闲时间需要 1–${lim.idle_unload_min_max} 分钟`)
      }
      if (memMode === 'custom' && !(body.mem_limit_mb! >= lim.mem_limit_mb_min && body.mem_limit_mb! <= lim.mem_limit_mb_max)) {
        throw new Error(`内存上限需要 ${lim.mem_limit_mb_min}–${lim.mem_limit_mb_max} MiB`)
      }
      fill(await api.saveModelSettings(id, body))
      onSaved()
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  const staticB = view.mem_static_bytes
  const usedB = view.mem_used_bytes
  return (
    <div className="model-settings" data-testid={`model-settings-${id}`}>
      <div className="ms-row">
        <div className="ms-label">空闲自动卸载</div>
        <div className="ms-control">
          <select value={idleMode} onChange={(e) => setIdleMode(e.target.value as IdleMode)} data-testid="ms-idle-mode">
            <option value="default">跟随默认（{dIdle ? `${dIdle} 分钟` : '不卸载'}）</option>
            <option value="off">不自动卸载</option>
            <option value="custom">空闲一段时间后卸载</option>
          </select>
          {idleMode === 'custom' && (
            <span className="ms-inline">
              <input type="number" min={1} max={lim.idle_unload_min_max} value={idleMin}
                     onChange={(e) => setIdleMin(e.target.value)} aria-label="空闲分钟数" data-testid="ms-idle-min" />
              <span className="note">分钟</span>
            </span>
          )}
        </div>
        <p className="note ms-help">
          {(aux ? '全局默认在「设置 → 辅助模型自动卸载」。' : '大模型默认不自动卸载，只有在这里单独开启才会生效。')
            + '没有请求在处理、并且超过这段时间没被用过，才会卸载。'}
        </p>
      </div>

      <div className="ms-row">
        <div className="ms-label">按需自动加载</div>
        <div className="ms-control">
          <select value={loadMode} onChange={(e) => setLoadMode(e.target.value as LoadMode)} data-testid="ms-load-mode">
            <option value="default">跟随默认（{dAuto ? '开启' : '关闭'}）</option>
            <option value="on">开启</option>
            <option value="off">关闭</option>
          </select>
        </div>
        <p className="note ms-help">
          未加载时有请求用到它，就先加载再处理；关闭时返回「未加载」。{!aux && view.auto_load_note}
        </p>
      </div>

      <div className="ms-row">
        <div className="ms-label">设备内存上限</div>
        <div className="ms-control">
          <select value={memMode} onChange={(e) => {
            const m = e.target.value as MemMode
            setMemMode(m)
            if (m === 'custom' && !memMb && dMem) setMemMb(String(Math.round(dMem / 2 ** 20)))
          }} data-testid="ms-mem-mode">
            <option value="default">推算默认（{dMem ? fmtBytes(dMem) : '未知'}）</option>
            <option value="custom">自定义</option>
          </select>
          {memMode === 'custom' && (
            <span className="ms-inline">
              <input type="number" min={lim.mem_limit_mb_min} max={lim.mem_limit_mb_max} step={64} value={memMb}
                     onChange={(e) => setMemMb(e.target.value)} aria-label="内存上限 MiB" data-testid="ms-mem-mb" />
              <span className="note">MiB</span>
            </span>
          )}
        </div>
        <p className="note ms-help">
          {`静态占用 ${staticB ? fmtBytes(staticB) : '加载后可知'}${usedB !== null ? ` · 当前占用 ${fmtBytes(usedB)}` : ''}。`
            + '静态占用超过上限时拒绝加载；会话和前缀缓存只能用「上限 − 静态占用」，超出时请求排队。'}
        </p>
      </div>

      {err && <p className="err-text" data-testid="ms-error">{err}</p>}
      <div className="row" style={{ marginTop: 'var(--s-3)' }}>
        <button className="btn sm" onClick={() => void save()} disabled={busy} data-testid="ms-save">
          {busy ? '保存中…' : '保存'}
        </button>
        <button className="btn ghost sm" onClick={onClose} disabled={busy}>取消</button>
        <div className="spacer" />
        <span className="note">立即生效，不需要重新加载</span>
      </div>
    </div>
  )
}
