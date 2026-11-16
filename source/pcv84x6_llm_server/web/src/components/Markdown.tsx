import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/* Model output is untrusted text: it is rendered as Markdown, then sanitized
   before it reaches the DOM. Two extra rules on top of DOMPurify's defaults:

   - No <img>. The board is usually offline, and a remote image in an answer
     would make the operator's browser fetch a URL the model made up. The alt
     text stays in place so nothing the model said disappears.
   - Links open in a new tab, so following one never drops the conversation. */
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const renderer = new marked.Renderer()
renderer.image = ({ text }) => (text ? `[${escapeHtml(text)}]` : '')

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Markdown → sanitized HTML. `breaks` keeps a single newline as a line break:
 *  Chinese answers routinely put list items and short lines on bare newlines,
 *  and folding them into one paragraph would misquote the model. */
export function renderMarkdown(src: string): string {
  const html = marked.parse(src, { gfm: true, breaks: true, async: false, renderer }) as string
  return DOMPurify.sanitize(html, { FORBID_TAGS: ['img', 'style', 'form', 'input', 'button'] })
}

export type ThinkSplit = { reasoning: string | null; answer: string; thinkingOpen: boolean }

/** Split a Qwen-style answer into its reasoning and the answer proper.
 *
 *  With thinking on, the chat template already opened `<think>`, so the stream
 *  is `reasoning</think>answer`; a stray leading `<think>` is tolerated. Until
 *  `</think>` arrives, everything so far is reasoning. With thinking off the
 *  template inserts an empty think block and the text is all answer. */
export function splitThinking(text: string, thinking: boolean): ThinkSplit {
  const close = text.indexOf('</think>')
  if (close >= 0) {
    const reasoning = text.slice(0, close).replace(/^\s*<think>/, '').trim()
    return { reasoning: reasoning || null, answer: text.slice(close + 8).replace(/^\s+/, ''), thinkingOpen: false }
  }
  if (thinking || /^\s*<think>/.test(text)) {
    return { reasoning: text.replace(/^\s*<think>/, '').trim(), answer: '', thinkingOpen: true }
  }
  return { reasoning: null, answer: text, thinkingOpen: false }
}

export default function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => renderMarkdown(text), [text])
  return <div className={`md ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: html }} />
}
