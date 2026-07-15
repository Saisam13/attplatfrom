import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, fmt, EprCompany } from '../api'
import { useRuns } from '../App'
import { AddLeadButton } from '../components/common'

/** Sourcing Agent console for one EPR producer: AI research (web search + LLM
 *  extraction), potential math, contacts with proof URLs, news timeline, and
 *  the EPR ↔ EXIM trade cross-link. */
export default function EprCompanyPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const { toast } = useRuns()
  const [company, setCompany] = useState<EprCompany | null>(null)
  const [trade, setTrade] = useState<any>(null)
  const [researching, setResearching] = useState(false)
  const companyId = Number(id)

  const load = () => {
    api.eprCompany(companyId).then(setCompany).catch(e => toast('error', String(e.message || e)))
    api.eprTrade(companyId).then(setTrade).catch(() => {})
  }
  useEffect(load, [companyId])

  const research = async (refresh: boolean) => {
    setResearching(true)
    try {
      const res = await api.eprResearch(companyId, refresh)
      toast('success', res.cached ? 'Loaded cached research' : `Research complete (${res.meta?.llm_provider || 'AI'})`)
      load()
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setResearching(false)
    }
  }

  // auto-run research when arriving via "AI research" button and none exists
  useEffect(() => {
    if (company && !company.has_research && params.get('research') === '1' && !researching) {
      research(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company?.id, company?.has_research])

  if (!company) return <div><h1>EPR company</h1><div className="dim">Loading…</div></div>

  const r = company.research || null

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ marginBottom: 2 }}>{company.company_name}</h1>
          <div className="subtitle">
            <Link to="/epr">← EPR Intel</Link> · {company.state || 'state unknown'}
            {company.registration_number ? ` · Reg ${company.registration_number}` : ''}
            {r?.classification ? <> · <span style={{ color: 'var(--teal)', fontWeight: 700 }}>{r.classification}</span></> : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <AddLeadButton name={company.company_name} leadType="epr" source="epr"
            entityKind="epr_company" entityRef={company.id}
            data={{ target_tons: company.target_tons, credits: company.credits, gap_tons: company.gap_tons, priority_score: company.priority_score, state: company.state }} />
          <button disabled={researching} onClick={() => research(!!company.has_research)}>
            {researching ? 'Researching… (can take ~30-60s)' : company.has_research ? '↻ Refresh research' : '⚡ Run AI research'}
          </button>
        </div>
      </div>

      <div className="stat-grid" style={{ margin: '14px 0' }}>
        <div className="stat-card"><div className="value">{fmt.num(company.target_tons)}</div><div className="label">EPR target (t)</div></div>
        <div className="stat-card"><div className="value">{fmt.num(company.credits)}</div><div className="label">Credits procured (t)</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--orange)' }}>{fmt.num(company.gap_tons)}</div><div className="label">Gap (t)</div></div>
        <div className="stat-card"><div className="value" style={{ color: 'var(--teal)' }}>{company.priority_score.toFixed(1)}</div><div className="label">Priority score</div></div>
        {r?.chemistry && <div className="stat-card"><div className="value" style={{ fontSize: 17 }}>{r.chemistry}</div><div className="label">Chemistry</div></div>}
        {r?.sourcing_sector && <div className="stat-card"><div className="value" style={{ fontSize: 17 }}>{r.sourcing_sector}</div><div className="label">Sector</div></div>}
      </div>

      {!r && (
        <div className="panel dim">
          No AI research yet. “Run AI research” searches the web (Tavily/Firecrawl) and extracts a
          sourcing report (Groq/Gemini/Claude) — configure keys on the <Link to="/settings">Settings</Link> page.
        </div>
      )}

      {r && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(430px, 1fr))', gap: 18 }}>
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Strategic summary</h2>
            <p style={{ lineHeight: 1.6 }}>{r.strategic_summary || '—'}</p>
            {r.potential && (
              <>
                <h3>Potential for MiniMines</h3>
                <table>
                  <tbody>
                    <tr><td className="dim">EPR certificates</td><td>{r.potential.epr_certificates || '—'}</td></tr>
                    <tr><td className="dim">Metal recovery</td><td>{r.potential.recovery_metals || '—'}</td></tr>
                    <tr><td className="dim">Import offset</td><td>{r.potential.offset_dependency || '—'}</td></tr>
                  </tbody>
                </table>
              </>
            )}
            {company.research_meta && (
              <div className="dim" style={{ fontSize: 11, marginTop: 10 }}>
                Search: {company.research_meta.search_provider} · LLM: {company.research_meta.llm_provider} ·
                Updated {company.research_meta.updated_at ? new Date(company.research_meta.updated_at + 'Z').toLocaleString() : '—'}
              </div>
            )}
          </div>

          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Contacts <span className="dim" style={{ fontSize: 12 }}>(only if found publicly — with proof link)</span></h2>
            {(r.contacts || []).length === 0 && <div className="dim">No contacts extracted.</div>}
            {(r.contacts || []).map((c: any, i: number) => (
              <div key={i} style={{ borderBottom: '1px solid var(--border)', padding: '8px 0' }}>
                <strong>{c.name}</strong> <span className="dim">— {c.role}</span>
                <div style={{ fontSize: 13 }}>
                  {c.email && c.email !== 'Not Publicly Available' && <span className="mono">{c.email} · </span>}
                  {c.linkedin && c.linkedin !== 'Not Publicly Available' && <a href={c.linkedin} target="_blank" rel="noreferrer">LinkedIn</a>}
                  {c.proof_source_url && <> · <a className="dim" href={c.proof_source_url} target="_blank" rel="noreferrer">source</a></>}
                </div>
              </div>
            ))}
            <h3 style={{ marginTop: 14 }}>Recent news &amp; trends</h3>
            {(r.recent_news_trends || []).length === 0 && <div className="dim">Nothing found.</div>}
            <div className="timeline">
              {(r.recent_news_trends || []).map((n: any, i: number) => (
                <div key={i} className="timeline-item">
                  <div className="when">{n.date}</div>
                  <strong style={{ fontSize: 13 }}>{n.headline}</strong>
                  <div className="dim" style={{ fontSize: 12 }}>{n.summary}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginTop: 18 }}>
        <h2 style={{ marginTop: 0 }}>
          Trade data cross-link <span className="src-badge src-ours">ours</span>
        </h2>
        <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
          EXIM shipments in recent runs where the buyer or seller name matches “{company.company_name}”.
        </div>
        {!trade?.items?.length && <div className="dim">No matching shipments in the uploaded trade data.</div>}
        {!!trade?.items?.length && (
          <div className="table-scroll" style={{ maxHeight: '40vh' }}>
            <table>
              <thead><tr><th>Date</th><th>HSN</th><th>Description</th><th>Seller</th><th>Buyer</th><th>Qty (kg)</th><th>Value</th><th>$/kg</th></tr></thead>
              <tbody>
                {trade.items.map((t: any, i: number) => (
                  <tr key={i}>
                    <td className="mono dim">{t.date}</td>
                    <td className="mono">{t.hsn6}</td>
                    <td style={{ maxWidth: 320 }}>{t.desc_clean}</td>
                    <td>{t.seller} <span className="dim">({t.seller_country})</span></td>
                    <td>{t.buyer} <span className="dim">({t.buyer_country})</span></td>
                    <td className="mono">{fmt.num(t.qty_kg)}</td>
                    <td className="mono">{fmt.usd(t.value_usd)}</td>
                    <td className="mono">{(t.unit_price || 0).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
