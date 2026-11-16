import { useEffect, useRef, useState } from 'react'
import { api, type Model, type OcrMode, type OcrResult } from '../../api'
import { OcrOverlay } from '../../components/TestViz'
import LayoutOverlay, { OUTSIDE_TEXT, typeLabel } from '../../components/LayoutOverlay'
import Markdown from '../../components/Markdown'
import { download, errText, FileDropMany, readyAll } from './common'

/* 文档识别: a batch of images through PP-OCR, one after another. The strip on
   the left is the queue; the selected image fills the middle with its boxes,
   and its lines sit beside it in reading order. Everything recognised can be
   copied or saved as one text file, one section per image. PDFs go through the
   knowledge-base tab, which OCRs scanned pages the same way.

   Three modes. 逐行 is the line list. 整页版面 runs PP-DocLayout first: the image
   shows the page's regions with their type, and the side panel shows the page
   as Markdown (headings, paragraphs; tables as text only) or the region list.
   VL 精细识别 uses the same regions but reads each with PaddleOCR-VL, so tables
   come back with their structure (HTML, merged cells included). */

const ACCEPT = 'image/png,image/jpeg,image/bmp,image/webp'

type Item = {
  key: string
  file: File
  url: string
  state: 'waiting' | 'running' | 'done' | 'failed'
  mode?: OcrMode
  res?: OcrResult
  took?: number
  error?: string
}

let seq = 0

