import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api, Lead } from '../api'
import { useRuns } from '../App'

/** Outreach: AI-drafted personalized email / call script / WhatsApp per lead,
 *  grounded in its linked data + research. Templates keep messaging consistent.
 *  Drafts and sends are logged onto the lead timeline. Sending stays manual. */
export default function OutreachPage() {
  const [tab, setTab] = useState<'draft' | 'templates'>('draft')
  return (
    <div>
      <h1>Outreach</h1>
      <div className="subtitle">
        Personalized drafts from lead data + AI research. Copy and send from your own mailbox / WhatsApp —
        every draft is logged on the lead's timeline.
      </div>
      <div className="tabs" style={{ marginBottom: 14 }}>
        <button className={tab === 'draft' ? 'active' : ''} onClick={() => setTab('draft')}>Draft pitch</button>
        <button className={tab === 'templates' ? 'active' : ''} onClick={() => setTab('templates')}>Templates</button>
      </div>
      {tab === 'draft' ? <DraftTab /> : <TemplatesTab />}
    </div>
  )
}

function DraftTab() {
  const { toast } = useRuns()
  const location = useLocation() as any
  const [leads, setLeads] = useState<Lead[]>([])
  const [leadId, setLeadId] = useState<number>(location.state?.leadId || 0)
  const [channel, setChannel] = useState<'email' | 'call' | 'whatsapp'>('email')
  const [templates, setTemplates] = useState<any[]>([])
  const [templateId, setTemplateId] = useState(0)
  const [extra, setExtra] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ draft: string; provider: string; wa_link?: string } | null>(null)

  useEffect(() => {
    api.leads({ limit: '500', sort: 'updated_at' }).then(r => {
      setLeads(r.items)
      if (!leadId && r.items.length) setLeadId(r.items[0].id)
    }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const lead = leads.find(l => l.id === leadId)
  useEffect(() => {
    api.templates(lead ? { lead_type: lead.lead_type, channel } : { channel })
      .then(ts => { setTemplates(ts); setTemplateId(ts[0]?.id || 0) })
      .catch(() => {})
  }, [lead?.lead_type, channel])

  const generate = async () => {
    if (!leadId) return
    setBusy(true); setResult(null)
    try {
      const res = await api.draft({ lead_id: leadId, channel, template_id: templateId, extra_instructions: extra })
      setResult(res)
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 2fr) minmax(420px, 3fr)', gap: 18, alignItems: 'start' }}>
      <div className="panel">
        <div className="field">
          <label>Lead</label>
          <select value={leadId} onChange={e => { setLeadId(Number(e.target.value)); setResult(null) }}>
            {leads.length === 0 && <option value={0}>— no leads yet —</option>}
            {leads.map(l => <option key={l.id} value={l.id}>{l.name} ({l.lead_type} · {l.stage})</option>)}
          </select>
        </div>
        <div className="field">
          <label>Channel</label>
          <div className="tabs">
            {(['email', 'call', 'whatsapp'] as const).map(c => (
              <button key={c} className={channel === c ? 'active' : ''} onClick={() => { setChannel(c); setResult(null) }}>
                {c === 'email' ? '✉ Email' : c === 'call' ? '📞 Call script' : '💬 WhatsApp'}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <label>Template / angle</label>
          <select value={templateId} onChange={e => setTemplateId(Number(e.target.value))}>
            <option value={0}>— freestyle (no template) —</option>
            {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Extra instructions (optional)</label>
          <textarea rows={3} value={extra} onChange={e => setExtra(e.target.value)}
            placeholder="e.g. mention our Hyderabad plant visit offer, keep it under 100 words…" />
        </div>
        <button disabled={busy || !leadId} onClick={generate} style={{ width: '100%' }}>
          {busy ? 'Generating…' : '⚡ Generate draft'}
        </button>
        {lead && Object.keys(lead.data || {}).length > 0 && (
          <div className="dim" style={{ fontSize: 12, marginTop: 10 }}>
            Grounded in: linked {lead.lead_type} data{lead.entity_kind === 'epr_company' ? ' + EPR research (if run)' : ''} + recent notes.
          </div>
        )}
      </div>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>Draft {result?.provider && <span className="dim" style={{ fontSize: 12 }}>via {result.provider}</span>}</h2>
        {!result && <div className="dim">Generate a draft to see it here. It is automatically logged on the lead's timeline.</div>}
        {result && (
          <>
            <div className="draft-box">{result.draft}</div>
            <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <button onClick={() => { navigator.clipboard.writeText(result.draft); }}>📋 Copy</button>
              {result.wa_link && (
                <a href={result.wa_link} target="_blank" rel="noreferrer">
                  <button className="ghost">💬 Open in WhatsApp</button>
                </a>
              )}
              <button className="ghost" onClick={async () => {
                await api.logOutreach({ lead_id: leadId, channel, text: result.draft.slice(0, 200) })
                setResult(null)
              }}>✓ Mark as sent</button>
              <button className="ghost" disabled={busy} onClick={generate}>↻ Regenerate</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function TemplatesTab() {
  const { toast } = useRuns()
  const [items, setItems] = useState<any[]>([])
  const [editing, setEditing] = useState<any>(null)

  const load = () => { api.templates().then(setItems).catch(() => {}) }
  useEffect(load, [])

  return (
    <div className="panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
        <span className="dim" style={{ fontSize: 13 }}>
          Templates steer the AI: the body describes the angle/structure, the AI personalizes it per lead.
        </span>
        <button onClick={() => setEditing({ id: 0, name: '', lead_type: 'any', channel: 'email', body: '' })}>+ New template</button>
      </div>
      <table>
        <thead><tr><th>Name</th><th>Lead type</th><th>Channel</th><th>Angle</th><th></th></tr></thead>
        <tbody>
          {items.map(t => (
            <tr key={t.id}>
              <td style={{ fontWeight: 600 }}>{t.name}</td>
              <td><span className="chip">{t.lead_type}</span></td>
              <td className="dim">{t.channel}</td>
              <td className="dim" style={{ fontSize: 12, maxWidth: 420 }}>{t.body.slice(0, 130)}…</td>
              <td style={{ whiteSpace: 'nowrap' }}>
                <button className="ghost" onClick={() => setEditing(t)}>Edit</button>{' '}
                <button className="ghost red" onClick={async () => { await api.deleteTemplate(t.id); load() }}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <div className="modal-overlay" onClick={() => setEditing(null)}>
          <div className="modal" style={{ width: 560 }} onClick={e => e.stopPropagation()}>
            <h3>{editing.id ? 'Edit template' : 'New template'}</h3>
            <div className="field"><label>Name</label>
              <input type="text" value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} /></div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div className="field"><label>Lead type</label>
                <select value={editing.lead_type} onChange={e => setEditing({ ...editing, lead_type: e.target.value })}>
                  {['any', 'chemical', 'epr', 'battery'].map(t => <option key={t} value={t}>{t}</option>)}
                </select></div>
              <div className="field"><label>Channel</label>
                <select value={editing.channel} onChange={e => setEditing({ ...editing, channel: e.target.value })}>
                  {['email', 'call', 'whatsapp'].map(c => <option key={c} value={c}>{c}</option>)}
                </select></div>
            </div>
            <div className="field"><label>Angle / structure (instructions for the AI)</label>
              <textarea rows={6} value={editing.body} onChange={e => setEditing({ ...editing, body: e.target.value })}
                placeholder="e.g. Highlight their {gap_tons} ton EPR shortfall, our certificate generation capability, propose a 15-min call…" /></div>
            <div className="actions">
              <button className="secondary" onClick={() => setEditing(null)}>Cancel</button>
              <button disabled={!editing.name.trim()} onClick={async () => {
                try {
                  await api.saveTemplate(editing, editing.id)
                  toast('success', 'Template saved')
                  setEditing(null); load()
                } catch (e: any) { toast('error', String(e.message || e)) }
              }}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
