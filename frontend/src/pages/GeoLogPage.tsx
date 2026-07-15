import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useRuns } from '../App'

export default function GeoLogPage() {
  const { selectedRun } = useRuns()
  const nav = useNavigate()
  const [rows, setRows] = useState<any[]>([])
  const [filter, setFilter] = useState('')

  useEffect(() => {
    if (!selectedRun || selectedRun.status !== 'done') { setRows([]); return }
    api.geo(selectedRun.id, filter).then(setRows).catch(() => {})
  }, [selectedRun?.id, selectedRun?.status, filter])

  if (!selectedRun) return <div><h1>Geo Anomalies</h1><div className="dim">No run selected.</div></div>

  return (
    <div>
      <h1>Geo Anomalies — {selectedRun.name}</h1>
      <div className="subtitle">
        Monthly trade volumes deviating &gt;2σ from a chemical's mean, correlated with known
        geopolitical events (sanctions, tariffs, shipping disruptions). The adjustment factor
        dampens the trend score so one-off shocks don't masquerade as demand shifts.
      </div>

      <div className="filters">
        <input type="text" placeholder="Filter by chemical…" value={filter} onChange={e => setFilter(e.target.value)} style={{ width: 260 }} />
        <span className="dim">{rows.length} anomalies</span>
      </div>

      <div className="table-scroll">
        <table>
          <thead><tr>
            <th>Chemical</th><th>Month</th><th>Direction</th><th>Z-score</th>
            <th>Deviation</th><th>Adj factor</th><th>Correlated event</th>
          </tr></thead>
          <tbody>
            {rows.map((g, i) => (
              <tr key={i} className="clickable" onClick={() => nav(`/chemical/${encodeURIComponent(g.chemical)}`)}>
                <td style={{ fontWeight: 600, maxWidth: 220 }}>{g.chemical}</td>
                <td className="mono">{g.month}</td>
                <td style={{ color: g.direction === 'spike' ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                  {g.direction === 'spike' ? '▲ spike' : '▼ drop'}
                </td>
                <td className="mono">{g.z_score?.toFixed(2)}</td>
                <td className="mono">{g.deviation_pct > 0 ? '+' : ''}{g.deviation_pct?.toFixed(0)}%</td>
                <td className="mono">{g.adj_factor?.toFixed(2)}</td>
                <td className="dim" style={{ maxWidth: 420, fontSize: 12 }}>{g.event}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="dim" style={{ padding: 20 }}>No anomalies detected in this run.</div>}
      </div>
    </div>
  )
}
