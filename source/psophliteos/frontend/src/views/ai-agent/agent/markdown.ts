import { marked } from 'marked';
import DOMPurify from 'dompurify';

// 渲染 markdown → 安全 HTML。AI 内容不可信，一律经 DOMPurify 消毒。
export function renderMarkdownToHtml(content: string): string {
  try {
    const raw = marked.parse(content || '', { async: false }) as string;
    return DOMPurify.sanitize(raw, { ADD_ATTR: ['target', 'rel'] });
  } catch (e) {
    return escapeHtml(content || '');
  }
}

export function escapeHtml(str: string): string {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
