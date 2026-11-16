/** OTSL -> table, as PaddleOCR-VL's own pipeline reads it.
 *
 *  PaddleOCR-VL answers "Table Recognition:" in OTSL: `<fcel>text` is a filled
 *  cell, `<ecel>` an empty one, `<lcel>` / `<ucel>` / `<xcel>` continue the cell
 *  to the left / above / both, `<nl>` ends a row. This is a port of PaddleX
 *  3.7.2 `paddleocr_vl/uilts.py` (`otsl_pad_to_sqr_v2`, `otsl_parse_texts`,
 *  `export_to_html`), so the console shows the same table the official client
 *  would produce from the same answer -- including how it repairs ragged rows.
 *  `toHtml` output is byte-identical to `convert_otsl_to_html` on the board's
 *  answers (checked when this was written; see the PR). */

const TAGS = ['<nl>', '<fcel>', '<ecel>', '<lcel>', '<ucel>', '<xcel>'] as const
type Tag = (typeof TAGS)[number]
const TAG_RE = /<nl>|<fcel>|<ecel>|<lcel>|<ucel>|<xcel>/
const TAG_SPLIT = /(<nl>|<fcel>|<ecel>|<lcel>|<ucel>|<xcel>)/
const CELL_RE = /(?:<fcel>|<ecel>|<nl>|<lcel>|<ucel>|<xcel>)[\s\S]*?(?=<fcel>|<ecel>|<nl>|<lcel>|<ucel>|<xcel>|$)/g

export interface OtslCell {
  text: string
  row: number
  col: number
  rowSpan: number
  colSpan: number
}

export interface OtslTable {
  rows: number
  cols: number
  cells: OtslCell[]
}

export function hasOtsl(s: string): boolean {
  return TAG_RE.test(s)
}

/** `otsl_pad_to_sqr_v2`: make every row the same width, choosing the width
 *  that costs the fewest padded / truncated cells but never cuts a filled one. */
function padToRect(otsl: string): string {
  const s = otsl.trim()
  if (!s.includes('<nl>')) return s + '<nl>'
  const rows: { cells: string[]; minLen: number }[] = []
  for (const line of s.split('<nl>')) {
    if (!line) continue
    const cells = line.match(CELL_RE) ?? []
    if (!cells.length) continue
    let minLen = 0
    cells.forEach((c, i) => { if (c.startsWith('<fcel>')) minLen = i + 1 })
    rows.push({ cells, minLen })
  }
  if (!rows.length) return '<nl>'
  const lo = Math.max(...rows.map((r) => r.minLen))
  const hi = Math.max(lo, ...rows.map((r) => r.cells.length))
  let best = Infinity
  let width = hi
  for (let w = lo; w <= hi; w++) {
    const cost = rows.reduce((a, r) => a + Math.abs(r.cells.length - w), 0)
    if (cost < best) { best = cost; width = w }
  }
  return rows.map((r) => {
    const c = r.cells.length > width ? r.cells.slice(0, width)
      : r.cells.concat(Array(width - r.cells.length).fill('<ecel>'))
    return c.join('')
  }).join('<nl>') + '<nl>'
}

