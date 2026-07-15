import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fmt } from '../api'
import { useRuns } from '../App'
import { StageBadge, TierBadge } from '../components/common'

/** Cross-module sales landing page: pipeline snapshot, follow-ups due,
 *  hot EPR producers, EPR↔trade cross-links, top ATT chemicals. */
export default function HomePage() {
  const { selectedRun, userName } = useRuns()
  const [leadsSum, setLeadsSum] = useState<any>(null)
  const [due, setDue] = useState<any[]>([])
  const [epr, setEpr] = useState<any>(null)
  const [cross, setCross] = useState<any[]>([])
  const [runSum, setRunSum] = useState<any>(null)
  const nav = useNavigate()

  useEffect(() => {
    api.leadsSummary().then(setLeadsSum).catch(() => {})
    api.leads({ due: 'overdue', limit: '8' }).then(r => setDue(d => [...r.items, ...d].slice(0, 8))).catch(() => {})
    api.leads({ due: 'today', limit: '8' }).then(r => setDue(d => [...d, ...r.items].slice(0, 8))).catch(() => {})
    api.eprSummary().then(setEpr).catch(() => {})
    api.eprCrossLinks().then(setCross).catch(() => {})
  }, [])

  useEffect(() => {
    if (selectedRun?.status === 'done') {
      api.summary(selectedRun.id).then(setRunSum).catch(() => setRunSum(null))
    }
  }, [selectedRun?.id, selectedRun?.status])

  return (
    <div>
      <h1>Home</h1>
      <div className="subtitle">
        {userName ? `Welcome, ${userName}. ` : ''}One place for trading intelligence, EPR producers, HSN analysis and your pipeline.
      </div>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <div className="stat-card"><div className="value">{leadsSum?.total ?? '—'}</div><div className="label">Leads</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--red)' }}>{leadsSum?.overdue ?? 0}</div><div className="label">Overdue follow-ups</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--orange)' }}>{leadsSum?.due_today ?? 0}</div><div className="label">Due today</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--green)' }}>{leadsSum?.by_stage?.deal ?? 0}</div><div className="label">Deals</div></div>
        <div className="stat-card"><div className="value">{epr?.total_companies ?? '—'}</div><div className="label">EPR producers</div></div>
        <div className="stat-card"><div className="value">{epr ? fmt.num(epr.total_gap_tons) : '—'}</div><div className="label">EPR gap (tons)</div></div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(430px, 1fr))', gap: 18 }}>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Follow-ups due</h2>
          {due.length === 0 && <div className="dim">Nothing due — check <Link to="/leads">Leads</Link> for the full pipeline.</div>}
          {due.length > 0 && (
            <table>
              <thead><tr><th>Lead</th><th>Type</th><th>Stage</th><th>Owner</th><th>Due</th></tr></thead>
              <tbody>
                {due.map(l => (
                  <tr key={l.id} className="clickable" onClick={() => nav('/leads')}>
                    <td style={{ fontWeight: 600 }}>{l.name}</td>
                    <td className="dim">{l.lead_type}</td>
                    <td><StageBadge stage={l.stage} /></td>
                    <td className="dim">{l.owner || '—'}</td>
                    <td className="mono" style={{ color: 'var(--orange)' }}>{l.next_followup}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Hot EPR producers</h2>
          {!epr?.top?.length && <div className="dim">Upload the CPCB EPR targets file on the <Link to="/epr">EPR Intel</Link> page.</div>}
          {!!epr?.top?.length && (
            <table>
              <thead><tr><th>Company</th><th>Target (t)</th><th>Gap (t)</th><th>Priority</th></tr></thead>
              <tbody>
                {epr.top.slice(0, 6).map((c: any) => (
                  <tr key={c.id} className="clickable" onClick={() => nav(`/epr/${c.id}`)}>
                    <td style={{ fontWeight: 600 }}>{c.company_name}{c.has_research && <span className="dim" title="AI research available"> ✓</span>}</td>
                    <td className="mono">{fmt.num(c.target_tons)}</td>
                    <td className="mono" style={{ color: 'var(--orange)' }}>{fmt.num(c.gap_tons)}</td>
                    <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{c.priority_score.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>EPR ↔ trade cross-links</h2>
          <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
            High-priority EPR producers that also appear in the uploaded EXIM trade data.
          </div>
          {cross.length === 0 && <div className="dim">No overlaps found yet (needs EPR data + a completed run).</div>}
          {cross.length > 0 && (
            <table>
              <thead><tr><th>Company</th><th>Priority</th><th>Shipments seen</th></tr></thead>
              <tbody>
                {cross.map(c => (
                  <tr key={c.id} className="clickable" onClick={() => nav(`/epr/${c.id}`)}>
                    <td style={{ fontWeight: 600 }}>{c.company_name}</td>
                    <td className="mono" style={{ color: 'var(--teal)' }}>{c.priority_score.toFixed(1)}</td>
                    <td className="mono">{c.trade_shipments}{c.trade_shipments >= 5 ? '+' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Top chemicals {selectedRun ? `(run #${selectedRun.id})` : ''}</h2>
          {!runSum?.top?.length && <div className="dim">No completed trading run — see <Link to="/upload">Upload &amp; Runs</Link>.</div>}
          {!!runSum?.top?.length && (
            <table>
              <thead><tr><th>Chemical</th><th>ATT</th><th>Tier</th></tr></thead>
              <tbody>
                {runSum.top.slice(0, 6).map((c: any) => (
                  <tr key={c.chemical} className="clickable" onClick={() => nav(`/chemical/${encodeURIComponent(c.chemical)}`)}>
                    <td style={{ fontWeight: 600 }}>{c.chemical}</td>
                    <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{c.att_final.toFixed(1)}</td>
                    <td><TierBadge tier={c.tier} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
