import { useCallback, useEffect, useState } from 'react'
import { api, type ApiKey } from '../api'

export default function Keys() {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'inference' | 'admin'>('inference')
  const [fresh, setFresh] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [pw, setPw] = useState('')
  const [pwMsg, setPwMsg] = useState('')

  const refresh = useCallback(async () => {
    try {
      const r = await api.keys()
      setKeys(r.keys)
      setErr('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : '读取失败')
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const create = async () => {
    setBusy(true); setErr(''); setFresh(null)
    try {
      const r = await api.createKey(name || 'unnamed', scope)
      setFresh(r.key)
      setName('')
      await refresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '创建失败')
    } finally { setBusy(false) }
  }

  const changePw = async () => {
    setPwMsg('')
    try {
      await api.setPassword(pw)
      setPwMsg('已更新管理密码')
      setPw('')
    } catch (e) {
      setPwMsg(e instanceof Error ? e.message : '修改失败')
    }
  }

  const base = window.location.origin

  return (
    <>
      <h1>API Key</h1>
      <p className="sub">
        OpenAI 兼容接口（/v1）与管理 API（/api）的访问凭据。密钥只在创建时完整显示一次，服务端只保存它的 SHA-256。
      </p>

      {err && <p className="err-text">{err}</p>}

      <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
        <h2>创建新 Key</h2>
        <div className="row">
          <input placeholder="用途备注，例如 laptop / cline" value={name}
                 onChange={(e) => setName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') void create() }}
                 style={{ maxWidth: 320 }} aria-label="用途备注" data-testid="key-name" />
          <select value={scope} onChange={(e) => setScope(e.target.value as 'inference' | 'admin')}
                  aria-label="权限范围" data-testid="key-scope" style={{ maxWidth: 240 }}>
            <option value="inference">推理（只能调 /v1）</option>
            <option value="admin">管理（/v1 + 管理 API /api）</option>
          </select>
          <button className="btn" onClick={() => void create()} disabled={busy}>
            {busy ? '创建中…' : '创建'}
          </button>
        </div>
        {scope === 'admin' && (
          <p className="note" style={{ marginTop: 'var(--s-2)' }} data-testid="key-admin-note">
            管理 Key 能加载 / 卸载模型、改设置、建删 Key，等同于管理员；只发给自己的脚本，不要配给 agent 或客户端。
          </p>
        )}
        {fresh && (
          <div className="card tight callout" data-testid="fresh-key">
            <div className="metric-label">新密钥（只显示这一次，请立刻复制）</div>
            <div className="mono" style={{ wordBreak: 'break-all', display: 'block' }}>{fresh}</div>
            <button className="btn ghost sm" style={{ marginTop: 'var(--s-2)' }}
                    onClick={() => void navigator.clipboard.writeText(fresh)}>复制</button>
          </div>
        )}
      </div>

      <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
        <h2>已有 Key</h2>
        {keys.length === 0 ? (
          <div className="empty">
            <strong>还没有创建任何 Key</strong>
            上面的输入框填一个用途备注（例如 laptop、cline），点「创建」即可；
            明文只显示一次，服务端只保存它的 SHA-256。
          </div>
        ) : (
          <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>备注</th><th>权限</th><th>前缀</th><th className="num">请求</th>
                <th className="num">输入 token</th><th className="num">输出 token</th>
                <th>状态</th><th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td>{k.name}</td>
                  <td>
                    {k.scope === 'admin'
                      ? <span className="pill warn" title="可调用管理 API /api">管理</span>
                      : <span className="pill" title="只能调用 /v1">推理</span>}
                  </td>
                  <td className="mono">{k.prefix}</td>
                  <td className="num">{k.requests}</td>
                  <td className="num">{k.prompt_tokens.toLocaleString()}</td>
                  <td className="num">{k.completion_tokens.toLocaleString()}</td>
                  <td>
                    {k.revoked
                      ? <span className="pill err">已吊销</span>
                      : <span className="pill ok"><span className="dot" />有效</span>}
                  </td>
                  <td className="num">
                    {/* Two destructive actions on every row would shout as
                        loud as the page's primary action (§2.8.1), so they are
                        ranked: 吊销 (reversible) as a link, 删除 (permanent) as
                        a quiet outline. */}
                    {!k.revoked && (
                      <button className="btn link" onClick={async () => { await api.revokeKey(k.id); await refresh() }}>
                        吊销
                      </button>
                    )}{' '}
                    <button className="btn danger sm" onClick={async () => { await api.deleteKey(k.id); await refresh() }}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>

      <div className="card" style={{ marginBottom: 'var(--s-4)' }}>
        <h2>接入地址</h2>
        <div className="table-wrap">
        <table className="kv">
          <tbody>
            <tr><th>OpenAI Base URL</th><td className="mono">{base}/v1</td></tr>
            <tr><th>模型名</th><td className="mono">已加载模型的 id（见「模型」页）</td></tr>
            <tr><th>鉴权</th><td className="mono">Authorization: Bearer sk-…</td></tr>
          </tbody>
        </table>
        </div>
      </div>

      <div className="card">
        <h2>修改管理密码</h2>
        <div className="row">
          <input type="password" placeholder="新密码（至少 6 位）" value={pw}
                 onChange={(e) => setPw(e.target.value)} style={{ maxWidth: 280 }} />
          <button className="btn" onClick={() => void changePw()} disabled={pw.length < 6}>更新</button>
        </div>
        {pwMsg && <p className={pwMsg.includes('已更新') ? 'ok-text' : 'err-text'}>{pwMsg}</p>}
      </div>
    </>
  )
}
