import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { OcrBox, TranscriptSegment } from '../api'

/* The playground's result figures (MYS-2599). Each is one encoding, drawn with
   the console's own tokens so it follows the theme switch without a reload:

   - similarity matrix: sequential, one hue (the accent) mixed into the inset
     surface -- light-to-dark on the day theme, dark-to-light at night, which is
     the anchor flip a sequential ramp needs in dark mode;
   - rerank scores: one series, so one colour; length is the value;
   - transcript timeline: segments on one time axis, separated by the 2px
     surface gap rather than by borders;
   - OCR boxes: outlines over the source image, the line under the pointer
     filled so it can be found in the list next to it. */

// -- theme-aware colour maths ------------------------------------------------

type Rgb = [number, number, number]

function parseHex(hex: string): Rgb | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function luminance([r, g, b]: Rgb): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function contrast(a: Rgb, b: Rgb): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

/** Re-render when the console's theme flips (`data-theme` on <html>). */
function useThemeTokens(names: string[]): Record<string, Rgb | null> {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? 'light')
  useEffect(() => {
    const obs = new MutationObserver(() =>
      setTheme(document.documentElement.dataset.theme ?? 'light'))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  return useMemo(() => {
    const cs = getComputedStyle(document.documentElement)
    return Object.fromEntries(names.map((n) => [n, parseHex(cs.getPropertyValue(n))]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, names.join()])
}

/** The share of accent in a similarity cell. Starts above zero so a cosine of
 *  0 is still a visible cell, not a hole in the grid. */
function cellShare(v: number): number {
  return Math.round(8 + 92 * Math.min(1, Math.max(0, v)))
}

// -- similarity matrix ------------------------------------------------------

export function cosine(a: number[], b: number[]): number {
  let dot = 0, na = 0, nb = 0
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i] }
  return na && nb ? dot / Math.sqrt(na * nb) : 0
}

export function SimilarityMatrix({ texts, matrix }: { texts: string[]; matrix: number[][] }) {
  const tokens = useThemeTokens(['--accent', '--panel-2', '--text', '--on-accent'])
  const [hover, setHover] = useState<[number, number] | null>(null)
  const n = texts.length

  // The ink for a cell is whichever of the two text tokens reads better on the
  // mixed fill, computed rather than thresholded: the crossover sits at a
  // different share in each theme.
  const ink = (share: number): string => {
    const { '--accent': acc, '--panel-2': base, '--text': text, '--on-accent': on } = tokens
    if (!acc || !base || !text || !on) return 'var(--text)'
    const t = share / 100
    const mixed = acc.map((c, i) => Math.round(c * t + base[i] * (1 - t))) as Rgb
    return contrast(mixed, text) >= contrast(mixed, on) ? 'var(--text)' : 'var(--on-accent)'
  }

  const grid: CSSProperties = { gridTemplateColumns: `32px repeat(${n}, minmax(36px, 1fr))` }
  const tip = hover && hover[0] !== hover[1] ? hover : null

  return (
    <div className="simx" data-testid="embed-matrix">
      <div className="simx-grid" style={grid} role="grid"
           aria-label={`${n} 段文本两两之间的余弦相似度`}
           onMouseLeave={() => setHover(null)}>
        <span />
        {texts.map((_, j) => <span key={j} className="simx-head" role="columnheader">T{j + 1}</span>)}
        {matrix.map((row, i) => (
          <div key={i} className="simx-row" role="row">
            <span className="simx-head" role="rowheader">T{i + 1}</span>
            {row.map((v, j) => {
              const self = i === j
              const share = cellShare(v)
              return (
                <span key={j} role="gridcell" tabIndex={self ? -1 : 0}
                      className={`simx-cell${self ? ' self' : ''}${tip && tip[0] === i && tip[1] === j ? ' on' : ''}`}
                      data-testid={`embed-cell-${i}-${j}`}
                      aria-label={self ? `T${i + 1} 与自身` : `T${i + 1} 与 T${j + 1}：${v.toFixed(3)}`}
                      style={self ? undefined : {
                        background: `color-mix(in srgb, var(--accent) ${share}%, var(--panel-2))`,
                        color: ink(share),
                      }}
                      onMouseEnter={() => setHover([i, j])}
                      onFocus={() => setHover([i, j])}
                      onBlur={() => setHover(null)}>
                  {self ? '—' : v.toFixed(2)}
                </span>
              )
            })}
          </div>
        ))}
      </div>
      <div className="simx-legend" aria-hidden="true">
        <span>0</span>
        <span className="simx-ramp" />
        <span>1</span>
        <span className="simx-legend-label">余弦相似度</span>
      </div>
      {/* The pair under the pointer, in words: the matrix says how close, this
          says which two texts that number is about. */}
      <div className="simx-tip" data-testid="embed-tip">
        {tip ? (
          <>
            <b>T{tip[0] + 1} × T{tip[1] + 1}</b>
            <span className="num">{matrix[tip[0]][tip[1]].toFixed(4)}</span>
            <span className="simx-tip-text">{texts[tip[0]]}</span>
            <span className="simx-tip-text">{texts[tip[1]]}</span>
          </>
        ) : <span className="muted">把鼠标移到格子上，查看是哪两段文本。</span>}
      </div>
    </div>
  )
}

// -- rerank scores ----------------------------------------------------------

export function ScoreBars({ rows }: {
  rows: { index: number; score: number; text: string }[]
}) {
  return (
    <ol className="scores" data-testid="rerank-results">
      {rows.map((r, rank) => (
        <li key={r.index} className="score-row" data-testid={`rerank-row-${rank}`}>
          <span className="score-rank">{rank + 1}</span>
          <div className="score-main">
            <div className="score-text" title={r.text}>{r.text}</div>
            <div className="score-line">
              <span className="score-track"
                    role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={r.score}
                    aria-label={`第 ${rank + 1} 名，相关度 ${r.score.toFixed(4)}`}>
                <span className="score-fill" style={{ width: `${Math.max(0.5, r.score * 100)}%` }} />
              </span>
              <span className="score-val">{r.score.toFixed(4)}</span>
            </div>
          </div>
          <span className="score-src mono" title="在输入里的位置">原 #{r.index + 1}</span>
        </li>
      ))}
    </ol>
  )
}

// -- transcript timeline ----------------------------------------------------

export function fmtClock(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${String(m).padStart(2, '0')}:${sec.toFixed(1).padStart(4, '0')}`
}

/** A clean tick step for an axis of `span` seconds, ~5 ticks. */
function tickStep(span: number): number {
  for (const s of [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]) if (span / s <= 6) return s
  return 900
}

export function SegmentTimeline({ segments, duration, position, onSeek }: {
  segments: TranscriptSegment[]
  duration: number
  position: number | null
  onSeek: (t: number) => void
}) {
  const span = Math.max(duration, 0.1)
  const step = tickStep(span)
  const ticks: number[] = []
  for (let t = 0; t <= span + 1e-6; t += step) ticks.push(t)
  const pct = (t: number) => `${(Math.min(span, Math.max(0, t)) / span) * 100}%`
  const active = position === null ? -1
    : segments.findIndex((s) => position >= s.start && position < s.end)
  return (
    <div className="timeline" data-testid="asr-timeline">
      <div className="timeline-track">
        {segments.map((s, i) => (
          <button key={s.id} className={`timeline-seg${i === active ? ' on' : ''}`}
                  style={{ left: pct(s.start), width: `calc(${pct(s.end)} - ${pct(s.start)})` }}
                  title={`${fmtClock(s.start)}–${fmtClock(s.end)}  ${s.text}`}
                  aria-label={`第 ${i + 1} 段 ${fmtClock(s.start)} 到 ${fmtClock(s.end)}，播放`}
                  onClick={() => onSeek(s.start)} />
        ))}
        {position !== null && <span className="timeline-head" style={{ left: pct(position) }} />}
      </div>
      <div className="timeline-axis" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} style={{ left: pct(t) }}>{t >= 60 ? fmtClock(t).replace(/\.0$/, '') : `${t}s`}</span>
        ))}
      </div>
    </div>
  )
}

// -- OCR overlay -------------------------------------------------------------

export function OcrOverlay({ src, boxes, show, active, onActive }: {
  src: string
  boxes: (OcrBox | null)[]
  show: boolean
  active: number | null
  onActive: (i: number | null) => void
}) {
  const [size, setSize] = useState<[number, number] | null>(null)
  return (
    <div className="ocr-stage" data-testid="ocr-stage">
      <img src={src} alt="待识别图片"
           onLoad={(e) => setSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} />
      {show && size && (
        <svg viewBox={`0 0 ${size[0]} ${size[1]}`} preserveAspectRatio="none"
             aria-label={`${boxes.filter(Boolean).length} 个检测框`} data-testid="ocr-boxes">
          {boxes.map((b, i) => b && (
            <polygon key={i} points={b.map((p) => p.join(',')).join(' ')}
                     className={`ocr-box${active === i ? ' on' : ''}`}
                     onMouseEnter={() => onActive(i)} onMouseLeave={() => onActive(null)} />
          ))}
        </svg>
      )}
    </div>
  )
}
