import { useRef, useState, useEffect } from 'react'
import { api, download, Run } from '../api'
import { useRuns } from '../App'

export default function UploadPage() {
  const { runs, batteryRuns, refresh, setSelectedId, toast } = useRuns()
  const [eximFiles, setEximFiles] = useState<File[]>([])
  const [baseFile, setBaseFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [trendExclude, setTrendExclude] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const [llmInfo, setLlmInfo] = useState<any>(null)
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const baseInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.config().then(cfg => {
      setLlmInfo(cfg.llm)
      setTrendExclude((cfg.default_trend_exclude || []).join(', '))
    }).catch(() => {})
  }, [])

  const addFiles = (files: FileList | null) => {
    if (!files) return
    const xlsx = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.xlsx'))
    setEximFiles(prev => [...prev, ...xlsx.filter(f => !prev.some(p => p.name === f.name))])
  }

  const start = async () => {
    setBusy(true)
    setErr('')
    try {
      const form = new FormData()
      form.append('name', name || `Run ${new Date().toLocaleString()}`)
      form.append('trend_exclude', trendExclude)
      form.append('use_llm', String(useLlm))
      eximFiles.forEach(f => form.append('exim_files', f))
      if (baseFile) form.append('base_file', baseFile)
      const { run_id } = await api.createRun(form)
      setEximFiles([])
      setBaseFile(null)
      setName('')
      refresh()
      setSelectedId(run_id)
    } catch (e: any) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const allRuns = [...runs, ...batteryRuns].sort((a, b) => b.id - a.id)

  return (
    <div>
      <h1>Upload &amp; Runs</h1>
      <div className="subtitle">Upload EXIM trade data files and start an attractiveness analysis run.
        {' '}Battery-scrap data has its own upload on the Battery Procurement page.</div>

      <div className="panel">
        <div
          className={`dropzone ${drag ? 'drag' : ''}`}
          onDragOver={e => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}
          onClick={() => fileInput.current?.click()}
        >
          {eximFiles.length === 0
            ? <>Drag &amp; drop EXIM .xlsx files here, or click to browse</>
            : <>{eximFiles.map(f => <span className="chip" key={f.name}>{f.name}</span>)}<br /><span className="dim">Click to add more</span></>}
          <input ref={fileInput} type="file" multiple accept=".xlsx" style={{ display: 'none' }}
            onChange={e => { addFiles(e.target.files); e.target.value = '' }} />
        </div>

        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 16, alignItems: 'flex-end' }}>
          <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label className="dim">Run name</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. HSN 2846 June refresh" style={{ width: 260 }} />
          </div>
          <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label className="dim">Trend-excluded months (still displayed, comma-separated)</label>
            <input type="text" value={trendExclude} onChange={e => setTrendExclude(e.target.value)} style={{ width: 300 }} />
          </div>
          <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label className="dim">Base portfolio (optional — default: 260-chemical Scimplify base)</label>
            <button className="secondary" onClick={() => baseInput.current?.click()}>
              {baseFile ? baseFile.name : 'Upload replacement base portfolio…'}
            </button>
            <input ref={baseInput} type="file" accept=".xlsx" style={{ display: 'none' }}
              onChange={e => setBaseFile(e.target.files?.[0] ?? null)} />
          </div>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', paddingBottom: 8 }}>
            <input type="checkbox" checked={useLlm} onChange={e => setUseLlm(e.target.checked)} />
            <span className="dim">
              LLM-assisted matching {llmInfo && (llmInfo.provider === 'off' || !(llmInfo.has_key || llmInfo.provider === 'ollama')
                ? '(provider off — pure rule-based)' : `(${llmInfo.provider})`)}
            </span>
          </label>
          <button disabled={busy || eximFiles.length === 0} onClick={start}>
            {busy ? 'Uploading…' : 'Start analysis'}
          </button>
        </div>
        {err && <div className="error" style={{ marginTop: 10 }}>{err}</div>}
      </div>

      <h2>Run history</h2>
      {allRuns.map(r => (
        <RunRow key={r.id} run={r} onSelect={() => setSelectedId(r.id)} onChanged={refresh} toast={toast} />
      ))}
      {allRuns.length === 0 && <div className="dim">No runs yet — upload EXIM files above to start.</div>}
    </div>
  )
}

