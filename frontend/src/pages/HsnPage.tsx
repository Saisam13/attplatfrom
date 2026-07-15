import { useEffect, useState } from 'react'
import { api, fmt, HsnEntry } from '../api'
import { useRuns } from '../App'
import { AddLeadButton } from '../components/common'

/** HSN Explorer: find codes (search / AI suggest / drill-down), see which
 *  exist in OUR data vs the EXTERNAL directory, map codes to products, and
 *  pull ranked buyer/supplier lead lists per code. */
export default function HsnPage() {
  const [tab, setTab] = useState<'explore' | 'map'>('explore')
  return (
    <div>
      <h1>HSN Explorer</h1>
      <div className="subtitle">
        WCO Harmonized System directory (bundled open dataset) + your uploaded EXIM data.
        <span className="src-badge src-ours" style={{ marginLeft: 8 }}>ours</span> = seen in uploaded shipments ·
        <span className="src-badge src-external" style={{ marginLeft: 4 }}>external</span> = directory info only.
      </div>
      <div className="tabs" style={{ marginBottom: 14 }}>
        <button className={tab === 'explore' ? 'active' : ''} onClick={() => setTab('explore')}>Explore codes</button>
        <button className={tab === 'map' ? 'active' : ''} onClick={() => setTab('map')}>Product mappings</button>
      </div>
      {tab === 'explore' ? <Explorer /> : <Mappings />}
    </div>
  )
}

