import { useEffect, useState, useRef, createContext, useContext, useCallback } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { api, auth, download, setCurrentUserName, AuthUser, Run } from './api'
import HomePage from './pages/HomePage'
import UploadPage from './pages/UploadPage'
import DashboardPage from './pages/DashboardPage'
import RankingsPage from './pages/RankingsPage'
import ChemicalDetailPage from './pages/ChemicalDetailPage'
import BatteryDashboardPage from './pages/BatteryDashboardPage'
import BatteryPage from './pages/BatteryPage'
import ComparePage from './pages/ComparePage'
import RawDataPage from './pages/RawDataPage'
import GeoLogPage from './pages/GeoLogPage'
import FeedbackPage from './pages/FeedbackPage'
import EprPage from './pages/EprPage'
import EprCompanyPage from './pages/EprCompanyPage'
import HsnPage from './pages/HsnPage'
import LeadsPage from './pages/LeadsPage'
import OutreachPage from './pages/OutreachPage'
import DigestPage from './pages/DigestPage'
import SettingsPage from './pages/SettingsPage'

interface Toast { id: number; kind: 'success' | 'error'; text: string }

interface RunCtx {
  runs: Run[]                    // chemical runs
  batteryRuns: Run[]
  selectedRun: Run | null
  selectedBatteryRun: Run | null
  setSelectedId: (id: number) => void
  setSelectedBatteryId: (id: number) => void
  refresh: () => void
  toast: (kind: 'success' | 'error', text: string) => void
  appSettings: any
  userName: string
}

const RunContext = createContext<RunCtx>(null as any)
export const useRuns = () => useContext(RunContext)

const BASE_TITLE = 'MiniMines Sales Hub'

