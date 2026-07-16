import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, download, fmt, BatteryEntity } from '../api'
import { useRuns } from '../App'
import { AddLeadButton, TierBadge } from '../components/common'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip,
} from 'recharts'

type Tab = 'suppliers' | 'buyers' | 'raw'

export default function BatteryPage() {
  const { batteryRuns, selectedBatteryRun, setSelectedBatteryId, refresh, toast } = useRuns()
  const [tab, setTab] = useState<Tab>('suppliers')

  return (
    <div>
      <h1>Battery — Suppliers &amp; Buyers</h1>
      <div className="subtitle">
        Feedstock sourcing intelligence — upload battery-scrap EXIM data, rank suppliers to buy
        from, and see who competes for the same material. Categories &amp; the price watch live on
        the <Link to="/battery-dashboard">Battery Dashboard</Link>.
      </div>

      <BatteryUpload onStarted={refresh} />

      {batteryRuns.length > 0 && (
        <div className="filters" style={{ marginTop: 4 }}>
          <label className="dim">Battery run</label>
          <select value={selectedBatteryRun?.id ?? ''} onChange={e => setSelectedBatteryId(Number(e.target.value))}>
            {batteryRuns.map(r => (
              <option key={r.id} value={r.id}>#{r.id} {r.name} ({r.status})</option>
            ))}
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

      {selectedBatteryRun && (selectedBatteryRun.status === 'running' || selectedBatteryRun.status === 'queued') && (
        <div className="panel">
          <div className="progress-outer">
            <div className="progress-inner" style={{ width: `${Math.max(selectedBatteryRun.progress, 4)}%` }}>
              {selectedBatteryRun.progress}%
            </div>
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{selectedBatteryRun.stage}</div>
        </div>
      )}
      {selectedBatteryRun?.status === 'error' && (
        <div className="panel error">✗ {selectedBatteryRun.error}</div>
      )}

      {selectedBatteryRun?.status === 'done' && (
        <>
          <div className="tabs">
            <button className={tab === 'suppliers' ? 'active' : ''} onClick={() => setTab('suppliers')}>
              Suppliers (procurement)
            </button>
            <button className={tab === 'buyers' ? 'active' : ''} onClick={() => setTab('buyers')}>
              Competing buyers
            </button>
            <button className={tab === 'raw' ? 'active' : ''} onClick={() => setTab('raw')}>
              Raw rows
            </button>
          </div>
          {(tab === 'suppliers' || tab === 'buyers') && (
            <EntityTable runId={selectedBatteryRun.id} role={tab === 'buyers' ? 'buyer' : 'supplier'} />
          )}
          {tab === 'raw' && <BatteryRaw runId={selectedBatteryRun.id} />}
        </>
      )}
      {batteryRuns.length === 0 && (
        <div className="dim">No battery runs yet — upload battery-scrap EXIM files above.</div>
      )}
    </div>
  )
}

function BatteryUpload({ onStarted }: { onStarted: () => void }) {
  const { setSelectedBatteryId, toast } = useRuns()
  const [files, setFiles] = useState<File[]>([])
  const [name, setName] = useState('')
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const addFiles = (fl: FileList | null) => {
    if (!fl) return
    const xlsx = Array.from(fl).filter(f => f.name.toLowerCase().endsWith('.xlsx'))
    setFiles(prev => [...prev, ...xlsx.filter(f => !prev.some(p => p.name === f.name))])
  }

  const start = async () => {
    setBusy(true)
    try {
      const form = new FormData()
      form.append('name', name || `Battery run ${new Date().toLocaleString()}`)
      files.forEach(f => form.append('exim_files', f))
      const { run_id, duplicate_warning } = await api.createBatteryRun(form)
      if (duplicate_warning) {
        toast('error', duplicate_warning.message + ' (' +
          duplicate_warning.runs.map(r => `#${r.run_id} ${r.run_name}`).join(', ') + ')')
      }
      setFiles([]); setName('')
      onStarted()
      setSelectedBatteryId(run_id)
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}
        onClick={() => input.current?.click()}
      >
        {files.length === 0
          ? <>Drag &amp; drop battery-scrap EXIM .xlsx files here (black mass, Li-ion scrap, spent catalyst, magnet scrap…)</>
          : <>{files.map(f => <span className="chip" key={f.name}>{f.name}</span>)}<br /><span className="dim">Click to add more</span></>}
        <input ref={input} type="file" multiple accept=".xlsx" style={{ display: 'none' }}
          onChange={e => { addFiles(e.target.files); e.target.value = '' }} />
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <label className="dim">Run name</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)}
            placeholder="e.g. Black mass imports H1" style={{ width: 260 }} />
        </div>
        <button disabled={busy || files.length === 0} onClick={start}>
          {busy ? 'Uploading…' : 'Start battery analysis'}
        </button>
      </div>
    </div>
  )
}

