import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Overview from './pages/Overview'
import Agents from './pages/Agents'
import Models from './pages/Models'
import Playground from './pages/Playground'
import Apps from './pages/Apps'
import Keys from './pages/Keys'
import Records from './pages/Records'
import Logs from './pages/Logs'
import Settings from './pages/Settings'
import Docs from './pages/Docs'
import { applyTheme, initialTheme, type Theme } from './components/theme'
import Icon, { type IconName } from './components/Icons'

type Page = 'overview' | 'models' | 'agents' | 'playground' | 'apps' | 'keys' | 'records' | 'logs' | 'settings' | 'docs'

/** Grouped by what the operator is doing: watching and running the box, trying
 *  it out, administering it, reading about it. The order inside the groups is
 *  the old flat order, so nothing moved for someone who knows the console. */
const NAV: { group: string; items: { id: Page; label: string; icon: IconName }[] }[] = [
  {
    group: '运行',
    items: [
      { id: 'overview', label: '总览', icon: 'overview' },
      { id: 'models', label: '模型', icon: 'models' },
      { id: 'agents', label: 'Agent', icon: 'agents' },
    ],
  },
  {
    group: '体验',
    items: [
      { id: 'playground', label: '对话测试', icon: 'playground' },
      { id: 'apps', label: '应用演示', icon: 'apps' },
    ],
  },
  {
    group: '管理',
    items: [
      { id: 'keys', label: 'API Key', icon: 'keys' },
      { id: 'records', label: '推理记录', icon: 'records' },
      { id: 'logs', label: '日志', icon: 'logs' },
      { id: 'settings', label: '设置', icon: 'settings' },
    ],
  },
  {
    group: '帮助',
    items: [{ id: 'docs', label: '文档', icon: 'docs' }],
  },
]

const NAV_KEY = 'cv84x6.nav'

function storedCollapsed(): boolean {
  try { return localStorage.getItem(NAV_KEY) === 'collapsed' } catch { return false }
}

/** The product mark: the die glyph on the accent tile, then the name. */
function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand" data-testid="brand">
      <span className="brand-mark" aria-hidden="true"><Icon name="chip" size={20} /></span>
      {!compact && (
        <span className="brand-text">
          <span className="brand-name">CV84X6 LLM</span>
          <span className="brand-sub">离线推理服务</span>
        </span>
      )}
    </div>
  )
}

/** Day/night switch. Two options rather than one that flips, so the current
 *  state is readable without clicking it. */
