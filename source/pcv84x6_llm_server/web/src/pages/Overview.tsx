import { useEffect, useRef, useState } from 'react'
import PageSkeleton from '../components/Skeleton'
import { api, fmtBytes, fmtMb, fmtPct, type Agent, type SmiStats, type Stats, type StorageInfo } from '../api'
import Chart, { type Point } from '../components/Chart'

/** The four trees a data directory holds. Labels here, keys in the API. */
const PART_LABELS: [keyof StorageInfo['parts'], string][] = [
  ['models', '模型'],
  ['state', '状态与日志'],
  ['agents', 'Agent 数据'],
  ['downloads', '下载临时文件'],
]

/** How many device samples the CPU chart keeps: 60 samples at the 2 s poll is
 *  two minutes of history. The x axis carries real timestamps, so the window is
 *  whatever the samples span -- nothing is invented. */
const CPU_WINDOW = 60

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [storage, setStorage] = useState<StorageInfo | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [err, setErr] = useState('')
  const cpuHist = useRef<Point[]>([])
  const tpuHist = useRef<Point[]>([])

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const s = await api.stats()
        if (!alive) return
        setStats(s)
        setErr('')
        // A null reading is kept as a gap in the series: the driver does not
        // report CPU on the first sample, and drawing it as 0% would be a lie.
        cpuHist.current = [
          ...cpuHist.current,
          { t: Date.now(), v: s.device.cpu_percent },
        ].slice(-CPU_WINDOW)
        tpuHist.current = [
          ...tpuHist.current,
          { t: Date.now(), v: s.device.tpu_usage?.percent ?? null },
        ].slice(-CPU_WINDOW)
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : '读取失败')
      }
      // Its own request: the data directory is on a different poll and its size
      // walk is cached server-side, so a failure here must not blank the page.
      try {
        const s = await api.storage()
        if (alive) setStorage(s)
      } catch { /* the disk card below falls back to the model figure */ }
      // Same again for agents: on a board with no agent installed this is an
      // empty list, and a failure must not take the resource view with it.
      try {
        const a = await api.agents()
        if (alive) setAgents(a.agents)
      } catch { /* the shortcut row simply stays hidden */ }
    }
    void tick()
    const id = setInterval(() => void tick(), 2000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (err && !stats) return <><h1>总览</h1><p className="err-text">读取设备状态失败：{err}</p></>
  if (!stats) return <PageSkeleton title="总览" sub="设备资源与推理服务实时状态，每 2 秒刷新。" stats={4} blocks={2} label="正在读取设备状态…" />

  const d = stats.device
  const mem = d.memory
  const memPct = mem.total_bytes && mem.used_bytes ? (mem.used_bytes / mem.total_bytes) * 100 : null
  const diskPct = stats.disk.total_bytes ? (stats.disk.used_bytes / stats.disk.total_bytes) * 100 : null
  // Device memory = every heap the TPU can keep models in (NPU + VPP on
  // CV84X6, MYS-2673). Older servers only report the NPU heap via bm-smi; that
  // is shown as the device figure with a note rather than as a different card.
  const dm = d.device_mem
  const dmHeaps = dm?.heaps ?? []
  const smi: SmiStats = d.npu.smi ?? {}
  const devTotal = dm?.total_bytes ?? smi.mem_total_bytes ?? null
  const devUsed = dm?.used_bytes ?? smi.mem_used_bytes ?? null
  const devPct = devTotal && devUsed !== null ? (devUsed / devTotal) * 100 : null
  const reserve = stats.vpp_reserve
  const tpu = d.tpu_usage
  const tpuPct = tpu?.percent ?? d.npu.total_percent ?? null
  const tpuCores = tpu?.cores ?? d.npu.cores ?? []
  const loaded = stats.models.filter((m) => m.loaded)
  // Only the ones actually serving: the shortcut is a "jump into a running
  // agent" row, and a stopped agent's link would only fail.
  const runningAgents = agents.filter((a) => a.running)
  const inflight = Object.values(stats.workers).reduce((a: number, w: any) => a + (w?.active ?? 0), 0)
  // tps_history is [unix-seconds, tok/s]; the chart plots them against that real
  // timestamp rather than against a sample index, so the x axis means time.
  const tpsPoints: Point[] = stats.usage.tps_history.map(([t, v]) => ({ t: t * 1000, v }))
  // Where the prefix-cache KV lives and how much it costs. On this board device
  // memory is plentiful (~24 GiB) and system RAM is not (~2.5 GiB), so a cache
  // that quietly sits in RAM is a capacity problem waiting to happen.
  const kvEntries = Object.values(stats.kv_cache ?? {})
  // v0.2.0 ships with the prefix cache off: every backend reports
  // enabled=false, and cached_tokens stays 0. Showing a 0.0% hit rate there
  // reads as "broken", so say plainly that it is not on.
  const kvDisabled = kvEntries.length === 0 || kvEntries.every((e) => e.enabled === false)
  const kvTotal = kvEntries.reduce((a, e) => a + (e.bytes ?? 0), 0)
  // The ceiling actually in force, summed across models because the card is
  // service-wide. A model that reports no ceiling contributes 0 rather than
  // making the whole figure unknown.
  const kvMax = kvEntries.reduce((a, e) => a + (e.max_bytes ?? 0), 0)
  const kvTtlS = kvEntries[0]?.ttl_s ?? 0
  // 0 minutes is "keep forever", which is a setting, not a missing value.
  const kvTtl = kvTtlS ? `${Math.round(kvTtlS / 60)} 分钟` : '不过期'
  // The mock backend has no real KV store, so an unknown location is normal
  // there; say so rather than showing a bare dash that reads as a failure.
  const kvLocation = kvEntries[0]?.location === 'device' ? '设备内存'
    : kvEntries[0]?.location === 'host' ? '系统内存'
    : kvEntries[0]?.location === 'tiered' ? '设备内存优先，超出后回退系统内存'
    : kvEntries.length ? '该后端不上报位置' : '暂无缓存条目'
  const kvHit = kvEntries.length
    ? kvEntries.reduce((a, e) => a + (e.tokens_reused ?? 0), 0) /
      Math.max(1, kvEntries.reduce((a, e) => a + (e.tokens_reused ?? 0) + (e.tokens_prompted ?? 0), 0))
    : 0

  const barClass = (p: number | null) => (p === null ? '' : p > 90 ? 'bar err' : p > 70 ? 'bar warn' : 'bar')
  // The filesystem is what runs out, not our own footprint: /data on the board
  // also holds everything else, so the bar tracks total used space.
  const fsPct = storage && storage.fs_total_bytes
    ? (storage.fs_used_bytes / storage.fs_total_bytes) * 100
    : null
  const lastTps = tpsPoints.length ? tpsPoints[tpsPoints.length - 1].v : null

  return (
    <>
      <h1>总览</h1>
      <p className="sub">设备资源与推理服务实时状态，每 2 秒刷新。</p>
      {err && <p className="err-text">刷新失败（显示的是上一次的数据）：{err}</p>}

      <div className="grid c4" data-testid="overview-summary">
        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">在线模型</div>
            <div className="metric">
              {loaded.length}
              {stats.max_loaded_models > 0 && <span className="unit"> / 上限 {stats.max_loaded_models}</span>}
            </div>
          </div>
          <div className="stat-dock note">
            {loaded.map((m) => m.display_name).join('、') || '未加载模型'}
          </div>
        </div>
        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">正在推理</div>
            <div className="metric">{inflight}</div>
          </div>
          <div className="stat-dock note">累计请求 {stats.usage.requests}</div>
        </div>
        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">缓存命中率</div>
            {kvDisabled
              ? <div className="metric small">未启用</div>
              : <div className="metric">{fmtPct((kvHit || stats.usage.cache_hit_rate) * 100)}</div>}
          </div>
          <div className="stat-dock note">
            {kvDisabled
              ? (kvEntries.length === 0 ? '还没有加载对话模型' : '已加载的模型不使用前缀缓存')
              : `已用 ${fmtMb(kvTotal)} / 模型额度合计 ${fmtMb(kvMax)} · 保留 ${kvTtl}`}
          </div>
        </div>
        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">累计 Token</div>
            <div className="metric">{stats.usage.completion_tokens.toLocaleString()}</div>
          </div>
          <div className="stat-dock note">
            输入 {stats.usage.prompt_tokens.toLocaleString()}
          </div>
        </div>
      </div>

      {runningAgents.length > 0 && (
        <>
          <h2>开源 Agent</h2>
          <div className="card tight">
            <div className="row">
              <span className="note">
                正在运行 {runningAgents.length} 个，点一下直接进入：
              </span>
              {runningAgents.map((a) => (
                <a key={a.id} className="btn ghost sm" href={a.web_url} target="_blank" rel="noreferrer">
                  {a.name}
                </a>
              ))}
              <div className="spacer" />
              <span className="note">在「Agent」页安装、启停与配置</span>
            </div>
          </div>
        </>
      )}

      <h2>设备资源</h2>
      <div className="grid c3" data-testid="overview-device">
        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">CPU 使用率</div>
            <div className="metric small">{fmtPct(d.cpu_percent)}</div>
            <div className={barClass(d.cpu_percent)}>
              <span style={{ width: `${Math.min(100, d.cpu_percent ?? 0)}%` }} />
            </div>
          </div>
          <div className="stat-dock note">
            负载 {d.load_average.join(' / ') || '—'}（1/5/15 分钟）
          </div>
        </div>

        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">系统内存</div>
            <div className="metric small">
              {fmtBytes(mem.used_bytes)}
              <span className="unit"> / {fmtBytes(mem.total_bytes)}</span>
            </div>
            <div className={barClass(memPct)}>
              <span style={{ width: `${Math.min(100, memPct ?? 0)}%` }} />
            </div>
          </div>
          <div className="stat-dock note">可用 {fmtBytes(mem.available_bytes)}</div>
        </div>

        <div className="card tight stat" data-testid="device-mem">
          <div className="stat-main">
            <div className="metric-label">设备内存</div>
            <div className="metric small">
              {fmtBytes(devUsed)}
              <span className="unit"> / {fmtBytes(devTotal)}</span>
            </div>
            {dmHeaps.length > 1 ? (
              <div className="heap-bar" role="img"
                   aria-label={dmHeaps.map((h) => `${h.name.toUpperCase()} 已用 ${fmtBytes(h.used_bytes)} / ${fmtBytes(h.total_bytes)}`).join('，')}>
                {dmHeaps.map((h) => (
                  <span key={h.name} className={`heap heap-${h.name}`}
                        style={{ flexGrow: h.total_bytes || 1 }}
                        title={`${h.name.toUpperCase()}：已用 ${fmtBytes(h.used_bytes)} / ${fmtBytes(h.total_bytes)}`}>
                    <span className={barClass(h.total_bytes ? (h.used_bytes / h.total_bytes) * 100 : null)
                      .replace('bar', 'fill')}
                          style={{ width: `${Math.min(100, h.total_bytes ? (h.used_bytes / h.total_bytes) * 100 : 0)}%` }} />
                  </span>
                ))}
              </div>
            ) : (
              <div className={barClass(devPct)}>
                <span style={{ width: `${Math.min(100, devPct ?? 0)}%` }} />
              </div>
            )}
          </div>
          <div className="stat-dock note" data-testid="device-mem-heaps">
            {dmHeaps.length
              ? dmHeaps.map((h) => `${h.name.toUpperCase()} ${fmtBytes(h.used_bytes)} / ${fmtBytes(h.total_bytes)}`).join(' · ')
              : smi.mem_total_bytes ? '仅 NPU 堆（来自 bm-smi）' : `前缀缓存占用 ${fmtBytes(kvTotal)}（${kvLocation}）`}
            {reserve?.acquired ? ` · VPP 为多媒体保留 ${fmtBytes(reserve.held_bytes)}` : ''}
          </div>
        </div>

        <div className="card tight stat" data-testid="tpu-usage">
          <div className="stat-main">
            <div className="metric-label">TPU 使用率</div>
            <div className="metric small">{fmtPct(tpuPct)}</div>
            <div className={barClass(tpuPct)}>
              <span style={{ width: `${Math.min(100, tpuPct ?? 0)}%` }} />
            </div>
          </div>
          <div className="stat-dock note">
            {tpuCores.length
              ? tpuCores.map((c, i) => `核 ${i} ${c.toFixed(0)}%`).join(' · ')
              : '未读到使用率（需要驱动使能 npu_usage_enable）'}
          </div>
        </div>

        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">磁盘 (/data)</div>
            <div className="metric small">
              {fmtBytes(stats.disk.free_bytes)}
              <span className="unit"> 可用</span>
            </div>
            <div className={barClass(diskPct)}>
              <span style={{ width: `${Math.min(100, diskPct ?? 0)}%` }} />
            </div>
          </div>
          <div className="stat-dock note">
            模型占用 {fmtBytes(stats.disk.models_bytes)} / 共 {fmtBytes(stats.disk.total_bytes)}
          </div>
        </div>

        <div className="card tight stat">
          <div className="stat-main">
            <div className="metric-label">温度</div>
            <div className="row" style={{ gap: 'var(--s-2)', marginTop: 2 }}>
              {d.temperatures.length
                ? d.temperatures.slice(0, 4).map((t) => (
                    <span key={t.zone} className="pill">{t.celsius.toFixed(1)}°C</span>
                  ))
                : <span className="note">未读到传感器</span>}
            </div>
          </div>
          <div className="stat-dock note">
            {d.temperatures.length
              ? `最高 ${Math.max(...d.temperatures.map((t) => t.celsius)).toFixed(1)}°C · ${d.temperatures.length} 个传感器`
              : '—'}
          </div>
        </div>
      </div>

      {/* CPU and TPU side by side (same window, same scale), decode speed below at
          full width: all three answer "is the box coping".
          They used to sit as two cards of different heights inside the 3-up
          resource grid, which left the two short cards below them carrying the
          taller card's height as ~130px of empty space. */}
      <h2>实时曲线</h2>
      <div className="grid c2" data-testid="overview-charts">
        <div className="card tight">
          <div className="row" style={{ alignItems: 'baseline', marginBottom: 'var(--s-1)' }}>
            <div className="metric-label" style={{ marginBottom: 0 }}>CPU 使用率</div>
            <div className="spacer" />
            <span className="note">最近两分钟，每 2 秒一个采样</span>
          </div>
          <Chart
            label="CPU 使用率" unit="%" points={cpuHist.current}
            yMax={100} digits={0} height={168} testId="chart-cpu" bare
            hint={`负载 ${d.load_average.join(' / ') || '—'}（1/5/15 分钟）`}
          />
        </div>

        <div className="card tight" data-testid="tpu-chart">
          <div className="row" style={{ alignItems: 'baseline', marginBottom: 'var(--s-1)' }}>
            <div className="metric-label" style={{ marginBottom: 0 }}>TPU 使用率</div>
            <div className="spacer" />
            <span className="note">最近两分钟，每 2 秒一个采样</span>
          </div>
          <Chart
            label="TPU 使用率" unit="%" points={tpuHist.current}
            yMax={100} digits={0} height={168} testId="chart-tpu" bare
            hint={tpuCores.length ? `四个核：${tpuCores.map((c) => `${c.toFixed(0)}%`).join(' / ')}` : '未读到使用率'}
          />
        </div>

        <div className="card tight" data-testid="inference-speed" style={{ gridColumn: '1 / -1' }}>
          <div className="row" style={{ alignItems: 'baseline', marginBottom: 'var(--s-1)' }}>
            <div>
              <div className="metric-label" style={{ marginBottom: 'var(--s-1)' }}>最新 decode 速度</div>
              <div className="metric small">
                {lastTps === null ? '—' : lastTps.toFixed(2)}
                <span className="unit"> token/s</span>
              </div>
            </div>
            <div className="spacer" />
            <span className="note">
              {tpsPoints.length
                ? `最近 ${tpsPoints.length} 次请求，每次一个点`
                : '还没有推理记录，去「对话测试」跑一次'}
            </span>
          </div>
          <Chart
            label="decode 速度" unit="token/s" points={tpsPoints}
            digits={2} height={168} testId="chart-tps" xTitle="请求时间" bare
            hint="纵轴为每次请求的平均 decode 速度；横轴是请求完成的真实时间。"
          />
        </div>
      </div>

      <h2>数据目录</h2>
      <div className="card">
        {storage === null ? (
          <div className="empty" style={{ padding: 'var(--s-3)' }}>正在读取数据目录…</div>
        ) : (
          <>
            <div className="row" style={{ alignItems: 'baseline' }}>
              <div style={{ minWidth: 0 }}>
                <div className="metric-label">路径</div>
                <div className="mono" style={{ wordBreak: 'break-all', display: 'block' }}>
                  {storage.data_dir}
                </div>
              </div>
              <div className="spacer" />
              <div style={{ textAlign: 'right' }}>
                <div className="metric-label">服务占用</div>
                <div className="metric small">{fmtBytes(storage.dir_bytes)}</div>
              </div>
            </div>

            <div className={barClass(fsPct)} style={{ marginTop: 'var(--s-3)' }}>
              <span style={{ width: `${Math.min(100, fsPct ?? 0)}%` }} />
            </div>
            <div className="note tight">
              文件系统已用 {fmtBytes(storage.fs_used_bytes)} · 可用 {fmtBytes(storage.fs_free_bytes)} · 共 {fmtBytes(storage.fs_total_bytes)}
            </div>

            <div className="grid c4" style={{ marginTop: 'var(--s-4)' }}>
              {PART_LABELS.map(([key, label]) => (
                <div key={key}>
                  <div className="metric-label">{label}</div>
                  <div className="value">{fmtBytes(storage.parts[key])}</div>
                  <div className="note">
                    {storage.dir_bytes
                      ? `${fmtPct((storage.parts[key] / storage.dir_bytes) * 100)} 占比`
                      : '—'}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        <p className="note" style={{ marginTop: 'var(--s-3)' }}>
          模型、密钥、用量与日志都在这个目录里；要换到别的盘，去「设置 → 数据目录」。
        </p>
      </div>
    </>
  )
}
