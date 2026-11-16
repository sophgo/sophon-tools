import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fmtBytes, type Model } from '../../api'
import {
  kb, type Citation, type KbDoc, type KbInfo, type KbResult, type SearchResult, type StageName,
} from '../../apps'
import { renderMarkdown, splitThinking } from '../../components/Markdown'
import { OcrOverlay } from '../../components/TestViz'
import RankFlow from '../../components/RankFlow'
import { errText, FileDropMany, ModelChip, readyOf } from './common'

/* 知识库问答 (MYS-2606's backend). The page is laid out as the pipeline runs:
   documents on the left (what went in, and whether OCR was needed), the
   question and its answer on the right, then the figure that shows what each
   retrieval stage did, then the passages themselves.

   Which stages run depends on what is loaded -- the 35B leaves no NPU room
   for the embedding model and the reranker -- so the model strip at the top
   says, before anything is clicked, which mode the next question will run in. */

const STAGE_LABEL: Record<StageName, string> = {
  bm25: '关键词 BM25', vector: '向量检索', fusion: 'RRF 融合', rerank: '精排',
}
const STAGE_HINT: Record<StageName, string> = {
  bm25: '按词频匹配，不需要模型',
  vector: 'Embedding 把问题和片段编码成向量，按余弦相似度召回',
  fusion: '把两路名次合成一个：Σ 1 / (60 + 名次)',
  rerank: 'Reranker 逐条读「问题 + 片段」打相关度',
}
const STATUS_LABEL: Record<KbDoc['status'], string> = {
  queued: '排队中', parsing: '解析中', ocr: 'OCR 中', embedding: '向量化',
  ready: '就绪', failed: '失败',
}
const TYPE_LABEL: Record<KbDoc['type'], string> = { txt: 'TXT', md: 'MD', pdf: 'PDF', image: '图片' }
const ACCEPT = '.txt,.md,.markdown,.pdf,.png,.jpg,.jpeg,.webp,.bmp,text/plain,application/pdf,image/*'

const busyStatus = (s: KbDoc['status']) => s !== 'ready' && s !== 'failed'

/** Characters of `text` covered by a query term: CJK bigrams and Latin words,
 *  the same units the BM25 stage scores, so the marks show why it matched. */
function highlight(text: string, query: string): (string | JSX.Element)[] {
  const q = query.toLowerCase()
  const grams = new Set<string>()
  const cjk = /[㐀-鿿豈-﫿]/
  for (const run of q.match(/[㐀-鿿豈-﫿]+/g) ?? []) {
    if (run.length === 1) grams.add(run)
    for (let i = 0; i + 2 <= run.length; i++) grams.add(run.slice(i, i + 2))
  }
  const words = new Set((q.match(/[a-z0-9]+/g) ?? []).filter((w) => w.length > 1))
  const on = new Array<boolean>(text.length).fill(false)
  const low = text.toLowerCase()
  for (let i = 0; i < low.length; i++) {
    if (!cjk.test(low[i])) continue
    const g2 = low.slice(i, i + 2)
    if (g2.length === 2 && grams.has(g2)) { on[i] = true; on[i + 1] = true }
    else if (grams.has(low[i])) on[i] = true  // a one-character query run
  }
  for (const m of low.matchAll(/[a-z0-9]+/g)) {
    if (words.has(m[0])) for (let k = 0; k < m[0].length; k++) on[(m.index ?? 0) + k] = true
  }
  const out: (string | JSX.Element)[] = []
  let i = 0
  while (i < text.length) {
    let j = i
    while (j < text.length && on[j] === on[i]) j++
    out.push(on[i] ? <mark key={i}>{text.slice(i, j)}</mark> : text.slice(i, j))
    i = j
  }
  return out
}

/** `[1]` / `[1][2]` / `[1, 2]` in the answer become clickable citation marks. */
function citeHtml(answer: string): string {
  const withMarks = answer.replace(/\[(\d+(?:\s*[,，、]\s*\d+)*)\]/g, (_, list: string) =>
    list.split(/\s*[,，、]\s*/).map((n) => `<sup class="cite" data-n="${n}">${n}</sup>`).join(''))
  return renderMarkdown(withMarks)
}

type Answer = {
  text: string
  citations: Citation[]
  busy: boolean
  error: string | null
  model: string
  ttft: number | null
  took: number | null
}

