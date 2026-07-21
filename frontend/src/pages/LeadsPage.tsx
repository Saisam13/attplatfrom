import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Lead } from '../api'
import { useRuns } from '../App'
import { StageBadge, STAGE_LABELS } from '../components/common'

const TYPES = ['chemical', 'epr', 'battery', 'other']
const STAGES = ['new', 'contacted', 'in_talks', 'deal', 'dead']

/** Universal lead tracker: all lead types, tagged by user/type/stage, with a
 *  timestamped timeline per lead. Also served raw at /api/v1/leads (API key). */
export default function LeadsPage() {
  const { toast, userName } = useRuns()
  const [items, setItems] = useState<Lead[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<any>(null)
  const [filters, setFilters] = useState({ lead_type: '', stage: '', owner: '', tag: '', search: '', due: '' })
  const [openLead, setOpenLead] = useState<Lead | null>(null)
  const [adding, setAdding] = useState(false)
  const [transferring, setTransferring] = useState<Set<number>>(new Set())

  const load = () => {
    const params: Record<string, string> = { limit: '500' }
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v })
    api.leads(params).then(r => { setItems(r.items); setTotal(r.total) })
      .catch(e => toast('error', String(e.message || e)))
    api.leadsSummary().then(setSummary).catch(() => {})
  }
  useEffect(load, [filters])

  const set = (k: string, v: string) => setFilters(f => ({ ...f, [k]: v }))

  const transferToCrm = async (lead: Lead) => {
    if (!window.confirm(`Transfer "${lead.name}" to the Twenty CRM leads tab? It will be removed from SalesHub — all further work on it happens in Twenty.`)) return
    setTransferring(prev => new Set(prev).add(lead.id))
    try {
      await api.transferLeadToCrm(lead.id)
      toast('success', `"${lead.name}" transferred to Twenty CRM`)
      if (openLead?.id === lead.id) setOpenLead(null)
      load()
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setTransferring(prev => { const n = new Set(prev); n.delete(lead.id); return n })
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h1 style={{ marginBottom: 2 }}>Leads</h1>
          <div className="subtitle">
            All lead types in one pipeline. External read-only API at <span className="mono">/api/v1/leads</span>
            (keys on <Link to="/settings">Settings</Link>).
          </div>
        </div>
        <button onClick={() => setAdding(true)}>+ New lead</button>
      </div>

      {summary && (
        <div className="stage-row" style={{ marginTop: 12 }}>
          {STAGES.map(s => (
            <div key={s} className="stage-col clickable" onClick={() => set('stage', filters.stage === s ? '' : s)}
              style={filters.stage === s ? { borderColor: 'var(--teal)' } : {}}>
              <div className="n">{summary.by_stage?.[s] ?? 0}</div>
              <div className="l">{STAGE_LABELS[s]}</div>
            </div>
          ))}
        </div>
      )}

      <div className="filters" style={{ marginBottom: 12 }}>
        <input type="text" placeholder="Search name…" value={filters.search} onChange={e => set('search', e.target.value)} />
        <select value={filters.lead_type} onChange={e => set('lead_type', e.target.value)}>
          <option value="">all types</option>
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <input type="text" placeholder="Owner…" value={filters.owner} onChange={e => set('owner', e.target.value)} style={{ width: 110 }} />
        <input type="text" placeholder="Tag…" value={filters.tag} onChange={e => set('tag', e.target.value)} style={{ width: 110 }} />
        <select value={filters.due} onChange={e => set('due', e.target.value)}>
          <option value="">any follow-up</option>
          <option value="overdue">overdue</option>
          <option value="today">due today</option>
          <option value="upcoming">upcoming</option>
        </select>
        <button className="ghost" onClick={() => set('owner', userName)}>My leads</button>
        <span className="dim" style={{ fontSize: 12 }}>{total} leads</span>
      </div>

      <div className="table-scroll">
        <table>
          <thead><tr><th>Lead</th><th>Type</th><th>Stage</th><th>Owner</th><th>Tags</th><th>Country</th><th>Follow-up</th><th>Updated</th><th>Actions</th></tr></thead>
          <tbody>
            {items.map(l => (
              <tr key={l.id} className="clickable" onClick={() => api.lead(l.id).then(setOpenLead)}>
                <td style={{ fontWeight: 600 }}>{l.name}</td>
                <td><span className="chip">{l.lead_type}</span></td>
                <td><StageBadge stage={l.stage} /></td>
                <td className="dim">{l.owner || '—'}</td>
                <td className="dim" style={{ fontSize: 12 }}>{l.tags}</td>
                <td className="dim">{l.country}</td>
                <td className="mono" style={{ color: l.next_followup && l.next_followup <= new Date().toISOString().slice(0, 10) ? 'var(--orange)' : undefined }}>
                  {l.next_followup || '—'}
                </td>
                <td className="mono dim" style={{ fontSize: 12 }}>{l.updated_at ? new Date(l.updated_at + 'Z').toLocaleDateString() : ''}</td>
                <td onClick={e => e.stopPropagation()}>
                  <button className="ghost" disabled={transferring.has(l.id)} onClick={() => transferToCrm(l)}>
                    {transferring.has(l.id) ? 'Transferring…' : '→ Add to CRM'}
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={9} className="dim" style={{ textAlign: 'center', padding: 28 }}>
                No leads match. Add them from EPR Intel, HSN Explorer, Battery pages — or “+ New lead”.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {openLead && (
        <LeadDrawer
          lead={openLead}
          onClose={() => { setOpenLead(null); load() }}
          onChanged={() => api.lead(openLead.id).then(setOpenLead)}
          onTransfer={() => transferToCrm(openLead)}
          transferring={transferring.has(openLead.id)}
        />
      )}
      {adding && <NewLeadModal onClose={() => setAdding(false)} onCreated={() => { setAdding(false); load() }} />}
    </div>
  )
}

function LeadDrawer({ lead, onClose, onChanged, onTransfer, transferring }: {
  lead: Lead; onClose: () => void; onChanged: () => void; onTransfer: () => void; transferring: boolean
}) {
  const { toast } = useRuns()
  const [note, setNote] = useState('')
  const [followup, setFollowup] = useState(lead.next_followup)
  const [tags, setTags] = useState(lead.tags)
  const [owner, setOwner] = useState(lead.owner)

  const patch = async (body: object, msg: string) => {
    try {
      await api.updateLead(lead.id, body)
      toast('success', msg)
      onChanged()
    } catch (e: any) { toast('error', String(e.message || e)) }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ width: 720, maxHeight: '88vh', overflow: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ marginBottom: 2 }}>{lead.name}</h3>
            <div className="dim" style={{ fontSize: 12 }}>
              <span className="chip">{lead.lead_type}</span> · source: {lead.source}
              {lead.hsn_code && <> · HSN <span className="mono">{lead.hsn_code}</span></>}
              {lead.entity_kind === 'epr_company' && <> · <Link to={`/epr/${lead.entity_ref}`}>EPR page →</Link></>}
              · created {lead.created_at ? new Date(lead.created_at + 'Z').toLocaleString() : '—'} by {lead.created_by || '—'}
            </div>
          </div>
          <button className="ghost" onClick={onClose}>✕</button>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0' }}>
          {STAGES.map(s => (
            <button key={s} className={lead.stage === s ? '' : 'ghost'}
              onClick={() => lead.stage !== s && patch({ stage: s }, `Stage → ${STAGE_LABELS[s]}`)}>
              {STAGE_LABELS[s]}
            </button>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
          <div className="field">
            <label>Owner</label>
            <input type="text" value={owner} onChange={e => setOwner(e.target.value)}
              onBlur={() => owner !== lead.owner && patch({ owner }, 'Owner updated')} />
          </div>
          <div className="field">
            <label>Tags (comma-separated)</label>
            <input type="text" value={tags} onChange={e => setTags(e.target.value)}
              onBlur={() => tags !== lead.tags && patch({ tags }, 'Tags updated')} />
          </div>
          <div className="field">
            <label>Next follow-up</label>
            <input type="date" value={followup} onChange={e => setFollowup(e.target.value)}
              onBlur={() => followup !== lead.next_followup && patch({ next_followup: followup }, 'Follow-up updated')} />
          </div>
        </div>

        {Object.keys(lead.data || {}).length > 0 && (
          <div style={{ margin: '8px 0' }}>
            <div className="dim" style={{ fontSize: 12, marginBottom: 4 }}>Linked data snapshot</div>
            <div className="mono" style={{ fontSize: 12, background: 'var(--navy)', padding: 10, borderRadius: 8, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(lead.data, null, 1).slice(1, -1).trim()}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, margin: '10px 0' }}>
          <input style={{ flex: 1 }} type="text" placeholder="Add a note…" value={note}
            onChange={e => setNote(e.target.value)}
            onKeyDown={async e => {
              if (e.key === 'Enter' && note.trim()) {
                await api.addLeadEvent(lead.id, { kind: 'note', text: note })
                setNote(''); onChanged()
              }
            }} />
          <button disabled={!note.trim()} onClick={async () => {
            await api.addLeadEvent(lead.id, { kind: 'note', text: note })
            setNote(''); onChanged()
          }}>Add note</button>
          <Link to="/outreach" state={{ leadId: lead.id }}>
            <button className="ghost">✉ Draft outreach</button>
          </Link>
        </div>

        <h4 style={{ margin: '14px 0 8px' }}>Timeline</h4>
        <div className="timeline">
          {(lead.events || []).map(e => (
            <div key={e.id} className="timeline-item">
              <div className="when">
                {e.created_at ? new Date(e.created_at + 'Z').toLocaleString() : ''} · {e.user_name || 'system'} · {e.kind}
              </div>
              <div style={{ fontSize: 13 }}>{e.text}</div>
              {e.data?.draft && (
                <details><summary className="dim" style={{ fontSize: 12, cursor: 'pointer' }}>show draft</summary>
                  <div className="draft-box" style={{ marginTop: 6 }}>{e.data.draft}</div>
                </details>
              )}
            </div>
          ))}
        </div>

        <div className="actions">
          <button className="ghost red" onClick={async () => {
            if (window.confirm(`Delete lead "${lead.name}" and its timeline?`)) {
              await api.deleteLead(lead.id); onClose()
            }
          }}>Delete lead</button>
          <button disabled={transferring} onClick={onTransfer}>
            {transferring ? 'Transferring…' : '→ Add to CRM'}
          </button>
          <button className="secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}

function NewLeadModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { toast, userName } = useRuns()
  const [form, setForm] = useState({
    name: '', lead_type: 'other', owner: userName, tags: '', country: 'India',
    contact_name: '', contact_email: '', contact_phone: '', next_followup: '',
  })
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ width: 460 }} onClick={e => e.stopPropagation()}>
        <h3>New lead</h3>
        <div className="field"><label>Company / name</label>
          <input type="text" value={form.name} autoFocus onChange={e => set('name', e.target.value)} /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div className="field"><label>Type</label>
            <select value={form.lead_type} onChange={e => set('lead_type', e.target.value)}>
              {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select></div>
          <div className="field"><label>Owner</label>
            <input type="text" value={form.owner} onChange={e => set('owner', e.target.value)} /></div>
          <div className="field"><label>Tags</label>
            <input type="text" value={form.tags} onChange={e => set('tags', e.target.value)} placeholder="e.g. black-mass, south" /></div>
          <div className="field"><label>Country</label>
            <input type="text" value={form.country} onChange={e => set('country', e.target.value)} /></div>
          <div className="field"><label>Contact person</label>
            <input type="text" value={form.contact_name} onChange={e => set('contact_name', e.target.value)} /></div>
          <div className="field"><label>Contact email</label>
            <input type="text" value={form.contact_email} onChange={e => set('contact_email', e.target.value)} /></div>
          <div className="field"><label>Contact phone</label>
            <input type="text" value={form.contact_phone} onChange={e => set('contact_phone', e.target.value)} placeholder="+91…" /></div>
          <div className="field"><label>Next follow-up</label>
            <input type="date" value={form.next_followup} onChange={e => set('next_followup', e.target.value)} /></div>
        </div>
        <div className="actions">
          <button className="secondary" onClick={onClose}>Cancel</button>
          <button disabled={!form.name.trim()} onClick={async () => {
            try {
              await api.createLead({ ...form, source: 'manual' })
              toast('success', 'Lead created')
              onCreated()
            } catch (e: any) { toast('error', String(e.message || e)) }
          }}>Create</button>
        </div>
      </div>
    </div>
  )
}
