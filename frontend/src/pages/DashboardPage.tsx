import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, download, fmt } from '../api'
import { useRuns } from '../App'
import { TierBadge } from '../components/common'

export default function DashboardPage() {
  const { selectedRun, batteryRuns, toast } = useRuns()
  const [summary, setSummary] = useState<any>(null)
  const nav = useNavigate()

  useEffect(() => {
    if (selectedRun?.status === 'done') {
      api.summary(selectedRun.id).then(setSummary).catch(() => setSummary(null))
    } else {
      setSummary(null)
    }
  }, [selectedRun?.id, selectedRun?.status])

  const latestBattery = batteryRuns.find(r => r.status === 'done')

  if (!selectedRun) {
    return (
      <div>
        <h1>Dashboard</h1>
        <div className="subtitle">No runs yet.</div>
        <div className="panel">
          Start by uploading EXIM trade data on the <Link to="/upload">Upload &amp; Runs</Link> page,
          or battery-scrap data on the <Link to="/battery">Battery Procurement</Link> page.
        </div>
      </div>
    )
  }

  const stats = selectedRun.stats || {}
  const tiers = stats.tiers || {}

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="subtitle">
        Active run: #{selectedRun.id} “{selectedRun.name}”
        {selectedRun.created_at ? ` · ${new Date(selectedRun.created_at + 'Z').toLocaleString()}` : ''}
      </div>

      {(selectedRun.status === 'running' || selectedRun.status === 'queued') && (
        <div className="panel">
          <div className="progress-outer">
            <div className="progress-inner" style={{ width: `${Math.max(selectedRun.progress, 4)}%` }}>
              {selectedRun.progress}%
            </div>
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{selectedRun.stage}</div>
        </div>
      )}
      {selectedRun.status === 'error' && <div className="panel error">✗ {selectedRun.error}</div>}

      {selectedRun.status === 'done' && (
        <>
          <div className="stat-grid" style={{ marginBottom: 18 }}>
            <div className="stat-card"><div className="value">{stats.base_chemicals ?? '—'}</div><div className="label">Base chemicals</div></div>
            <div className="stat-card"><div className="value">{stats.opportunity_chemicals ?? '—'}</div><div className="label">Opportunity pool</div></div>
            <div className="stat-card"><div className="value" style={{ color: 'var(--green)' }}>{tiers.A ?? 0}</div><div className="label">Tier A</div></div>
            <div className="stat-card"><div className="value" style={{ color: 'var(--orange)' }}>{tiers.B ?? 0}</div><div className="label">Tier B</div></div>
            <div className="stat-card"><div className="value">{(stats.total_rows ?? 0).toLocaleString()}</div><div className="label">EXIM rows</div></div>
            <div className="stat-card"><div className="value">{stats.geo_anomalies ?? 0}</div><div className="label">Geo anomalies</div></div>
            <div className="stat-card"><div className="value">{summary?.feedback_count ?? 0}</div><div className="label">Feedback entries</div></div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(430px, 1fr))', gap: 18 }}>
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>Top 10 by attractiveness</h2>
              <table>
                <thead><tr><th>#</th><th>Chemical</th><th>ATT</th><th>Tier</th><th>Trend</th></tr></thead>
                <tbody>
                  {(summary?.top || []).map((c: any, i: number) => (
                    <tr key={c.chemical} className="clickable" onClick={() => nav(`/chemical/${encodeURIComponent(c.chemical)}`)}>
                      <td className="dim">{i + 1}</td>
                      <td style={{ fontWeight: 600 }}>{c.chemical}</td>
                      <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{c.att_final.toFixed(1)}</td>
                      <td><TierBadge tier={c.tier} /></td>
                      <td className="dim">{c.trend_direction}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="panel">
              <h2 style={{ marginTop: 0 }}>
                Biggest movers {summary?.prev_run ? `vs #${summary.prev_run.id} ${summary.prev_run.name}` : ''}
              </h2>
              {(summary?.movers || []).length === 0 && (
                <div className="dim">
                  {summary?.prev_run
                    ? 'No overlapping chemicals with the previous run.'
                    : 'No previous completed run to compare against.'}
                </div>
              )}
              {(summary?.movers || []).length > 0 && (
                <table>
                  <thead><tr><th>Chemical</th><th>Δ ATT</th><th>Rank</th><th>Tier</th></tr></thead>
                  <tbody>
                    {summary.movers.map((m: any) => (
                      <tr key={m.chemical} className="clickable" onClick={() => nav(`/chemical/${encodeURIComponent(m.chemical)}`)}>
                        <td style={{ fontWeight: 600 }}>{m.chemical}</td>
                        <td className={m.delta >= 0 ? 'delta-up' : 'delta-down'}>{m.delta > 0 ? '+' : ''}{m.delta.toFixed(1)}</td>
                        <td className="mono dim">{m.rank_b} → {m.rank_a}</td>
                        <td className="dim">{m.tier_b === m.tier_a ? m.tier_a : `${m.tier_b} → ${m.tier_a}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {summary?.prev_run && (
                <div style={{ marginTop: 10 }}>
                  <Link to="/compare">Full comparison →</Link>
                  {(summary.new_chemicals > 0 || summary.dropped_chemicals > 0) && (
                    <span className="dim" style={{ marginLeft: 10, fontSize: 12 }}>
                      {summary.new_chemicals} new · {summary.dropped_chemicals} dropped
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="panel" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <strong>Exports:</strong>
            <button className="ghost" onClick={() =>
              download(`/api/runs/${selectedRun.id}/export`, `ATT_Results_Run${selectedRun.id}.xlsx`)
                .catch(e => toast('error', String(e.message || e)))}>
              9-tab workbook (.xlsx)
            </button>
            <button className="ghost" onClick={() =>
              download(`/api/runs/${selectedRun.id}/report.pdf`, `ATT_Summary_Run${selectedRun.id}.pdf`)
                .catch(e => toast('error', String(e.message || e)))}>
              PDF summary report
            </button>
            {latestBattery && (
              <button className="ghost" onClick={() =>
                download(`/api/runs/${latestBattery.id}/battery/export`, `Battery_Procurement_Run${latestBattery.id}.xlsx`)
                  .catch(e => toast('error', String(e.message || e)))}>
                Battery workbook (#{latestBattery.id})
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