function EntityTable({ runId, role }: { runId: number; role: 'supplier' | 'buyer' }) {
  const [items, setItems] = useState<BatteryEntity[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [tier, setTier] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('proc_score')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [detail, setDetail] = useState<BatteryEntity | null>(null)

  useEffect(() => {
    api.batteryEntities(runId, { role, search, tier, category, sort, order, limit: '2000' })
      .then(r => { setItems(r.items); setTotal(r.total) })
      .catch(() => {})
  }, [runId, role, search, tier, category, sort, order])

  const clickSort = (col: string) => {
    if (sort === col) setOrder(o => (o === 'desc' ? 'asc' : 'desc'))
    else { setSort(col); setOrder('desc') }
  }

  const TH = ({ col, children }: { col: string; children: any }) => (
    <th onClick={() => clickSort(col)}>{children}{sort === col ? (order === 'desc' ? ' ↓' : ' ↑') : ''}</th>
  )

  return (
    <div>
      <div className="filters">
        <input type="text" placeholder={`Search ${role}s…`} value={search} onChange={e => setSearch(e.target.value)} />
        <input type="text" placeholder="Category contains…" value={category} onChange={e => setCategory(e.target.value)} style={{ width: 180 }} />
        <select value={tier} onChange={e => setTier(e.target.value)}>
          <option value="">All tiers</option>
          <option value="A">Tier A</option><option value="B">Tier B</option><option value="C">Tier C</option>
        </select>
        <span className="dim">{total} {role}s</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <TH col="name">{role === 'supplier' ? 'Supplier' : 'Buyer'}</TH>
              <th>Country</th>
              <th>Categories</th>
              <TH col="shipments">Ship.</TH>
              <TH col="qty_kg">Qty (KG)</TH>
              <TH col="value_usd">Value</TH>
              <TH col="median_price">Med. price</TH>
              <TH col="price_index">Price idx</TH>
              <TH col="consistency">Consist.</TH>
              <TH col="months_active">Months</TH>
              <TH col="proc_score">{role === 'supplier' ? 'Proc score' : 'Presence'}</TH>
              <th>Tier</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((e, i) => (
              <tr key={e.name} className="clickable" onClick={() => setDetail(e)}>
                <td className="dim">{i + 1}</td>
                <td style={{ maxWidth: 260, fontWeight: 600 }}><span className="linkish">{e.name}</span></td>
                <td>{e.country}</td>
                <td className="dim" style={{ maxWidth: 220, fontSize: 12 }}>{e.categories}</td>
                <td className="mono">{e.shipments}</td>
                <td className="mono">{fmt.num(e.qty_kg)}</td>
                <td className="mono">{fmt.usd(e.value_usd)}</td>
                <td className="mono">{e.median_price ? '$' + e.median_price : '—'}</td>
                <td className="mono" style={{ color: e.price_index == null ? undefined : e.price_index < 1 ? 'var(--green)' : e.price_index > 1.1 ? 'var(--orange)' : undefined }}>
                  {e.price_index == null ? <span className="dim" title="Fewer than 3 priced shipments in a comparable category">—</span> : e.price_index.toFixed(2)}
                </td>
                <td className="mono">{Math.round((e.consistency || 0) * 100)}%</td>
                <td className="mono">{e.months_active}</td>
                <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{e.proc_score.toFixed(1)}</td>
                <td><TierBadge tier={e.tier} /></td>
                <td onClick={ev => ev.stopPropagation()}>
                  <AddLeadButton name={e.name} leadType="battery" source="battery"
                    entityKind="battery_entity" entityRef={e.name} country={e.country}
                    data={{ role, categories: e.categories, shipments: e.shipments, qty_kg: e.qty_kg, value_usd: e.value_usd, median_price: e.median_price, proc_score: e.proc_score, tier: e.tier }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail && <EntityDetail entity={detail} role={role} onClose={() => setDetail(null)} />}
    </div>
  )
}

function EntityDetail({ entity, role, onClose }: { entity: BatteryEntity; role: string; onClose: () => void }) {
  const d = entity.detail || {}
  const monthly = Object.entries(d.monthly_shipments || {}).map(([month, n]) => ({ month, shipments: n }))
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ width: 640, maxHeight: '86vh', overflow: 'auto' }} onClick={e => e.stopPropagation()}>
        <h3>{entity.name} <TierBadge tier={entity.tier} /></h3>
        <div className="dim" style={{ marginBottom: 12 }}>
          {entity.country} · {entity.shipments} shipments · {fmt.num(entity.qty_kg)} KG · {fmt.usd(entity.value_usd)} ·
          active {entity.first_month} → {entity.last_month}
        </div>
        <h2 style={{ marginTop: 0 }}>Category pricing vs market</h2>
        <table>
          <thead><tr><th>Category</th><th>Shipments</th><th>Their median</th><th>Market median</th></tr></thead>
          <tbody>
            {(d.category_breakdown || []).map(c => (
              <tr key={c.category}>
                <td>{c.category}</td>
                <td className="mono">{c.shipments}</td>
                <td className="mono" style={{ color: c.market_median && c.median_price < c.market_median ? 'var(--green)' : undefined }}>
                  {c.median_price ? '$' + c.median_price : '—'}
                </td>
                <td className="mono dim">{c.market_median ? '$' + c.market_median : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h2>{role === 'supplier' ? 'Their buyers' : 'Their suppliers'}</h2>
        <div>
          {(d.top_counterparties || []).map(([n, c]) => <span className="chip" key={n}>{n} ({c})</span>)}
          {(d.top_counterparties || []).length === 0 && <span className="dim">—</span>}
        </div>
        {monthly.length > 1 && (
          <>
            <h2>Monthly shipments</h2>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={monthly}>
                <XAxis dataKey="month" tick={{ fill: '#9db4c4', fontSize: 10 }} angle={-45} textAnchor="end" height={52} />
                <YAxis tick={{ fill: '#9db4c4', fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: '#0f2e45', border: '1px solid #294962' }} />
                <Bar dataKey="shipments" fill="#4c9eaf" />
              </BarChart>
            </ResponsiveContainer>
          </>
        )}
        <div className="actions"><button className="secondary" onClick={onClose}>Close</button></div>
      </div>
    </div>
  )
}

function BatteryRaw({ runId }: { runId: number }) {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const PAGE = 100

  useEffect(() => {
    api.raw(runId, { search, limit: String(PAGE), offset: String(page * PAGE) })
      .then(r => { setRows(r.items); setTotal(r.total) })
      .catch(() => {})
  }, [runId, search, page])

  return (
    <div>
      <div className="filters">
        <input type="text" placeholder="Search descriptions…" value={search}
          onChange={e => { setSearch(e.target.value); setPage(0) }} style={{ width: 280 }} />
        <span className="dim">{total.toLocaleString()} rows</span>
        <button className="ghost" disabled={page === 0} onClick={() => setPage(p => p - 1)}>‹ Prev</button>
        <span className="dim">page {page + 1} / {Math.max(1, Math.ceil(total / PAGE))}</span>
        <button className="ghost" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(p => p + 1)}>Next ›</button>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr>
            <th>Date</th><th>HSN</th><th>Category</th><th>Description</th>
            <th>Seller</th><th>From</th><th>Buyer</th><th>To</th>
            <th>Qty KG</th><th>Value</th><th>Unit $</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono dim">{r.date}</td>
                <td className="mono dim">{r.hsn6}</td>
                <td>{r.chemical}</td>
                <td className="dim" style={{ maxWidth: 320, fontSize: 12 }}>{r.desc_clean}</td>
                <td style={{ maxWidth: 180 }}>{r.seller}</td>
                <td className="dim">{r.seller_country}</td>
                <td style={{ maxWidth: 180 }}>{r.buyer}</td>
                <td className="dim">{r.buyer_country}</td>
                <td className="mono">{fmt.num(r.qty_kg)}</td>
                <td className="mono">{fmt.usd(r.value_usd)}</td>
                <td className="mono">{r.unit_price || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
