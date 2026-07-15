import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, Chemical, fmt } from '../api'
import { useRuns } from '../App'
import { TierBadge, PoolBadge, FeedbackButtons } from '../components/common'

const DIMS: (keyof Chemical['scores'])[] = ['volume', 'price', 'buyers', 'suppliers', 'trend', 'structure', 'freedom', 'barrier']
const COLS_KEY = 'att_rankings_cols'
const ROW_H = 37          // px, fixed row height for windowed rendering
const OVERSCAN = 12

type Tab = 'all' | 'base' | 'opportunity'

function loadCols(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(COLS_KEY) || '{}')
  } catch { return {} }
}

export default function RankingsPage() {
  const { selectedRun } = useRuns()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'all'
  const [items, setItems] = useState<Chemical[]>([])
  const [total, setTotal] = useState(0)
  const [tier, setTier] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('att_final')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [loading, setLoading] = useState(false)
  const [cols, setCols] = useState<Record<string, boolean>>(loadCols)
  const [colMenu, setColMenu] = useState(false)
  const [heat, setHeat] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewH, setViewH] = useState(600)

  const pool = tab === 'all' ? '' : tab
  const setTab = (t: Tab) => setParams(t === 'all' ? {} : { tab: t })

  useEffect(() => {
    if (!selectedRun || selectedRun.status !== 'done') { setItems([]); return }
    setLoading(true)
    api.chemicals(selectedRun.id, { pool, tier, search, sort, order, limit: '10000', include_detail: 'false' })
      .then(r => { setItems(r.items); setTotal(r.total) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [selectedRun?.id, selectedRun?.status, pool, tier, search, sort, order])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => setScrollTop(el.scrollTop)
    const measure = () => setViewH(el.clientHeight || 600)
    measure()
    el.addEventListener('scroll', onScroll)
    window.addEventListener('resize', measure)
    return () => { el.removeEventListener('scroll', onScroll); window.removeEventListener('resize', measure) }
  }, [selectedRun?.status])

  const show = (col: string) => cols[col] !== false
  const toggleCol = (col: string) => {
    const next = { ...cols, [col]: !show(col) }
    setCols(next)
    localStorage.setItem(COLS_KEY, JSON.stringify(next))
  }

  const clickSort = (col: string) => {
    if (sort === col) setOrder(o => (o === 'desc' ? 'asc' : 'desc'))
    else { setSort(col); setOrder('desc') }
  }

  const visibleDims = DIMS.filter(d => show(d))
  const showReasoning = tab === 'opportunity'

  // windowed rendering
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(items.length, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN)
  const slice = useMemo(() => items.slice(start, end), [items, start, end])

  const exportCsv = () => {
    const head = ['Rank', 'Chemical', 'HSN', 'Pool', 'Shipments',
      ...visibleDims.map(d => d), 'ATT', 'ATT India', 'Feedback adj', 'Tier', 'Trend', 'Growth %',
      ...(showReasoning ? ['Reasoning'] : [])]
    const lines = [head.join(',')]
    items.forEach((c, i) => {
      const cells = [i + 1, c.chemical, c.hsn_codes, c.pool, c.shipments,
        ...visibleDims.map(d => (c.scores[d] ?? 0).toFixed(1)),
        c.att_final.toFixed(1), c.att_india.toFixed(1), c.feedback_adj || 0, c.tier,
        c.trend_direction, c.growth_rate,
        ...(showReasoning ? [c.reasoning] : [])]
      lines.push(cells.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
    })
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `ATT_Rankings_Run${selectedRun!.id}_${tab}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  if (!selectedRun) return <div><h1>Rankings</h1><div className="dim">No run selected — upload data first.</div></div>
  if (selectedRun.status !== 'done')
    return <div><h1>Rankings</h1><div className="dim">Run #{selectedRun.id} is {selectedRun.status} ({selectedRun.stage}) — results appear when complete.</div></div>

  const heatStyle = (v: number) => heat
    ? { background: `color-mix(in srgb, var(--teal) ${Math.round((v ?? 0) * 0.3)}%, transparent)` }
    : undefined

  return (
    <div>
      <h1>Rankings — {selectedRun.name}</h1>
      <div className="subtitle">ATT = 8 weighted dimension percentiles × regulatory factor + variance modifier ± trader-feedback adjustment.</div>

      <div className="tabs">
        <button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>All</button>
        <button className={tab === 'base' ? 'active' : ''} onClick={() => setTab('base')}>Base portfolio</button>
        <button className={tab === 'opportunity' ? 'active' : ''} onClick={() => setTab('opportunity')}>Opportunity map</button>
      </div>

      <div className="filters">
        <select value={tier} onChange={e => setTier(e.target.value)}>
          <option value="">All tiers</option>
          <option value="A">Tier A</option>
          <option value="B">Tier B</option>
          <option value="C">Tier C</option>
        </select>
        <input type="text" placeholder="Search chemical…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 240 }} />
        <div className="col-picker">
          <button className="secondary" onClick={() => setColMenu(m => !m)}>Columns ▾</button>
          {colMenu && (
            <div className="menu" onMouseLeave={() => setColMenu(false)}>
              {DIMS.map(d => (
                <label key={d}>
                  <input type="checkbox" checked={show(d)} onChange={() => toggleCol(d)} />
                  {d.charAt(0).toUpperCase() + d.slice(1)}
                </label>
              ))}
              <label style={{ borderTop: '1px solid var(--border)', marginTop: 6, paddingTop: 6 }}>
                <input type="checkbox" checked={heat} onChange={() => setHeat(h => !h)} />
                Score heat colors
              </label>
            </div>
          )}
        </div>
        <button className="secondary" onClick={exportCsv}>Export view (CSV)</button>
        <span className="dim">{total} chemicals{loading ? ' · loading…' : ''}</span>
      </div>

      <div className="table-scroll" ref={scrollRef} style={{ maxHeight: '70vh' }}>
        <table style={{ tableLayout: 'fixed', minWidth: 900 + visibleDims.length * 72 }}>
          <thead>
            <tr>
              <th style={{ width: 44 }}>#</th>
              <th onClick={() => clickSort('chemical')} style={{ width: 220 }}>Chemical</th>
              <th style={{ width: 90 }}>HSN</th>
              <th onClick={() => clickSort('shipments')} style={{ width: 66 }}>Ships</th>
              {visibleDims.map(d => (
                <th key={d} style={{ width: 72 }} onClick={() => clickSort(d === 'trend' ? 'trend_adjusted' : d + '_norm')}>
                  {d.charAt(0).toUpperCase() + d.slice(1)}
                </th>
              ))}
              <th style={{ width: 66 }} onClick={() => clickSort('att_final')}>ATT{sort === 'att_final' ? (order === 'desc' ? ' ↓' : ' ↑') : ''}</th>
              <th style={{ width: 78 }} onClick={() => clickSort('att_india')}>ATT India</th>
              <th style={{ width: 58 }} onClick={() => clickSort('feedback_adj')}>Fb adj</th>
              <th style={{ width: 72 }} onClick={() => clickSort('tier')}>Tier</th>
              {tab === 'all' && <th style={{ width: 92 }}>Pool</th>}
              {showReasoning && <th style={{ width: 320 }}>Reasoning</th>}
              <th style={{ width: 210 }}>Feedback</th>
            </tr>
          </thead>
          <tbody>
            {start > 0 && <tr style={{ height: start * ROW_H }}><td colSpan={20} /></tr>}
            {slice.map((c, i) => (
              <tr key={c.chemical} className="clickable" style={{ height: ROW_H }}
                onClick={() => nav(`/chemical/${encodeURIComponent(c.chemical)}`)}>
                <td className="dim">{start + i + 1}</td>
                <td style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.chemical}>{c.chemical}</td>
                <td className="mono dim" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.hsn_codes}</td>
                <td className="mono">{fmt.num(c.shipments)}</td>
                {visibleDims.map(d => (
                  <td key={d} className="mono" style={heatStyle(c.scores[d])}>{fmt.score(c.scores[d])}</td>
                ))}
                <td className="mono" style={{ color: 'var(--teal)', fontWeight: 700 }}>{c.att_final.toFixed(1)}</td>
                <td className="mono">{c.att_india.toFixed(1)}</td>
                <td className="mono" style={{ color: c.feedback_adj > 0 ? 'var(--green)' : c.feedback_adj < 0 ? 'var(--red)' : undefined }}>
                  {c.feedback_adj ? (c.feedback_adj > 0 ? '+' : '') + c.feedback_adj : '—'}
                </td>
                <td><TierBadge tier={c.tier} /></td>
                {tab === 'all' && <td><PoolBadge pool={c.pool} /></td>}
                {showReasoning && (
                  <td className="dim" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.reasoning}>
                    {c.reasoning}
                  </td>
                )}
                <td style={{ whiteSpace: 'nowrap' }}><FeedbackButtons runId={selectedRun.id} chemical={c.chemical} /></td>
              </tr>
            ))}
            {end < items.length && <tr style={{ height: (items.length - end) * ROW_H }}><td colSpan={20} /></tr>}
          </tbody>
        </table>
        {items.length === 0 && !loading && <div className="dim" style={{ padding: 20 }}>No chemicals match the filters.</div>}
      </div>
    </div>
  )
}