export default function App() {
  const [allRuns, setAllRuns] = useState<Run[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedBatteryId, setSelectedBatteryId] = useState<number | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [appSettings, setAppSettings] = useState<any>(null)
  const [authState, setAuthState] = useState<'loading' | 'setup' | 'login' | 'ok'>('loading')
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [authRateLimited, setAuthRateLimited] = useState(false)
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem('att_theme') as 'dark' | 'light') || 'dark')
  const prevStatuses = useRef<Record<number, string>>({})

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('att_theme', theme)
  }, [theme])

  const toast = useCallback((kind: 'success' | 'error', text: string) => {
    const id = Date.now() + Math.random()
    setToasts(ts => [...ts, { id, kind, text }])
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 7000)
  }, [])

  const refresh = useCallback(() => {
    api.listRuns().then(rs => {
      // notify on run completion / failure
      for (const r of rs) {
        const prev = prevStatuses.current[r.id]
        if (prev && (prev === 'running' || prev === 'queued') && r.status === 'done') {
          toast('success', `Run #${r.id} "${r.name}" completed`)
          document.title = `Run done - ${BASE_TITLE}`
          setTimeout(() => { document.title = BASE_TITLE }, 30000)
        }
        if (prev && (prev === 'running' || prev === 'queued') && r.status === 'error') {
          toast('error', `Run #${r.id} "${r.name}" failed: ${r.error}`)
        }
        prevStatuses.current[r.id] = r.status
      }
      setAllRuns(rs)
      const chem = rs.filter(r => r.kind !== 'battery')
      const bat = rs.filter(r => r.kind === 'battery')
      setSelectedId(prev => {
        if (prev != null && chem.some(r => r.id === prev)) return prev
        const done = chem.find(r => r.status === 'done')
        return done ? done.id : (chem[0]?.id ?? null)
      })
      setSelectedBatteryId(prev => {
        if (prev != null && bat.some(r => r.id === prev)) return prev
        const done = bat.find(r => r.status === 'done')
        return done ? done.id : (bat[0]?.id ?? null)
      })
    }).catch(() => {})
  }, [toast])

  useEffect(() => {
    const onAuthRequired = () => { setCurrentUser(null); setAuthState('login') }
    window.addEventListener('att-auth-required', onAuthRequired)
    return () => window.removeEventListener('att-auth-required', onAuthRequired)
  }, [])

  // Preflight: check the session cookie before rendering the app at all -
  // without this, a hard refresh would briefly show the full authenticated
  // shell while the first real API call fails in the background.
  useEffect(() => {
    auth.me()
      .then(u => { setCurrentUser(u); setAuthState('ok') })
      .catch(() => {
        auth.needsSetup()
          .then(r => setAuthState(r.needs_setup ? 'setup' : 'login'))
          .catch(() => setAuthState('login'))
      })
  }, [])

  useEffect(() => {
    if (authState !== 'ok') return
    refresh()
    api.settings().then(setAppSettings).catch(() => {})
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh, authState])

  const userName = currentUser?.display_name || currentUser?.username || ''
  useEffect(() => { setCurrentUserName(userName) }, [userName])

  const logout = async () => {
    try { await auth.logout() } catch { /* ignore - we're logging out regardless */ }
    setCurrentUser(null)
    setAuthState('login')
  }

  const runs = allRuns.filter(r => r.kind !== 'battery')
  const batteryRuns = allRuns.filter(r => r.kind === 'battery')
  const selectedRun = runs.find(r => r.id === selectedId) ?? null
  const selectedBatteryRun = batteryRuns.find(r => r.id === selectedBatteryId) ?? null
  const showFeedback = appSettings?.show_feedback_page !== false

  if (authState === 'loading') {
    return null
  }

  if (authState === 'setup') {
    return <SetupScreen onDone={u => { setCurrentUser(u); setAuthState('ok') }} />
  }

  if (authState === 'login') {
    return <LoginScreen rateLimited={authRateLimited}
      onOk={u => { setCurrentUser(u); setAuthRateLimited(false); setAuthState('ok') }} />
  }

  return (
    <RunContext.Provider value={{
      runs, batteryRuns, selectedRun, selectedBatteryRun,
      setSelectedId, setSelectedBatteryId, refresh, toast,
      appSettings, userName,
    }}>
      <div className="layout">
        <aside className="sidebar">
          <div className="logo">
            <img src="/minimines-logo.svg" alt="MiniMines" />
            Sales Hub<span>MiniMines internal sales platform</span>
          </div>
          <nav>
            <NavLink to="/home">Home</NavLink>
            <div className="nav-group">Trading</div>
            <NavLink to="/dashboard">Trading Dashboard</NavLink>
            <NavLink to="/upload">Upload &amp; Runs</NavLink>
            <NavLink to="/rankings">Rankings</NavLink>
            <NavLink to="/compare">Run Compare</NavLink>
            <NavLink to="/raw">Raw Data</NavLink>
            <NavLink to="/geo">Geo Anomalies</NavLink>
            {showFeedback && <NavLink to="/feedback">Feedback</NavLink>}
            <div className="nav-group">Battery</div>
            <NavLink to="/battery-dashboard">Battery Dashboard</NavLink>
            <NavLink to="/battery">Suppliers &amp; Buyers</NavLink>
            <div className="nav-group">Sales</div>
            <NavLink to="/epr">EPR Intel</NavLink>
            <NavLink to="/hsn">HSN Explorer</NavLink>
            <NavLink to="/leads">Leads</NavLink>
            <NavLink to="/outreach">Outreach</NavLink>
            <NavLink to="/digest">Digest</NavLink>
            <div className="nav-group"> </div>
            <NavLink to="/settings">Settings</NavLink>
          </nav>
          <div className="user-badge" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div>
              <span className="dim">Signed in as</span>
              <strong>{userName || '-'}</strong>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button className="ghost" style={{ flex: 1 }} onClick={logout}>Log out</button>
              <button className="ghost" style={{ padding: '5px 8px', fontSize: 16 }} onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')} title="Toggle theme">
                {theme === 'dark' ? 'Light' : 'Dark'}
              </button>
            </div>
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/rankings" element={<RankingsPage />} />
            <Route path="/chemical/:name" element={<ChemicalDetailPage />} />
            <Route path="/battery-dashboard" element={<BatteryDashboardPage />} />
            <Route path="/battery" element={<BatteryPage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/raw" element={<RawDataPage />} />
            <Route path="/geo" element={<GeoLogPage />} />
            <Route path="/opportunities" element={<Navigate to="/rankings?tab=opportunity" replace />} />
            {showFeedback && <Route path="/feedback" element={<FeedbackPage />} />}
            <Route path="/epr" element={<EprPage />} />
            <Route path="/epr/:id" element={<EprCompanyPage />} />
            <Route path="/hsn" element={<HsnPage />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/outreach" element={<OutreachPage />} />
            <Route path="/digest" element={<DigestPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </main>
      </div>
      <div className="toasts">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => setToasts(ts => ts.filter(x => x.id !== t.id))}>
            {t.text}
          </div>
        ))}
      </div>
    </RunContext.Provider>
  )
}

