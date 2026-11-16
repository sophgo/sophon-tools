import { useState } from 'react'
import type { OcrBlock } from '../api'

/* Layout regions over the page image. One colour (the chart accent) for every
   region that reaches the Markdown, the recessive grey dashed for the ones that
   do not (page header, footer, page number, aside): identity is carried by the
   type label on each box and in the side list, never by hue. */

export const BLOCK_TYPE_LABEL: Record<string, string> = {
  title: '标题', subtitle: '小标题', text: '正文', table: '表格', image: '图片',
  chart: '图表', formula: '公式', header: '页眉', footer: '页脚', seal: '印章',
  number: '页码', aside_text: '旁注',
}

/** Region types PaddleX leaves out of the page Markdown by default. */
export const OUTSIDE_TEXT = new Set(['header', 'footer', 'number', 'aside_text'])

export function typeLabel(t: string): string {
  return BLOCK_TYPE_LABEL[t] ?? t
}

export default function LayoutOverlay({ src, blocks, show, active, onActive }: {
  src: string
  blocks: OcrBlock[]
  show: boolean
  active: number | null
  onActive: (i: number | null) => void
}) {
  const [size, setSize] = useState<[number, number] | null>(null)
  // Label text scales with the image so it reads the same on a phone and a
  // desktop: ~1.6% of the long side, i.e. ~12-14 px at the rendered width.
  const fs = size ? Math.max(10, Math.round(Math.max(size[0], size[1]) * 0.016)) : 12
  return (
    <div className="ocr-stage" data-testid="layout-stage">
      <img src={src} alt="待识别页面"
           onLoad={(e) => setSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} />
      {show && size && (
        <svg viewBox={`0 0 ${size[0]} ${size[1]}`} preserveAspectRatio="none"
             aria-label={`${blocks.length} 个版面区域`} data-testid="layout-boxes">
          {blocks.map((b, i) => {
            const [x1, y1, x2, y2] = b.box
            const off = OUTSIDE_TEXT.has(b.type)
            const label = `${b.index + 1} ${typeLabel(b.type)}`
            const w = label.length * fs * 0.75 + fs * 0.8
            return (
              <g key={i} className={`layout-region${off ? ' off' : ''}${active === i ? ' on' : ''}`}
                 onMouseEnter={() => onActive(i)} onMouseLeave={() => onActive(null)}>
                <rect x={x1} y={y1} width={Math.max(1, x2 - x1)} height={Math.max(1, y2 - y1)}
                      className="layout-box" />
                <rect x={x1} y={Math.max(0, y1 - fs * 1.5)} width={w} height={fs * 1.5}
                      rx={fs * 0.25} className="layout-tag" />
                <text x={x1 + fs * 0.4} y={Math.max(0, y1 - fs * 1.5) + fs * 1.1}
                      fontSize={fs} className="layout-tag-text">{label}</text>
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}