function ThemeToggle({ theme, onChange }: { theme: Theme; onChange: (t: Theme) => void }) {
  return (
    <div className="theme-toggle" role="group" aria-label="外观主题" data-testid="theme-toggle">
      <span
        role="button" tabIndex={0} data-on={theme === 'light'} data-testid="theme-light"
        aria-pressed={theme === 'light'} title="白天模式"
        onClick={() => onChange('light')}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onChange('light') } }}
      ><Icon name="sun" size={14} /><span className="theme-word">白天</span></span>
      <span
        role="button" tabIndex={0} data-on={theme === 'dark'} data-testid="theme-dark"
        aria-pressed={theme === 'dark'} title="夜间模式"
        onClick={() => onChange('dark')}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onChange('dark') } }}
      ><Icon name="moon" size={14} /><span className="theme-word">夜间</span></span>
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)
  const [page, setPage] = useState<Page>('overview')
  const [password, setPassword] = useState('')
  const [loginErr, setLoginErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    // Applying here keeps the attribute in sync if anything else ever changes
    // the state. Persisting happens in `pick`, i.e. only for a choice the
    // operator actually made -- an OS-derived initial value must not be frozen
    // into localStorage.
    applyTheme(theme, false)
  }, [theme])

  useEffect(() => {
    api.session()
      .then((s) => setAuthed(s.authenticated))
      .catch(() => setAuthed(false))
  }, [])

  const login = useCallback(async () => {
    setBusy(true)
    setLoginErr('')
    try {
      await api.login(password)
      setAuthed(true)
      setPassword('')
    } catch (e) {
      setLoginErr(e instanceof Error ? e.message : '登录失败')
    } finally {
      setBusy(false)
    }
  }, [password])

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined)
    setAuthed(false)
  }, [])

  const [collapsed, setCollapsed] = useState<boolean>(storedCollapsed)
  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => {
      try { localStorage.setItem(NAV_KEY, c ? 'open' : 'collapsed') } catch { /* not remembered */ }
      return !c
    })
  }, [])

  // Each page starts at its top: switching from a long page used to land the
  // next one scrolled to wherever the previous one was.
  useEffect(() => {
    window.scrollTo(0, 0)
    // On a phone the nav is a sideways strip: bring the current item into it.
    document.querySelector('.nav button.active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [page])

  const pick = useCallback((t: Theme) => {
    applyTheme(t, true)
    setTheme(t)
  }, [])

  if (authed === null) {
    return (
      <div className="login-wrap boot" data-testid="boot">
        <div className="boot-inner">
          <Brand />
          <span className="spin" aria-label="正在连接" />
        </div>
      </div>
    )
  }

  if (!authed) {
    return (
      <div className="login-wrap">
        <div className="login-theme"><ThemeToggle theme={theme} onChange={pick} /></div>
        <div className="login-card" data-testid="login-card">
          <div className="login-head">
            <span className="brand-mark lg" aria-hidden="true"><Icon name="chip" size={26} /></span>
            <h1>CV84X6 LLM</h1>
            <p className="login-sub">离线推理服务控制台</p>
          </div>
          <form
            className="login-form"
            onSubmit={(e) => { e.preventDefault(); void login() }}
          >
            <label className="field">
              管理密码
              <span className="input-icon">
                <Icon name="lock" size={16} />
                <input
                  type="password" placeholder="输入管理密码" value={password}
                  autoFocus data-testid="login-password" autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                />
              </span>
            </label>
            {loginErr && (
              <div className="login-err" role="alert">
                <Icon name="alert" size={16} />{loginErr}
              </div>
            )}
            <button type="submit" className="btn block" disabled={busy} data-testid="login-submit">
              {busy ? <><span className="spin on-accent" /> 登录中…</> : '登录'}
            </button>
          </form>
          <p className="note login-note">
            首次启动的默认密码是 <code>admin</code>，登录后请在「API Key」页修改。
          </p>
        </div>
        <p className="login-foot">
          <Icon name="shield" size={14} />模型与数据都在本机运行，不需要联网
        </p>
      </div>
    )
  }

  return (
    <div className={collapsed ? 'shell collapsed' : 'shell'}>
      <aside className="sidebar" data-testid="sidebar">
        <div className="sidebar-head">
          <Brand compact={collapsed} />
        </div>
        <nav className="nav" data-testid="nav" aria-label="主导航">
          {NAV.map((g) => (
            <div className="nav-group" key={g.group} role="group" aria-label={g.group}>
              <div className="nav-group-label" aria-hidden="true">{g.group}</div>
              {g.items.map((n) => (
                <button
                  key={n.id}
                  className={page === n.id ? 'active' : ''}
                  aria-current={page === n.id ? 'page' : undefined}
                  data-testid={`nav-${n.id}`}
                  title={collapsed ? n.label : undefined}
                  onClick={() => setPage(n.id)}
                >
                  <Icon name={n.icon} className="icon" />
                  <span className="nav-label">{n.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ThemeToggle theme={theme} onChange={pick} />
          <div className="sidebar-foot-row">
            <button
              className="btn ghost sm logout" onClick={() => void logout()} data-testid="logout"
              title="退出登录" aria-label="退出登录"
            >
              <Icon name="logout" size={14} /><span className="btn-word">退出登录</span>
            </button>
            <button
              className="btn ghost icon sm nav-collapse" data-testid="nav-collapse"
              onClick={toggleCollapsed}
              title={collapsed ? '展开侧边栏' : '收起侧边栏'}
              aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
              aria-expanded={!collapsed}
            >
              <Icon name={collapsed ? 'expand' : 'collapse'} size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="main-inner">
          {page === 'overview' && <Overview />}
          {page === 'models' && <Models />}
          {page === 'agents' && <Agents />}
          {page === 'playground' && <Playground />}
          {page === 'apps' && <Apps />}
          {page === 'keys' && <Keys />}
          {page === 'records' && <Records />}
          {page === 'logs' && <Logs />}
          {page === 'settings' && <Settings />}
          {page === 'docs' && <Docs />}
        </div>
      </main>
    </div>
  )
}
