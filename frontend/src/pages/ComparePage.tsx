import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, Mover } from '../api'
import { useRuns } from '../App'

export default function ComparePage() {
  const { runs } = useRuns()
  const nav = useNavigate()
  const done = runs.filter(r => r.status === 'done')
  const [aId, setAId] = useState<number | null>(null)
  const [bId, setBId] = useState<number | null>(null)
  const [data, setData] = useState<{ movers: Mover[]; new: any[]; dropped: any[] } | null>(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('')

  useEffect(() => {
    if (aId == null && done.length > 0) setAId(done[0].id)
    if (bId == null && done.length > 1) setBId(done[1].id)
  }, [done.length])  // eslint-disable-line

  useEffect(() => {
    if (aId == null || bId == null || aId === bId) { setData(null); return }
    setErr('')
    api.compare(aId, bId).then(setData).catch(e => setErr(String(e.message || e)))
  }, [aId, bId])

  const movers = (data?.movers || []).filter(m =>
    !filter || m.chemical.toLowerCase().includes(filter.toLowerCase()))
  const gainers = movers.filter(m => m.delta > 0).slice(0, 400)
  const losers = movers.filter(m => m.delta < 0).slice(0, 400)

  return (
    <div>
      <h1>Run Compare</h1>
      <div className="subtitle">Which chemicals moved up or down between two runs.</div>

      {done.length < 2 && <div className="panel dim">Need at least two completed runs to compare.</div>}

      {done.length >= 2 && (
        <>
          <div className="filters">
            <label className="dim">Current</label>
            <select value={aId ?? ''} onChange={e => setAId(Number(e.target.value))}>
              {done.map(r => <option key={r.id} value={r.id}>#{r.id} {r.name}</option>)}
            </select>
            <label className="dim">vs previous</label>
            <select value={bId ?? ''} onChange={e => setBId(Number(e.target.value))}>
              {done.map(r => <option key={r.id} value={r.id}>#{r.id} {r.name}</option>)}
            </select>
            <input type="text" placeholder="Filter chemical…" value={filter} onChange={e => setFilter(e.target.value)} />
            {data && (
              <span className="dim">
                {data.movers.length} in both · {data.new.length} new · {data.dropped.length} dropped
              </span>
            )}
          </div>
          {err && <div className="error">{err}</div>}
          {aId === bId && <div className="dim">Pick two different runs.</div>}

          {data && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(430px, 1fr))', gap: 18 }}>
              <MoverTable title="▲ Gainers" rows={gainers} up onOpen={c => nav(`/chemical/${encodeURIComponent(c)}`)} />
              <MoverTable title="▼ Losers" rows={losers} onOpen={c => nav(`/chemical/${encodeURIComponent(c)}`)} />
              <div className="panel">
                <h2 style={{ marginTop: 0 }}>New in current run ({data.new.length})</h2>
                {data.new.slice(0, 30).map(n => (
                  <div key={n.chemical} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                    <span className="linkish" onClick={() => nav(`/chemical/${encodeURIComponent(n.chemical)}`)}>{n.chemical}</span>
                    <span className="mono" style={{ float: 'right', color: 'var(--teal)' }}>{n.att_a?.toFixed(1)} ({n.tier_a})</span>
                  </div>
                ))}
                {data.new.length === 0 && <div className="dim">None</div>}
              </div>
              <div className="panel">
                <h2 style={{ marginTop: 0 }}>Dropped since previous ({data.dropped.length})</h2>
                {data.dropped.slice(0, 30).map(n => (
                  <div key={n.chemical} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                    {n.chemical}
                    <span className="mono dim" style={{ float: 'right' }}>{n.att_b?.toFixed(1)} ({n.tier_b})</span>
                  </div>
                ))}
                {data.dropped.length === 0 && <div className="dim">None</div>}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function MoverTable({ title, rows, up, onOpen }: {
  title: string; rows: Mover[]; up?: boolean; onOpen: (c: string) => void
}) {
  return (
    <div className="panel">
      <h2 style={{ marginTop: 0, color: up ? 'var(--green)' : 'var(--red)' }}>{title} ({rows.length})</h2>
      <div style={{ maxHeight: '52vh', overflow: 'auto' }}>
        <table>
          <thead><tr><th>Chemical</th><th>Prev</th><th>Now</th><th>Δ ATT</th><th>Rank</th><th>Tier</th></tr></thead>
          <tbody>
            {rows.map(m => (
              <tr key={m.chemical} className="clickable" onClick={() => onOpen(m.chemical)}>
                <td style={{ fontWeight: 600, maxWidth: 220 }}>{m.chemical}</td>
                <td className="mono dim">{m.att_b.toFixed(1)}</td>
                <td className="mono">{m.att_a.toFixed(1)}</td>
                <td className={m.delta >= 0 ? 'delta-up' : 'delta-down'}>{m.delta > 0 ? '+' : ''}{m.delta.toFixed(1)}</td>
                <td className="mono dim">{m.rank_b}→{m.rank_a}</td>
                <td className="dim">{m.tier_b === m.tier_a ? m.tier_a : `${m.tier_b}→${m.tier_a}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="dim">None</div>}
      </div>
    </div>
  )
}
