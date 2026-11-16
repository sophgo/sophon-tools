import { kindOf, type ModelKind } from '../api'

/** The model page's sub-tabs, one per family an operator thinks in.
 *
 *  OCR holds both recognisers: PP-OCR (`ocr`, boxes + lines) and PaddleOCR-VL
 *  (`ocr_vl`, a vision chat model). They answer the same question ("what does
 *  this image say?"), so splitting them would put one model on each tab. */
export type KindTab = 'chat' | 'embedding' | 'rerank' | 'asr' | 'ocr'

export const KIND_TABS: { id: KindTab; label: string; kinds: ModelKind[]; blurb: string }[] = [
  { id: 'chat', label: '大语言模型', kinds: ['chat'],
    blurb: '对话、视觉理解与函数调用，走 /v1/chat/completions。' },
  { id: 'embedding', label: 'Embedding', kinds: ['embedding'],
    blurb: '把文本编码成向量，用于检索与聚类，走 /v1/embeddings。' },
  { id: 'rerank', label: 'Reranker', kinds: ['rerank'],
    blurb: '给「查询 + 候选文档」逐对打分并排序，走 /v1/rerank（Jina/Cohere 格式）。' },
  { id: 'asr', label: '语音识别', kinds: ['asr'],
    blurb: '音频转文字，走 /v1/audio/transcriptions（OpenAI 格式）。' },
  { id: 'ocr', label: 'OCR', kinds: ['ocr', 'ocr_vl'],
    blurb: '图片文字识别：PP-OCR 给逐行文本与检测框，走 /v1/ocr；PaddleOCR-VL 还能识别表格（含合并单元格）、公式与图表，走 /v1/chat/completions（与官方 vLLM 服务的调用方式相同）。' },
]

export function tabOf(kind: ModelKind): KindTab {
  return KIND_TABS.find((t) => t.kinds.includes(kind))?.id ?? 'chat'
}

export function tabOfModel(m: { kind?: string | null }): KindTab {
  return tabOf(kindOf(m))
}

/** Short label for one kind, for pills and the playground's model list. */
export const KIND_LABEL: Record<ModelKind, string> = {
  chat: '大语言模型',
  embedding: 'Embedding',
  rerank: 'Reranker',
  asr: '语音识别',
  ocr: 'OCR',
  ocr_vl: 'OCR-VL',
}

/** The /v1 route a kind is served on, as the docs page names it. */
export const KIND_ROUTE: Record<ModelKind, string> = {
  chat: '/v1/chat/completions',
  embedding: '/v1/embeddings',
  rerank: '/v1/rerank',
  asr: '/v1/audio/transcriptions',
  ocr: '/v1/ocr',
  ocr_vl: '/v1/chat/completions',
}
