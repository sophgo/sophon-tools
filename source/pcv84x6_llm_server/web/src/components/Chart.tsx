import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icons'

/** One sample. `t` is a real timestamp in ms; `v` is null when the backend
 *  genuinely has no value for that sample, which draws a gap rather than a
 *  made-up number. */
export type Point = { t: number; v: number | null }

export type ChartProps = {
  /** Series name, shown in the tooltip and in the accessible description. */
  label: string
  unit: string
  points: Point[]
  /** Axis captions. Both are real: the x axis says what its ticks mean. */
  xTitle?: string
  /** Fixed y domain. Leave unset to fit the data (always including 0). */
  yMax?: number
  yMin?: number
  height?: number
  /** Show x ticks as clock time (true) or as a sample counter (false). CPU and
   *  speed samples are timestamped, so they get clock time. */
  timeX?: boolean
  /** Digits after the point in the y labels and tooltip. */
  digits?: number
  /** Data attribute for browser tests. */
  testId?: string
  hint?: string
  /** Leave out the chart's own title row, for a card whose header already
   *  names the series (the overview cards did, and showed it twice). */
  bare?: boolean
}

const M = { top: 12, right: 14, bottom: 34, left: 56 }

/** Round a raw step up to 1/2/5×10^n so labels read 0/25/50 rather than 0/23.7/47.4. */
function niceStep(raw: number): number {
  if (!isFinite(raw) || raw <= 0) return 1
  const exp = Math.floor(Math.log10(raw))
  const base = Math.pow(10, exp)
  const norm = raw / base
  const mult = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  return mult * base
}

function ticks(min: number, max: number, count: number): number[] {
  const step = niceStep((max - min) / count)
  const start = Math.ceil(min / step) * step
  const out: number[] = []
  // The epsilon keeps 0.30000000000000004 from producing a duplicate tick.
  for (let v = start; v <= max + step * 1e-9; v += step) out.push(Number(v.toFixed(10)))
  return out.length >= 2 ? out : [min, max]
}

