import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  api, fmtBytes, streamOpenAIChat,
  type Model, type OcrResult, type TranscriptResult,
} from '../api'
import VlAnswer from '../components/VlAnswer'
import {
  cosine, fmtClock, OcrOverlay, ScoreBars, SegmentTimeline, SimilarityMatrix,
} from '../components/TestViz'

/* The playground's panels for the non-chat kinds (MYS-2599). Each one is the
   smallest form that exercises its endpoint the way a client would, and a
   result view that answers "is this model working?" at a glance. They all go
   through /api/test/*, which runs the /v1 handlers behind the admin cookie, so
   what the panel shows is what an API client gets. */

type PanelProps = { model: Model; picker: (disabled: boolean) => ReactNode }

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback
}

/** Seconds since `t0`, for the client-side "took" figure. */
function since(t0: number): number {
  return (performance.now() - t0) / 1000
}

function RunButton({ busy, disabled, onClick, label, busyLabel, testid }: {
  busy: boolean; disabled: boolean; onClick: () => void
  label: string; busyLabel: string; testid: string
}) {
  return (
    <button className="btn" onClick={onClick} disabled={busy || disabled}
            data-testid={testid} style={{ alignSelf: 'center' }}>
      {busy ? <><span className="spin" /> {busyLabel}</> : label}
    </button>
  )
}

/** An editable list of short texts: the input both embedding and rerank need. */
function TextList({ items, onChange, max, label, testid, disabled }: {
  items: string[]; onChange: (v: string[]) => void; max: number
  label: (i: number) => string; testid: string; disabled: boolean
}) {
  return (
    <div className="stack" data-testid={testid}>
      {items.map((t, i) => (
        <div key={i} className="text-item">
          <span className="text-item-label">{label(i)}</span>
          <textarea rows={2} value={t} disabled={disabled}
                    aria-label={label(i)} data-testid={`${testid}-${i}`}
                    onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))} />
          <button className="btn ghost sm icon" title="移除" aria-label={`移除${label(i)}`}
                  disabled={disabled || items.length <= 2}
                  onClick={() => onChange(items.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div className="row">
        <button className="btn ghost sm" disabled={disabled || items.length >= max}
                data-testid={`${testid}-add`}
                onClick={() => onChange([...items, ''])}>添加一条</button>
        <span className="note">最多 {max} 条</span>
      </div>
    </div>
  )
}

/** A file well: click to pick, or drop a file on it. */
function FileDrop({ accept, file, onFile, hint, testid, disabled, children }: {
  accept: string; file: File | null; onFile: (f: File) => void
  hint: string; testid: string; disabled: boolean; children?: ReactNode
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div className={`dropzone${over ? ' over' : ''}${file ? ' has-file' : ''}`}
         data-testid={testid}
         onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true) }}
         onDragLeave={() => setOver(false)}
         onDrop={(e) => {
           e.preventDefault(); setOver(false)
           const f = e.dataTransfer.files?.[0]
           if (f && !disabled) onFile(f)
         }}>
      <input ref={ref} type="file" accept={accept} data-testid={`${testid}-input`}
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
      {children}
      <div className="row dropzone-bar">
        <button className="btn ghost sm" disabled={disabled} onClick={() => ref.current?.click()}>
          {file ? '换一个文件' : '选择文件'}
        </button>
        {file
          ? <span className="note dropzone-name" title={file.name}>{file.name} · {fmtBytes(file.size)}</span>
          : <span className="note">{hint}</span>}
      </div>
    </div>
  )
}

function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  return url
}

// -- embedding ----------------------------------------------------------------

const EMBED_SAMPLES = [
  'NPU 内存不足时，新的请求会排队等待。',
  '显存不够的时候，请求会先进入队列。',
  '今天下午天气晴朗，适合出门散步。',
  'How does the server handle low NPU memory?',
]

type EmbedInput = { text: string; file: File | null }

