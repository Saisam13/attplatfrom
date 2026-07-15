import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, download, fmt, BatteryCategory } from '../api'
import { useRuns } from '../App'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
  LineChart, Line, Legend,
} from 'recharts'

const LINE_COLORS = ['#04AED1', '#27AE60', '#F39C12', '#C39BD3', '#E74C3C', '#9FC3DD', '#F7DC6F']

/** Battery Dashboard — KPIs, all categories and the price watch in one place. */
export default function BatteryDashboardPage() {
  const { batteryRuns, selectedBatteryRun, setSelectedBatteryId, toast } = useRuns()
  const [cats, setCats] = useState<BatteryCategory[]>([])

  useEffect(() => {
    if (selectedBatteryRun?.status === 'done') {
      api.batteryCategories(selectedBatteryRun.id).then(setCats).catch(() => setCats([]))
    } else {
      setCats([])
    }
  }, [selectedBatteryRun?.id, selectedBatteryRun?.status])

  // price watch: avg $/kg per month per category (value/qty from monthly aggregates)
  const priceSeries = useMemo(() => {
    const months = new Set<string>()
    cats.forEach(c => c.monthly.forEach(m => months.add(m.month)))
    return Array.from(months).sort().map(month => {
      const row: any = { month }
      cats.forEach(c => {
        const m = c.monthly.find(x => x.month === month)
        if (m && m.qty_kg > 0) row[c.category] = +(m.value_usd / m.qty_kg).toFixed(2)
      })
      return row
    })
  }, [cats])

  const totals = useMemo(() => ({
    shipments: cats.reduce((s, c) => s + c.shipments, 0),
    qty: cats.reduce((s, c) => s + c.qty_kg, 0),
    value: cats.reduce((s, c) => s + c.value_usd, 0),
    suppliers: cats.reduce((s, c) => s + c.n_suppliers, 0),
    buyers: cats.reduce((s, c) => s + c.n_buyers, 0),
  }), [cats])

  return (
    <div>
      <h1>Battery Dashboard</h1>
      <div className="subtitle">
        Feedstock market overview — categories, volumes and the price watch in one place.
        Rank counterparties on <Link to="/battery">Suppliers &amp; Buyers</Link>.
      </div>

      {batteryRuns.length === 0 && (
        <div className="panel dim">
          No battery runs yet — upload battery-scrap EXIM files on the <Link to="/battery">Suppliers &amp; Buyers</Link> page.
        </div>
      )}

      {batteryRuns.length > 0 && (
        <div className="filters">
          <label className="dim">Battery run</label>
          <select value={selectedBatteryRun?.id ?? ''} onChange={e => setSelectedBatteryId(Number(e.target.value))}>
            {batteryRuns.map(r => <option key={r.id} value={r.id}>#{r.id} {r.name} ({r.status})</option>)}
          </select>
          {selectedBatteryRun?.status === 'done' && (
            <button className="ghost" onClick={() =>
              download(`/api/runs/${selectedBatteryRun.id}/battery/export`, `Battery_Procurement_Run${selectedBatteryRun.id}.xlsx`)
                .catch(e => toast('error', String(e.message || e)))}>
              ⬇ Battery workbook
            </button>
          )}
        </div>
      )}

      {selectedBatteryRun?.status === 'done' && cats.length > 0 && (
        <>
          <div className="stat-grid" style={{ margin: '14px 0' }}>
            <div className="stat-card"><div className="value">{cats.length}</div><div className="label">Categories</div></div>
            <div className="stat-card"><div className="value">{fmt.num(totals.shipments)}</div><div className="label">Shipments</div></div>
            <div className="stat-card"><div className="value">{fmt.num(totals.qty)}</div><div className="label">Qty (KG)</div></div>
            <div className="stat-card"><div className="value">{fmt.usd(totals.value)}</div><div className="label">Value</div></div>
            <div className="stat-card"><div className="value">{totals.suppliers}</div><div className="label">Suppliers</div></div>
            <div className="stat-card"><div className="value">{totals.buyers}</div><div className="label">Buyers</div></div>
          </div>

          {priceSeries.length > 1 && (
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>Price watch — avg $/kg per category by month</h2>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={priceSeries}>
                  <XAxis dataKey="month" tick={{ fill: '#9db4c4', fontSize: 10 }} angle={-40} textAnchor="end" height={52} />
                  <YAxis tick={{ fill: '#9db4c4', fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {cats.map((c, i) => (
                    <Line key={c.category} type="monotone" dataKey={c.category} connectNulls
                      stroke={LINE_COLORS[i % LINE_COLORS.length]} strokeWidth={2} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
              <div className="dim" style={{ fontSize: 11 }}>
                Avg $/kg = monthly value ÷ monthly quantity per category — quote with current market context.
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 18, marginTop: 18 }}>
            {cats.map(c => (
              <div className="panel" key={c.category}>
                <h2 style={{ marginTop: 0 }}>{c.category}</h2>
                <div className="stat-grid" style={{ marginBottom: 10 }}>
                  <div className="stat-card"><div className="value">{fmt.num(c.shipments)}</div><div className="label">Shipments</div></div>
                  <div className="stat-card"><div className="value">{fmt.num(c.qty_kg)}</div><div className="label">Qty (KG)</div></div>
                  <div className="stat-card"><div className="value">{fmt.usd(c.value_usd)}</div><div className="label">Value</div></div>
                  <div className="stat-card"><div className="value">{c.median_price ? '$' + c.median_price : '—'}</div><div className="label">Median price</div></div>
                  <div className="stat-card"><div className="value">{c.n_suppliers}</div><div className="label">Suppliers</div></div>
                  <div className="stat-card"><div className="value">{c.n_buyers}</div><div className="label">Buyers</div></div>
                </div>
                <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
                  Top origins: {c.top_countries.slice(0, 5).map(([co, n]) => `${co} (${n})`).join(', ') || '—'}
                </div>
                {c.monthly.length > 1 && (
                  <ResponsiveContainer width="100%" height={140}>
                    <BarChart data={c.monthly}>
                      <XAxis dataKey="month" tick={{ fill: '#9db4c4', fontSize: 9 }} angle={-45} textAnchor="end" height={46} />
                      <YAxis tick={{ fill: '#9db4c4', fontSize: 9 }} allowDecimals={false} />
                      <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }} />
                      <Bar dataKey="shipments">
                        {c.monthly.map((_, i) => <Cell key={i} fill="#04aed1" />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {selectedBatteryRun?.status === 'done' && cats.length === 0 && (
        <div className="panel dim">No categories found in this run.</div>
      )}
    </div>
  )
}
