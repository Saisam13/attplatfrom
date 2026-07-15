import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, download, FeedbackItem } from '../api'
import { useRuns } from '../App'

const VERDICT_COLOR: Record<string, string> = {
  confirm: 'var(--green)', challenge: 'var(--orange)', correct: 'var(--red)',
}

export default function FeedbackPage() {
  const { selectedRun } = useRuns()
  const [items, setItems] = useState<FeedbackItem[]>([])

  const load = () => {
    if (!selectedRun) return
    api.feedback(selectedRun.id).then(setItems).catch(() => {})
  }
  useEffect(load, [selectedRun?.id])

  if (!selectedRun) return <div><h1>Feedback</h1><div className="dim">No run selected.</div></div>

  const counts = items.reduce((a, f) => { a[f.verdict] = (a[f.verdict] || 0) + 1; return a }, {} as Record<string, number>)

  return (
    <div>
      <h1>Trader Feedback — {selectedRun.name}</h1>
      <div className="subtitle">
        Feedback collected from the Rankings and Chemical detail pages.
        Use Confirm / Challenge / Correct buttons there to add entries.
      </div>

      <div className="filters">
        <span className="chip" style={{ color: VERDICT_COLOR.confirm }}>Confirm: {counts.confirm || 0}</span>
        <span className="chip" style={{ color: VERDICT_COLOR.challenge }}>Challenge: {counts.challenge || 0}</span>
        <span className="chip" style={{ color: VERDICT_COLOR.correct }}>Correct: {counts.correct || 0}</span>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() =>
          download(`/api/runs/${selectedRun.id}/feedback/export`, `ATT_Feedback_Run${selectedRun.id}.xlsx`)}>
          ⬇ Export feedback (xlsx)
        </button>
      </div>

      <div className="panel" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>When</th><th>Chemical</th><th>Verdict</th><th>User</th>
              <th>Suggested tier</th><th>Duration of view</th><th>Comment</th>
            </tr>
          </thead>
          <tbody>
            {items.map(f => (
              <tr key={f.id}>
                <td className="dim" style={{ whiteSpace: 'nowrap' }}>{f.created_at ? new Date(f.created_at + 'Z').toLocaleString() : ''}</td>
                <td><Link to={`/chemical/${encodeURIComponent(f.chemical)}`}>{f.chemical}</Link></td>
                <td style={{ color: VERDICT_COLOR[f.verdict], fontWeight: 700, textTransform: 'uppercase', fontSize: 12 }}>{f.verdict}</td>
                <td>{f.user_name || <span className="dim">anonymous</span>}</td>
                <td>{f.suggested_tier ? `Tier ${f.suggested_tier}` : '—'}</td>
                <td>{f.expected_duration || '—'}</td>
                <td style={{ maxWidth: 400 }}>{f.comment}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <div className="dim" style={{ padding: 20 }}>No feedback yet for this run.</div>}
      </div>
    </div>
  )
}