/** `otsl_parse_texts` after `otsl_extract_tokens_and_text`. */
export function parseOtsl(otsl: string): OtslTable {
  const padded = padToRect(otsl)
  const tokens = padded.match(new RegExp(TAG_SPLIT.source, 'g')) as Tag[] | null ?? []
  let texts = padded.split(TAG_SPLIT).filter((t) => t.trim() !== '')

  const grid: Tag[][] = []
  let cur: Tag[] = []
  for (const t of tokens) {
    if (t === '<nl>') { if (cur.length) grid.push(cur); cur = [] } else cur.push(t)
  }
  if (cur.length) grid.push(cur)
  const cols = grid.length ? Math.max(...grid.map((r) => r.length)) : 0
  for (const r of grid) while (r.length < cols) r.push('<ecel>')

  // Re-interleave texts with the (now rectangular) tag grid, as PaddleX does.
  if (grid.length) {
    const out: string[] = []
    let i = 0
    for (const row of grid) {
      for (const tag of row) {
        out.push(tag)
        if (i < texts.length && texts[i] === tag) {
          i++
          if (i < texts.length && !(TAGS as readonly string[]).includes(texts[i])) out.push(texts[i++])
        }
      }
      out.push('<nl>')
      if (i < texts.length && texts[i] === '<nl>') i++
    }
    texts = out
  }

  const run = (r: number, c: number, dr: number, dc: number, ok: Tag[]) => {
    let n = 0
    while (r < grid.length && c < (grid[r]?.length ?? 0) && ok.includes(grid[r][c])) {
      n++; r += dr; c += dc
    }
    return n
  }

  const cells: OtslCell[] = []
  let r = 0
  let c = 0
  texts.forEach((t, i) => {
    if (t === '<fcel>' || t === '<ecel>') {
      const off = t === '<fcel>' ? 2 : 1
      const text = t === '<fcel>' ? (texts[i + 1] ?? '') : ''
      const right = texts[i + off] ?? ''
      const below = r + 1 < grid.length && c < grid[r + 1].length ? grid[r + 1][c] : ''
      let colSpan = 1
      let rowSpan = 1
      if (right === '<lcel>' || right === '<xcel>') colSpan += run(r, c + 1, 0, 1, ['<lcel>', '<xcel>'])
      if (below === '<ucel>' || below === '<xcel>') rowSpan += run(r + 1, c, 1, 0, ['<ucel>', '<xcel>'])
      cells.push({ text: text.trim(), row: r, col: c, rowSpan, colSpan })
    }
    if (t === '<fcel>' || t === '<ecel>' || t === '<lcel>' || t === '<ucel>' || t === '<xcel>') c++
    if (t === '<nl>') { r++; c = 0 }
  })
  return { rows: grid.length, cols, cells }
}

/** For each (row, col), the cell that starts there, or null where a span
 *  covers it. Mirrors PaddleX's `TableData.grid`: the *last* cell written over
 *  a position owns it, and a position no cell covers (an orphaned `<lcel>` or
 *  `<ucel>` with nothing to continue) becomes an empty 1x1 cell. */
export function startGrid(t: OtslTable): (OtslCell | null)[][] {
  const owner: OtslCell[][] = Array.from({ length: t.rows }, (_, i) =>
    Array.from({ length: t.cols }, (_, j) => ({ text: '', row: i, col: j, rowSpan: 1, colSpan: 1 })))
  for (const cell of t.cells) {
    for (let i = Math.min(cell.row, t.rows); i < Math.min(t.rows, cell.row + cell.rowSpan); i++) {
      for (let j = Math.min(cell.col, t.cols); j < Math.min(t.cols, cell.col + cell.colSpan); j++) {
        owner[i][j] = cell
      }
    }
  }
  return owner.map((row, i) => row.map((o, j) => (o.row === i && o.col === j ? o : null)))
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#x27;')

/** `export_to_html`: the HTML the official client hands downstream. */
export function toHtml(t: OtslTable): string {
  if (!t.cells.length) return ''
  const g = startGrid(t)
  let body = ''
  for (const row of g) {
    body += '<tr>'
    for (const cell of row) {
      if (!cell) continue
      let open = 'td'
      if (cell.rowSpan > 1) open += ` rowspan="${cell.rowSpan}"`
      if (cell.colSpan > 1) open += ` colspan="${cell.colSpan}"`
      body += `<${open}>${esc(cell.text.trim())}</td>`
    }
    body += '</tr>'
  }
  return `<table>${body}</table>`
}

export type VlSegment = { kind: 'text'; text: string } | { kind: 'table'; otsl: string }

/** Split a (possibly still streaming) answer into prose and OTSL runs.
 *
 *  A table runs from its first tag to its last `<nl>`; prose around it stays
 *  Markdown. While streaming, a half-written tag at the very end ("<fc") is
 *  held back so it never flashes as text. */
export function splitAnswer(answer: string, streaming = false): VlSegment[] {
  let s = answer
  if (streaming) s = s.replace(/<[a-z]{0,4}$/, '')
  const first = s.search(TAG_RE)
  if (first < 0) return s ? [{ kind: 'text', text: s }] : []
  const lastNl = s.lastIndexOf('<nl>')
  const end = lastNl >= first ? lastNl + 4 : s.length
  const segs: VlSegment[] = []
  if (s.slice(0, first).trim()) segs.push({ kind: 'text', text: s.slice(0, first) })
  segs.push({ kind: 'table', otsl: s.slice(first, end) })
  const rest = s.slice(end)
  if (rest.trim()) segs.push(...splitAnswer(rest, streaming))
  return segs
}