function RunRow({ run: r, onSelect, onChanged, toast }: {
  run: Run; onSelect: () => void; onChanged: () => void
  toast: (kind: 'success' | 'error', text: string) => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [newName, setNewName] = useState(r.name)
  const [confirmDel, setConfirmDel] = useState(false)
  const isBattery = r.kind === 'battery'

  const rename = async () => {
    try {
      await api.renameRun(r.id, newName)
      setRenaming(false)
      onChanged()
    } catch (e: any) {
      toast('error', String(e.message || e))
    }
  }

  const del = async () => {
    try {
      await api.deleteRun(r.id)
      toast('success', `Run #${r.id} deleted`)
      onChanged()
    } catch (e: any) {
      toast('error', String(e.message || e))
    }
  }

  return (
    <div className="panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 240 }}>
          {renaming ? (
            <span style={{ display: 'flex', gap: 6 }}>
              <input type="text" value={newName} autoFocus onChange={e => setNewName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') rename(); if (e.key === 'Escape') setRenaming(false) }} />
              <button className="ghost" onClick={rename}>Save</button>
            </span>
          ) : (
            <strong>#{r.id} — {r.name} {isBattery && <span className="pool-badge opportunity">battery</span>}</strong>
          )}
          <div className="dim" style={{ fontSize: 12 }}>
            {r.created_at ? new Date(r.created_at + 'Z').toLocaleString() : ''} · {(r.config.files || []).length} EXIM file(s)
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 220, maxWidth: 420 }}>
          {r.status === 'running' || r.status === 'queued' ? (
            <>
              <div className="progress-outer">
                <div className="progress-inner" style={{ width: `${Math.max(r.progress, 4)}%` }}>{r.progress}%</div>
              </div>
              <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{r.stage}</div>
            </>
          ) : r.status === 'done' ? (
            <span className="success">✓ Complete — {isBattery
              ? `${r.stats.suppliers ?? 0} suppliers + ${r.stats.buyers ?? 0} buyers from ${(r.stats.total_rows || 0).toLocaleString()} rows`
              : `${r.stats.base_chemicals} base + ${r.stats.opportunity_chemicals} opportunity chemicals from ${(r.stats.total_rows || 0).toLocaleString()} rows`}
              {(r.stats.skipped_files || []).length > 0 && <span className="error"> · skipped: {r.stats.skipped_files.join(', ')}</span>}
            </span>
          ) : (
            <span className="error">✗ {r.error || 'Failed'}</span>
          )}
        </div>
        <div style={{ whiteSpace: 'nowrap' }}>
          {r.status === 'done' && !isBattery && (
            <>
              <button className="ghost" onClick={onSelect}>Select</button>{' '}
              <button className="ghost" onClick={() =>
                download(`/api/runs/${r.id}/export`, `ATT_Results_Run${r.id}.xlsx`)
                  .catch(e => toast('error', String(e.message || e)))}>Export</button>{' '}
              <button className="ghost" onClick={() =>
                download(`/api/runs/${r.id}/report.pdf`, `ATT_Summary_Run${r.id}.pdf`)
                  .catch(e => toast('error', String(e.message || e)))}>PDF</button>{' '}
            </>
          )}
          {r.status === 'done' && isBattery && (
            <>
              <button className="ghost" onClick={() =>
                download(`/api/runs/${r.id}/battery/export`, `Battery_Procurement_Run${r.id}.xlsx`)
                  .catch(e => toast('error', String(e.message || e)))}>Export</button>{' '}
            </>
          )}
          <button className="ghost gold" onClick={() => { setNewName(r.name); setRenaming(v => !v) }}>Rename</button>{' '}
          {r.status !== 'running' && (
            confirmDel
              ? <>
                  <button className="ghost red" onClick={del}>Really delete?</button>{' '}
                  <button className="ghost" onClick={() => setConfirmDel(false)}>Cancel</button>
                </>
              : <button className="ghost red" onClick={() => setConfirmDel(true)}>Delete</button>
          )}
        </div>
      </div>
    </div>
  )
}
