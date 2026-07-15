import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, download, fmt } from '../api'
import { useRuns } from '../App'
import { StageBadge } from '../components/common'

/** Weekly sales digest — always shows the current week; one-click branded PDF. */
export default function DigestPage() {
  const { toast } = useRuns()
  const [d, setD] = useState<any>(null)
  const nav = useNavigate()

  useEffect(() => {
    api.digest().then(setD).catch(e => toast('error', String(e.message || e)))
  }, [])

  if (!d) return <div><h1>Weekly Digest</h1><div className="dim">Building digest…</div></div>

  const p = d.pipeline
  const followupRows: any[] = []
  Object.entries(d.followups || {}).forEach(([owner, buckets]: [string, any]) => {
    buckets.overdue.forEach((i: any) => followupRows.push({ ...i, owner, overdue: true }))
    buckets.today.forEach((i: any) => followupRows.push({ ...i, owner, overdue: false }))
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h1 style={{ marginBottom: 2 }}>Weekly Digest</h1>
          <div className="subtitle">Last {d.period_days} days · generated {new Date(d.generated_at + 'Z').toLocaleString()}</div>
        </div>
        <button onClick={() => download('/api/digest/pdf', `Sales_Digest_${new Date().toISOString().slice(0, 10)}.pdf`)
          .catch(e => toast('error', String(e.message || e)))}>
          ⬇ Branded PDF
        </button>
      </div>

      <div className="stat-grid" style={{ margin: '14px 0' }}>
        <div className="stat-card"><div className="value">{p.total_leads}</div><div className="label">Total leads</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--teal)' }}>{p.new_leads}</div><div className="label">New this week</div></div>
        <div className="stat-card"><div className="value">{p.stage_changes}</div><div className="label">Stage changes</div></div>
        <div className="stat-card"><div className="value">{p.outreach_touches}</div><div className="label">Outreach touches</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--green)' }}>{p.deals}</div><div className="label">Deals</div></div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(430px, 1fr))', gap: 18 }}>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Follow-ups due / overdue</h2>
          {followupRows.length === 0 && <div className="dim">All caught up ✓</div>}
          {followupRows.length > 0 && (
            <table>
              <thead><tr><th>Owner</th><th>Lead</th><th>Stage</th><th>Due</th></tr></thead>
              <tbody>
                {followupRows.map((r, i) => (
                  <tr key={i} className="clickable" onClick={() => nav('/leads')}>
                    <td>{r.owner}</td>
                    <td style={{ fontWeight: 600 }}>{r.name}</td>
                    <td><StageBadge stage={r.stage} /></td>
                    <td className="mono" style={{ color: r.overdue ? 'var(--red)' : 'var(--orange)' }}>{r.next_followup}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>This week's pipeline activity</h2>
          {p.new_lead_items.length === 0 && p.stage_change_items.length === 0 && <div className="dim">No activity this week.</div>}
          {p.new_lead_items.length > 0 && (
            <>
              <h3>New leads</h3>
              <table>
                <tbody>
                  {p.new_lead_items.map((l: any) => (
                    <tr key={l.id} className="clickable" onClick={() => nav('/leads')}>
                      <td style={{ fontWeight: 600 }}>{l.name}</td>
                      <td><span className="chip">{l.lead_type}</span></td>
                      <td><StageBadge stage={l.stage} /></td>
                      <td className="dim">{l.owner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {p.stage_change_items.length > 0 && (
            <>
              <h3>Stage changes</h3>
              {p.stage_change_items.map((e: any, i: number) => (
                <div key={i} style={{ fontSize: 13, padding: '3px 0' }}>
                  <span className="dim">{e.at ? new Date(e.at + 'Z').toLocaleDateString() : ''}</span> {e.text}
                  <span className="dim"> — {e.user_name}</span>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Top EPR producers</h2>
          {d.top_epr.length === 0 && <div className="dim">No EPR data uploaded.</div>}
          {d.top_epr.length > 0 && (
            <table>
              <thead><tr><th>Company</th><th>Gap (t)</th><th>Priority</th><th></th></tr></thead>
              <tbody>
                {d.top_epr.map((c: any) => (
                  <tr key={c.id} className="clickable" onClick={() => nav(`/epr/${c.id}`)}>
                    <td style={{ fontWeight: 600 }}>
                      {c.company_name}
                      {c.is_new && <span className="chip" style={{ marginLeft: 6, color: 'var(--teal)' }}>NEW</span>}
                    </td>
                    <td className="mono" style={{ color: 'var(--orange)' }}>{fmt.num(c.gap_tons)}</td>
                    <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{c.priority_score.toFixed(1)}</td>
                    <td className="dim" style={{ fontSize: 12 }}>{c.has_research ? '✓ researched' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Market movers &amp; prices</h2>
          {d.movers.length > 0 && (
            <>
              <h3>ATT movers ({d.movers_runs.join(' vs ')})</h3>
              <table>
                <tbody>
                  {d.movers.map((m: any) => (
                    <tr key={m.chemical} className="clickable" onClick={() => nav(`/chemical/${encodeURIComponent(m.chemical)}`)}>
                      <td style={{ fontWeight: 600 }}>{m.chemical}</td>
                      <td className={m.delta >= 0 ? 'delta-up' : 'delta-down'}>{m.delta > 0 ? '+' : ''}{m.delta.toFixed(1)}</td>
                      <td className="dim">{m.tier_b} → {m.tier_a}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {d.price_watch.length > 0 && (
            <>
              <h3>Battery feedstock price watch</h3>
              <table>
                <thead><tr><th>Category</th><th>Median $/kg</th><th>Change</th></tr></thead>
                <tbody>
                  {d.price_watch.map((c: any) => (
                    <tr key={c.category}>
                      <td>{c.category}</td>
                      <td className="mono">${(c.median_price || 0).toFixed(2)}</td>
                      <td className={c.change_pct == null ? 'dim' : c.change_pct >= 0 ? 'delta-up' : 'delta-down'}>
                        {c.change_pct == null ? '—' : `${c.change_pct > 0 ? '+' : ''}${c.change_pct}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {d.movers.length === 0 && d.price_watch.length === 0 && (
            <div className="dim">Needs two completed runs for movers / battery runs for prices.</div>
          )}
        </div>
      </div>
    </div>
  )
}