export default function KbApp({ models }: { models: Model[] }) {
  const embed = readyOf(models, 'embedding')
  const rerank = readyOf(models, 'rerank')
  const ocr = readyOf(models, 'ocr')
  const chat = readyOf(models, 'chat')

  const [kbs, setKbs] = useState<KbInfo[] | null>(null)
  const [kbId, setKbId] = useState<string>('')
  const [docs, setDocs] = useState<KbDoc[]>([])
  const [listErr, setListErr] = useState('')
  const [uploads, setUploads] = useState<{ name: string; error?: string }[]>([])
  const [confirmDrop, setConfirmDrop] = useState(false)

  const [query, setQuery] = useState('')
  const [withAnswer, setWithAnswer] = useState(true)
  const [searching, setSearching] = useState(false)
  const [res, setRes] = useState<SearchResult | null>(null)
  const [searchErr, setSearchErr] = useState('')
  const [active, setActive] = useState<string | null>(null)
  const [preview, setPreview] = useState<KbResult | null>(null)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const abort = useRef<AbortController | null>(null)
  const resultsRef = useRef<HTMLOListElement>(null)

  const current = kbs?.find((k) => k.id === kbId) ?? null

  const refreshKbs = useCallback(async (pick?: string) => {
    try {
      const r = await kb.list()
      setKbs(r.kbs)
      setListErr('')
      setKbId((cur) => pick ?? (r.kbs.some((k) => k.id === cur) ? cur : (r.kbs[0]?.id ?? '')))
    } catch (e) {
      setListErr(errText(e, '读取知识库失败'))
      setKbs((v) => v ?? [])
    }
  }, [])

  useEffect(() => { void refreshKbs() }, [refreshKbs])

  const refreshDocs = useCallback(async () => {
    if (!kbId) { setDocs([]); return }
    try {
      setDocs((await kb.docs(kbId)).docs)
    } catch (e) {
      setListErr(errText(e, '读取文档失败'))
    }
  }, [kbId])

  useEffect(() => { void refreshDocs() }, [refreshDocs])

  // Poll while anything is still being processed; refresh the kb counts when
  // the last one settles.
  const working = docs.some((d) => busyStatus(d.status))
  useEffect(() => {
    if (!working) return
    const t = setInterval(() => { void refreshDocs() }, 1500)
    return () => { clearInterval(t); void refreshKbs() }
  }, [working, refreshDocs, refreshKbs])

  useEffect(() => () => abort.current?.abort(), [])

  const ensureKb = async (): Promise<string> => {
    if (kbId) return kbId
    const r = await kb.create('演示知识库')
    await refreshKbs(r.kb.id)
    return r.kb.id
  }

  const upload = async (files: File[]) => {
    setUploads(files.map((f) => ({ name: f.name })))
    let id: string
    try {
      id = await ensureKb()
    } catch (e) {
      setUploads([{ name: '新建知识库', error: errText(e, '新建失败') }])
      return
    }
    const failed: { name: string; error: string }[] = []
    for (const f of files) {
      try {
        await kb.upload(id, f)
      } catch (e) {
        failed.push({ name: f.name, error: errText(e, '上传失败') })
      }
      setUploads((u) => u.filter((x) => x.name !== f.name))
      if (id === kbId) void refreshDocs()
    }
    setUploads(failed)
    if (id === kbId) void refreshDocs()
  }

  const createKb = async () => {
    const name = window.prompt('知识库名称', `知识库 ${(kbs?.length ?? 0) + 1}`)
    if (!name?.trim()) return
    try {
      const r = await kb.create(name.trim())
      await refreshKbs(r.kb.id)
      setRes(null); setAnswer(null)
    } catch (e) {
      setListErr(errText(e, '新建失败'))
    }
  }

  const dropKb = async () => {
    if (!kbId) return
    try {
      await kb.remove(kbId)
      setConfirmDrop(false); setRes(null); setAnswer(null)
      await refreshKbs('')
    } catch (e) {
      setListErr(errText(e, '删除失败'))
    }
  }

  const ask = async () => {
    const q = query.trim()
    if (!q || !kbId) return
    abort.current?.abort()
    setSearching(true); setSearchErr(''); setActive(null); setAnswer(null)
    let r: SearchResult
    try {
      r = await kb.search(kbId, { query: q, top_k: 5, candidates: 20 })
      setRes(r)
    } catch (e) {
      setSearchErr(errText(e, '检索失败'))
      setSearching(false)
      return
    }
    setSearching(false)
    if (!(withAnswer && chat) || r.results.length === 0) return

    const ctl = new AbortController()
    abort.current = ctl
    const t0 = performance.now()
    const base: Answer = { text: '', citations: [], busy: true, error: null, model: chat.id, ttft: null, took: null }
    setAnswer(base)
    try {
      await kb.answer(kbId, { query: q, chunk_ids: r.results.map((x) => x.chunk_id), model: chat.id },
        { signal: ctl.signal }, {
          citations: (c) => setAnswer((a) => a && { ...a, citations: c }),
          delta: (t) => setAnswer((a) => a && {
            ...a, text: a.text + t, ttft: a.ttft ?? (performance.now() - t0) / 1000,
          }),
        })
      setAnswer((a) => a && { ...a, busy: false, took: (performance.now() - t0) / 1000 })
    } catch (e) {
      const stopped = ctl.signal.aborted
      setAnswer((a) => a && { ...a, busy: false, error: stopped ? '已停止' : errText(e, '生成失败') })
    }
  }

  const stop = () => abort.current?.abort()

  const focusResult = (chunk: string | null) => {
    setActive(chunk)
    if (!chunk) return
    const el = resultsRef.current?.querySelector<HTMLElement>(`[data-chunk="${CSS.escape(chunk)}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  const onCite = (e: React.MouseEvent) => {
    const n = (e.target as HTMLElement).closest<HTMLElement>('sup.cite')?.dataset.n
    if (!n || !answer) return
    const c = answer.citations.find((x) => String(x.n) === n)
    const hit = c && res?.results.find((x) => x.chunk_id === c.chunk_id)
    if (hit) { focusResult(hit.chunk_id); setPreview(hit) }
  }

  const ready = docs.filter((d) => d.status === 'ready').length
  const answerSplit = answer ? splitThinking(answer.text, false) : null
  const answerHtml = useMemo(() => (answerSplit ? citeHtml(answerSplit.answer) : ''), [answerSplit?.answer])

  // The mode the next question runs in, in words.
  const mode = embed && rerank ? '完整混合检索：关键词 + 向量 → 融合 → 精排'
    : embed ? '关键词 + 向量 → 融合（未加载 Reranker，不精排）'
      : rerank ? '关键词检索 → 精排（未加载 Embedding，不做向量检索）'
        : '仅关键词检索（Embedding、Reranker 都未加载）'

  return (
    <div className="kb" data-testid="kb-app">
      <div className="card tight kb-models" data-testid="kb-models">
        <div className="row" style={{ gap: 'var(--s-2)' }}>
          <ModelChip label="Embedding" model={embed} need="建库、向量检索" />
          <ModelChip label="Reranker" model={rerank} need="精排" />
          <ModelChip label="OCR" model={ocr} need="扫描页与图片" />
          <ModelChip label="对话模型" model={chat} need="生成回答" />
        </div>
        <p className="note tight" data-testid="kb-mode">
          当前：<b>{mode}</b>{chat ? '，并用对话模型生成带引用的回答。' : '；未加载对话模型，只返回检索到的原文。'}
          {!(embed && rerank && chat) && (
            <>
              {' '}在 32 GB 的设备上，35B 加载后 NPU 只剩约 1 GiB，放不下 Embedding（1.4 GiB）和 Reranker（1.1 GiB），
              「向量 + 精排」与「生成回答」要分两次演示：先加载辅助模型建库、检索，再换成 35B 提问；
              64 GB 的设备可以四个模型同时加载。
            </>
          )}
        </p>
      </div>

      <div className="kb-grid">
        {/* -- documents -------------------------------------------------- */}
        <section className="card kb-docs" data-testid="kb-docs">
          <div className="row" style={{ marginBottom: 'var(--s-3)' }}>
            <h2 style={{ margin: 0 }}>文档</h2>
            <div className="spacer" />
            {kbs && kbs.length > 0 && (
              <select value={kbId} aria-label="知识库" data-testid="kb-select" className="kb-select"
                      onChange={(e) => { setKbId(e.target.value); setRes(null); setAnswer(null) }}>
                {kbs.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
              </select>
            )}
            <button className="btn ghost sm" onClick={() => void createKb()} data-testid="kb-new">新建</button>
          </div>

          {current && (
            <p className="note tight" data-testid="kb-summary">
              {current.docs} 个文档 · {current.chunks} 个片段
              {current.embedding_model ? ` · 向量：${current.embedding_model}（${current.dims} 维）` : ''}
            </p>
          )}
          {current?.needs_reindex && (
            <div className="kb-warn" data-testid="kb-reindex">
              向量索引与片段不一致，向量检索已停用。
              <button className="btn link" disabled={!embed}
                      onClick={() => void kb.reindex(current.id).then(() => refreshDocs())}>
                用当前 Embedding 重建
              </button>
            </div>
          )}

          <FileDropMany accept={ACCEPT} onFiles={(fs) => void upload(fs)} disabled={uploads.length > 0}
                        testid="kb-upload"
                        hint="TXT / MD / PDF / 图片，单个 ≤ 50 MiB。PDF 没有文字层的页和图片会先走 OCR。" />
          {!embed && (
            <p className="note warn-note" data-testid="kb-need-embed">
              建库需要 Embedding 模型：请先在「模型」页加载 qwen3-embedding-0.6b，否则文档会处理失败。
            </p>
          )}
          {uploads.some((u) => !u.error) && (
            <p className="note"><span className="spin" /> 正在上传 {uploads.filter((u) => !u.error).length} 个文件…</p>
          )}
          {uploads.filter((u) => u.error).map((u) => (
            <p key={u.name} className="err-text">{u.name}：{u.error}</p>
          ))}
          {listErr && <p className="err-text">{listErr}</p>}

          {docs.length === 0 ? (
            <div className="empty" data-testid="kb-docs-empty">
              <strong>知识库还是空的</strong>
              拖入几份文档试试：制度、手册、扫描件或截图都可以。处理完成后在右边提问。
            </div>
          ) : (
            <ul className="kb-doclist" data-testid="kb-doclist">
              {docs.map((d) => (
                <li key={d.id} data-testid={`kb-doc-${d.status}`}>
                  <span className="kb-type" aria-hidden="true">{TYPE_LABEL[d.type]}</span>
                  <div className="kb-doc-main">
                    <div className="kb-doc-name" title={d.name}>{d.name}</div>
                    <div className="kb-doc-meta">
                      {d.type === 'pdf' || d.type === 'image' ? `${d.pages} 页 · ` : ''}
                      {d.chunks} 个片段
                      {d.ocr_pages > 0 && ` · OCR ${d.ocr_pages} 页`}
                      {` · ${fmtBytes(d.bytes)}`}
                    </div>
                    {busyStatus(d.status) && d.progress && (
                      <div className="bar kb-doc-bar" role="progressbar" aria-valuemin={0}
                           aria-valuemax={d.progress.total} aria-valuenow={d.progress.done}>
                        <span style={{ width: `${d.progress.total ? (d.progress.done / d.progress.total) * 100 : 0}%` }} />
                      </div>
                    )}
                    {d.status === 'failed' && d.error && <div className="err-text kb-doc-err">{d.error}</div>}
                    {d.warnings.map((w, i) => <div key={i} className="note tight warn-note">{w}</div>)}
                  </div>
                  <div className="kb-doc-side">
                    <span className={`pill ${d.status === 'ready' ? 'ok' : d.status === 'failed' ? 'err' : 'warn'}`}>
                      {busyStatus(d.status) ? <span className="spin" /> : <span className="dot" />}
                      {STATUS_LABEL[d.status]}
                      {busyStatus(d.status) && d.progress && d.progress.total > 1 && ` ${d.progress.done}/${d.progress.total}`}
                    </span>
                    <div className="row kb-doc-actions">
                      {d.status === 'failed' && (
                        <button className="btn link" onClick={() => void kb.retryDoc(kbId, d.id).then(refreshDocs)}>重试</button>
                      )}
                      <a className="kb-link" href={kb.fileUrl(kbId, d.id)} target="_blank" rel="noreferrer">原文</a>
                      <button className="btn link" aria-label={`删除 ${d.name}`}
                              onClick={() => void kb.removeDoc(kbId, d.id).then(() => { void refreshDocs(); void refreshKbs() })}>
                        删除
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {current && (
            confirmDrop ? (
              <div className="confirm" style={{ marginTop: 'var(--s-4)' }}>
                <span className="note">删除「{current.name}」和其中 {current.docs} 个文档，不能恢复。</span>
                <div className="row">
                  <button className="btn danger-solid sm" onClick={() => void dropKb()} data-testid="kb-drop-confirm">删除</button>
                  <button className="btn ghost sm" onClick={() => setConfirmDrop(false)}>取消</button>
                </div>
              </div>
            ) : (
              <button className="btn link kb-drop" onClick={() => setConfirmDrop(true)} data-testid="kb-drop">删除这个知识库</button>
            )
          )}
        </section>

        {/* -- question & answer ------------------------------------------ */}
        <section className="kb-qa">
          <div className="card">
            <form className="kb-ask" onSubmit={(e) => { e.preventDefault(); void ask() }}>
              <input value={query} onChange={(e) => setQuery(e.target.value)} data-testid="kb-query"
                     placeholder={ready ? '针对这些文档提一个问题，例如：盘点差异超过多少需要复核？' : '先上传文档，处理完成后在这里提问'}
                     aria-label="问题" />
              {answer?.busy
                ? <button type="button" className="btn ghost" onClick={stop} data-testid="kb-stop">停止</button>
                : (
                  <button className="btn" type="submit" data-testid="kb-ask"
                          disabled={!query.trim() || !ready || searching}>
                    {searching ? <><span className="spin" /> 检索中…</> : chat && withAnswer ? '检索并回答' : '检索'}
                  </button>
                )}
            </form>
            <label className="field inline kb-answer-toggle">
              <input type="checkbox" checked={withAnswer && !!chat} disabled={!chat}
                     onChange={(e) => setWithAnswer(e.target.checked)} data-testid="kb-with-answer" />
              用对话模型生成回答{chat ? `（${chat.display_name}）` : '（未加载对话模型）'}
            </label>
            {searchErr && <p className="err-text" data-testid="kb-error">{searchErr}</p>}

            {answer && (
              <div className="kb-answer" data-testid="kb-answer">
                <div className="row kb-answer-head">
                  <h3 style={{ margin: 0 }}>回答</h3>
                  <span className="note">
                    {answer.busy && !answer.text ? '等待首字…' : ''}
                    {answer.ttft !== null && `首字 ${answer.ttft.toFixed(1)} s`}
                    {answer.took !== null && ` · 共 ${answer.took.toFixed(1)} s`}
                  </span>
                </div>
                {answerSplit?.answer
                  ? <div className="md kb-answer-body" onClick={onCite} dangerouslySetInnerHTML={{ __html: answerHtml }} />
                  : answer.busy && <p className="muted"><span className="spin" /> 正在根据 {res?.results.length ?? 0} 条资料生成…</p>}
                {answer.error && <p className={answer.error === '已停止' ? 'note' : 'err-text'}>{answer.error}</p>}
                {answer.citations.length > 0 && (
                  <p className="note tight">
                    资料：{answer.citations.map((c) => `[${c.n}] ${c.doc_name ?? ''}${c.page ? ` 第 ${c.page} 页` : ''}`).join('　')}
                  </p>
                )}
              </div>
            )}
          </div>

          {res ? (
            <>
              <div className="kb-stages" data-testid="kb-stages">
                {(['bm25', 'vector', 'fusion', 'rerank'] as StageName[]).map((s, i) => {
                  const st = res.stages[s]
                  const okStage = st?.status === 'ok'
                  return (
                    <div key={s} className={`kb-stage${okStage ? '' : ' off'}`} data-testid={`kb-stage-${s}`}
                         title={STAGE_HINT[s]}>
                      <div className="kb-stage-name"><span className="kb-stage-no">{i + 1}</span>{STAGE_LABEL[s]}</div>
                      {okStage ? (
                        <div className="kb-stage-val">
                          <b>{st.hits.length}</b> 条 · {st.ms < 10 ? st.ms.toFixed(1) : st.ms.toFixed(0)} ms
                        </div>
                      ) : (
                        <div className="kb-stage-val">已跳过</div>
                      )}
                      <div className="kb-stage-note">
                        {okStage ? (s === 'vector' && res.models.embedding) || (s === 'rerank' && res.models.rerank) || STAGE_HINT[s] : st?.reason}
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="card">
                <div className="chart-head">
                  <span className="chart-title">每一步的名次</span>
                  <span className="chart-unit">名次（1 最相关）· 共 {res.timings.total_ms.toFixed(0)} ms</span>
                </div>
                <RankFlow res={res} active={active} onActive={focusResult} />
              </div>

              <div className="card">
                <h2>检索结果</h2>
                {res.results.length === 0 ? (
                  <div className="empty"><strong>没有找到相关片段</strong>换个说法，或确认文档已经处理完成。</div>
                ) : (
                  <ol className="kb-results" ref={resultsRef} data-testid="kb-results">
                    {res.results.map((r) => {
                      const cite = answer?.citations.find((c) => c.chunk_id === r.chunk_id)
                      return (
                        <li key={r.chunk_id} data-chunk={r.chunk_id}
                            className={active === r.chunk_id ? 'on' : ''}
                            onMouseEnter={() => setActive(r.chunk_id)}>
                          <span className="kb-rank">{r.rank}</span>
                          <div className="kb-result-main">
                            <div className="kb-result-src">
                              {cite && <span className="cite-tag">[{cite.n}]</span>}
                              <b>{r.doc_name}</b>
                              {r.page ? ` · 第 ${r.page} 页` : ''}
                              <span className={`pill ${r.source === 'ocr' ? 'warn' : ''}`}>{r.source === 'ocr' ? 'OCR' : '文字层'}</span>
                            </div>
                            <p className="kb-result-text">{highlight(r.text, res.query)}</p>
                            <div className="kb-scores">
                              <Score label="BM25" v={r.scores.bm25} rank={r.scores.bm25_rank} digits={2} />
                              <Score label="向量" v={r.scores.vector} rank={r.scores.vector_rank} digits={3} />
                              <Score label="RRF" v={r.scores.rrf} rank={r.scores.rrf_rank} digits={4} />
                              {r.scores.rerank !== null && (
                                <span className="kb-score kb-score-rr" title="Reranker 相关度（0–1）">
                                  精排
                                  <span className="score-track"><span className="score-fill" style={{ width: `${Math.max(1, r.scores.rerank * 100)}%` }} /></span>
                                  <b>{r.scores.rerank.toFixed(3)}</b>
                                </span>
                              )}
                              <div className="spacer" />
                              <button className="btn link" onClick={() => setPreview(r)} data-testid="kb-preview-open">查看原文位置</button>
                            </div>
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                )}
              </div>
            </>
          ) : (
            <div className="card">
              <div className="empty" data-testid="kb-results-empty">
                <strong>提一个问题，看检索是怎么一步步找到答案的</strong>
                结果下方会画出每个片段在「关键词 → 向量 → 融合 → 精排」四步中的名次变化，
                点任意一条结果可以跳到它在原文中的位置。
              </div>
            </div>
          )}
        </section>
      </div>

      {preview && <Preview kbId={kbId} r={preview} query={res?.query ?? ''} onClose={() => setPreview(null)} />}
    </div>
  )
}

function Score({ label, v, rank, digits }: { label: string; v: number | null; rank: number | null; digits: number }) {
  if (v === null) return <span className="kb-score muted">{label} —</span>
  return (
    <span className="kb-score" title={`${label} 分数 ${v}，第 ${rank} 名`}>
      {label} <b>{v.toFixed(digits)}</b>{rank !== null && <span className="muted"> #{rank}</span>}
    </span>
  )
}

/** The passage where it came from: the page image with its OCR lines boxed, or
 *  for a text-layer page, the page image beside the passage text. */
function Preview({ kbId, r, query, onClose }: { kbId: string; r: KbResult; query: string; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  const [imgErr, setImgErr] = useState(false)
  const src = r.page ? kb.pageUrl(kbId, r.doc_id, r.page) : null
  return (
    <div className="modal-scrim" onClick={onClose} data-testid="kb-preview">
      <div className="modal card" role="dialog" aria-modal="true" aria-label="原文位置"
           onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 'var(--s-3)' }}>
          <h2 style={{ margin: 0 }}>{r.doc_name}{r.page ? ` · 第 ${r.page} 页` : ''}</h2>
          <div className="spacer" />
          <a className="btn ghost sm" href={kb.fileUrl(kbId, r.doc_id)} target="_blank" rel="noreferrer">打开原文件</a>
          <button className="btn ghost sm" onClick={onClose} autoFocus>关闭</button>
        </div>
        <div className={src && !imgErr ? 'modal-grid' : ''}>
          {src && !imgErr && (
            <div className="modal-page">
              {r.boxes.length > 0
                ? <OcrOverlay src={src} boxes={r.boxes} show active={null} onActive={() => undefined} />
                : <img src={src} alt={`第 ${r.page} 页`} onError={() => setImgErr(true)} />}
              <p className="note tight">
                {r.boxes.length > 0 ? `框出的是这个片段覆盖的 ${r.boxes.length} 行 OCR 结果。` : '这一页来自 PDF 文字层，右边是匹配的片段。'}
              </p>
            </div>
          )}
          <div className="modal-text">
            <h3 style={{ marginTop: 0 }}>片段 #{r.rank}</h3>
            <p className="kb-result-text full">{highlight(r.text, query)}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
