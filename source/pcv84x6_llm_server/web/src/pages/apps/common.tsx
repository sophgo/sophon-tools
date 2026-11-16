import { useRef, useState, type ReactNode } from 'react'
import type { Model, ModelKind } from '../../api'

/* Small pieces the three demo apps share. */

export function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback
}

/** The first model of `kind` that is loaded and idle, i.e. one a request would
 *  be admitted to right now. */
export function readyOf(models: Model[], kind: ModelKind): Model | null {
  return models.find((m) => (m.kind ?? 'chat') === kind && m.loaded && !m.operation) ?? null
}

export function readyAll(models: Model[], kind: ModelKind): Model[] {
  return models.filter((m) => (m.kind ?? 'chat') === kind && m.loaded && !m.operation)
}

/** Whether a model the app needs is loaded, and what it is needed for. The dot
 *  plus the word carry the state, so it is never colour alone. */
export function ModelChip({ label, model, need }: { label: string; model: Model | null; need: string }) {
  return (
    <span className={`model-chip${model ? ' on' : ''}`} title={model ? model.id : `未加载 · 用于${need}`}
          data-testid={`chip-${label}`}>
      <span className="dot" aria-hidden="true" />
      <b>{label}</b>
      <span className="model-chip-state">{model ? model.display_name : `未加载 · ${need}`}</span>
    </span>
  )
}

/** A file well for several files at once: click to pick, or drop them on it. */
export function FileDropMany({ accept, onFiles, hint, testid, disabled, multiple = true, children }: {
  accept: string; onFiles: (f: File[]) => void; hint: string; testid: string
  disabled?: boolean; multiple?: boolean; children?: ReactNode
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div className={`dropzone${over ? ' over' : ''}`} data-testid={testid}
         onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true) }}
         onDragLeave={() => setOver(false)}
         onDrop={(e) => {
           e.preventDefault(); setOver(false)
           const fs = [...(e.dataTransfer.files ?? [])]
           if (fs.length && !disabled) onFiles(multiple ? fs : fs.slice(0, 1))
         }}>
      <input ref={ref} type="file" accept={accept} multiple={multiple} data-testid={`${testid}-input`}
             onChange={(e) => {
               const fs = [...(e.target.files ?? [])]
               if (fs.length) onFiles(fs)
               e.target.value = ''
             }} />
      {children}
      <div className="row dropzone-bar">
        <button className="btn ghost sm" disabled={disabled} onClick={() => ref.current?.click()}>
          {multiple ? '选择文件' : '选择文件'}
        </button>
        <span className="note">{hint}</span>
      </div>
    </div>
  )
}

export function download(name: string, text: string, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function baseName(name: string): string {
  return name.replace(/\.[^.]+$/, '') || name
}