function EmbedImage({ file, disabled, onFile, index }: {
  file: File | null; disabled: boolean; onFile: (f: File | null) => void; index: number
}) {
  const ref = useRef<HTMLInputElement>(null)
  const preview = useObjectUrl(file)
  return (
    <div className="embed-image">
      <input ref={ref} type="file" hidden accept="image/jpeg,image/png" disabled={disabled}
             data-testid={`embed-image-${index}`}
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
      {preview && <img src={preview} alt={`T${index + 1} 附图`} />}
      <div className="embed-image-detail">
        {file && <span className="note dropzone-name" title={file.name}>{file.name}</span>}
        <div className="row">
          <button className="btn ghost sm" disabled={disabled} onClick={() => ref.current?.click()}>
            {file ? '更换图片' : '添加图片'}
          </button>
          {file
            ? <button className="btn ghost sm" disabled={disabled} onClick={() => onFile(null)}
                      aria-label={`移除 T${index + 1} 的图片`}>移除</button>
            : <span className="note">可只传图片，也可配文字</span>}
        </div>
      </div>
    </div>
  )
}

export function EmbeddingPanel({ model, picker }: PanelProps) {
  const [inputs, setInputs] = useState<EmbedInput[]>(EMBED_SAMPLES.map((text) => ({ text, file: null })))
  const [instruction, setInstruction] = useState('')
  const [dims, setDims] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<{ texts: string[]; matrix: number[][]; dim: number; tokens: number; took: number } | null>(null)

  const vision = model.supports_vision
  const hidden = model.hidden_size ?? (vision ? 2048 : 1024)
  const dimOptions = [0, ...[1024, 512, 256, 128, 64, 32].filter((d) => d < hidden && d >= (vision ? 64 : 32))]
  const selectedDim = dimOptions.includes(dims) ? dims : 0
  const ready = inputs.filter((item) => item.text.trim() || (vision && item.file))
  useEffect(() => { setRes(null); setErr('') }, [model.id])

  const attach = (index: number, file: File | null) => {
    if (file && (!['image/jpeg', 'image/png'].includes(file.type) || file.size > 4 * 1024 * 1024)) {
      setErr('请选择不超过 4 MiB 的 JPEG 或 PNG 图片。'); return
    }
    setErr('')
    setInputs(inputs.map((item, i) => i === index ? { ...item, file } : item))
  }

  const run = async () => {
    setBusy(true); setErr('')
    const t0 = performance.now()
    try {
      const payload = await Promise.all(ready.map(async ({ text, file }) =>
        vision ? { text, ...(file ? { image: await readDataUrl(file) } : {}) } : text))
      const r = await api.testEmbeddings({
        model: model.id, input: payload,
        ...(selectedDim ? { dimensions: selectedDim } : {}),
        ...(instruction.trim() ? { instruction } : {}),
      })
      const vecs = [...r.data].sort((a, b) => a.index - b.index).map((d) => d.embedding)
      setRes({
        texts: ready.map(({ text, file }) => [file?.name, text.trim()].filter(Boolean).join(' · ')),
        matrix: vecs.map((a) => vecs.map((b) => cosine(a, b))),
        dim: vecs[0]?.length ?? 0,
        tokens: r.usage.prompt_tokens,
        took: since(t0),
      })
    } catch (e) {
      setErr(errText(e, '请求失败'))
    } finally {
      setBusy(false)
    }
  }

  // The headline: the closest pair, i.e. the answer a retrieval test is after.
  const best = useMemo(() => {
    if (!res || res.texts.length < 2) return null
    let top: [number, number, number] = [0, 1, -2]
    res.matrix.forEach((row, i) => row.forEach((v, j) => { if (i < j && v > top[2]) top = [i, j, v] }))
    return top
  }, [res])

  return (
    <>
      <div className="toolbar" data-testid="playground-toolbar">
        {picker(busy)}
        <label className="field" style={{ width: 144 }}>
          维度
          <select value={selectedDim} onChange={(e) => setDims(Number(e.target.value))} disabled={busy}
                  data-testid="embed-dims">
            {dimOptions.map((d) => <option key={d} value={d}>{d ? `${d}（截断）` : `完整（${hidden}）`}</option>)}
          </select>
        </label>
        <label className="field" style={{ flex: '1 1 240px' }}
               title={vision ? '描述本次检索任务，作为整批输入的系统指令。' : '非标准字段：拼在每条文本前面。Qwen3-Embedding 检索查询应带指令，文档不带。'}>
          指令（可选）
          <input value={instruction} disabled={busy} data-testid="embed-instruction"
                 placeholder={vision ? '例如：根据描述检索相关图片' : '可选，原样拼在每条文本前面'}
                 onChange={(e) => setInstruction(e.target.value)} />
        </label>
        <RunButton busy={busy} disabled={ready.length < 2} onClick={() => void run()}
                   label="计算相似度" busyLabel="计算中…" testid="embed-run" />
      </div>
      {err && <p className="err-text" data-testid="panel-error">{err}</p>}
      <div className="grid c2 panel-grid">
        <div className="card">
          <h2>{vision ? '输入内容' : '输入文本'}</h2>
          {vision && <p className="note">每条可包含文字和一张图片。JPEG / PNG，单张最多 4 MiB。</p>}
          <div className="stack" data-testid="embed-texts">
            {inputs.map((item, i) => (
              <div key={i} className={vision ? 'embed-entry' : undefined}>
                <div className="text-item">
                  <span className="text-item-label">T{i + 1}</span>
                  <textarea rows={2} value={item.text} disabled={busy} aria-label={`T${i + 1}`}
                            data-testid={`embed-texts-${i}`}
                            placeholder={vision ? '输入文字，或在下方添加图片' : ''}
                            onChange={(e) => setInputs(inputs.map((x, j) => j === i ? { ...x, text: e.target.value } : x))} />
                  <button className="btn ghost sm icon" aria-label={`移除T${i + 1}`} title="移除"
                          disabled={busy || inputs.length <= 2}
                          onClick={() => setInputs(inputs.filter((_, j) => j !== i))}>×</button>
                </div>
                {vision && <EmbedImage file={item.file} disabled={busy} index={i} onFile={(f) => attach(i, f)} />}
              </div>
            ))}
            <div className="row">
              <button className="btn ghost sm" disabled={busy || inputs.length >= 8}
                      data-testid="embed-texts-add"
                      onClick={() => setInputs([...inputs, { text: '', file: null }])}>添加一条</button>
              <span className="note">最多 8 条</span>
            </div>
          </div>
        </div>
        <div className="card" data-testid="embed-result">
          <h2>两两余弦相似度</h2>
          {res ? (
            <>
              {best && (
                <p className="headline" data-testid="embed-best">
                  最接近的是 <b>T{best[0] + 1}</b> 与 <b>T{best[1] + 1}</b>
                  <span className="headline-num">{best[2].toFixed(3)}</span>
                </p>
              )}
              <SimilarityMatrix texts={res.texts} matrix={res.matrix} />
              <p className="note" style={{ marginTop: 'var(--s-3)' }} data-testid="embed-meta">
                {res.dim} 维 · {res.tokens} token · 耗时 {res.took.toFixed(2)} s
              </p>
            </>
          ) : (
            <div className="empty">
              <strong>还没有结果</strong>
              {vision
                ? '添加至少两条内容，点「计算相似度」。试着比较一张图片和它的文字描述，观察跨模态的相似程度。'
                : '输入至少两段文本，点「计算相似度」。意思相近的文本相似度更高，可以用来判断向量是否正常。'}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// -- rerank -------------------------------------------------------------------

const RERANK_QUERY = '设备内存不够时会发生什么？'
const RERANK_DOCS = [
  '35B 模型加载后约占用 20 GB NPU 内存。',
  'NPU 内存不足时，新的请求会排队等待，不会直接报错。',
  '今天下午天气晴朗，适合出门散步。',
  'PicoClaw 启动后空闲时约占用 52 MB 内存。',
]

export function RerankPanel({ model, picker }: PanelProps) {
  const [query, setQuery] = useState(RERANK_QUERY)
  const [docs, setDocs] = useState(RERANK_DOCS)
  const [topN, setTopN] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<{ rows: { index: number; score: number; text: string }[]; tokens: number; took: number } | null>(null)
  const ready = docs.filter((d) => d.trim())

  const run = async () => {
    setBusy(true); setErr('')
    const t0 = performance.now()
    try {
      const r = await api.testRerank({
        model: model.id, query, documents: ready, ...(topN ? { top_n: topN } : {}),
      })
      setRes({
        rows: r.results.map((x) => ({ index: x.index, score: x.relevance_score, text: x.document?.text ?? ready[x.index] })),
        tokens: r.usage.prompt_tokens,
        took: since(t0),
      })
    } catch (e) {
      setErr(errText(e, '请求失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="toolbar" data-testid="playground-toolbar">
        {picker(busy)}
        <label className="field" style={{ width: 108 }}>
          返回前 N 条
          <select value={topN} onChange={(e) => setTopN(Number(e.target.value))} disabled={busy}
                  data-testid="rerank-topn">
            <option value={0}>全部</option>
            {[1, 3, 5, 10].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <div className="spacer" />
        <RunButton busy={busy} disabled={!query.trim() || ready.length < 1} onClick={() => void run()}
                   label="排序" busyLabel="打分中…" testid="rerank-run" />
      </div>
      {err && <p className="err-text" data-testid="panel-error">{err}</p>}
      <div className="grid c2 panel-grid">
        <div className="card">
          <h2>查询与候选文档</h2>
          <label className="field" style={{ marginBottom: 'var(--s-3)' }}>
            查询
            <input value={query} disabled={busy} data-testid="rerank-query"
                   onChange={(e) => setQuery(e.target.value)} />
          </label>
          <TextList items={docs} onChange={setDocs} max={16} disabled={busy}
                    label={(i) => `#${i + 1}`} testid="rerank-docs" />
        </div>
        <div className="card" data-testid="rerank-result">
          <h2>相关度排序</h2>
          {res ? (
            <>
              <ScoreBars rows={res.rows} />
              <p className="note" style={{ marginTop: 'var(--s-3)' }} data-testid="rerank-meta">
                分数为 sigmoid(logit)，范围 0–1 · {res.tokens} token · 耗时 {res.took.toFixed(2)} s
              </p>
            </>
          ) : (
            <div className="empty">
              <strong>还没有结果</strong>
              点「排序」给每条文档打分。与查询最相关的文档应排在第一。
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// -- ASR ------------------------------------------------------------------------

const ASR_LANGUAGES: [string, string][] = [
  ['', '自动识别'], ['zh', '中文'], ['en', '英语'], ['yue', '粤语'], ['ja', '日语'],
  ['ko', '韩语'], ['fr', '法语'], ['de', '德语'], ['es', '西班牙语'], ['ru', '俄语'],
]

export function AsrPanel({ model, picker }: PanelProps) {
  const [file, setFile] = useState<File | null>(null)
  const [language, setLanguage] = useState('')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<(TranscriptResult & { took: number }) | null>(null)
  const [pos, setPos] = useState<number | null>(null)
  const audio = useRef<HTMLAudioElement>(null)
  const url = useObjectUrl(file)

  const run = async () => {
    if (!file) return
    setBusy(true); setErr('')
    const t0 = performance.now()
    try {
      const r = await api.testTranscribe(model.id, file, { language, prompt: prompt.trim() })
      setRes({ ...r, took: since(t0) })
    } catch (e) {
      setErr(errText(e, '转写失败'))
    } finally {
      setBusy(false)
    }
  }

  const seek = (t: number) => {
    const a = audio.current
    if (!a) return
    a.currentTime = t
    void a.play().catch(() => undefined)
  }

  return (
    <>
      <div className="toolbar" data-testid="playground-toolbar">
        {picker(busy)}
        <label className="field" style={{ width: 120 }}>
          语言
          <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={busy}
                  data-testid="asr-language">
            {ASR_LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field" style={{ flex: '1 1 200px' }} title="作为上下文交给模型，例如专有名词">
          提示词（可选）
          <input value={prompt} disabled={busy} onChange={(e) => setPrompt(e.target.value)}
                 placeholder="例如：CV84X6、PicoClaw" data-testid="asr-prompt" />
        </label>
        <RunButton busy={busy} disabled={!file} onClick={() => void run()}
                   label="转写" busyLabel="转写中…" testid="asr-run" />
      </div>
      {err && <p className="err-text" data-testid="panel-error">{err}</p>}
      <div className="grid c2 panel-grid">
        <div className="card">
          <h2>音频</h2>
          <FileDrop accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac" file={file} disabled={busy}
                    onFile={(f) => { setFile(f); setRes(null); setPos(null) }}
                    hint="WAV 直接解码，其他格式经设备上的 ffmpeg；≤ 50 MB、≤ 30 分钟" testid="asr-file">
            {url && (
              <audio ref={audio} src={url} controls preload="metadata" className="audio"
                     data-testid="asr-audio"
                     onTimeUpdate={(e) => setPos(e.currentTarget.currentTime)}
                     onEnded={() => setPos(null)} />
            )}
          </FileDrop>
        </div>
        <div className="card" data-testid="asr-result">
          <h2>转写结果</h2>
          {res ? (
            <>
              <p className="transcript" data-testid="asr-text">
                {res.text || <span className="muted">（没有识别出文字）</span>}
              </p>
              <p className="note" data-testid="asr-meta">
                时长 {res.duration.toFixed(2)} s · 语言 {res.language ?? '未知'} · 处理 {res.took.toFixed(2)} s
                {res.took > 0 && res.duration > 0 && ` · ${(res.duration / res.took).toFixed(1)}× 实时`}
                {` · ${res.segments.length} 段`}
              </p>
              {res.segments.length > 0 && (
                <>
                  <h3>分段</h3>
                  <SegmentTimeline segments={res.segments} duration={res.duration}
                                   position={pos} onSeek={seek} />
                  <ol className="segs" data-testid="asr-segments">
                    {res.segments.map((s) => (
                      <li key={s.id}>
                        <button className="btn link seg-time mono" onClick={() => seek(s.start)}
                                title="从这里播放">
                          {fmtClock(s.start)}–{fmtClock(s.end)}
                        </button>
                        <span>{s.text}</span>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </>
          ) : (
            <div className="empty">
              <strong>还没有结果</strong>
              选择一个音频文件，点「转写」。超过 30 秒的音频会自动切段，每段对应时间轴上的一块。
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// -- OCR (PP-OCR) ---------------------------------------------------------------

export function OcrPanel({ model, picker }: PanelProps) {
  const [file, setFile] = useState<File | null>(null)
  const [showBoxes, setShowBoxes] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<(OcrResult & { took: number }) | null>(null)
  const [active, setActive] = useState<number | null>(null)
  const url = useObjectUrl(file)

  const run = async () => {
    if (!file) return
    setBusy(true); setErr('')
    const t0 = performance.now()
    try {
      const r = await api.testOcr(model.id, file)
      setRes({ ...r, took: since(t0) })
    } catch (e) {
      setErr(errText(e, '识别失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="toolbar" data-testid="playground-toolbar">
        {picker(busy)}
        <label className="field inline" style={{ alignSelf: 'center' }}>
          <input type="checkbox" checked={showBoxes} data-testid="ocr-show-boxes"
                 onChange={(e) => setShowBoxes(e.target.checked)} />
          显示检测框
        </label>
        <div className="spacer" />
        <RunButton busy={busy} disabled={!file} onClick={() => void run()}
                   label="识别" busyLabel="识别中…" testid="ocr-run" />
      </div>
      {err && <p className="err-text" data-testid="panel-error">{err}</p>}
      <div className="grid c2 panel-grid">
        <div className="card">
          <h2>图片</h2>
          <FileDrop accept="image/png,image/jpeg,image/bmp,image/webp" file={file} disabled={busy}
                    onFile={(f) => { setFile(f); setRes(null); setActive(null) }}
                    hint="PNG / JPEG，≤ 20 MiB；横排文字" testid="ocr-file">
            {url && (
              <OcrOverlay src={url} boxes={res?.lines.map((l) => l.box) ?? []}
                          show={showBoxes} active={active} onActive={setActive} />
            )}
          </FileDrop>
        </div>
        <div className="card" data-testid="ocr-result">
          <div className="row" style={{ marginBottom: 'var(--s-3)' }}>
            <h2 style={{ margin: 0 }}>识别结果</h2>
            <div className="spacer" />
            {res && res.text && (
              <button className="btn ghost sm" data-testid="ocr-copy"
                      onClick={() => void navigator.clipboard?.writeText(res.text).catch(() => undefined)}>
                复制全文
              </button>
            )}
          </div>
          {res ? (
            <>
              <p className="note" style={{ marginBottom: 'var(--s-3)' }} data-testid="ocr-meta">
                {res.usage.lines} 行 · 检测 {res.usage.det_ms.toFixed(0)} ms · 识别 {res.usage.rec_ms.toFixed(0)} ms ·
                端到端 {res.took.toFixed(2)} s
              </p>
              {res.lines.length === 0 ? (
                <div className="empty"><strong>没有检测到文字</strong>换一张横排文字清晰的图片试试。</div>
              ) : (
                <ol className="ocr-lines" data-testid="ocr-lines" onMouseLeave={() => setActive(null)}>
                  {res.lines.map((l, i) => (
                    <li key={i} className={active === i ? 'on' : ''} onMouseEnter={() => setActive(i)}>
                      <span className="ocr-line-no">{i + 1}</span>
                      <span className="ocr-line-text">{l.text}</span>
                      <span className="ocr-line-score" title="识别置信度">{(l.score * 100).toFixed(0)}%</span>
                    </li>
                  ))}
                </ol>
              )}
            </>
          ) : (
            <div className="empty">
              <strong>还没有结果</strong>
              选择一张图片，点「识别」。结果按阅读顺序逐行列出，鼠标移到某一行会在图上标出它的位置。
              竖排文字识别不了，两栏正文的行会交错。
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// -- OCR-VL (PaddleOCR-VL) --------------------------------------------------------

/** The task prompts PaddleOCR-VL was trained on. They are fixed strings, not
 *  free text: anything else is outside what the model was taught to do. */
const VL_TASKS: [string, string][] = [
  ['OCR:', '文字识别'],
  ['Table Recognition:', '表格识别'],
  ['Formula Recognition:', '公式识别'],
  ['Chart Recognition:', '图表识别'],
]

function readDataUrl(f: File): Promise<string> {
  return new Promise((res, rej) => {
    const fr = new FileReader()
    fr.onload = () => res(String(fr.result))
    fr.onerror = () => rej(new Error('读取图片失败'))
    fr.readAsDataURL(f)
  })
}

export function OcrVlPanel({ model, picker }: PanelProps) {
  const [file, setFile] = useState<File | null>(null)
  const [task, setTask] = useState(VL_TASKS[0][0])
  const [maxTokens, setMaxTokens] = useState(1024)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [out, setOut] = useState('')
  const [stats, setStats] = useState('')
  const [raw, setRaw] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const url = useObjectUrl(file)

  const run = async () => {
    if (!file) return
    setBusy(true); setErr(''); setOut(''); setStats('')
    const ctrl = new AbortController()
    abort.current = ctrl
    const t0 = performance.now()
    let first: number | null = null
    try {
      const image = await readDataUrl(file)
      const u = await streamOpenAIChat({
        model: model.id, max_tokens: maxTokens,
        messages: [{ role: 'user', content: [
          { type: 'image_url', image_url: { url: image } },
          { type: 'text', text: task },
        ] }],
      }, { signal: ctrl.signal }, (t) => {
        if (first === null) first = since(t0)
        setOut((s) => s + t)
      })
      const total = since(t0)
      const decode = first !== null && u.completion_tokens > 1 ? (u.completion_tokens - 1) / (total - first) : null
      setStats([
        `${u.prompt_tokens} 输入 / ${u.completion_tokens} 输出 token`,
        decode ? `${decode.toFixed(1)} tok/s` : null,
        first !== null ? `首字 ${(first as number).toFixed(2)} s` : null,
        u.finish_reason === 'length' ? '达到最大 token，输出被截断' : null,
      ].filter(Boolean).join(' · '))
    } catch (e) {
      if (ctrl.signal.aborted) setStats('已中止')
      else setErr(errText(e, '识别失败'))
    } finally {
      abort.current = null
      setBusy(false)
    }
  }

  return (
    <>
      <div className="toolbar" data-testid="playground-toolbar">
        {picker(busy)}
        <label className="field" style={{ width: 132 }}>
          任务
          <select value={task} onChange={(e) => setTask(e.target.value)} disabled={busy}
                  data-testid="vl-task">
            {VL_TASKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field" style={{ width: 108 }}>
          最大 token
          <input type="number" value={maxTokens} min={1} max={2048}
                 onChange={(e) => setMaxTokens(Number(e.target.value))} disabled={busy} />
        </label>
        <div className="spacer" />
        {busy
          ? <button className="btn danger" onClick={() => abort.current?.abort()} data-testid="vl-stop"
                    style={{ alignSelf: 'center' }}>停止</button>
          : <RunButton busy={false} disabled={!file} onClick={() => void run()}
                       label="识别" busyLabel="" testid="vl-run" />}
      </div>
      {err && <p className="err-text" data-testid="panel-error">{err}</p>}
      <div className="grid c2 panel-grid">
        <div className="card">
          <h2>图片</h2>
          <FileDrop accept="image/png,image/jpeg,image/webp" file={file} disabled={busy}
                    onFile={(f) => { setFile(f); setOut(''); setStats('') }}
                    hint="单张图片，识别前统一缩放到 784×784；适合单个区域（一段文字、一张表格、一个公式），整页文档请先裁剪" testid="vl-file">
            {url && <div className="ocr-stage"><img src={url} alt="待识别图片" /></div>}
          </FileDrop>
        </div>
        <div className="card" data-testid="vl-result">
          <div className="row" style={{ marginBottom: 'var(--s-3)' }}>
            <h2 style={{ margin: 0 }}>输出</h2>
            <div className="spacer" />
            {out && (
              <button className="btn link" onClick={() => setRaw((r) => !r)} data-testid="vl-raw-toggle"
                      title="渲染视图与模型原始输出之间切换">
                {raw ? '渲染' : '原文'}
              </button>
            )}
          </div>
          {out ? (
            raw ? <pre className="block" data-testid="vl-raw">{out}</pre>
              : <div className="vl-out" data-testid="vl-text"><VlAnswer text={out} streaming={busy} /></div>
          ) : busy ? (
            <span className="row" style={{ gap: 'var(--s-2)' }}><span className="spin" /><span className="muted">正在识别…</span></span>
          ) : (
            <div className="empty">
              <strong>还没有结果</strong>
              选择一张图片和任务，点「识别」。输出逐字流式显示；表格识别结果显示为表格（含合并单元格），可复制 HTML。
            </div>
          )}
          {stats && <p className="note" style={{ marginTop: 'var(--s-3)' }} data-testid="vl-meta">{stats}</p>}
        </div>
      </div>
    </>
  )
}
