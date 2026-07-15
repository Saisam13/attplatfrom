import { useEffect, useState } from 'react'
import { api, RawRow, fmt } from '../api'
import { useRuns } from '../App'

const PAGE = 100

export default function RawDataPage() {
  const { selectedRun, runs, setSelectedId } = useRuns()
  const [rows, setRows] = useState<RawRow[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [chemical, setChemical] = useState('')
  const [matchType, setMatchType] = useState('')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(false)

  useEffect(() => { setPage(0) }, [search, chemical, matchType, selectedRun?.id])

  useEffect(() => {
    if (!selectedRun || selectedRun.status !== 'done') { setRows([]); setTotal(0); return }
    setLoading(true)
    api.raw(selectedRun.id, {
      search, chemical, match_type: matchType,
      limit: String(PAGE), offset: String(page * PAGE),
    }).then(r => { setRows(r.items); setTotal(r.total) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [selectedRun?.id, selectedRun?.status, search, chemical, matchType, page])

  if (!selectedRun) return <div><h1>Raw Data</h1><div className="dim">No run selected.</div></div>

  const mtColor: Record<string, string> = {
    direct: 'var(--green)', llm: 'var(--teal)', near: 'var(--orange)', none: 'var(--grey)',
  }

  return (
    <div>
      <h1>Raw Data — {selectedRun.name}</h1>
      <div className="subtitle">
        Every parsed EXIM row with how it was matched. Match types: direct (≥60% NLP),
        llm (identified by LLM assist), near (40-60%, flagged), none (unmatched → opportunity pool).
      </div>

      <div className="filters">
        <input type="text" placeholder="Search descriptions…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 260 }} />
        <input type="text" placeholder="Chemical (exact)…" value={chemical} onChange={e => setChemical(e.target.value)} style={{ width: 220 }} />
        <select value={matchType} onChange={e => setMatchType(e.target.value)}>
          <option value="">All match types</option>
          <option value="direct">direct</option>
          <option value="llm">llm</option>
          <option value="near">near</option>
          <option value="none">none</option>
        </select>
        <span className="dim">{total.toLocaleString()} rows{loading ? ' · loading…' : ''}</span>
        <button className="ghost" disabled={page === 0} onClick={() => setPage(p => p - 1)}>‹ Prev</button>
        <span className="dim">page {page + 1} / {Math.max(1, Math.ceil(total / PAGE))}</span>
        <button className="ghost" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(p => p + 1)}>Next ›</button>
        
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <label className="dim" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 }}>Active run:</label>
          <select value={selectedRun?.id ?? ''} onChange={e => setSelectedId(Number(e.target.value))} style={{ minWidth: 160 }}>
            {runs.length === 0 && <option value="">— no runs yet —</option>}
            {runs.map(r => (
              <option key={r.id} value={r.id}>#{r.id} {r.name} ({r.status})</option>
            ))}
          </select>
        </div>
      </div>

      <div className="table-scroll">
        <table>
          <thead><tr>
            <th>Date</th><th>HSN</th><th>Description</th><th>Matched chemical</th>
            <th>Match</th><th>Score</th><th>Seller</th><th>From</th><th>Buyer</th><th>To</th>
            <th>Qty KG</th><th>Value</th><th>Unit $</th><th>File</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono dim">{r.date}</td>
                <td className="mono dim">{r.hsn6}</td>
                <td className="dim" style={{ maxWidth: 340, fontSize: 12 }}>{r.desc_clean}</td>
                <td style={{ fontWeight: 600, maxWidth: 200 }}>{r.chemical}</td>
                <td style={{ color: mtColor[r.match_type] || undefined, fontWeight: 600 }}>{r.match_type}</td>
                <td className="mono dim">{(r.match_score ?? 0).toFixed(2)}</td>
                <td style={{ maxWidth: 170, fontSize: 12 }}>{r.seller}</td>
                <td className="dim">{r.seller_country}</td>
                <td style={{ maxWidth: 170, fontSize: 12 }}>{r.buyer}</td>
                <td className="dim">{r.buyer_country}</td>
                <td className="mono">{fmt.num(r.qty_kg)}</td>
                <td className="mono">{fmt.usd(r.value_usd)}</td>
                <td className="mono">{r.unit_price || '—'}</td>
                <td className="mono dim" style={{ maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.file}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !loading && <div className="dim" style={{ padding: 20 }}>No rows.</div>}
      </div>
    </div>
  )
}
