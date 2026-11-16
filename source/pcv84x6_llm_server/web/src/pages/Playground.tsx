import { useEffect, useRef, useState, type ReactNode } from 'react'
import PageSkeleton from '../components/Skeleton'
import { api, kindOf, streamChat, type ChatMessage, type Model, type ModelKind } from '../api'
import Markdown, { splitThinking } from '../components/Markdown'
import { KIND_LABEL } from '../components/kinds'
import { AsrPanel, EmbeddingPanel, OcrPanel, OcrVlPanel, RerankPanel } from './KindPanels'

type Msg = {
  role: 'user' | 'assistant'
  text: string
  stats?: string
  images?: string[]
  /** Sent with thinking mode on: the answer starts inside the think block. */
  thinking?: boolean
}

/** Turn one turn of the visible transcript into an OpenAI message.
 *
 *  Images only exist as raw base64 in the console (the mime the file came in as
 *  was never kept), so they go out as image/png data URLs: the backend decodes
 *  the bytes itself and only looks at the base64 payload.
 */
function toChatMessage(m: Msg): ChatMessage {
  if (m.images?.length) {
    return {
      role: m.role,
      content: [
        ...m.images.map((b64) => ({
          type: 'image_url' as const,
          image_url: { url: `data:image/png;base64,${b64}` },
        })),
        { type: 'text' as const, text: m.text },
      ],
    }
  }
  return { role: m.role, content: m.text }
}

/** Whole conversation to send: the transcript so far plus this turn's input. */
function buildMessages(history: Msg[], prompt: string, images: string[]): ChatMessage[] {
  const out: ChatMessage[] = []
  for (const m of history) {
    // An aborted answer leaves an empty assistant turn behind; replaying it
    // would tell the model it already replied with nothing.
    if (m.role === 'assistant' && !m.text.trim()) continue
    out.push(toChatMessage(m))
  }
  out.push(toChatMessage({ role: 'user', text: prompt, images }))
  return out
}

const MODEL_KEY = 'cv84x6.playground.model'

/** The order kinds are listed in the model picker, and what each tests. */
const KIND_ORDER: ModelKind[] = ['chat', 'embedding', 'rerank', 'asr', 'ocr', 'ocr_vl']

const KIND_SUB: Record<ModelKind, string> = {
  chat: '用页面里的对话框验证模型是否正常：流式输出，并显示速度与缓存命中。',
  embedding: '输入几段文本，查看它们两两之间的余弦相似度：意思相近的应该更接近。',
  rerank: '给一个查询和若干候选文档打分排序：最相关的文档应该排在第一。',
  asr: '上传一段音频，查看转写文本和分段时间轴，点击分段可以从该处播放。',
  ocr: '上传一张图片，查看逐行识别结果；检测框画在原图上。',
  ocr_vl: '上传一张图片并选择任务（文字、表格、公式、图表），识别结果流式输出。',
}

/** The test page: one model picker, and the panel for that model's kind.
 *
 *  Panels are keyed by kind, so switching between two embedding models keeps
 *  the inputs, while switching kinds starts that kind's panel fresh. */
