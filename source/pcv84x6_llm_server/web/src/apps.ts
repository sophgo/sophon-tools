/* The demo apps' API (MYS-2606 knowledge base, MYS-2607 streaming ASR).

   Both live under /api/apps/* behind the admin cookie, like /api/test/*. The
   shapes below are the backends' contracts (docs/kb-app.md, docs/aux-models.md);
   fields a later backend adds are optional here so an older server still
   renders. */

import type { OcrBox } from './api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: 'same-origin',
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new Error(await errorDetail(r))
  return r.json() as Promise<T>
}

async function errorDetail(r: Response): Promise<string> {
  const t = await r.text().catch(() => '')
  try {
    const j = JSON.parse(t)
    if (typeof j.detail === 'string') return j.detail
    if (j.detail) return JSON.stringify(j.detail)
  } catch { /* plain text */ }
  return t || `${r.status} ${r.statusText}`
}

/** Read an SSE body frame by frame; `onFrame` gets each `data:` payload. */
async function readSse(r: Response, onFrame: (data: string) => boolean | void): Promise<void> {
  if (!r.body) return
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let cut: number
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, cut)
      buf = buf.slice(cut + 2)
      const data = block.split('\n').filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trimStart()).join('\n')
      if (data && onFrame(data) === false) { await reader.cancel().catch(() => undefined); return }
    }
  }
}

// -- knowledge base ------------------------------------------------------------

export type KbInfo = {
  id: string
  name: string
  created_at: number
  docs: number
  chunks: number
  embedding_model: string | null
  dims: number | null
  needs_reindex?: boolean
}

export type DocStatus = 'queued' | 'parsing' | 'ocr' | 'embedding' | 'ready' | 'failed'

export type KbDoc = {
  id: string
  name: string
  type: 'txt' | 'md' | 'pdf' | 'image'
  bytes: number
  pages: number
  status: DocStatus
  progress: { stage: string; done: number; total: number } | null
  error: string | null
  warnings: string[]
  chunks: number
  text_pages: number
  ocr_pages: number
  created_at: number
}

export type StageName = 'bm25' | 'vector' | 'fusion' | 'rerank'

export type Stage = {
  status: 'ok' | 'skipped'
  reason: string | null
  ms: number
  hits: { chunk_id: string; rank: number; score: number }[]
}

export type KbResult = {
  rank: number
  chunk_id: string
  doc_id: string
  doc_name: string
  page: number | null
  source: 'text' | 'ocr'
  text: string
  boxes: OcrBox[]
  scores: {
    bm25: number | null; bm25_rank: number | null
    vector: number | null; vector_rank: number | null
    rrf: number | null; rrf_rank: number | null
    rerank: number | null
  }
}

export type SearchResult = {
  query: string
  models: { embedding: string | null; rerank: string | null }
  stages: Record<StageName, Stage>
  results: KbResult[]
  timings: { total_ms: number }
}

export type Citation = { n: number; chunk_id: string; doc_name?: string; page?: number | null }

const KB = '/api/apps/kb'
const enc = encodeURIComponent

