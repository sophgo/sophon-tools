import { useMemo, useState } from 'react'
import { useWidth } from './Chart'
import type { KbResult, SearchResult, StageName } from '../apps'

/* How each candidate's rank moves through the retrieval pipeline: one column per
   stage, one line per passage. This is the figure that makes hybrid retrieval
   legible -- a passage BM25 missed but the vectors found, or one RRF ranked
   third that the reranker lifts to first.

   Form: a bump chart (rank by stage). Colour has one job, emphasis: the final
   top-k are the accent, every other candidate is the recessive grey, so no
   categorical palette is needed and identity is carried by the end labels
   (#1..#k) and the hover readout, never by hue. Ranks deeper than ROWS fold into
   a single "以外" row so a 20-candidate run stays readable. */

const ROWS = 10
const STAGES: { id: StageName; label: string; short: string }[] = [
  { id: 'bm25', label: '关键词 BM25', short: 'BM25' },
  { id: 'vector', label: '向量检索', short: '向量' },
  { id: 'fusion', label: 'RRF 融合', short: '融合' },
  { id: 'rerank', label: '精排', short: '精排' },
]

type Line = {
  chunk: string
  final: number | null          // final rank (1-based) when in the shown results
  ranks: (number | null)[]      // per stage, null = not ranked there / stage skipped
}

export default function RankFlow({ res, active, onActive }: {
  res: SearchResult
  active: string | null
  onActive: (chunk: string | null) => void
}) {
  const [ref, width] = useWidth(640)
  const [hover, setHover] = useState<string | null>(null)
  const focus = hover ?? active

  const byChunk = useMemo(() => new Map(res.results.map((r) => [r.chunk_id, r])), [res])
  const lines = useMemo<Line[]>(() => {
    const ids = new Set<string>()
    for (const s of STAGES) for (const h of res.stages[s.id]?.hits ?? []) ids.add(h.chunk_id)
    const final = new Map(res.results.map((r) => [r.chunk_id, r.rank]))
    const rankAt = STAGES.map((s) => {
      const m = new Map<string, number>()
      const st = res.stages[s.id]
      if (st?.status === 'ok') for (const h of st.hits) m.set(h.chunk_id, h.rank)
      return m
    })
    return [...ids].map((chunk) => ({
      chunk,
      final: final.get(chunk) ?? null,
      ranks: rankAt.map((m) => m.get(chunk) ?? null),
    }))
    // Grey first, accent last: the emphasised lines are drawn on top.
      .sort((a, b) => (a.final === null ? 0 : 1) - (b.final === null ? 0 : 1)
        || (b.final ?? 0) - (a.final ?? 0))
  }, [res])

  const pad = { l: 40, r: 44, t: 40, b: 12 }
  const rowH = 26
  const h = pad.t + (ROWS + 1) * rowH + pad.b
  const plotW = Math.max(160, width - pad.l - pad.r)
  const x = (i: number) => pad.l + (STAGES.length === 1 ? 0 : (i / (STAGES.length - 1)) * plotW)
  const y = (rank: number) => pad.t + (Math.min(rank, ROWS + 1) - 0.5) * rowH
  // Column labels are centred on their column; below ~520 px the long names
  // of neighbouring columns would run into each other.
  const narrow = width < 520
  const ok = STAGES.map((s) => res.stages[s.id]?.status === 'ok')

  const segments = (l: Line) => {
    // A line joins consecutive *ranked* stages; a skipped stage is bridged so
    // BM25 -> RRF still reads as one path when the vector stage did not run.
    const pts: [number, number][] = []
    l.ranks.forEach((r, i) => { if (r !== null) pts.push([x(i), y(r)]) })
    return pts
  }

  const tip = focus ? lines.find((l) => l.chunk === focus) : undefined
  const tipRes: KbResult | undefined = focus ? byChunk.get(focus) : undefined

  return (
    <div className="rankflow" ref={ref} data-testid="kb-rankflow">
      <svg width={width} height={h} role="img"
           aria-label={`检索各阶段名次变化，${lines.length} 个候选，前 ${res.results.length} 条高亮`}
           onMouseLeave={() => { setHover(null) }}>
        {/* rank gridlines and labels */}
        {Array.from({ length: ROWS + 1 }, (_, i) => i + 1).map((r) => (
          <g key={r}>
            <line className="chart-grid" x1={pad.l} x2={pad.l + plotW} y1={y(r)} y2={y(r)} />
            <text className="chart-tick" x={pad.l - 12} y={y(r) + 4} textAnchor="end">
              {r > ROWS ? '以外' : r}
            </text>
          </g>
        ))}
        {/* stage columns */}
        {STAGES.map((s, i) => (
          <g key={s.id}>
            <line className={ok[i] ? 'chart-axis' : 'rankflow-off'} x1={x(i)} x2={x(i)}
                  y1={pad.t - 8} y2={h - pad.b} />
            <text className={ok[i] ? 'rankflow-stage' : 'rankflow-stage off'} x={x(i)} y={16}
                  textAnchor={i === 0 ? 'start' : i === STAGES.length - 1 ? 'end' : 'middle'}>
              {narrow ? s.short : s.label}
            </text>
            <text className="chart-tick" x={x(i)} y={30}
                  textAnchor={i === 0 ? 'start' : i === STAGES.length - 1 ? 'end' : 'middle'}>
              {ok[i] ? `${res.stages[s.id].ms.toFixed(res.stages[s.id].ms < 10 ? 1 : 0)} ms` : '已跳过'}
            </text>
          </g>
        ))}
        {/* lines: hit areas first so the thin marks stay crisp */}
        {lines.map((l) => {
          const pts = segments(l)
          if (pts.length === 0) return null
          const on = focus === l.chunk
          const cls = l.final !== null ? 'rankflow-line top' : 'rankflow-line'
          const d = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px},${py}`).join(' ')
          return (
            <g key={l.chunk} className={on ? 'on' : focus ? 'dim' : ''}
               onMouseEnter={() => setHover(l.chunk)}
               onClick={() => onActive(l.final !== null ? l.chunk : null)}
               style={{ cursor: l.final !== null ? 'pointer' : 'default' }}>
              <path d={d} className="rankflow-hit" />
              <path d={d} className={cls} />
              {pts.map(([px, py], i) => (
                <circle key={i} cx={px} cy={py} r={l.final !== null ? 4 : 3}
                        className={l.final !== null ? 'rankflow-dot top' : 'rankflow-dot'} />
              ))}
              {l.final !== null && (
                <text className="rankflow-end" x={pts[pts.length - 1][0] + 10}
                      y={pts[pts.length - 1][1] + 4}>#{l.final}</text>
              )}
            </g>
          )
        })}
      </svg>
      <div className="rankflow-tip" aria-live="polite" data-testid="kb-rankflow-tip">
        {tip ? (
          <>
            <span className="rankflow-tip-ranks">
              {STAGES.map((s, i) => (
                <span key={s.id}>{s.short} {tip.ranks[i] ?? '—'}</span>
              ))}
            </span>
            <span className="rankflow-tip-text">
              {tipRes
                ? <>结果 #{tipRes.rank} · {tipRes.doc_name}{tipRes.page ? ` 第 ${tipRes.page} 页` : ''} · {tipRes.text}</>
                : '未进入最终结果'}
            </span>
          </>
        ) : (
          <span className="muted">把鼠标移到一条线上，查看这个片段在每一步的名次；高亮的是最终返回的结果。</span>
        )}
      </div>
    </div>
  )
}