export default function OcrApp({ models }: { models: Model[] }) {
  const ocr = readyAll(models, 'ocr')
  const model = ocr[0] ?? null
  // mode "vl" needs PaddleOCR-VL loaded as well (the layout model lives in the
  // OCR model); without it the server answers 409, so the option says why.
  const vlModel = readyAll(models, 'ocr_vl')[0] ?? null
  const [items, setItems] = useState<Item[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [active, setActive] = useState<number | null>(null)
  const [showBoxes, setShowBoxes] = useState(true)
  const [running, setRunning] = useState(false)
  const [copied, setCopied] = useState(false)
  const [mode, setMode] = useState<OcrMode>('lines')
  const [view, setView] = useState<'md' | 'blocks'>('md')
  const stopRef = useRef(false)
  const itemsRef = useRef(items)
  itemsRef.current = items

  useEffect(() => () => { itemsRef.current.forEach((i) => URL.revokeObjectURL(i.url)) }, [])

  const add = (files: File[]) => {
    const next = files.map((file) => ({
      key: `i${++seq}`, file, url: URL.createObjectURL(file), state: 'waiting' as const,
    }))
    setItems((v) => [...v, ...next])
    setSel((s) => s ?? next[0]?.key ?? null)
  }

  const patch = (key: string, p: Partial<Item>) =>
    setItems((v) => v.map((i) => (i.key === key ? { ...i, ...p } : i)))

  const runAll = async () => {
    if (!model) return
    stopRef.current = false
    setRunning(true)
    for (const it of itemsRef.current) {
      if (stopRef.current) break
      if (it.state === 'done' && it.mode === mode) continue
      patch(it.key, { state: 'running', error: undefined })
      setSel(it.key)
      const t0 = performance.now()
      try {
        const res = await api.testOcr(model.id, it.file, mode)
        patch(it.key, { state: 'done', mode, res, took: (performance.now() - t0) / 1000 })
      } catch (e) {
        patch(it.key, { state: 'failed', error: errText(e, '识别失败') })
      }
    }
    setRunning(false)
  }

  const remove = (key: string) => {
    const it = items.find((i) => i.key === key)
    if (it) URL.revokeObjectURL(it.url)
    const rest = items.filter((i) => i.key !== key)
    setItems(rest)
    if (sel === key) setSel(rest[0]?.key ?? null)
  }

  const cur = items.find((i) => i.key === sel) ?? null
  const done = items.filter((i) => i.state === 'done')
  const allText = done.map((i) => `# ${i.file.name}\n\n${i.res?.text ?? ''}`).join('\n\n')
  const pending = items.filter((i) => i.state !== 'done' || i.mode !== mode).length
  const layout = mode === 'layout' || mode === 'vl'
  const curLayout = cur?.state === 'done' && (cur.mode === 'layout' || cur.mode === 'vl') && !!cur.res?.blocks
  const curVl = curLayout && cur?.mode === 'vl'
  const blocks = curLayout ? cur!.res!.blocks! : []

  return (
    <div className="ocrapp" data-testid="ocr-app">
      <div className="toolbar">
        <span className="note" data-testid="ocr-model">
          {model ? <>模型 <b>{model.display_name}</b> · 横排文字，竖排暂不支持</>
            : <span className="err-text">没有已加载的 OCR 模型，请先在「模型」页加载 ppocrv6-medium。</span>}
        </span>
        <div className="spacer" />
        <div className="segmented" role="radiogroup" aria-label="识别方式" data-testid="ocr-mode">
          {([['lines', '逐行'], ['layout', '整页版面'], ['vl', 'VL 精细识别']] as [OcrMode, string][]).map(([m, l]) => (
            <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? 'on' : ''}
                    disabled={running || (m === 'vl' && !vlModel)} data-testid={`ocr-mode-${m}`}
                    title={m === 'vl'
                      ? (vlModel ? '同样先分区域，再逐个区域交给 PaddleOCR-VL：表格还原结构（含合并单元格），公式输出 LaTeX；比「整页版面」慢'
                        : '需要先在「模型」页加载 paddleocr-vl-1.5')
                      : m === 'layout' ? '先分出标题、段落、表格、图片等区域，输出整页 Markdown（表格只输出文字）' : '按阅读顺序逐行输出'}
                    onClick={() => { setMode(m); setActive(null) }}>{l}</button>
          ))}
        </div>
        <label className="field inline" style={{ alignSelf: 'center' }}>
          <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
          {layout ? '显示区域' : '显示检测框'}
        </label>
        {done.length > 0 && (
          <>
            <button className="btn ghost sm" data-testid="ocr-copy-all"
                    onClick={() => void navigator.clipboard?.writeText(allText).then(() => {
                      setCopied(true); setTimeout(() => setCopied(false), 1500)
                    }).catch(() => undefined)}>
              {copied ? '已复制' : `复制全部（${done.length} 张）`}
            </button>
            <button className="btn ghost sm" data-testid="ocr-save"
                    onClick={() => download(layout ? 'ocr.md' : 'ocr.txt', allText + '\n')}>
              {layout ? '保存 Markdown' : '保存 TXT'}</button>
          </>
        )}
        {running
          ? <button className="btn ghost" onClick={() => { stopRef.current = true }} data-testid="ocr-stop">停止</button>
          : <button className="btn" disabled={!model || pending === 0} onClick={() => void runAll()} data-testid="ocr-run-all">
              {items.length === 0 ? '识别' : pending === 0 ? '已全部识别'
                : done.length > 0 ? `识别剩余 ${pending} 张` : `识别${items.length > 1 ? `全部 ${items.length} 张` : ''}`}
            </button>}
      </div>

      <div className="ocr-grid">
        <aside className="card tight ocr-queue" data-testid="ocr-queue">
          <FileDropMany accept={ACCEPT} onFiles={add} disabled={running} testid="ocr-drop"
                        hint="可一次选多张，PNG / JPEG，单张 ≤ 20 MiB" />
          {items.length > 0 && (
            <ul className="ocr-thumbs">
              {items.map((it, i) => (
                <li key={it.key} className={it.key === sel ? 'on' : ''}>
                  <button className="ocr-thumb" onClick={() => { setSel(it.key); setActive(null) }}
                          aria-label={`第 ${i + 1} 张：${it.file.name}`} data-testid={`ocr-thumb-${i}`}>
                    <img src={it.url} alt="" />
                    <span className="ocr-thumb-meta">
                      <span className="ocr-thumb-name" title={it.file.name}>{it.file.name}</span>
                      <span className={it.state === 'failed' ? 'err-text' : 'note tight'}>
                        {it.state === 'waiting' && '待识别'}
                        {it.state === 'running' && <><span className="spin" /> 识别中</>}
                        {it.state === 'done' && ((it.mode === 'layout' || it.mode === 'vl') && it.res?.blocks
                          ? `${it.res.blocks.length} 个区域 · ${it.took?.toFixed(2)} s`
                          : `${it.res?.lines.length ?? 0} 行 · ${it.took?.toFixed(2)} s`)}
                        {it.state === 'done' && it.mode !== mode && ' · 需重新识别'}
                        {it.state === 'failed' && '失败'}
                      </span>
                    </span>
                  </button>
                  <button className="btn ghost sm icon" aria-label={`移除 ${it.file.name}`} disabled={running}
                          onClick={() => remove(it.key)}>×</button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {cur ? (
          <>
            <section className="card ocr-view" data-testid="ocr-view">
              {curLayout
                ? <LayoutOverlay src={cur.url} blocks={blocks} show={showBoxes} active={active} onActive={setActive} />
                : <OcrOverlay src={cur.url} boxes={cur.res?.lines.map((l) => l.box) ?? []}
                              show={showBoxes} active={active} onActive={setActive} />}
            </section>
            <section className="card ocr-text" data-testid="ocr-text">
              <div className="row" style={{ marginBottom: 'var(--s-2)' }}>
                <h2 style={{ margin: 0 }} title={cur.file.name}>识别结果</h2>
                <div className="spacer" />
                {curLayout && (
                  <div className="segmented sm" role="tablist" aria-label="结果视图" data-testid="ocr-view-switch">
                    <button role="tab" aria-selected={view === 'md'} className={view === 'md' ? 'on' : ''}
                            onClick={() => setView('md')} data-testid="ocr-view-md">Markdown</button>
                    <button role="tab" aria-selected={view === 'blocks'} className={view === 'blocks' ? 'on' : ''}
                            onClick={() => setView('blocks')} data-testid="ocr-view-blocks">区域</button>
                  </div>
                )}
                {cur.res?.text && (
                  <button className="btn ghost sm"
                          onClick={() => void navigator.clipboard?.writeText(cur.res!.text).catch(() => undefined)}>复制</button>
                )}
              </div>
              {curLayout ? (
                <>
                  <p className="note tight" style={{ marginBottom: 'var(--s-3)' }} data-testid="ocr-layout-meta">
                    {curVl
                      ? <>{blocks.length} 个区域 · 版面 {(cur.res!.usage.layout_ms ?? 0).toFixed(0)} ms ·
                          VL {((cur.res!.usage.vl_ms ?? 0) / 1000).toFixed(1)} s · {cur.res!.usage.vl_tokens ?? 0} token</>
                      : <>{blocks.length} 个区域 · {cur.res!.usage.lines} 行 · 版面 {(cur.res!.usage.layout_ms ?? 0).toFixed(0)} ms ·
                          检测 {cur.res!.usage.det_ms.toFixed(0)} ms · 识别 {cur.res!.usage.rec_ms.toFixed(0)} ms</>}
                  </p>
                  {blocks.length === 0 ? (
                    <div className="empty"><strong>没有检测到版面区域</strong>换一张整页文档图片试试。</div>
                  ) : view === 'md' ? (
                    <div className="ocr-md" data-testid="ocr-markdown">
                      <Markdown text={cur.res!.text} />
                    </div>
                  ) : (
                    <ol className="layout-list" onMouseLeave={() => setActive(null)} data-testid="ocr-blocks">
                      {blocks.map((b, i) => (
                        <li key={i} className={`${active === i ? 'on' : ''}${OUTSIDE_TEXT.has(b.type) ? ' off' : ''}`}
                            onMouseEnter={() => setActive(i)}>
                          <span className="ocr-line-no">{b.index + 1}</span>
                          <span className="layout-type" title={b.label}>{typeLabel(b.type)}</span>
                          <span className="ocr-line-text">
                            {b.error
                              ? <span className="err-text">识别失败：{b.error}</span>
                              : curVl && b.type === 'table' && b.text
                                ? <div className="ocr-md md-tight"><Markdown text={b.text} /></div>
                                : b.text || <span className="muted">（无文字）</span>}
                            {OUTSIDE_TEXT.has(b.type) && <span className="note tight">不计入正文</span>}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              ) : cur.state === 'done' && cur.mode !== mode ? (
                <div className="empty"><strong>已切换识别方式</strong>点上方按钮按「{mode === 'vl' ? 'VL 精细识别' : layout ? '整页版面' : '逐行'}」重新识别。</div>
              ) : cur.state === 'done' && cur.res ? (
                <>
                  <p className="note tight" style={{ marginBottom: 'var(--s-3)' }}>
                    {cur.res.usage.lines} 行 · 检测 {cur.res.usage.det_ms.toFixed(0)} ms · 识别 {cur.res.usage.rec_ms.toFixed(0)} ms
                  </p>
                  {cur.res.lines.length === 0 ? (
                    <div className="empty"><strong>没有检测到文字</strong>换一张横排文字清晰的图片试试。</div>
                  ) : (
                    <ol className="ocr-lines" onMouseLeave={() => setActive(null)} data-testid="ocr-app-lines">
                      {cur.res.lines.map((l, i) => (
                        <li key={i} className={active === i ? 'on' : ''} onMouseEnter={() => setActive(i)}>
                          <span className="ocr-line-no">{i + 1}</span>
                          <span className="ocr-line-text">{l.text}</span>
                          <span className="ocr-line-score" title="识别置信度">{(l.score * 100).toFixed(0)}%</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              ) : cur.state === 'failed' ? (
                <p className="err-text">{cur.error}</p>
              ) : cur.state === 'running' ? (
                <p className="muted"><span className="spin" /> 识别中…</p>
              ) : (
                <div className="empty"><strong>还没有识别</strong>点上方的「识别」开始；多张图片按顺序处理。</div>
              )}
            </section>
          </>
        ) : (
          <section className="card ocr-view-empty">
            <div className="empty" data-testid="ocr-app-empty">
              <strong>拖入一批图片，逐张识别文字</strong>
              截图、照片、扫描页都可以。识别后鼠标移到某一行，会在图上框出它的位置；
              全部结果可以一键复制或保存成一个文本文件。
              选「整页版面」则先把页面分成标题、段落、表格、图片等区域，按阅读顺序（支持多栏）输出整页 Markdown，
              表格只输出文字；选「VL 精细识别」（需加载 PaddleOCR-VL）则逐个区域交给视觉模型，
              表格还原成带合并单元格的表格，速度慢一些。
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