function Explorer() {
  const { toast } = useRuns()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<HsnEntry[] | null>(null)
  const [crumb, setCrumb] = useState<HsnEntry[]>([])
  const [children, setChildren] = useState<HsnEntry[]>([])
  const [selected, setSelected] = useState<string>('')
  const [detail, setDetail] = useState<any>(null)
  const [leadRole, setLeadRole] = useState<'buyer' | 'seller'>('buyer')
  const [leadList, setLeadList] = useState<any>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState<any>(null)

  const loadTree = (code = '') => {
    api.hsnTree(code).then(r => {
      setChildren(r.children)
      if (!code) setCrumb([])
      else if (r.node) {
        setCrumb(prev => {
          const idx = prev.findIndex(c => c.hscode === code)
          if (idx >= 0) return prev.slice(0, idx + 1)
          return [...prev, r.node!]
        })
      }
    }).catch(e => toast('error', String(e.message || e)))
  }
  useEffect(() => loadTree(), [])

  useEffect(() => {
    if (!q.trim()) { setResults(null); return }
    const t = setTimeout(() => {
      api.hsnSearch(q).then(setResults).catch(() => {})
    }, 350)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    if (!selected) return
    setDetail(null); setLeadList(null)
    api.hsnData(selected).then(setDetail).catch(e => toast('error', String(e.message || e)))
  }, [selected])

  useEffect(() => {
    if (!selected) return
    api.hsnLeads(selected, leadRole).then(setLeadList).catch(() => {})
  }, [selected, leadRole])

  const suggest = async () => {
    if (!q.trim()) return
    setSuggesting(true)
    try {
      setSuggestions(await api.hsnSuggest(q))
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setSuggesting(false)
    }
  }

  const rows = results ?? children
  const ours = detail?.ours

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(380px, 4fr) minmax(430px, 6fr)', gap: 18, alignItems: 'start' }}>
      <div className="panel">
        <div style={{ display: 'flex', gap: 8 }}>
          <input style={{ flex: 1 }} type="text" value={q} onChange={e => setQ(e.target.value)}
            placeholder="Search code (2820) or product (manganese oxide)…" />
          <button className="ghost" disabled={suggesting || !q.trim()} title="Ask AI which codes fit this product" onClick={suggest}>
            {suggesting ? '…' : '✨ AI suggest'}
          </button>
        </div>

        {suggestions && (
          <div style={{ margin: '10px 0', padding: 10, background: 'var(--navy)', borderRadius: 8 }}>
            <div className="dim" style={{ fontSize: 11, marginBottom: 6 }}>
              AI suggestions {suggestions.provider ? `(${suggestions.provider})` : ''}{suggestions.note ? ` — ${suggestions.note}` : ''}
            </div>
            {(suggestions.suggestions?.length ? suggestions.suggestions : suggestions.fallback || []).map((s: any) => (
              <div key={s.hscode} className="clickable" style={{ padding: '3px 0', fontSize: 13 }} onClick={() => setSelected(s.hscode)}>
                <span className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{s.hscode}</span> {s.description}
                {s.reason && <div className="dim" style={{ fontSize: 11 }}>{s.reason}</div>}
              </div>
            ))}
            <button className="ghost" style={{ marginTop: 4 }} onClick={() => setSuggestions(null)}>dismiss</button>
          </div>
        )}

        {!results && (
          <div className="crumbs" style={{ marginTop: 10 }}>
            <span className="crumb" onClick={() => { setCrumb([]); loadTree() }}>All chapters</span>
            {crumb.map(c => (
              <span key={c.hscode}>
                <span className="sep"> / </span>
                <span className="crumb" onClick={() => loadTree(c.hscode)}>{c.hscode}</span>
              </span>
            ))}
          </div>
        )}

        <div className="table-scroll" style={{ maxHeight: '58vh', marginTop: 8 }}>
          <table>
            <thead><tr><th>Code</th><th>Description</th><th>Data</th></tr></thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.hscode} className="clickable"
                  onClick={() => { setSelected(r.hscode); if (!results && r.level < 6) loadTree(r.hscode) }}>
                  <td className="mono" style={{ fontWeight: 700, color: selected === r.hscode ? 'var(--teal)' : undefined }}>
                    {r.hscode}{!results && r.level < 6 ? ' ▸' : ''}
                  </td>
                  <td style={{ fontSize: 13 }}>
                    {r.description}
                    {r.mapped.length > 0 && (
                      <div>{r.mapped.map(m => <span key={m.id} className="chip" style={{ marginRight: 4 }}>{m.label}</span>)}</div>
                    )}
                  </td>
                  <td>
                    {r.in_our_data
                      ? <span className="src-badge src-ours" title={`${r.our_shipments} shipments in our data`}>ours ({fmt.num(r.our_shipments)})</span>
                      : <span className="src-badge src-external">external</span>}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={3} className="dim" style={{ padding: 20, textAlign: 'center' }}>No codes found.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        {!selected && <div className="panel dim">Select a code to see its data — sub-types, our shipments, prices, and buyer/supplier lead lists.</div>}
        {selected && detail && (
          <>
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>
                <span className="mono">{selected}</span>
                {detail.external
                  ? <> — {detail.external.description} <span className="src-badge src-external" title={detail.external.source}>external</span></>
                  : <span className="dim"> (not in directory)</span>}
              </h2>
              {detail.mapped?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  Mapped to: {detail.mapped.map((m: any) => <span key={m.id} className="chip" style={{ marginRight: 4 }}>{m.label} ({m.map_type})</span>)}
                </div>
              )}
              <MapAdder code={selected} onAdded={() => api.hsnData(selected).then(setDetail)} />

              <h3>Our data <span className="src-badge src-ours">ours</span></h3>
              {ours?.shipments ? (
                <div className="stat-grid">
                  <div className="stat-card"><div className="value">{fmt.num(ours.shipments)}</div><div className="label">Shipments</div></div>
                  <div className="stat-card"><div className="value">{fmt.num(ours.qty_kg)}</div><div className="label">Qty (kg)</div></div>
                  <div className="stat-card"><div className="value">{fmt.usd(ours.value_usd)}</div><div className="label">Value</div></div>
                  <div className="stat-card"><div className="value">${(ours.median_price || 0).toFixed(2)}</div><div className="label">Median $/kg</div></div>
                </div>
              ) : <div className="dim">No shipments with this code in the uploaded data — directory info only.</div>}

              {ours?.monthly?.length > 1 && (
                <table style={{ marginTop: 10 }}>
                  <thead><tr><th>Month</th><th>Shipments</th><th>Qty (kg)</th><th>Value</th></tr></thead>
                  <tbody>
                    {ours.monthly.slice(-8).map((m: any) => (
                      <tr key={m.month}>
                        <td className="mono">{m.month}</td>
                        <td className="mono">{m.shipments}</td>
                        <td className="mono">{fmt.num(m.qty_kg)}</td>
                        <td className="mono">{fmt.usd(m.value_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {ours?.shipments > 0 && (
              <div className="panel" style={{ marginTop: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h2 style={{ margin: 0 }}>Lead list <span className="src-badge src-ours">ours</span></h2>
                  <div className="tabs">
                    <button className={leadRole === 'buyer' ? 'active' : ''} onClick={() => setLeadRole('buyer')}>Buyers</button>
                    <button className={leadRole === 'seller' ? 'active' : ''} onClick={() => setLeadRole('seller')}>Suppliers</button>
                  </div>
                </div>
                <div className="table-scroll" style={{ maxHeight: '38vh', marginTop: 8 }}>
                  <table>
                    <thead><tr><th>Name</th><th>Country</th><th>Shipments</th><th>Value</th><th>Last seen</th><th></th></tr></thead>
                    <tbody>
                      {(leadList?.items || []).map((l: any) => (
                        <tr key={l.name}>
                          <td style={{ fontWeight: 600 }}>{l.name}</td>
                          <td className="dim">{l.country}</td>
                          <td className="mono">{l.shipments}</td>
                          <td className="mono">{fmt.usd(l.value_usd)}</td>
                          <td className="mono dim">{l.last_date}</td>
                          <td>
                            <AddLeadButton name={l.name} leadType="chemical" source="hsn"
                              entityKind="hsn_buyer" entityRef={l.name} hsnCode={selected} country={l.country}
                              data={{ hscode: selected, role: leadRole, shipments: l.shipments, value_usd: l.value_usd, last_date: l.last_date }} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function MapAdder({ code, onAdded }: { code: string; onAdded: () => void }) {
  const { toast } = useRuns()
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [mapType, setMapType] = useState('chemical')
  if (!open) return <button className="ghost" style={{ marginBottom: 8 }} onClick={() => setOpen(true)}>+ Map to product</button>
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '8px 0', flexWrap: 'wrap' }}>
      <input type="text" placeholder="Product / chemical name" value={label} onChange={e => setLabel(e.target.value)} />
      <select value={mapType} onChange={e => setMapType(e.target.value)}>
        <option value="chemical">chemical</option>
        <option value="battery">battery</option>
        <option value="other">other</option>
      </select>
      <button disabled={!label.trim()} onClick={async () => {
        try {
          await api.hsnAddMap({ hscode: code, label, map_type: mapType, user_name: '' })
          setOpen(false); setLabel(''); onAdded()
          toast('success', `Mapped ${code} → ${label}`)
        } catch (e: any) { toast('error', String(e.message || e)) }
      }}>Save</button>
      <button className="secondary" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  )
}

function Mappings() {
  const { toast } = useRuns()
  const [items, setItems] = useState<any[]>([])
  const [filter, setFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  const load = () => { api.hsnMap({ q: filter, map_type: typeFilter }).then(setItems).catch(() => {}) }
  useEffect(load, [filter, typeFilter])

  return (
    <div className="panel">
      <div className="filters" style={{ marginBottom: 12 }}>
        <input type="text" placeholder="Filter by product or code…" value={filter} onChange={e => setFilter(e.target.value)} />
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
          <option value="">all types</option>
          <option value="chemical">chemical</option>
          <option value="battery">battery</option>
          <option value="other">other</option>
        </select>
        <button className="ghost" title="Create mappings from the latest run's per-chemical HSN codes"
          onClick={async () => {
            try {
              const r = await api.hsnSeedMap()
              toast('success', `Seeded ${r.added} mappings from run #${r.from_run}`)
              load()
            } catch (e: any) { toast('error', String(e.message || e)) }
          }}>
          ⚡ Seed from latest run
        </button>
        <span className="dim" style={{ fontSize: 12 }}>{items.length} mappings</span>
      </div>
      <div className="table-scroll" style={{ maxHeight: '62vh' }}>
        <table>
          <thead><tr><th>Product</th><th>Type</th><th>HSN</th><th>Directory description</th><th>By</th><th></th></tr></thead>
          <tbody>
            {items.map(m => (
              <tr key={m.id}>
                <td style={{ fontWeight: 600 }}>{m.label}</td>
                <td><span className="chip">{m.map_type}</span></td>
                <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{m.hscode}</td>
                <td className="dim" style={{ fontSize: 12 }}>{m.description || '—'}</td>
                <td className="dim">{m.created_by}</td>
                <td><button className="ghost red" onClick={async () => { await api.hsnDeleteMap(m.id); load() }}>✕</button></td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={6} className="dim" style={{ textAlign: 'center', padding: 24 }}>
                No mappings yet — add them from the Explore tab or seed from the latest run.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
