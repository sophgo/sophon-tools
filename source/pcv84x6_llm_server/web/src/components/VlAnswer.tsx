import { useMemo, useState } from 'react'
import Markdown from './Markdown'
import { parseOtsl, splitAnswer, startGrid, toHtml, type OtslTable } from './otsl'

/** A PaddleOCR-VL answer, read the way its own pipeline reads it: OTSL runs
 *  become tables (merged cells included), everything else stays Markdown. */
export default function VlAnswer({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const segs = useMemo(() => splitAnswer(text, streaming), [text, streaming])
  return (
    <div className="vl-answer" data-testid="vl-answer">
      {segs.map((s, i) => s.kind === 'text'
        ? <div key={i} className="md-body"><Markdown text={s.text} /></div>
        : <VlTable key={i} otsl={s.otsl} streaming={streaming && i === segs.length - 1} />)}
    </div>
  )
}

const NUMERIC = /^[\s+\-−]?[\d.,，]+\s*(%|‰|台|个|件|元|万|亿)?\s*$/

function VlTable({ otsl, streaming }: { otsl: string; streaming: boolean }) {
  const table: OtslTable = useMemo(() => parseOtsl(otsl), [otsl])
  const grid = useMemo(() => startGrid(table), [table])
  const merged = table.cells.filter((c) => c.rowSpan > 1 || c.colSpan > 1).length
  const [copied, setCopied] = useState(false)

  if (!table.cells.length) return null
  const copy = () => {
    void navigator.clipboard?.writeText(toHtml(table)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }).catch(() => undefined)
  }

  return (
    <figure className="vl-table" data-testid="vl-table">
      <figcaption className="vl-table-bar">
        <span>表格 · {table.rows} 行 × {table.cols} 列{merged ? ` · ${merged} 处合并单元格` : ''}</span>
        {streaming && <span className="muted">（识别中）</span>}
        <span className="spacer" />
        <button className="btn ghost sm" onClick={copy} disabled={streaming} data-testid="vl-copy-html"
                title="复制与 PaddleOCR 官方产线相同的 HTML">
          {copied ? '已复制' : '复制 HTML'}
        </button>
      </figcaption>
      <div className="table-wrap">
        <table>
          <tbody>
            {grid.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => {
                  if (!cell) return null
                  const span = cell.rowSpan > 1 || cell.colSpan > 1
                  const cls = [span ? 'span' : '', NUMERIC.test(cell.text) ? 'num' : ''].filter(Boolean).join(' ')
                  return (
                    <td key={j} rowSpan={cell.rowSpan > 1 ? cell.rowSpan : undefined}
                        colSpan={cell.colSpan > 1 ? cell.colSpan : undefined}
                        className={cls || undefined}
                        title={span ? `合并单元格：${cell.rowSpan} 行 × ${cell.colSpan} 列` : undefined}>
                      {cell.text}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