export default function Playground() {
  const [models, setModels] = useState<Model[] | null>(null)
  const [model, setModelState] = useState(() => sessionStorage.getItem(MODEL_KEY) ?? '')
  const setModel = (id: string) => {
    setModelState(id)
    sessionStorage.setItem(MODEL_KEY, id)
  }

  useEffect(() => {
    api.models().then((r) => {
      const loaded = r.models.filter((m) => m.loaded)
      setModels(loaded)
      // Keep the remembered model if it is still serving; otherwise start on a
      // chat model, the page's historical default.
      if (!loaded.some((m) => m.id === model)) {
        const first = loaded.find((m) => kindOf(m) === 'chat') ?? loaded[0]
        if (first) setModel(first.id)
      }
    }).catch(() => setModels([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const current = models?.find((m) => m.id === model)
  const kind = current ? kindOf(current) : 'chat'

  if (models === null) {
    return <PageSkeleton title="对话测试" sub={KIND_SUB.chat} blocks={1} label="正在读取已加载的模型…" />
  }

  if (models.length === 0 || !current) {
    return (
      <>
        <h1>对话测试</h1>
        <p className="sub">在页面里直接测试已加载的模型：对话、向量、重排序、语音识别与 OCR。</p>
        <div className="card" data-testid="playground-empty"><div className="empty">
          <strong>还没有已加载的模型</strong>
          这个页面只列出正在服务的模型。先到「模型」页对应类型的页签里点「加载」，
          35B 首次加载约一分钟，辅助模型几秒；加载完成后回到这里就能开始测试。
        </div></div>
      </>
    )
  }

  const picker = (disabled: boolean): ReactNode => (
    <label className="field" style={{ minWidth: 240 }}>
      模型
      <select value={model} onChange={(e) => setModel(e.target.value)}
              disabled={disabled} data-testid="chat-model">
        {KIND_ORDER.map((k) => {
          const of = models.filter((m) => kindOf(m) === k)
          return of.length > 0 && (
            <optgroup key={k} label={KIND_LABEL[k]}>
              {of.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
            </optgroup>
          )
        })}
      </select>
    </label>
  )

  const props = { model: current, picker }
  return (
    <>
      <h1>对话测试</h1>
      <p className="sub" data-testid="playground-sub">{kind === 'embedding' && current.supports_vision
        ? '比较图片、文字或图文组合的语义相似度，验证跨模态检索效果。' : KIND_SUB[kind]}</p>
      <div data-testid={`panel-${kind}`} style={{ display: 'contents' }}>
        {kind === 'chat' && <ChatPanel key="chat" models={models} model={model} picker={picker} />}
        {kind === 'embedding' && <EmbeddingPanel key={`embedding-${current.supports_vision}`} {...props} />}
        {kind === 'rerank' && <RerankPanel key="rerank" {...props} />}
        {kind === 'asr' && <AsrPanel key="asr" {...props} />}
        {kind === 'ocr' && <OcrPanel key="ocr" {...props} />}
        {kind === 'ocr_vl' && <OcrVlPanel key="ocr_vl" {...props} />}
      </div>
    </>
  )
}

function ChatPanel({ models, model, picker }: {
  models: Model[]; model: string; picker: (disabled: boolean) => ReactNode
}) {
  const samplingSupported = models.find((m) => m.id === model)?.supports_sampling !== false
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [maxTokens, setMaxTokens] = useState(512)
  const [temperature, setTemperature] = useState(0.8)
  const [thinking, setThinking] = useState(false)
  // Assistant turns shown as the model's raw text instead of rendered Markdown.
  // Keyed by index: the transcript only ever grows or is cleared as a whole.
  const [rawShown, setRawShown] = useState<Set<number>>(new Set())
  const abort = useRef<AbortController | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs])

  const pickImages = async (files: FileList | null) => {
    if (!files) return
    const out: string[] = []
    for (const f of Array.from(files)) {
      const b64 = await new Promise<string>((res, rej) => {
        const fr = new FileReader()
        fr.onload = () => res(String(fr.result).split(',')[1] ?? '')
        fr.onerror = () => rej(new Error('读取图片失败'))
        fr.readAsDataURL(f)
      })
      out.push(b64)
    }
    setImages((prev) => [...prev, ...out].slice(0, 4))
  }

  const send = async () => {
    if (!input.trim() || !model || busy) return
    setErr('')
    const prompt = input
    const imgs = images
    // Built from the transcript as it stands now: the backend re-renders the
    // whole conversation each turn, which is what lets the prefix cache hit.
    const history = msgs
    setInput('')
    setImages([])
    setBusy(true)
    setMsgs((m) => [...m, { role: 'user', text: prompt, images: imgs }, { role: 'assistant', text: '', thinking }])

    const ctrl = new AbortController()
    abort.current = ctrl
    const t0 = performance.now()
    try {
      const usage = await streamChat(
        model, prompt,
        {
          maxTokens, temperature, enableThinking: thinking, signal: ctrl.signal,
          messages: buildMessages(history, prompt, imgs),
        },
        (t) => {
          setMsgs((m) => {
            const copy = [...m]
            const last = copy[copy.length - 1]
            copy[copy.length - 1] = { ...last, text: last.text + t }
            return copy
          })
        },
      )
      const elapsed = (performance.now() - t0) / 1000
      // Prefer the backend's own decode rate: it excludes prefill, which is the
      // number the overview page also plots.
      const measured = usage.decode_tps
      const tps = measured ?? (usage.completion_tokens > 0 ? usage.completion_tokens / elapsed : null)
      setMsgs((m) => {
        const copy = [...m]
        const last = copy[copy.length - 1]
        const parts = [
          `${usage.prompt_tokens} 输入 / ${usage.completion_tokens} 输出 token`,
          tps ? `${tps.toFixed(1)} tok/s` : null,
          // Always shown, zero included: "0" is the answer to "did the prefix
          // cache hit?" and hiding it would read as "not measured".
          `缓存 ${usage.cached_tokens}`,
          usage.first_token_latency_s ? `首字 ${usage.first_token_latency_s.toFixed(2)} s` : null,
        ].filter(Boolean)
        copy[copy.length - 1] = { ...last, stats: parts.join(' · ') }
        return copy
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : '请求失败'
      if (ctrl.signal.aborted) {
        setMsgs((m) => {
          const copy = [...m]
          copy[copy.length - 1] = { ...copy[copy.length - 1], stats: '已中止' }
          return copy
        })
      } else {
        setErr(msg)
      }
    } finally {
      abort.current = null
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  const stop = () => abort.current?.abort()

  const clear = () => {
    abort.current?.abort()
    setMsgs([])
    setRawShown(new Set())
    setErr('')
  }

  const toggleRaw = (i: number) => setRawShown((prev) => {
    const next = new Set(prev)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    return next
  })

  const current = models.find((m) => m.id === model)
  const canSend = !busy && input.trim().length > 0

  return (
    <>
      {/* One row: the model on the left, the run-time knobs beside it, the
          destructive action pushed to the far right. */}
      <div className="toolbar" data-testid="playground-toolbar">
        {picker(busy)}
        <label className="field" style={{ width: 108 }}>
          最大 token
          <input type="number" value={maxTokens} min={1} max={16384}
                 data-testid="chat-max-tokens"
                 onChange={(e) => setMaxTokens(Number(e.target.value))} />
        </label>
        <label className="field" style={{ width: 108 }}
               title={samplingSupported ? undefined
                 : '这个 bmodel 的 lm_head 已经把 argmax 编进图里，只输出一个 token id，' +
                   '没有可采样的概率分布。温度/采样参数对它不起作用，只能返回 argmax。'}>
          温度
          <input type="number" value={temperature} min={0} max={2} step={0.1}
                 onChange={(e) => setTemperature(Number(e.target.value))}
                 disabled={!samplingSupported} />
        </label>
        <label className="field inline" style={{ alignSelf: 'center' }}
               title="默认关闭，与官方 demo 一致（回答前插入空的 think 块）。勾选后模型先输出思考内容再给答案。">
          <input type="checkbox" checked={thinking} data-testid="chat-thinking"
                 onChange={(e) => setThinking(e.target.checked)} />
          思考模式
        </label>
        {!samplingSupported && (
          <span className="pill warn" style={{ alignSelf: 'center' }}>该模型 argmax 输出，温度不生效</span>
        )}
        <div className="spacer" />
        <button className="btn ghost sm" onClick={clear} disabled={msgs.length === 0 && !busy}
                data-testid="chat-clear" style={{ alignSelf: 'center' }}>
          清空对话
        </button>
      </div>

      {err && <p className="err-text">{err}</p>}

      <div className="chat">
        <div className="chat-log" ref={logRef} data-testid="chat-log">
          {msgs.length === 0 && (
            <div className="empty">
              输入问题开始测试。多轮对话会复用前缀缓存，回答下方的「缓存 N」就是命中量。
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`} data-testid={`chat-msg-${m.role}`}>
              <div className="msg-role">{m.role === 'user' ? '你' : '模型'}</div>
              {m.images?.length ? (
                <div className="msg-images">
                  {m.images.map((b, j) => (
                    <img key={j} src={`data:image/png;base64,${b}`} alt={`附图 ${j + 1}`} />
                  ))}
                </div>
              ) : null}
              {m.role === 'assistant' && m.text
                ? <AssistantBody text={m.text} thinking={!!m.thinking} raw={rawShown.has(i)}
                                 streaming={busy && i === msgs.length - 1} />
                : (
                  <div className="msg-body">
                    {m.text || (m.role === 'assistant' && busy && i === msgs.length - 1
                      ? <span className="row" style={{ gap: 'var(--s-2)' }}><span className="spin" /><span className="muted">正在生成…</span></span>
                      : m.role === 'assistant' ? <span className="muted">（空回答）</span> : '')}
                  </div>
                )}
              {(m.stats || (m.role === 'assistant' && m.text)) && (
                <div className="meta">
                  {m.stats}
                  {m.role === 'assistant' && m.text && (
                    <button className="btn link raw-toggle" onClick={() => toggleRaw(i)}
                            data-testid="chat-raw-toggle"
                            title="Markdown 渲染与模型原始输出之间切换，排查格式问题时看原文">
                      {rawShown.has(i) ? '渲染' : '原文'}
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="composer">
          {images.length > 0 && (
            <div className="attach-list">
              {images.map((b, i) => (
                <span key={i} className="attach">
                  <img src={`data:image/png;base64,${b}`} alt={`待发送图片 ${i + 1}`} />
                  <button className="btn ghost sm icon" title="移除"
                          onClick={() => setImages((p) => p.filter((_, j) => j !== i))}>×</button>
                </span>
              ))}
            </div>
          )}
          <textarea
            ref={inputRef} rows={3} value={input} data-testid="chat-input"
            placeholder="输入问题。Enter 换行，Ctrl+Enter（macOS 为 ⌘+Enter）发送。"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send() }
            }}
          />
          <div className="composer-actions">
            <input ref={fileRef} type="file" accept="image/*" multiple
                   onChange={(e) => void pickImages(e.target.files)} />
            <button className="btn ghost sm" data-testid="chat-attach"
                    onClick={() => fileRef.current?.click()}
                    disabled={!current?.supports_vision || busy}
                    title={current?.supports_vision ? '添加图片（最多 4 张）' : '该模型不支持图片'}>
              加图片
            </button>
            <span className="composer-hint">
              {current?.supports_vision ? '最多 4 张图片，随下一条消息发送' : '当前模型不支持图片输入'}
              {images.length > 0 && ` · 已选 ${images.length} 张`}
            </span>
            <div className="spacer" />
            <span className="composer-hint">
              <span className="kbd">Ctrl</span> + <span className="kbd">Enter</span> 发送
            </span>
            {busy ? (
              <button className="btn danger" onClick={stop} data-testid="chat-stop">停止生成</button>
            ) : (
              <button className="btn" onClick={() => void send()} disabled={!canSend}
                      data-testid="chat-send">发送</button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

/** One model turn: reasoning (if any) folded above the answer, the answer
 *  rendered as Markdown. `raw` shows the exact text the model produced, which
 *  is what to quote when an answer looks wrong. */
function AssistantBody({ text, thinking, raw, streaming }: {
  text: string; thinking: boolean; raw: boolean; streaming: boolean
}) {
  if (raw) return <div className="msg-body" data-testid="chat-raw">{text}</div>
  const { reasoning, answer, thinkingOpen } = splitThinking(text, thinking)
  return (
    <div className="msg-body md-body">
      {reasoning !== null && (
        // Open while the model is still thinking, so the operator sees it
        // working; folded once the answer starts.
        <details className="think" open={thinkingOpen && streaming}>
          <summary>{thinkingOpen && streaming ? '思考中…' : '思考过程'}</summary>
          <Markdown text={reasoning} />
        </details>
      )}
      {answer
        ? <Markdown text={answer} />
        : !thinkingOpen && <span className="muted">（空回答）</span>}
    </div>
  )
}
