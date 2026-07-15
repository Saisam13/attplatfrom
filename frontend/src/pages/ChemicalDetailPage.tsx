import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar,
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  LineChart, Line,
} from 'recharts'
import { api, Chemical, RawRow, fmt } from '../api'
import { useRuns } from '../App'
import { TierBadge, PoolBadge, FeedbackButtons } from '../components/common'

export default function ChemicalDetailPage() {
  const { name } = useParams()
  const { selectedRun } = useRuns()
  const [c, setC] = useState<Chemical | null>(null)
  const [history, setHistory] = useState<any[]>([])
  const [drill, setDrill] = useState<{ kind: 'buyer' | 'seller'; name: string } | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!selectedRun || !name) return
    api.chemicalDetail(selectedRun.id, name).then(setC).catch(e => setErr(String(e.message || e)))
    api.chemicalHistory(name).then(setHistory).catch(() => {})
  }, [selectedRun?.id, name])

  if (err) return <div><h1>{name}</h1><div className="error">{err}</div></div>
  if (!c || !selectedRun) return <div className="dim">Loading…</div>

  const radar = Object.entries(c.scores).map(([dim, v]) => ({ dim: dim.toUpperCase(), score: Math.round(v * 10) / 10 }))
  const monthly = (c.monthly || []).map(m => ({ ...m, label: m.month + (m.excluded ? ' *' : '') }))
  const ps = c.detail?.price_stats
  const priceSeries = Object.entries(c.detail?.monthly_price_medians || {})
    .map(([month, price]) => ({ month, price }))

  return (
    <div>
      <Link to="/rankings" className="dim">← Back to rankings</Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginTop: 8 }}>
        <h1 style={{ margin: 0 }}>{c.chemical}</h1>
        <TierBadge tier={c.tier} />
        <PoolBadge pool={c.pool} />
        <span className="chip mono">HSN {c.hsn_codes}</span>
        <FeedbackButtons runId={selectedRun.id} chemical={c.chemical} />
      </div>

      <div className="stat-grid" style={{ margin: '18px 0' }}>
        <div className="stat-card"><div className="value">{c.att_final.toFixed(1)}</div><div className="label">ATT Final</div></div>
        <div className="stat-card"><div className="value">{c.att_india.toFixed(1)}</div><div className="label">ATT India (+{c.rodtep_bonus.toFixed(1)} RoDTEP, +{c.drawback_bonus.toFixed(1)} DBK)</div></div>
        <div className="stat-card"><div className="value">{fmt.num(c.shipments)}</div><div className="label">Shipments</div></div>
        <div className="stat-card"><div className="value">{fmt.usd(c.total_value_usd)}</div><div className="label">Total value</div></div>
        <div className="stat-card"><div className="value">{fmt.num(c.total_qty_kg)}</div><div className="label">Total qty (KG)</div></div>
        <div className="stat-card"><div className="value">{c.trend_direction} {c.growth_rate ? `(${c.growth_rate > 0 ? '+' : ''}${c.growth_rate}%)` : ''}</div><div className="label">Trend</div></div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 18 }}>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Dimension scores (percentile-normalized)</h2>
          <ResponsiveContainer width="100%" height={300}>
            <RadarChart data={radar}>
              <PolarGrid stroke="#294962" />
              <PolarAngleAxis dataKey="dim" tick={{ fill: '#9db4c4', fontSize: 11 }} />
              <PolarRadiusAxis domain={[0, 100]} tick={{ fill: '#9db4c4', fontSize: 10 }} />
              <Radar dataKey="score" stroke="#04aed1" fill="#04aed1" fillOpacity={0.35} />
              <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }} />
            </RadarChart>
          </ResponsiveContainer>
          <div className="dim" style={{ fontSize: 12 }}>
            Variance: <strong>{c.variance_type}</strong> ({c.variance_mod > 0 ? '+' : ''}{c.variance_mod} modifier) ·
            Reg factor: <strong>{c.reg_factor}</strong> · ATT base: {c.att_base.toFixed(1)}
          </div>
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Monthly shipment trend</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={monthly}>
              <XAxis dataKey="label" tick={{ fill: '#9db4c4', fontSize: 10 }} angle={-45} textAnchor="end" height={60} />
              <YAxis tick={{ fill: '#9db4c4', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }}
                formatter={(v: any, k: any) => [v, k]} />
              <Bar dataKey="shipments">
                {monthly.map((m, i) => (
                  <Cell key={i} fill={m.excluded ? '#f39c12' : '#4c9eaf'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="excluded-mark">* orange months are excluded from trend regression (still displayed)</div>
        </div>

        {priceSeries.length > 1 && (
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Monthly median unit price</h2>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={priceSeries}>
                <XAxis dataKey="month" tick={{ fill: '#9db4c4', fontSize: 10 }} angle={-45} textAnchor="end" height={60} />
                <YAxis tick={{ fill: '#9db4c4', fontSize: 10 }} domain={['auto', 'auto']} />
                <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }}
                  formatter={(v: any) => ['$' + v, 'median price']} />
                <Line type="monotone" dataKey="price" stroke="#04aed1" strokeWidth={2} dot={{ r: 3, fill: '#04aed1' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {history.length > 1 && (
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>ATT history across runs</h2>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={history}>
                <XAxis dataKey="run_id" tick={{ fill: '#9db4c4', fontSize: 10 }}
                  tickFormatter={(id: any) => '#' + id} />
                <YAxis domain={[0, 100]} tick={{ fill: '#9db4c4', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }}
                  labelFormatter={(id: any) => {
                    const h = history.find(x => x.run_id === id)
                    return h ? `#${id} ${h.run_name}` : `#${id}`
                  }} />
                <Line type="monotone" dataKey="att_final" stroke="#3b6e93" strokeWidth={2} dot={{ r: 4, fill: '#04aed1' }} />
              </LineChart>
            </ResponsiveContainer>
            <table style={{ marginTop: 6 }}>
              <thead><tr><th>Run</th><th>ATT</th><th>Fb adj</th><th>Tier</th></tr></thead>
              <tbody>
                {history.slice(-6).map(h => (
                  <tr key={h.run_id}>
                    <td className="dim">#{h.run_id} {h.run_name}</td>
                    <td className="mono">{h.att_final?.toFixed(1)}</td>
                    <td className="mono dim">{h.feedback_adj ? (h.feedback_adj > 0 ? '+' : '') + h.feedback_adj : '—'}</td>
                    <td>{h.tier}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {ps && (
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Price statistics</h2>
            <table>
              <tbody>
                <tr><td className="dim">Median $/unit</td><td className="mono">${ps.median}</td><td className="dim">IQR</td><td className="mono">${ps.iqr}</td></tr>
                <tr><td className="dim">P5 / P95</td><td className="mono">${ps.p5} / ${ps.p95}</td><td className="dim">CV %</td><td className="mono">{ps.cv_pct}%</td></tr>
                <tr><td className="dim">Min / Max (clean)</td><td className="mono">${ps.min} / ${ps.max}</td><td className="dim">Outliers removed</td><td className="mono">{ps.outliers_removed} of {ps.raw_prices}</td></tr>
                <tr><td className="dim">Highest country</td><td colSpan={3}>{ps.highest_country || '—'}</td></tr>
                <tr><td className="dim">Lowest country</td><td colSpan={3}>{ps.lowest_country || '—'}</td></tr>
              </tbody>
            </table>
            {ps.spread_opportunity && <div style={{ marginTop: 10, color: 'var(--teal)' }}>💡 {ps.spread_opportunity}</div>}
            <div className="dim" style={{ marginTop: 10, fontSize: 12 }}>
              Variance classification: <strong>{c.variance_type}</strong> — {
                c.variance_type === 'opportunity' ? 'geographic price differences dominate (arbitrage potential, +5 bonus)' :
                c.variance_type === 'risk' ? 'temporal price swings dominate (instability, -10 penalty)' :
                'no dominant variance pattern (no modifier)'}
            </div>
          </div>
        )}

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Top buyers &amp; suppliers</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <div className="dim" style={{ marginBottom: 6 }}>BUYERS ({c.detail?.top_buyer_countries?.map((x: any) => x[0]).slice(0, 3).join(', ')})</div>
              {(c.detail?.top_buyers || []).slice(0, 8).map(([b, n]: [string, number]) => (
                <div key={b} style={{ fontSize: 12, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span className="linkish" onClick={() => setDrill({ kind: 'buyer', name: b })}>{b}</span> <span className="dim">({n})</span>
                </div>
              ))}
            </div>
            <div>
              <div className="dim" style={{ marginBottom: 6 }}>SUPPLIERS — India {c.detail?.india_pct}%</div>
              {(c.detail?.top_suppliers || []).slice(0, 8).map(([s, n]: [string, number]) => (
                <div key={s} style={{ fontSize: 12, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span className="linkish" onClick={() => setDrill({ kind: 'seller', name: s })}>{s}</span> <span className="dim">({n})</span>
                </div>
              ))}
            </div>
          </div>
          <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>Click a name to see its raw shipment rows.</div>
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Regulatory status</h2>
          <div>
            <span className={`tier-badge ${c.regulatory?.status === 'clear' ? 'tier-A' : c.regulatory?.status === 'conditional' ? 'tier-B' : 'tier-C'}`}>
              {(c.regulatory?.status || 'clear').toUpperCase()}
            </span>{' '}
            <span className="mono">factor {c.regulatory?.factor}</span>
          </div>
          {c.regulatory?.note && <div className="dim" style={{ marginTop: 8 }}>{c.regulatory.note}</div>}
        </div>

        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Geo anomalies</h2>
          {(c.geo_anomalies || []).length === 0 && <div className="dim">No volume anomalies detected.</div>}
          {(c.geo_anomalies || []).map((g, i) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
              <strong>{g.month}</strong> — {g.direction} (z={g.z_score}, {g.deviation_pct > 0 ? '+' : ''}{g.deviation_pct}%) · adj {g.adj_factor}
              <div className="dim" style={{ fontSize: 12 }}>{g.event}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 18 }}>
        <h2 style={{ marginTop: 0 }}>Reasoning</h2>
        <div>{c.reasoning}</div>
        {c.feedback_adj !== 0 && (
          <div className="dim" style={{ marginTop: 8, fontSize: 13 }}>
            Includes trader-feedback adjustment of {c.feedback_adj > 0 ? '+' : ''}{c.feedback_adj} on ATT.
          </div>
        )}
      </div>

      {drill && (
        <DrilldownModal runId={selectedRun.id} chemical={c.chemical}
          kind={drill.kind} name={drill.name} onClose={() => setDrill(null)} />
      )}
    </div>
  )
}

function DrilldownModal({ runId, chemical, kind, name, onClose }: {
  runId: number; chemical: string; kind: 'buyer' | 'seller'; name: string; onClose: () => void
}) {
  const [rows, setRows] = useState<RawRow[]>([])
  const [total, setTotal] = useState(0)

  useEffect(() => {
    api.raw(runId, { chemical, [kind]: name, limit: '200' })
      .then(r => { setRows(r.items); setTotal(r.total) })
      .catch(() => {})
  }, [runId, chemical, kind, name])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ width: 860, maxHeight: '84vh', overflow: 'auto' }} onClick={e => e.stopPropagation()}>
        <h3>{name} — {total} shipment{total === 1 ? '' : 's'} of {chemical}</h3>
        <table>
          <thead><tr>
            <th>Date</th><th>Description</th><th>{kind === 'buyer' ? 'Seller' : 'Buyer'}</th>
            <th>Country</th><th>Qty KG</th><th>Value</th><th>Unit $</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono dim">{r.date}</td>
                <td className="dim" style={{ maxWidth: 300, fontSize: 12 }}>{r.desc_clean}</td>
                <td style={{ maxWidth: 180, fontSize: 12 }}>{kind === 'buyer' ? r.seller : r.buyer}</td>
                <td className="dim">{kind === 'buyer' ? r.seller_country : r.buyer_country}</td>
                <td className="mono">{fmt.num(r.qty_kg)}</td>
                <td className="mono">{fmt.usd(r.value_usd)}</td>
                <td className="mono">{r.unit_price || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="dim" style={{ padding: 12 }}>No rows found.</div>}
        <div className="actions"><button className="secondary" onClick={onClose}>Close</button></div>
      </div>
    </div>
  )
}