function clock(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function stamp(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
         `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** Width-tracking hook: the chart draws at CSS pixel size so labels stay sharp
 *  instead of being scaled by a viewBox. */
export function useWidth(fallback: number): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width ?? 0
      if (cw > 0) setW(Math.round(cw))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

/** A line chart with real axes, units and hover readout.
 *
 *  Hand-drawn SVG on purpose: the board has no network, so no charting library
 *  can be fetched, and every library would also paper over the one thing that
 *  matters here -- a signal that is null must stay visibly absent.
 */
export default function Chart({
  label, unit, points, xTitle = '时间', yMax, yMin, height = 168,
  timeX = true, digits = 0, testId, hint, bare = false,
}: ChartProps) {
  const [boxRef, width] = useWidth(560)
  const [active, setActive] = useState<number | null>(null)

  const real = useMemo(() => points.filter((p): p is { t: number; v: number } => p.v !== null), [points])
  const plotW = Math.max(10, width - M.left - M.right)
  const plotH = Math.max(10, height - M.top - M.bottom)

  // The y domain always includes 0 unless the caller pins it: percentage and
  // speed readings are meaningless without their zero line.
  const lo = yMin ?? 0
  const hiRaw = yMax ?? Math.max(...real.map((p) => p.v), 0)
  const hi = hiRaw > lo ? hiRaw : lo + 1
  const yTicks = ticks(lo, hi, 4)
  const yTop = Math.max(hi, yTicks[yTicks.length - 1] ?? hi)

  const t0 = real.length ? real[0].t : 0
  const t1 = real.length ? real[real.length - 1].t : 1
  const tSpan = t1 - t0 || 1

  const xAt = (t: number) => M.left + (timeX ? (t - t0) / tSpan : 0) * plotW
  const idxAt = (i: number) =>
    M.left + (real.length > 1 ? (i / (real.length - 1)) * plotW : plotW / 2)
  const px = (p: { t: number }, i: number) => (timeX ? xAt(p.t) : idxAt(i))
  const yAt = (v: number) => M.top + plotH - ((v - lo) / (yTop - lo)) * plotH

  // A null splits the line: each run of real samples becomes its own polyline,
  // so a gap in the data looks like a gap and never like a straight
  // interpolation between two points that were never measured.
  const runs = useMemo(() => {
    const out: { idx: number; p: { t: number; v: number } }[][] = []
    let cur: { idx: number; p: { t: number; v: number } }[] = []
    let idx = 0
    for (const p of points) {
      if (p.v === null) {
        if (cur.length) out.push(cur)
        cur = []
      } else {
        cur.push({ idx, p: { t: p.t, v: p.v } })
        idx++
      }
    }
    if (cur.length) out.push(cur)
    return out
  }, [points])

  const xTicks = useMemo(() => {
    if (!real.length) return [] as { x: number; text: string }[]
    if (timeX) {
      const n = Math.max(2, Math.min(5, Math.floor(plotW / 90)))
      const out: { x: number; text: string }[] = []
      for (let k = 0; k < n; k++) {
        const frac = n === 1 ? 0 : k / (n - 1)
        const t = t0 + frac * tSpan
        // Two ticks a second apart print the same clock text; while the window
        // is still filling (the first few samples) only distinct times are
        // labelled, so the axis never repeats one timestamp five times.
        const text = clock(t)
        if (out.length && out[out.length - 1].text === text) continue
        out.push({ x: M.left + frac * plotW, text })
      }
      return out
    }
    const n = Math.max(2, Math.min(6, real.length))
    const out: { x: number; text: string }[] = []
    for (let k = 0; k < n; k++) {
      const i = Math.round((k / (n - 1)) * (real.length - 1))
      out.push({ x: idxAt(i), text: `#${i + 1}` })
    }
    return out
  }, [real, plotW, t0, tSpan, timeX])

  const pick = useCallback((clientX: number, target: SVGSVGElement) => {
    if (!real.length) return
    const rect = target.getBoundingClientRect()
    const x = clientX - rect.left
    let best = 0
    let bestD = Infinity
    real.forEach((p, i) => {
      const d = Math.abs(px(p, i) - x)
      if (d < bestD) { bestD = d; best = i }
    })
    setActive(best)
  }, [real, px])

  const onKey = (e: React.KeyboardEvent) => {
    if (!real.length) return
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const step = e.key === 'ArrowRight' ? 1 : -1
      setActive((a) => {
        const next = a === null ? (step > 0 ? 0 : real.length - 1) : a + step
        return Math.max(0, Math.min(real.length - 1, next))
      })
    } else if (e.key === 'Escape') {
      setActive(null)
    }
  }

  const sel = active !== null ? real[active] : null
  const selX = sel ? px(sel, active as number) : 0
  const selY = sel ? yAt(sel.v) : 0
  // Keep the readout inside the plot: a tags-width label would overflow on the
  // right edge of the last sample.
  const tipLeft = Math.max(M.left, Math.min(width - M.right - 132, selX - 66))
  const fmt = (v: number) => v.toFixed(digits)

  const summary = real.length
    ? `${label}：共 ${real.length} 个采样，最新 ${fmt(real[real.length - 1].v)} ${unit}，` +
      `最小 ${fmt(Math.min(...real.map((p) => p.v)))} ${unit}，` +
      `最大 ${fmt(Math.max(...real.map((p) => p.v)))} ${unit}`
    : `${label}：暂无数据`

  return (
    <div className="chart" ref={boxRef} data-testid={testId}>
      {!bare && (
        <div className="chart-head">
          <span className="chart-title">{label}</span>
          <span className="chart-unit">{unit}</span>
        </div>
      )}
      {real.length === 0 ? (
        // An empty chart is a short note, not a plot-sized grey block: the
        // card should not look broken before the first sample arrives.
        <div className="chart-empty" data-testid={testId ? `${testId}-empty` : undefined}>
          <Icon name="inbox" size={18} />
          <span>暂无数据</span>
        </div>
      ) : (
        <div className="chart-body" style={{ height }}>
          <svg
            width={width} height={height} role="img"
            aria-label={summary}
            tabIndex={0}
            data-testid={testId ? `${testId}-svg` : undefined}
            onMouseMove={(e) => pick(e.clientX, e.currentTarget)}
            onMouseLeave={() => setActive(null)}
            onTouchStart={(e) => pick(e.touches[0].clientX, e.currentTarget)}
            onTouchMove={(e) => pick(e.touches[0].clientX, e.currentTarget)}
            onKeyDown={onKey}
            onBlur={() => setActive(null)}
          >
            {/* Horizontal grid + y labels: the y axis carries its unit in the
                rotated caption, so the numbers themselves stay bare. */}
            {yTicks.map((v) => (
              <g key={`y${v}`}>
                <line className="chart-grid" x1={M.left} x2={M.left + plotW}
                      y1={yAt(v)} y2={yAt(v)} />
                <text className="chart-tick" x={M.left - 8} y={yAt(v)}
                      textAnchor="end" dominantBaseline="middle">{fmt(v)}</text>
              </g>
            ))}
            <line className="chart-axis" x1={M.left} x2={M.left + plotW}
                  y1={M.top + plotH} y2={M.top + plotH} />
            <line className="chart-axis" x1={M.left} x2={M.left}
                  y1={M.top} y2={M.top + plotH} />

            {xTicks.map((t, i) => (
              <g key={`x${i}`}>
                <line className="chart-axis" x1={t.x} x2={t.x}
                      y1={M.top + plotH} y2={M.top + plotH + 4} />
                <text className="chart-tick" x={t.x} y={M.top + plotH + 17}
                      textAnchor="middle">{t.text}</text>
              </g>
            ))}

            <text className="chart-axis-title" x={M.left + plotW / 2}
                  y={height - 2} textAnchor="middle">{xTitle}</text>
            <text className="chart-axis-title" transform={`translate(12 ${M.top + plotH / 2}) rotate(-90)`}
                  textAnchor="middle">{unit}</text>

            {/* A 10% wash under each run (dataviz: an area is a wash, never a
                block), closed down to the baseline so a gap stays a gap. */}
            {runs.map((run, ri) => {
              if (run.length < 2) return null
              const base = yAt(lo).toFixed(1)
              const d = run.map((s, i) =>
                `${i === 0 ? 'M' : 'L'}${px(s.p, s.idx).toFixed(1)},${yAt(s.p.v).toFixed(1)}`,
              ).join(' ') +
                ` L${px(run[run.length - 1].p, run[run.length - 1].idx).toFixed(1)},${base}` +
                ` L${px(run[0].p, run[0].idx).toFixed(1)},${base} Z`
              return <path key={`a${ri}`} className="chart-area" d={d} />
            })}
            {runs.map((run, ri) => {
              const d = run.map((s, i) =>
                `${i === 0 ? 'M' : 'L'}${px(s.p, s.idx).toFixed(1)},${yAt(s.p.v).toFixed(1)}`,
              ).join(' ')
              return <path key={ri} className="chart-line" d={d} />
            })}

            {real.length === 1 && (
              <circle className="chart-dot" cx={px(real[0], 0)} cy={yAt(real[0].v)} r={4} />
            )}

            {sel && (
              <g className="chart-active">
                <line className="chart-guide" x1={selX} x2={selX} y1={M.top} y2={M.top + plotH} />
                <circle className="chart-dot active" cx={selX} cy={selY} r={4.5} />
              </g>
            )}
          </svg>

          {sel && (
            <div className="chart-tip" style={{ left: tipLeft, top: 4 }} data-testid={testId ? `${testId}-tip` : undefined}>
              <div className="chart-tip-time">{stamp(sel.t)}</div>
              <div className="chart-tip-val">
                <span className="chart-tip-label">{label}</span>
                <b>{fmt(sel.v)}</b> <span className="muted">{unit}</span>
              </div>
            </div>
          )}
        </div>
      )}
      {hint && <div className="chart-hint">{hint}</div>}
    </div>
  )
}
