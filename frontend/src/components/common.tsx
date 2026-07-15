import { useState } from 'react'
import { api, user } from '../api'

export function TierBadge({ tier }: { tier: string }) {
  return <span className={`tier-badge tier-${tier}`}>Tier {tier}</span>
}

export function PoolBadge({ pool }: { pool: string }) {
  return <span className={`pool-badge ${pool}`}>{pool}</span>
}

export const STAGE_LABELS: Record<string, string> = {
  new: 'New', contacted: 'Contacted', in_talks: 'In talks', deal: 'Deal', dead: 'Dead',
}

export function StageBadge({ stage }: { stage: string }) {
  return <span className={`stage-badge stage-${stage}`}>{STAGE_LABELS[stage] || stage}</span>
}

/** Per-row "+ Lead" button used across EPR / HSN / battery / rankings tables.
 *  Snapshots the row data (timestamped server-side) onto the lead. */
export function AddLeadButton({ name, leadType, source, entityKind, entityRef, hsnCode, country, data, onDone }: {
  name: string; leadType: string; source: string
  entityKind?: string; entityRef?: string | number; hsnCode?: string; country?: string
  data?: any; onDone?: (id: number, existing: boolean) => void
}) {
  const [state, setState] = useState<'idle' | 'busy' | 'added' | 'exists'>('idle')
  const add = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setState('busy')
    try {
      const res = await api.createLead({
        name, lead_type: leadType, source,
        entity_kind: entityKind || '', entity_ref: String(entityRef ?? ''),
        hsn_code: hsnCode || '', country: country || '', data: data || {},
      })
      setState(res.existing ? 'exists' : 'added')
      onDone?.(res.id, res.existing)
    } catch {
      setState('idle')
    }
  }
  if (state === 'added') return <span className="success" style={{ fontSize: 12 }}>Lead ✓</span>
  if (state === 'exists') return <span className="dim" style={{ fontSize: 12 }}>In leads</span>
  return (
    <button className="ghost" disabled={state === 'busy'} title="Add to lead tracker" onClick={add}>
      {state === 'busy' ? '…' : '+ Lead'}
    </button>
  )
}

// ── Feedback (Confirm / Challenge / Correct) ──────────────────
const DURATIONS = ['<1 month', '1-3 months', '3-6 months', '6+ months']

export function FeedbackButtons({ runId, chemical, onDone }: {
  runId: number; chemical: string; onDone?: () => void
}) {
  const [modal, setModal] = useState<'challenge' | 'correct' | null>(null)
  const [sent, setSent] = useState('')

  const confirm = async () => {
    await api.addFeedback({ run_id: runId, chemical, verdict: 'confirm', user_name: user.get() })
    setSent('Confirmed')
    onDone?.()
  }

  return (
    <span onClick={e => e.stopPropagation()}>
      {sent ? (
        <span className="success">{sent} ✓</span>
      ) : (
        <>
          <button className="ghost" title="Agree with this ranking" onClick={confirm}>Confirm</button>{' '}
          <button className="ghost gold" title="Disagree — flag for review" onClick={() => setModal('challenge')}>Challenge</button>{' '}
          <button className="ghost red" title="Propose a correction" onClick={() => setModal('correct')}>Correct</button>
        </>
      )}
      {modal && (
        <FeedbackModal
          runId={runId} chemical={chemical} verdict={modal}
          onClose={() => setModal(null)}
          onSubmitted={() => { setModal(null); setSent(modal === 'challenge' ? 'Challenged' : 'Corrected'); onDone?.() }}
        />
      )}
    </span>
  )
}

function FeedbackModal({ runId, chemical, verdict, onClose, onSubmitted }: {
  runId: number; chemical: string; verdict: 'challenge' | 'correct'
  onClose: () => void; onSubmitted: () => void
}) {
  const [name, setName] = useState(user.get())
  const [tier, setTier] = useState('')
  const [duration, setDuration] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true)
    setErr('')
    try {
      await api.addFeedback({
        run_id: runId, chemical, verdict, user_name: name,
        suggested_tier: tier, expected_duration: duration, comment,
      })
      onSubmitted()
    } catch (e: any) {
      setErr(String(e.message || e))
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>{verdict === 'challenge' ? 'Challenge ranking' : 'Correct ranking'} — {chemical}</h3>
        <div className="field">
          <label>Your name</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Anuraag" />
        </div>
        <div className="field">
          <label>Suggested tier</label>
          <select value={tier} onChange={e => setTier(e.target.value)}>
            <option value="">— select —</option>
            <option value="A">Tier A (≥70)</option>
            <option value="B">Tier B (40-69)</option>
            <option value="C">Tier C (&lt;40)</option>
          </select>
        </div>
        <div className="field">
          <label>Expected duration of your view</label>
          <select value={duration} onChange={e => setDuration(e.target.value)}>
            <option value="">— select —</option>
            {DURATIONS.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Comment</label>
          <textarea rows={3} value={comment} onChange={e => setComment(e.target.value)}
            placeholder="Why do you disagree? Market context, customer intel, pricing knowledge…" />
        </div>
        {err && <div className="error">{err}</div>}
        <div className="actions">
          <button className="secondary" onClick={onClose}>Cancel</button>
          <button disabled={busy || !name.trim()} onClick={submit}>Submit</button>
        </div>
      </div>
    </div>
  )
}