function LoginScreen({ onOk, rateLimited }: { onOk: (u: AuthUser) => void; rateLimited?: boolean }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState(rateLimited ? 'Too many attempts - try again in a few minutes.' : '')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (!username.trim() || !password) return
    setErr(''); setBusy(true)
    try {
      const res = await auth.login(username.trim(), password)
      onOk(res.user)
    } catch (e: any) {
      const msg = String(e?.message ?? e)
      setErr(msg.startsWith('429') ? 'Too many attempts - try again in a few minutes.' : 'Invalid username or password')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="pin-screen">
      <img src="/minimines-logo.svg" alt="MiniMines" style={{ width: 140, marginBottom: 18 }} />
      <h1 style={{ marginBottom: 4 }}>MiniMines Sales Hub</h1>
      <div className="dim" style={{ marginBottom: 20 }}>Sign in to continue.</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: 260 }}>
        <input type="text" value={username} autoFocus placeholder="Username"
          onChange={e => setUsername(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }} />
        <input type="password" value={password} placeholder="Password"
          onChange={e => setPassword(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }} />
        <button disabled={busy || !username.trim() || !password} onClick={submit}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
      </div>
      {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
    </div>
  )
}

function SetupScreen({ onDone }: { onDone: (u: AuthUser) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const valid = username.trim().length > 0 && password.length >= 6 && password === confirm
  const submit = async () => {
    if (!valid) return
    setErr(''); setBusy(true)
    try {
      const res = await auth.setup(username.trim(), password, displayName.trim())
      onDone(res.user)
    } catch (e: any) {
      setErr(String(e?.message ?? e).replace(/^\d+:\s*/, ''))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="pin-screen">
      <img src="/minimines-logo.svg" alt="MiniMines" style={{ width: 140, marginBottom: 18 }} />
      <h1 style={{ marginBottom: 4 }}>MiniMines Sales Hub</h1>
      <div className="dim" style={{ marginBottom: 20, maxWidth: 320, textAlign: 'center' }}>
        No account exists yet - create the first one. It becomes the admin account
        used to add the rest of the team from Settings afterward.
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="text" value={username} autoFocus placeholder="Username"
          onChange={e => setUsername(e.target.value)} />
        <input type="text" value={displayName} placeholder="Display name (optional)"
          onChange={e => setDisplayName(e.target.value)} />
        <input type="password" value={password} placeholder="Password (min 6 characters)"
          onChange={e => setPassword(e.target.value)} />
        <input type="password" value={confirm} placeholder="Confirm password"
          onChange={e => setConfirm(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }} />
        <button disabled={busy || !valid} onClick={submit}>
          {busy ? 'Creating...' : 'Create account'}
        </button>
      </div>
      {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
    </div>
  )
}
