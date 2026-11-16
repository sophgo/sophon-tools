import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icons'
import {
  api, fmtBytes, type InferenceRecord, type InferenceRecordStatus,
  type InferenceRecordSummary, type RecordedMessage,
} from '../api'

/** The audit log of real inferences (MYS-2496).
 *
 *  Two panes rather than two pages: an operator chasing a bad answer compares
 *  the list against one row's detail, and a round trip between pages loses the
 *  place in the list every time. The list is a summary (no conversation text --
 *  see the backend's reason), so the detail pane is what actually answers
 *  "what did the customer ask, and what did the model say".
 */

const PAGE_SIZES = [20, 50, 100]

const STATUS_LABEL: Record<string, string> = {
  ok: '完成',
  error: '出错',
  cancelled: '已断开',
}

const SOURCE_LABEL: Record<string, string> = {
  '/v1/chat/completions': 'OpenAI 接口',
  '/api/chat/stream': '控制台（流式）',
  '/api/chat': '控制台',
}

function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source
}

/** Local wall-clock time with seconds: the record's timestamps are UTC so they
 *  can be compared with journald, but an operator reads them against the clock
 *  on the wall. */
function localTime(iso: string, epoch: number): string {
  const d = new Date(epoch * 1000)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function num(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toLocaleString()
}

function dec(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? '—' : n.toFixed(digits)
}

/** `content` is either the text or the parts list with images replaced by
 *  their dimensions; this renders the text and names the pictures. */
function contentText(content: RecordedMessage['content']): string {
  if (content === null || content === undefined) return ''
  if (typeof content === 'string') return content
  return content
    .map((p) => (p.type === 'text'
      ? String(p.text ?? '')
      : `[图片 #${p.index ?? '?'} ${p.width ?? '?'}×${p.height ?? '?'}]`))
    .join('\n')
}

export default function Records() {
  const [rows, setRows] = useState<InferenceRecordSummary[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(50)
  const [status, setStatus] = useState<InferenceRecordStatus | null>(null)
  const [detail, setDetail] = useState<InferenceRecord | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [detailErr, setDetailErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(async (nextOffset = offset, nextLimit = limit) => {
    setLoading(true)
    try {
      const r = await api.inferenceRecords({ limit: nextLimit, offset: nextOffset })
      setRows(r.items)
      setTotal(r.total)
      setOffset(r.offset)
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取推理记录失败')
    } finally {
      setLoading(false)
    }
    // The store's own health is separate from the list: a broken database and
    // an idle service both show zero rows, and only one of them needs fixing.
    try {
      setStatus(await api.inferenceRecordStatus())
    } catch { /* the list's error is the one worth showing */ }
  }, [offset, limit])

  // The first page only. `load` changes identity with the page state, so
  // depending on it here would re-fetch on every navigation, racing the click
  // that caused it.
  const loadedFirst = useRef(false)
  useEffect(() => {
    if (loadedFirst.current) return
    loadedFirst.current = true
    void load(0, 50)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const open = useCallback(async (id: string) => {
    setSelected(id)
    setDetail(null)
    setDetailErr('')
    try {
      setDetail(await api.inferenceRecord(id))
    } catch (e) {
      setDetailErr(e instanceof Error ? e.message : '读取记录详情失败')
    }
  }, [])

  const clearAll = async () => {
    setClearing(true)
    setNotice('')
    try {
      const r = await api.clearInferenceRecords()
      setConfirmClear(false)
      setNotice(`已删除 ${r.deleted} 条记录`)
      setDetail(null)
      setSelected(null)
      await load(0, limit)
    } catch (e) {
      setErr(e instanceof Error ? e.message : '清空失败')
    } finally {
      setClearing(false)
    }
  }

  const pages = Math.max(1, Math.ceil(total / limit))
  const page = Math.floor(offset / limit) + 1

  return (
    <>
      <h1>推理记录</h1>
      <p className="sub">
        每一次真正发起的模型推理都会留下一条记录：请求内容、实际生效的参数、完整输出与耗时。
        成功、流式中断和推理异常都会落盘，便于事后定位现场问题。
      </p>

      <div className="card notice" style={{ marginBottom: 'var(--s-4)' }} data-testid="records-privacy">
        <div className="notice-title"><Icon name="shield" size={16} />隐私说明</div>
        <p style={{ margin: 'var(--s-1) 0 0' }}>
          客户对话默认<strong>明文</strong>保存在本机数据目录{' '}
          <span className="mono">state/inference_records.sqlite3</span>，仅管理员可查看；导出的
          NDJSON 文件同样是敏感数据，请自行妥善保管。图片只记录数量与尺寸，不保存原图，
          也不保存 API Key 明文、哈希或会话 cookie。清理方式有两种：按保留策略自动清理
          （超过保留条数或保留天数的最旧记录），以及在下方一次性<strong>全部清空</strong>。
        </p>
        {status && (
          <p className="note tight mono" style={{ wordBreak: 'break-all' }}>
            {status.path} · {fmtBytes(status.bytes)} · {status.total} 条 · 保留{' '}
            {status.retention_count} 条 / {status.retention_days} 天
            {status.enabled ? '' : ' · 记录已关闭'}
          </p>
        )}
        {status?.moving && !status.last_error && (
          <p className="note tight">
            数据目录正在迁移，记录库暂停写入；此期间的推理记录不会保存，迁移结束后自动恢复。
          </p>
        )}
        {status && !status.readable && (
          <p className="err-text">
            记录库当前不可读：{status.error ?? '未知原因'}。推理服务本身不受影响，
            但记录可能正在丢失。
          </p>
        )}
        {status?.last_error && (
          // Not always a fault: a record dropped while the data directory moves
          // is reported here too, so "记录少了" never has to be guessed at.
          <p className={status.moving ? 'note' : 'err-text'}>
            {status.moving ? '记录暂停：' : '最近一次写入失败：'}{status.last_error}
          </p>
        )}
      </div>

      {err && <p className="err-text">{err}</p>}
      {notice && <p className="ok-text">{notice}</p>}

      <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
        <div className="row" style={{ alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>记录列表</h2>
          <div className="spacer" />
          <select
            aria-label="每页条数" value={limit}
            onChange={(e) => { const n = Number(e.target.value); setLimit(n); void load(0, n) }}
            className="sm" style={{ width: 'auto' }}
          >
            {PAGE_SIZES.map((n) => <option key={n} value={n}>每页 {n} 条</option>)}
          </select>
          <button className="btn ghost sm" onClick={() => void load()} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
          <a className="btn ghost sm" href={api.inferenceRecordsExportUrl()} download>
            导出 NDJSON
          </a>
          <button className="btn danger sm" onClick={() => setConfirmClear(true)} disabled={clearing}>
            全部清空
          </button>
        </div>

        {confirmClear && (
          <div className="card confirm" data-testid="clear-confirm">
            <p style={{ margin: 0 }}>
              确定要删除全部 <strong>{total}</strong> 条推理记录吗？
            </p>
            <p className="note tight">
              此操作<strong>不可恢复</strong>：记录里是客户真实对话，删除后无法再用于排查。
              建议先「导出 NDJSON」留档。
            </p>
            <div className="row" style={{ marginTop: 'var(--s-3)' }}>
              <button className="btn danger-solid sm" onClick={() => void clearAll()} disabled={clearing}>
                {clearing ? '删除中…' : '确认全部清空'}
              </button>
              <button className="btn ghost sm" onClick={() => setConfirmClear(false)} disabled={clearing}>
                取消
              </button>
            </div>
          </div>
        )}

        {rows.length === 0 ? (
          <div className="empty">
            <strong>{loading ? '正在读取…' : '还没有推理记录'}</strong>
            {status && !status.enabled
              ? '记录功能已在「设置」页关闭；打开后新的推理才会落盘。'
              : '发起一次对话（OpenAI 接口或「对话测试」页）后，这里会出现对应记录。'}
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>时间</th><th>来源</th><th>模型</th><th>调用方</th>
                    <th>状态</th><th className="num">输入</th><th className="num">输出</th>
                    <th className="num">TTFT</th><th className="num">TPS</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className={selected === r.id ? 'selected' : ''}>
                      <td className="mono" title={r.started_iso}>{localTime(r.started_iso, r.started_at)}</td>
                      <td>{sourceLabel(r.source)}</td>
                      <td className="mono">{r.model ?? '—'}</td>
                      <td>
                        {r.actor_type === 'api_key'
                          ? <span className="mono">{r.actor_name ?? r.actor_id ?? 'key'}</span>
                          : r.actor_type === 'admin' ? 'admin' : '—'}
                      </td>
                      <td>
                        {r.status === 'ok'
                          ? <span className="pill ok"><span className="dot" />{STATUS_LABEL.ok}</span>
                          : r.status === 'cancelled'
                            ? <span className="pill warn">{STATUS_LABEL.cancelled}</span>
                            : <span className="pill err">{STATUS_LABEL.error}</span>}
                        {r.finish_reason && <span className="muted"> {r.finish_reason}</span>}
                      </td>
                      <td className="num">{num(r.prompt_tokens)}</td>
                      <td className="num">{num(r.completion_tokens)}</td>
                      <td className="num">{r.first_token_latency_s == null ? '—' : `${dec(r.first_token_latency_s, 2)} s`}</td>
                      <td className="num">{dec(r.decode_tps)}</td>
                      <td className="num">
                        <button className="btn link" onClick={() => void open(r.id)}>详情</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: 'var(--s-3)', alignItems: 'center' }}>
              <span className="note" style={{ margin: 0 }}>
                共 {total} 条 · 第 {page} / {pages} 页
              </span>
              <div className="spacer" />
              <button className="btn ghost sm" disabled={loading || offset === 0}
                      onClick={() => void load(Math.max(0, offset - limit))}>上一页</button>
              <button className="btn ghost sm" disabled={loading || offset + limit >= total}
                      onClick={() => void load(offset + limit)}>下一页</button>
            </div>
          </>
        )}
      </div>

      {selected && (
        <RecordDetail
          record={detail} error={detailErr} onClose={() => { setSelected(null); setDetail(null) }}
        />
      )}
    </>
  )
}

/** One record, read in full: the request, the parameters, the raw answer. */
function RecordDetail({ record, error, onClose }: {
  record: InferenceRecord | null
  error: string
  onClose: () => void
}) {
  return (
    <div className="card" data-testid="record-detail">
      <div className="row" style={{ alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>记录详情</h2>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={onClose}>收起</button>
      </div>

      {error && <p className="err-text">{error}</p>}
      {!record && !error && <div className="empty"><span className="spin" /> 正在读取…</div>}

      {record && (
        <>
          <div className="grid" style={{ gap: 'var(--s-2)', marginTop: 'var(--s-3)' }}>
            <div className="value">
              <span className="muted">请求 id：</span><span className="mono">{record.id}</span>
            </div>
            <div className="value">
              <span className="muted">时间：</span>
              <span className="mono">{localTime(record.started_iso, record.started_at)}</span>
              <span className="muted"> → </span>
              <span className="mono">{localTime(record.finished_iso, record.finished_at)}</span>
              <span className="muted">（UTC {record.started_iso}）</span>
            </div>
            <div className="value">
              <span className="muted">来源：</span>{sourceLabel(record.source)}
              <span className="muted"> · 模型：</span><span className="mono">{record.model ?? '—'}</span>
              <span className="muted"> · 调用方：</span>
              {record.actor_type === 'api_key'
                ? <span className="mono">{record.actor_name ?? '—'}（key {record.actor_id ?? '—'}）</span>
                : (record.actor_type ?? '—')}
            </div>
            <div className="value">
              <span className="muted">状态：</span>
              {STATUS_LABEL[record.status] ?? record.status}
              {record.finish_reason && <><span className="muted"> · finish_reason：</span>{record.finish_reason}</>}
              {record.stop_hit && <><span className="muted"> · 命中 stop：</span><span className="mono">{record.stop_hit}</span></>}
              <span className="muted"> · token：</span>
              输入 {num(record.prompt_tokens)} / 输出 {num(record.completion_tokens)}
              {record.cached_tokens ? <>（缓存命中 {num(record.cached_tokens)}）</> : null}
              <span className="muted"> · TTFT </span>{dec(record.first_token_latency_s, 2)} s
              <span className="muted"> · TPS </span>{dec(record.decode_tps)}
            </div>
          </div>

          {record.error && (
            <p className="err-text">
              {record.error.type ?? '错误'}：{record.error.message ?? ''}
            </p>
          )}

          <h3>采样参数</h3>
          <pre className="mono block">{JSON.stringify(record.params ?? {}, null, 2)}</pre>
          {(record.tools?.length || record.tool_choice != null) && (
            <>
              <h3>工具定义</h3>
              <pre className="mono block">{JSON.stringify(
                { tool_choice: record.tool_choice, tools: record.tools }, null, 2)}</pre>
            </>
          )}

          <h3>输入消息</h3>
          {record.images?.length ? (
            <p className="note tight">
              图片：
              {record.images.map((im, i) => (
                <span key={i} className="mono">
                  {i > 0 ? ' · ' : ''}
                  {im.count ?? 1} 张 {im.width ?? '?'}×{im.height ?? '?'}
                </span>
              ))}
            </p>
          ) : null}
          {record.messages?.length ? (
            <div className="grid" style={{ gap: 'var(--s-2)' }}>
              {record.messages.map((m, i) => (
                <div key={i} className="card tight">
                  <div className="metric-label">
                    {m.role}
                    {m.name ? ` · ${m.name}` : ''}
                    {m.tool_call_id ? ` · ${m.tool_call_id}` : ''}
                  </div>
                  <pre className="mono block" style={{ margin: 0 }}>{contentText(m.content)}</pre>
                  {m.reasoning_content && (
                    <details>
                      <summary className="note">历史 reasoning</summary>
                      <pre className="mono block">{m.reasoning_content}</pre>
                    </details>
                  )}
                  {m.tool_calls?.length ? (
                    <pre className="mono block">{JSON.stringify(m.tool_calls, null, 2)}</pre>
                  ) : null}
                </div>
              ))}
            </div>
          ) : <div className="empty">请求里没有消息（不应出现）。</div>}

          <h3>模型输出</h3>
          {record.reasoning_content && (
            <>
              <div className="metric-label">reasoning_content</div>
              <pre className="mono block">{record.reasoning_content}</pre>
            </>
          )}
          <div className="metric-label">完整原始文本 output_text</div>
          <pre className="mono block">{record.output_text ?? '（无输出）'}</pre>
          <p className="note tight">
            output_text 是模型实际生成并按 API 语义截断后的文本（命中 stop 时不包含 stop 本身
            及其之后的内容），与客户端看到的回复一致。原始生成长度见
            {' '}raw_output_chars = {num(record.raw_output_chars)}。
          </p>
          {record.response_content !== record.output_text && (
            <>
              <div className="metric-label">客户端看到的 content</div>
              <pre className="mono block">{record.response_content ?? '（空）'}</pre>
            </>
          )}
          {record.tool_calls?.length ? (
            <>
              <div className="metric-label">tool_calls</div>
              <pre className="mono block">{JSON.stringify(record.tool_calls, null, 2)}</pre>
            </>
          ) : null}
        </>
      )}
    </div>
  )
}
