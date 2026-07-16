import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt, EprCompany } from '../api'
import { useRuns } from '../App'
import { AddLeadButton } from '../components/common'

/** EPR Producer Intel — upload CPCB targets file, ranked producer list,
 *  per-row research shortcut + add-as-lead. */
export default function EprPage() {
  const { toast, userName } = useRuns()
  const [items, setItems] = useState<EprCompany[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('priority_score')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [summary, setSummary] = useState<any>(null)
  const [weights, setWeights] = useState({ target_tons: 1.0, credits: 0.5 })
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const nav = useNavigate()
  const [material, setMaterial] = useState('lithium')

  const load = () => {
    api.eprCompanies({ search, sort, order, limit: '500' })
      .then(r => { setItems(r.items); setTotal(r.total); if (r.weights) setWeights(r.weights) })
      .catch(e => toast('error', String(e.message || e)))
    api.eprSummary().then(setSummary).catch(() => {})
  }
  useEffect(load, [search, sort, order])

  const upload = async (file: File, mode: string) => {
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    form.append('mode', mode)
    form.append('material', material)
    form.append('user_name', userName)
    try {
      const res = await api.eprUpload(form)
      toast('success', `EPR upload: ${res.created} new, ${res.updated} updated (${res.total_in_file} rows in file)`)
      load()
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const clickSort = (col: string) => {
    if (sort === col) setOrder(o => (o === 'desc' ? 'asc' : 'desc'))
    else { setSort(col); setOrder('desc') }
  }
  const arrow = (col: string) => (sort === col ? (order === 'desc' ? ' ↓' : ' ↑') : '')

  return (
    <div>
      <h1>EPR Producer Intel</h1>
      <div className="subtitle">
        CPCB “EPR Targets for Producers” intelligence — priority = target × {weights.target_tons.toFixed(1)} +
        credits × {weights.credits.toFixed(1)} (editable in Settings).
        Click a company for the AI Sourcing Agent console.
      </div>

      {summary && (
        <div className="stat-grid" style={{ marginBottom: 16 }}>
          <div className="stat-card"><div className="value">{summary.total_companies}</div><div className="label">Producers</div></div>
          <div className="stat-card"><div className="value">{fmt.num(summary.total_target_tons)}</div><div className="label">Total target (t)</div></div>
          <div className="stat-card"><div className="value">{fmt.num(summary.total_credits)}</div><div className="label">Credits procured (t)</div></div>
          <div className="stat-card"><div className="value" style={{ color: 'var(--orange)' }}>{fmt.num(summary.total_gap_tons)}</div><div className="label">Unmet gap (t)</div></div>
          <div className="stat-card"><div className="value" style={{ color: 'var(--teal)' }}>{summary.researched}</div><div className="label">AI researched</div></div>
        </div>
      )}

      <div className="panel" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <strong>Upload targets file:</strong>
        <select value={material} onChange={e => setMaterial(e.target.value)} disabled={uploading} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}>
          <option value="lithium">Lithium</option>
          <option value="cobalt">Cobalt</option>
          <option value="nickel">Nickel</option>
          <option value="manganese">Manganese</option>
        </select>
        <input ref={fileRef} type="file" accept=".xlsx" disabled={uploading}
          onChange={e => { const f = e.target.files?.[0]; if (f) upload(f, 'merge') }} />
        <button className="ghost" disabled={uploading} title="Wipe the table and load only this file"
          onClick={() => { const f = fileRef.current?.files?.[0]; if (f) upload(f, 'replace'); else toast('error', 'Choose a file first') }}>
          Upload as replace
        </button>
        {uploading && <span className="dim">Uploading…</span>}
        <span className="dim" style={{ fontSize: 12 }}>
          Header row is auto-detected (Producer Name / Target / Credits columns). Re-uploads merge by company name.
        </span>
      </div>

      <div className="filters" style={{ margin: '14px 0' }}>
        <input type="text" placeholder="Search company…" value={search} onChange={e => setSearch(e.target.value)} />
        <span className="dim" style={{ fontSize: 12 }}>{total} producers</span>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="clickable" onClick={() => clickSort('company_name')}>Company{arrow('company_name')}</th>
              <th>State</th>
              <th className="clickable" onClick={() => clickSort('target_tons')}>Target (t){arrow('target_tons')}</th>
              <th className="clickable" onClick={() => clickSort('credits')}>Credits (t){arrow('credits')}</th>
              <th className="clickable" onClick={() => clickSort('gap_tons')}>Gap (t){arrow('gap_tons')}</th>
              <th className="clickable" onClick={() => clickSort('priority_score')}>Priority{arrow('priority_score')}</th>
              <th>Research</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map(c => (
              <tr key={c.id} className="clickable" onClick={() => nav(`/epr/${c.id}`)}>
                <td style={{ fontWeight: 600 }}>{c.company_name}</td>
                <td className="dim">{c.state || '—'}</td>
                <td className="mono">{fmt.num(c.target_tons)}</td>
                <td className="mono">{fmt.num(c.credits)}</td>
                <td className="mono" style={{ color: c.gap_tons > 0 ? 'var(--orange)' : 'var(--dim)' }}>{fmt.num(c.gap_tons)}</td>
                <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{c.priority_score.toFixed(1)}</td>
                <td>{c.has_research
                  ? <span className="success" style={{ fontSize: 12 }}>✓ done</span>
                  : <button className="ghost" onClick={e => { e.stopPropagation(); nav(`/epr/${c.id}?research=1`) }}>AI research</button>}
                </td>
                <td onClick={e => e.stopPropagation()}>
                  <AddLeadButton name={c.company_name} leadType="epr" source="epr"
                    entityKind="epr_company" entityRef={c.id}
                    data={{ target_tons: c.target_tons, credits: c.credits, gap_tons: c.gap_tons, priority_score: c.priority_score, state: c.state }} />
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={8} className="dim" style={{ textAlign: 'center', padding: 30 }}>
                No producers yet — upload the CPCB EPR targets .xlsx above.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
