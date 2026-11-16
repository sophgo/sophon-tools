import { useEffect, useMemo, useRef, useState } from 'react'
import { fmtBytes, type Model } from '../../api'
import { transcribeStream, type AsrDone, type AsrMeta, type AsrSegment } from '../../apps'
import { fmtClock, SegmentTimeline } from '../../components/TestViz'
import { baseName, download, errText, FileDropMany, readyAll } from './common'

/* 语音转写 (MYS-2607's streaming endpoint). The transcript is the page: it
   grows a paragraph per ~30 s segment while the audio is still being worked
   on, each paragraph is a seek target, and the one under the playhead is
   marked. Recording is offered only where the browser allows the microphone
   (HTTPS or localhost) -- the console is usually plain HTTP on a LAN, where
   getUserMedia does not exist, so the page says so instead of failing. */

const LANGUAGES: [string, string][] = [
  ['', '自动识别'], ['zh', '中文'], ['en', '英语'], ['yue', '粤语'], ['ja', '日语'],
  ['ko', '韩语'], ['fr', '法语'], ['de', '德语'], ['es', '西班牙语'], ['ru', '俄语'],
]
const ACCEPT = 'audio/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac,.webm'

type Source = { blob: Blob; name: string; recorded: boolean }

function srtTime(s: number): string {
  const ms = Math.round(s * 1000)
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const sec = Math.floor((ms % 60000) / 1000)
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${p(h)}:${p(m)}:${p(sec)},${p(ms % 1000, 3)}`
}

function toSrt(segs: AsrSegment[]): string {
  return segs.filter((s) => s.text.trim())
    .map((s, i) => `${i + 1}\n${srtTime(s.start)} --> ${srtTime(s.end)}\n${s.text.trim()}\n`).join('\n')
}

export default function AsrApp({ models }: { models: Model[] }) {
  const asr = readyAll(models, 'asr')
  const [modelId, setModelId] = useState('')
  const model = asr.find((m) => m.id === modelId) ?? asr[0] ?? null

  const [src, setSrc] = useState<Source | null>(null)
  const [language, setLanguage] = useState('')
  const [prompt, setPrompt] = useState('')
  const [meta, setMeta] = useState<AsrMeta | null>(null)
  const [segs, setSegs] = useState<AsrSegment[]>([])
  const [done, setDone] = useState<AsrDone | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [t0, setT0] = useState<number | null>(null)
  const [now, setNow] = useState(0)
  const [pos, setPos] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)
  const audio = useRef<HTMLAudioElement>(null)
  const abort = useRef<AbortController | null>(null)

  const url = useMemo(() => (src ? URL.createObjectURL(src.blob) : null), [src])
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  useEffect(() => () => abort.current?.abort(), [])

  // A clock for the elapsed / real-time figures while a run is in flight.
  useEffect(() => {
    if (!busy) return
    const t = setInterval(() => setNow(performance.now()), 250)
    return () => clearInterval(t)
  }, [busy])

  const reset = () => { setMeta(null); setSegs([]); setDone(null); setErr(''); setPos(null) }

  const run = async () => {
    if (!src || !model) return
    abort.current?.abort()
    const ctl = new AbortController()
    abort.current = ctl
    reset()
    setBusy(true)
    const start = performance.now()
    setT0(start); setNow(start)
    try {
      await transcribeStream(src.blob, src.name,
        { model: model.id, language, prompt: prompt.trim(), signal: ctl.signal },
        {
          meta: setMeta,
          segment: (s) => setSegs((v) => [...v, s]),
          done: (d) => setDone(d),
        })
    } catch (e) {
      if (!ctl.signal.aborted) setErr(errText(e, '转写失败'))
    } finally {
      setNow(performance.now())
      setBusy(false)
    }
  }

  const stop = () => abort.current?.abort()

  const seek = (t: number) => {
    const a = audio.current
    if (!a) return
    a.currentTime = t
    void a.play().catch(() => undefined)
  }

  const text = done?.text ?? segs.map((s) => s.text.trim()).filter(Boolean).join('\n')
  const elapsed = t0 !== null ? ((busy ? now : now) - t0) / 1000 : 0
  const audioDone = segs.length ? segs[segs.length - 1].end : 0
  const rtf = elapsed > 0 && audioDone > 0 ? audioDone / elapsed : null
  const total = meta?.segments_total ?? 0
  const activeSeg = pos === null ? -1 : segs.findIndex((s) => pos >= s.start && pos < s.end)
  const stopped = !busy && meta && !done && !err

  // Segments still to come, as placeholders, so the shape of the whole
  // transcript is visible from the first frame.
  const pending = meta ? Array.from({ length: Math.max(0, total - segs.length) }, (_, i) => {
    const k = segs.length + i
    const s = k * meta.segment_seconds
    return { k, start: s, end: Math.min(meta.duration, s + meta.segment_seconds) }
  }) : []

  return (
    <div className="asr" data-testid="asr-app">
      <div className="grid asr-grid">
        <section className="card asr-input" data-testid="asr-input">
          <h2>音频</h2>
          <div className="stack" style={{ gap: 'var(--s-3)' }}>
            <label className="field">
              模型
              {asr.length > 0 ? (
                <select value={model?.id ?? ''} disabled={busy} onChange={(e) => setModelId(e.target.value)}
                        data-testid="asr-model">
                  {asr.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
                </select>
              ) : (
                <span className="err-text" data-testid="asr-no-model">没有已加载的语音识别模型，请先在「模型」页加载 qwen3-asr-0.6b 或 1.7b。</span>
              )}
            </label>
            <div className="grid c2" style={{ gap: 'var(--s-3)' }}>
              <label className="field">
                语言
                <select value={language} disabled={busy} onChange={(e) => setLanguage(e.target.value)}
                        data-testid="asr-lang">
                  {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label className="field" title="作为上下文交给模型，例如专有名词">
                提示词（可选）
                <input value={prompt} disabled={busy} placeholder="例如：CV84X6、PicoClaw"
                       onChange={(e) => setPrompt(e.target.value)} data-testid="asr-hint" />
              </label>
            </div>
            <FileDropMany accept={ACCEPT} multiple={false} disabled={busy} testid="asr-drop"
                          onFiles={([f]) => { setSrc({ blob: f, name: f.name, recorded: false }); reset() }}
                          hint={src ? `${src.name} · ${fmtBytes(src.blob.size)}` : 'WAV / MP3 / M4A / FLAC / OGG，≤ 50 MB、≤ 30 分钟'}>
              {url && (
                <audio ref={audio} src={url} controls preload="metadata" className="audio" data-testid="asr-player"
                       onTimeUpdate={(e) => setPos(e.currentTarget.currentTime)} onEnded={() => setPos(null)} />
              )}
            </FileDropMany>
            <Recorder disabled={busy} onDone={(b) => { setSrc({ blob: b, name: 'recording.webm', recorded: true }); reset() }} />
            <div className="row">
              {busy
                ? <button className="btn ghost" onClick={stop} data-testid="asr-stop">停止</button>
                : <button className="btn" onClick={() => void run()} disabled={!src || !model} data-testid="asr-start">
                    开始转写
                  </button>}
              <span className="note">每段约 30 秒，转完一段就显示一段；中途停止，已转的部分保留。</span>
            </div>
          </div>
        </section>

        <section className="card asr-out" data-testid="asr-out">
          <div className="row" style={{ marginBottom: 'var(--s-2)' }}>
            <h2 style={{ margin: 0 }}>转写稿</h2>
            <div className="spacer" />
            {text && (
              <>
                <button className="btn ghost sm" data-testid="asr-copy"
                        onClick={() => void navigator.clipboard?.writeText(text).then(() => {
                          setCopied(true); setTimeout(() => setCopied(false), 1500)
                        }).catch(() => undefined)}>
                  {copied ? '已复制' : '复制'}
                </button>
                <button className="btn ghost sm" data-testid="asr-txt"
                        onClick={() => download(`${baseName(src?.name ?? 'transcript')}.txt`, text + '\n')}>TXT</button>
                <button className="btn ghost sm" data-testid="asr-srt"
                        onClick={() => download(`${baseName(src?.name ?? 'transcript')}.srt`, toSrt(segs), 'application/x-subrip')}>SRT</button>
              </>
            )}
          </div>

          {meta ? (
            <>
              <div className="asr-progress" data-testid="asr-progress">
                <div className="asr-stats">
                  <span><b className="metric small">{segs.length}</b> / {total} 段</span>
                  <span>音频 <b>{fmtClock(audioDone)}</b> / {fmtClock(meta.duration)}</span>
                  <span>用时 <b>{elapsed.toFixed(1)}</b> s</span>
                  {rtf !== null && <span data-testid="asr-rtf"><b>{rtf.toFixed(1)}×</b> 实时</span>}
                  {done?.language && <span>语言 <b>{done.language}</b></span>}
                </div>
                <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={segs.length}>
                  <span style={{ width: `${total ? (segs.length / total) * 100 : 0}%` }} />
                </div>
                {stopped && <p className="note tight">已停止：保留了前 {segs.length} 段。</p>}
              </div>
              <SegmentTimeline segments={segs.map((s) => ({ id: s.id, start: s.start, end: s.end, text: s.text }))}
                               duration={meta.duration} position={pos} onSeek={seek} />
              <ol className="asr-doc" data-testid="asr-doc">
                {segs.map((s, i) => (
                  <li key={s.id} className={i === activeSeg ? 'on' : ''}>
                    <button className="btn link mono asr-ts" onClick={() => seek(s.start)} title="从这里播放">
                      {fmtClock(s.start)}
                    </button>
                    <p>{s.text.trim() || <span className="muted">（这一段没有识别出语音）</span>}</p>
                  </li>
                ))}
                {busy && pending.map((p, i) => (
                  <li key={`p${p.k}`} className="pending" aria-hidden={i > 0}>
                    <span className="mono asr-ts muted">{fmtClock(p.start)}</span>
                    <p className="muted">{i === 0 ? <><span className="spin" /> 正在转写 {fmtClock(p.start)}–{fmtClock(p.end)}</> : '…'}</p>
                  </li>
                )).slice(0, 3)}
              </ol>
            </>
          ) : busy ? (
            <p className="muted"><span className="spin" /> 正在解码音频…</p>
          ) : (
            <div className="empty" data-testid="asr-empty">
              <strong>选择或录制一段音频，开始转写</strong>
              全程在本机 NPU 上完成，音频不会离开这台设备。转好的部分可以点时间跳到对应位置播放，
              也可以导出成 TXT 或 SRT 字幕。
            </div>
          )}
          {err && <p className="err-text" data-testid="asr-error">{err}</p>}
        </section>
      </div>
    </div>
  )
}

/** Microphone capture, where the browser allows it. */
function Recorder({ disabled, onDone }: { disabled: boolean; onDone: (b: Blob) => void }) {
  const can = typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
  const [rec, setRec] = useState<MediaRecorder | null>(null)
  const [secs, setSecs] = useState(0)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!rec) return
    const t0 = performance.now()
    const t = setInterval(() => setSecs((performance.now() - t0) / 1000), 200)
    return () => clearInterval(t)
  }, [rec])

  if (!can) {
    return (
      <p className="note tight" data-testid="asr-rec-off">
        录音需要 HTTPS 或在本机（localhost）打开控制台，当前地址浏览器不允许使用麦克风，请上传录好的音频文件。
      </p>
    )
  }

  const start = async () => {
    setErr('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const type = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm']
        .find((t) => MediaRecorder.isTypeSupported(t))
      const r = new MediaRecorder(stream, type ? { mimeType: type } : undefined)
      const parts: Blob[] = []
      r.ondataavailable = (e) => { if (e.data.size) parts.push(e.data) }
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        setRec(null)
        onDone(new Blob(parts, { type: r.mimeType || 'audio/webm' }))
      }
      r.start(1000)
      setSecs(0)
      setRec(r)
    } catch (e) {
      setErr(errText(e, '无法使用麦克风'))
    }
  }

  return (
    <div className="row" data-testid="asr-rec">
      {rec
        ? <button className="btn ghost sm" onClick={() => rec.stop()}>■ 停止录音 {fmtClock(secs)}</button>
        : <button className="btn ghost sm" disabled={disabled} onClick={() => void start()}>● 录音</button>}
      {err && <span className="err-text">{err}</span>}
    </div>
  )
}