export const kb = {
  list: () => req<{ kbs: KbInfo[] }>(KB),
  create: (name: string) => req<{ kb: KbInfo }>(KB, { method: 'POST', body: JSON.stringify({ name }) }),
  remove: (id: string) => req<{ ok: boolean }>(`${KB}/${enc(id)}`, { method: 'DELETE' }),
  reindex: (id: string) => req<{ ok: boolean }>(`${KB}/${enc(id)}/reindex`, { method: 'POST' }),
  docs: (id: string) => req<{ docs: KbDoc[] }>(`${KB}/${enc(id)}/docs`),
  /** One file per request: the body cap is per request, not per file. */
  upload: (id: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    return req<{ docs: KbDoc[] }>(`${KB}/${enc(id)}/docs`, { method: 'POST', body: fd })
  },
  removeDoc: (id: string, doc: string) =>
    req<{ ok: boolean }>(`${KB}/${enc(id)}/docs/${enc(doc)}`, { method: 'DELETE' }),
  retryDoc: (id: string, doc: string) =>
    req<{ ok: boolean }>(`${KB}/${enc(id)}/docs/${enc(doc)}/retry`, { method: 'POST' }),
  pageUrl: (id: string, doc: string, page: number) =>
    `${KB}/${enc(id)}/docs/${enc(doc)}/pages/${page}.png`,
  fileUrl: (id: string, doc: string) => `${KB}/${enc(id)}/docs/${enc(doc)}/file`,
  search: (id: string, body: {
    query: string; top_k?: number; candidates?: number
    use_bm25?: boolean; use_vector?: boolean; use_rerank?: boolean
  }) => req<SearchResult>(`${KB}/${enc(id)}/search`, { method: 'POST', body: JSON.stringify(body) }),

  /** Stream a cited answer. Frames are OpenAI chat chunks plus one
   *  `{type: "citations"}` frame, which this server sends first. */
  answer: async (id: string, body: { query: string; chunk_ids: string[]; model?: string },
                 opts: { signal?: AbortSignal },
                 on: { citations: (c: Citation[]) => void; delta: (t: string) => void }) => {
    const r = await fetch(`${KB}/${enc(id)}/answer`, {
      method: 'POST', credentials: 'same-origin', signal: opts.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(await errorDetail(r))
    const out = { completion_tokens: 0, finish_reason: null as string | null }
    let failure: string | null = null
    await readSse(r, (data) => {
      if (data === '[DONE]') return false
      let f: any
      try { f = JSON.parse(data) } catch { return }
      if (f.type === 'citations') { on.citations(f.items ?? []); return }
      if (f.error) { failure = f.error.message ?? String(f.error); return false }
      const ch = f.choices?.[0]
      if (ch?.delta?.content) on.delta(ch.delta.content)
      if (ch?.finish_reason) out.finish_reason = ch.finish_reason
      if (f.usage) out.completion_tokens = f.usage.completion_tokens ?? 0
    })
    if (failure) throw new Error(failure)
    return out
  },
}

// -- streaming transcription ----------------------------------------------------

export type AsrMeta = { duration: number; segments_total: number; segment_seconds: number; language: string | null }
export type AsrSegment = { id: number; start: number; end: number; text: string; infer_ms: number }
export type AsrDone = {
  text: string; language: string | null; duration: number; infer_seconds: number
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
}

/** POST the upload and relay frames as they arrive. Refusals (415/400/409/429)
 *  come back as a status before any frame; a failure mid-stream is an
 *  `error` frame, raised here. */
export async function transcribeStream(
  file: File | Blob, filename: string,
  opts: { model: string; language?: string; prompt?: string; signal?: AbortSignal },
  on: { meta: (m: AsrMeta) => void; segment: (s: AsrSegment) => void; done: (d: AsrDone) => void },
): Promise<void> {
  const fd = new FormData()
  fd.append('model', opts.model)
  fd.append('file', file, filename)
  if (opts.language) fd.append('language', opts.language)
  if (opts.prompt) fd.append('prompt', opts.prompt)
  const r = await fetch('/api/apps/asr/transcriptions/stream', {
    method: 'POST', credentials: 'same-origin', body: fd, signal: opts.signal,
  })
  if (!r.ok) throw new Error(await errorDetail(r))
  let failure: string | null = null
  await readSse(r, (data) => {
    let f: any
    try { f = JSON.parse(data) } catch { return }
    if (f.type === 'meta') on.meta(f)
    else if (f.type === 'segment') on.segment(f)
    else if (f.type === 'done') { on.done(f); return false }
    else if (f.type === 'error') { failure = f.detail || '转写失败'; return false }
  })
  if (failure) throw new Error(failure)
}
