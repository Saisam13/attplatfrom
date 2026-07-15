import { useEffect, useState, useRef, createContext, useContext, useCallback } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { api, download, pin, user, Run } from './api'
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
  setUserName: (n: string) => void
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
  const [userName, setUserNameState] = useState(user.get())
  const [askName, setAskName] = useState(!user.get())
  const [pinNeeded, setPinNeeded] = useState(false)
  const prevStatuses = useRef<Record<number, string>>({})

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
          toast('success', `Run #${r.id} “${r.name}” completed`)
          document.title = `✓ Run done — ${BASE_TITLE}`
          setTimeout(() => { document.title = BASE_TITLE }, 30000)
        }
        if (prev && (prev === 'running' || prev === 'queued') && r.status === 'error') {
          toast('error', `Run #${r.id} “${r.name}” failed: ${r.error}`)
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
    const onPin = () => setPinNeeded(true)
    window.addEventListener('att-pin-required', onPin)
    return () => window.removeEventListener('att-pin-required', onPin)
  }, [])

  useEffect(() => {
    refresh()
    api.settings().then(setAppSettings).catch(() => {})
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  const setUserName = (n: string) => {
    user.set(n)
    setUserNameState(n.trim())
  }

  const runs = allRuns.filter(r => r.kind !== 'battery')
  const batteryRuns = allRuns.filter(r => r.kind === 'battery')
  const selectedRun = runs.find(r => r.id === selectedId) ?? null
  const selectedBatteryRun = batteryRuns.find(r => r.id === selectedBatteryId) ?? null
  const showFeedback = appSettings?.show_feedback_page !== false

  if (pinNeeded) {
    return <PinScreen onOk={() => { setPinNeeded(false); refresh(); api.settings().then(setAppSettings).catch(() => {}) }} />
  }

  return (
    <RunContext.Provider value={{
      runs, batteryRuns, selectedRun, selectedBatteryRun,
      setSelectedId, setSelectedBatteryId, refresh, toast,
      appSettings, userName, setUserName,
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
          <div className="run-select">
            <label>Active run</label>
            <select
              style={{ width: '100%', marginTop: 6 }}
              value={selectedId ?? ''}
              onChange={e => setSelectedId(Number(e.target.value))}
            >
              {runs.length === 0 && <option value="">— no runs yet —</option>}
              {runs.map(r => (
                <option key={r.id} value={r.id}>
                  #{r.id} {r.name} ({r.status})
                </option>
              ))}
            </select>
            {selectedRun?.status === 'done' && (
              <button className="btn" style={{ display: 'block', width: '100%', textAlign: 'center', marginTop: 10, fontSize: 13 }}
                onClick={() => download(`/api/runs/${selectedRun.id}/export`, `ATT_Results_Run${selectedRun.id}.xlsx`)}>
                ⬇ Export workbook
              </button>
            )}
          </div>
          <div className="user-badge">
            <span className="dim">Signed in as</span>
            <strong>{userName || '—'}</strong>
            <button className="ghost" style={{ marginTop: 6 }} onClick={() => setAskName(true)}>Change</button>
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
      {askName && <NameModal current={userName} onSave={n => { setUserName(n); setAskName(false) }} />}
    </RunContext.Provider>
  )
}

function NameModal({ current, onSave }: { current: string; onSave: (n: string) => void }) {
  const [name, setName] = useState(current)
  return (
    <div className="modal-overlay">
      <div className="modal" style={{ width: 380 }}>
        <h3>Who's using the platform?</h3>
        <div className="dim" style={{ fontSize: 13, marginBottom: 12 }}>
          Your name is stamped on leads, feedback and settings changes so the team knows who said what.
          No password — this is an internal tool.
        </div>
        <div className="field">
          <label>Your name</label>
          <input type="text" value={name} autoFocus onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && name.trim()) onSave(name) }}
            placeholder="e.g. Anuraag" />
        </div>
        <div className="actions">
          <button disabled={!name.trim()} onClick={() => onSave(name)}>Continue</button>
        </div>
      </div>
    </div>
  )
}

function PinScreen({ onOk }: { onOk: () => void }) {
  const [value, setValue] = useState('')
  const [err, setErr] = useState('')
  const submit = async () => {
    setErr('')
    try {
      const res = await api.verifyPin(value)
      if (res.ok) {
        pin.set(value)
        onOk()
      } else {
        setErr('Wrong PIN')
      }
    } catch (e: any) {
      setErr(String(e.message || e))
    }
  }
  return (
    <div className="pin-screen">
      <img src="/minimines-logo.svg" alt="MiniMines" style={{ width: 140, marginBottom: 18 }} />
      <h1 style={{ marginBottom: 4 }}>MiniMines Sales Hub</h1>
      <div className="dim" style={{ marginBottom: 20 }}>This deployment is PIN-protected.</div>
      <div style={{ display: 'flex', gap: 8 }}>
        <input type="password" value={value} autoFocus placeholder="Team PIN"
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }} />
        <button onClick={submit}>Enter</button>
      </div>
      {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
    </div>
  )
}
