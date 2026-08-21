import { useEffect, useState } from 'react'
import { api } from '../api'
import { useRuns } from '../App'

const DIMS = ['volume', 'price', 'buyers', 'suppliers', 'trend', 'structure', 'freedom', 'barrier']

export default function SettingsPage() {
  const { selectedRun, toast, userName } = useRuns()
  const [s, setS] = useState<any>(null)
  const [log, setLog] = useState<any[]>([])
  const [showLog, setShowLog] = useState(false)

  const load = () => {
    api.settings().then(setS).catch(e => toast('error', String(e.message || e)))
    api.settingsLog().then(setLog).catch(() => {})
  }
  useEffect(load, [])  // eslint-disable-line

  const save = async (changes: object, msg = 'Settings saved') => {
    try {
      const next = await api.saveSettings(changes)
      setS(next)
      api.settingsLog().then(setLog).catch(() => {})
      toast('success', msg)
    } catch (e: any) {
      toast('error', String(e.message || e))
    }
  }

  if (!s) return <div><h1>Settings</h1><div className="dim">Loading…</div></div>

  return (
    <div>
      <h1>Settings</h1>
      <div className="subtitle">
        Changes apply to future runs and are logged (who, when, old → new) — saved as {userName || 'anonymous'}.
      </div>

      <AiProvidersPanel s={s} save={save} toast={toast} />
      <LlmPanel s={s} save={save} toast={toast} />
      <EprWeightsPanel s={s} save={save} />
      <ApiKeysPanel toast={toast} />
      <CachePanel toast={toast} />
      <WeightsPanel s={s} save={save} runId={selectedRun?.status === 'done' ? selectedRun.id : null} toast={toast} />
      <GeneralPanel s={s} save={save} />
      <SecurityPanel s={s} save={save} />

      <h2>Change log</h2>
      <div className="panel">
        {log.length === 0 && <div className="dim">No settings changes recorded yet.</div>}
        {log.length > 0 && (
          <>
            <table>
              <thead><tr><th>When</th><th>Who</th><th>Setting</th><th>Old</th><th>New</th></tr></thead>
              <tbody>
                {(showLog ? log : log.slice(0, 10)).map(l => (
                  <tr key={l.id}>
                    <td className="mono dim">{l.created_at ? new Date(l.created_at + 'Z').toLocaleString() : ''}</td>
                    <td>{l.user_name || '—'}</td>
                    <td style={{ fontWeight: 600 }}>{l.key}</td>
                    <td className="mono dim" style={{ maxWidth: 260, fontSize: 11, wordBreak: 'break-all' }}>{l.old_value}</td>
                    <td className="mono" style={{ maxWidth: 260, fontSize: 11, wordBreak: 'break-all' }}>{l.new_value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {log.length > 10 && (
              <button className="ghost" style={{ marginTop: 8 }} onClick={() => setShowLog(v => !v)}>
                {showLog ? 'Show less' : `Show all ${log.length}`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function AiProvidersPanel({ s, save, toast }: any) {
  const p = s.ai_providers || {}
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [testResult, setTestResult] = useState('')
  const [testing, setTesting] = useState('')
  const [config, setConfig] = useState<Record<string, string>>({})

  const KeyInput = ({ field, label, hint }: { field: string; label: string; hint: string }) => (
    <div>
      <label className="dim" style={{ display: 'block', marginBottom: 4 }}>{label} <span style={{ opacity: 0.7 }}>({hint})</span></label>
      <input type="password" style={{ width: 250 }}
        placeholder={p[`has_${field}`] ? 'Key saved — paste to replace' : 'Not set'}
        value={keys[field] || ''} onChange={e => setKeys(k => ({ ...k, [field]: e.target.value }))} />
    </div>
  )

  const ConfigInput = ({ field, label, hint, width = 220, placeholder }: any) => (
    <div>
      <label className="dim" style={{ display: 'block', marginBottom: 4 }}>{label} <span style={{ opacity: 0.7 }}>({hint})</span></label>
      <input style={{ width }} placeholder={placeholder || ''}
        value={config[field] ?? p[field] ?? ''}
        onChange={e => setConfig(c => ({ ...c, [field]: e.target.value }))} />
    </div>
  )

  const apply = () => {
    const changes: any = {}
    Object.entries(keys).forEach(([k, v]) => { if (v.trim()) changes[k] = v.trim() })
    if (Object.keys(changes).length === 0) { toast('error', 'No new keys entered'); return }
    save({ ai_providers: changes }, 'AI provider keys saved')
    setKeys({})
  }

  const applyConfig = () => {
    if (Object.keys(config).length === 0) { toast('error', 'No changes to save'); return }
    save({ ai_providers: config }, 'AI config saved')
    setConfig({})
  }

  const test = async (kind: 'llm' | 'search') => {
    setTesting(kind); setTestResult('')
    try {
      const r = await api.testAi(kind)
      setTestResult(r.ok
        ? `✓ ${kind === 'llm' ? 'AI' : 'Search'} working via ${r.provider}${r.model ? ` (${r.model})` : ''}`
        : `✗ ${r.error || 'failed'}`)
    } catch (e: any) {
      setTestResult(`✗ ${String(e.message || e)}`)
    } finally {
      setTesting('')
    }
  }

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>AI providers (research · drafts · HSN suggest · /api/v1/ai)</h2>
      <div className="dim" style={{ fontSize: 13, marginBottom: 12 }}>
        All optional — free tiers work: Groq + Tavily are enough to start. Bharat Router is always
        tried first whenever its key is set, regardless of the order below. Fallback order:
        LLM {(() => {
          const order = p.llm_order || ['groq', 'gemini', 'anthropic']
          return (order.includes('bharatrouter') ? order : ['bharatrouter', ...order]).join(' → ')
        })()} · search {(p.search_order || ['tavily', 'firecrawl']).join(' → ')}.
        Keys are stored in the local database and never shown again.
      </div>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <KeyInput field="bharatrouter_key" label="Bharat Router" hint="paid, INR credits — bharatrouter.com, tried first" />
        <KeyInput field="groq_key" label="Groq" hint="free — console.groq.com" />
        <KeyInput field="gemini_key" label="Gemini" hint="free — aistudio.google.com" />
        <KeyInput field="anthropic_key" label="Anthropic" hint="paid — console.anthropic.com" />
        <KeyInput field="tavily_key" label="Tavily search" hint="free 1000/mo — tavily.com" />
        <KeyInput field="firecrawl_key" label="Firecrawl search" hint="fallback — firecrawl.dev" />
        <KeyInput field="apify_token" label="Apify token" hint="apify.com — contact/people enrichment" />
      </div>
      <div className="filters" style={{ marginTop: 14 }}>
        <button onClick={apply}>Save keys</button>
        <button className="secondary" disabled={!!testing} onClick={() => test('llm')}>
          {testing === 'llm' ? 'Testing…' : 'Test AI'}
        </button>
        <button className="secondary" disabled={!!testing} onClick={() => test('search')}>
          {testing === 'search' ? 'Testing…' : 'Test search'}
        </button>
        {testResult && <span className={testResult.startsWith('✓') ? 'success' : 'error'}>{testResult}</span>}
      </div>

      <div className="dim" style={{ fontSize: 13, margin: '18px 0 12px' }}>
        Sourcing-agent research (per-company AI search + Apify enrichment): rate-limited and
        time-boxed to protect paid credits.
      </div>
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <ConfigInput field="bharatrouter_model" label="Bharat Router model" hint="e.g. qwen2.5-7b-instruct"
          placeholder="qwen2.5-7b-instruct" />
        <ConfigInput field="apify_actor_id" label="Apify actor ID" hint="e.g. username~actor-name" width={260} />
        <ConfigInput field="apify_input_template" label="Apify actor input (JSON)" hint="{company} is substituted"
          width={320} placeholder='{"query": "{company}"}' />
        <ConfigInput field="research_rate_limit_per_hour" label="Research rate limit" hint="calls/hour, 0=unlimited" width={140} />
        <ConfigInput field="research_timeout_seconds" label="Research timeout" hint="max seconds per company" width={140} />
      </div>
      <div className="filters" style={{ marginTop: 14 }}>
        <button onClick={applyConfig}>Save AI config</button>
      </div>
    </div>
  )
}

function EprWeightsPanel({ s, save, toast }: any) {
  const [mats, setMats] = useState<any[]>([])
  const [edits, setEdits] = useState<Record<number, any>>({})
  const [dirty, setDirty] = useState(false)
  const [addName, setAddName] = useState('')

  const loadMats = () => {
    api.eprMaterials().then(data => {
      setMats(data)
      setEdits({})
      setDirty(false)
    }).catch(() => {})
  }
  useEffect(loadMats, [])

  const getVal = (m: any, field: string) => {
    if (edits[m.id] && field in edits[m.id]) return edits[m.id][field]
    return m[field]
  }

  const setField = (id: number, field: string, value: any) => {
    setEdits(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }))
    setDirty(true)
  }

  const overallTotal = mats.reduce((acc, m) => acc + (getVal(m, 'active') ? Number(getVal(m, 'overall_weight')) || 0 : 0), 0)
  const overallOk = Math.abs(overallTotal - 1) < 0.001

  const normalizeOverall = () => {
    const total = mats.reduce((acc, m) => acc + (getVal(m, 'active') ? Number(getVal(m, 'overall_weight')) || 0 : 0), 0)
    if (total <= 0) return toast('error', 'Total active weight is 0')
    mats.forEach(m => {
      if (getVal(m, 'active')) {
        setField(m.id, 'overall_weight', Number((Number(getVal(m, 'overall_weight')) / total).toFixed(4)))
      }
    })
  }

  const normalizeRow = (m: any) => {
    const tw = Math.abs(Number(getVal(m, 'target_weight')) || 0)
    const cw = Math.abs(Number(getVal(m, 'credit_weight')) || 0)
    const total = tw + cw
    if (total <= 0) return toast('error', 'Target + Credit weight is 0')
    setField(m.id, 'target_weight', Number((tw / total).toFixed(4)))
    setField(m.id, 'credit_weight', Number((cw / total).toFixed(4)))
  }

  const saveAll = async () => {
    try {
      for (const m of mats) {
        const ow = Number(getVal(m, 'overall_weight'))
        const tw = Number(getVal(m, 'target_weight'))
        const cw = Number(getVal(m, 'credit_weight'))
        const active = getVal(m, 'active')
        await api.eprUpdateMaterial(m.id, {
          overall_weight: ow,
          target_weight: tw,
          credit_weight: cw,
          active,
        })
      }
      toast('success', 'Material weights saved — grades recomputed')
      loadMats()
    } catch (e: any) {
      toast('error', String(e.message || e))
    }
  }

  const addMaterial = async () => {
    const name = addName.trim()
    if (!name) return
    try {
      await api.eprCreateMaterial({ name, overall_weight: 0 })
      toast('success', `Material "${name}" added`)
      setAddName('')
      loadMats()
    } catch (e: any) {
      toast('error', String(e.message || e))
    }
  }

  return (
    <div className="panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ marginTop: 0, color: 'var(--teal)' }}>Material Management &amp; Priority Weights</h2>
          <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
            Configure which materials are tracked and their priority calculation weights.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input type="text" placeholder="New material name" value={addName}
            onChange={e => setAddName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addMaterial() }}
            style={{ width: 180, padding: '6px 10px' }} />
          <button className="secondary" onClick={addMaterial} disabled={!addName.trim()}>+ Add Material</button>
        </div>
      </div>

      <div className="panel" style={{ background: 'var(--bg-light)', padding: '10px 14px', marginBottom: 14, fontSize: 13 }}>
        <strong>Priority Score Formula (Scaled 1-100):</strong>{' '}
        <span className="mono" style={{ color: 'var(--teal)' }}>
          SUM( [Score(Target) × Target Weight + Score(Credits) × Credit Weight] × Overall Weight )
        </span>
        <br />
        <span className="dim">* Tip: For mathematical purity, Target Weight + Credit Weight should equal 1.0 per row.</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Material Name</th>
              <th>Active</th>
              <th style={{ minWidth: 130 }}>
                Overall Weight{' '}
                <button className="ghost" style={{ fontSize: 11, padding: '2px 6px' }} onClick={normalizeOverall}>Normalize</button>
              </th>
              <th style={{ minWidth: 120 }}>Target Weight</th>
              <th style={{ minWidth: 120 }}>Credit Weight</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {mats.map(m => {
              const tw = Number(getVal(m, 'target_weight')) || 0
              const cw = Number(getVal(m, 'credit_weight')) || 0
              const rowTotal = tw + cw
              const rowOk = Math.abs(rowTotal - 1) < 0.001
              return (
                <tr key={m.id} style={{ opacity: getVal(m, 'active') ? 1 : 0.5 }}>
                  <td style={{ fontWeight: 600 }}>{m.name}</td>
                  <td>
                    <label className="toggle-switch">
                      <input type="checkbox" checked={!!getVal(m, 'active')}
                        onChange={e => setField(m.id, 'active', e.target.checked)} />
                      <span className="toggle-slider" />
                    </label>
                  </td>
                  <td>
                    <input type="number" step={0.01} min={0}
                      value={getVal(m, 'overall_weight')} style={{ width: 90, background: 'var(--bg-light)' }}
                      onChange={e => setField(m.id, 'overall_weight', Number(e.target.value))} />
                  </td>
                  <td>
                    <input type="number" step={0.01} min={0}
                      value={getVal(m, 'target_weight')} style={{ width: 90 }}
                      onChange={e => setField(m.id, 'target_weight', Number(e.target.value))} />
                  </td>
                  <td>
                    <input type="number" step={0.01} min={0}
                      value={getVal(m, 'credit_weight')} style={{ width: 90 }}
                      onChange={e => setField(m.id, 'credit_weight', Number(e.target.value))} />
                  </td>
                  <td>
                    <button className="ghost" onClick={() => normalizeRow(m)}
                      title="Normalize Target + Credit to sum 1.0"
                      style={{ fontSize: 12 }}>
                      Normalize Row
                    </button>
                    {!rowOk && <span className="dim" style={{ fontSize: 11, marginLeft: 6 }}>Σ={rowTotal.toFixed(2)}</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2} style={{ textAlign: 'right', fontWeight: 600 }}>Overall Weight Total:</td>
              <td>
                <span className={overallOk ? 'success' : 'error'} style={{ fontWeight: 700 }}>
                  {overallTotal.toFixed(2)}
                </span>
                {!overallOk && <span className="dim" style={{ fontSize: 11, marginLeft: 4 }}>(should be 1.0)</span>}
              </td>
              <td colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
        <button onClick={saveAll} disabled={!dirty} style={{ padding: '8px 24px' }}>
          Save Materials
        </button>
      </div>
    </div>
  )
}

function ApiKeysPanel({ toast }: any) {
  const [keys, setKeys] = useState<any[]>([])
  const [label, setLabel] = useState('')
  const [newKey, setNewKey] = useState('')

  const load = () => { api.apiKeys().then(setKeys).catch(() => {}) }
  useEffect(load, [])

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>External API keys (/api/v1/*)</h2>
      <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
        Keys give other tools read-only access to leads (<span className="mono">GET /api/v1/leads</span>)
        and the AI gateway (<span className="mono">POST /api/v1/ai/complete|search|research|match</span>) —
        send as <span className="mono">X-API-Key</span> header.
      </div>
      <div className="filters" style={{ marginBottom: 10 }}>
        <input type="text" placeholder="Key label (e.g. sheets-dashboard)" value={label}
          onChange={e => setLabel(e.target.value)} style={{ width: 240 }} />
        <button disabled={!label.trim()} onClick={async () => {
          try {
            const r = await api.createApiKey(label)
            setNewKey(r.key); setLabel(''); load()
          } catch (e: any) { toast('error', String(e.message || e)) }
        }}>Generate key</button>
      </div>
      {newKey && (
        <div className="success" style={{ marginBottom: 10, wordBreak: 'break-all' }}>
          New key (copy now — it is never shown again): <span className="mono">{newKey}</span>{' '}
          <button className="ghost" onClick={() => { navigator.clipboard.writeText(newKey); setNewKey('') }}>📋 Copy &amp; hide</button>
        </div>
      )}
      {keys.length > 0 && (
        <table>
          <thead><tr><th>Label</th><th>Key</th><th>Created</th><th>Last used</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {keys.map(k => (
              <tr key={k.id}>
                <td style={{ fontWeight: 600 }}>{k.label || '—'}</td>
                <td className="mono dim">{k.key_preview}</td>
                <td className="mono dim">{k.created_at ? new Date(k.created_at + 'Z').toLocaleDateString() : ''}</td>
                <td className="mono dim">{k.last_used_at ? new Date(k.last_used_at + 'Z').toLocaleString() : 'never'}</td>
                <td>{k.revoked ? <span className="error">revoked</span> : <span className="success">active</span>}</td>
                <td>{!k.revoked && <button className="ghost red" onClick={async () => { await api.revokeApiKey(k.id); load() }}>Revoke</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function CachePanel({ toast }: any) {
  const [stats, setStats] = useState<any[]>([])
  const load = () => { api.cacheStats().then(setStats).catch(() => {}) }
  useEffect(load, [])

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>Unified cache</h2>
      <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
        One cache for all modules — LLM matching, EPR research, web search, AI answers, HSN lookups.
        Entries expire by namespace TTL (0 = kept forever) and can be cleared here.
      </div>
      {stats.length === 0 && <div className="dim">Cache is empty.</div>}
      {stats.length > 0 && (
        <table>
          <thead><tr><th>Namespace</th><th>Entries</th><th>Hits</th><th>TTL (days)</th><th>Newest</th><th></th></tr></thead>
          <tbody>
            {stats.map(n => (
              <tr key={n.namespace}>
                <td className="mono" style={{ fontWeight: 600 }}>{n.namespace}</td>
                <td className="mono">{n.entries.toLocaleString()}</td>
                <td className="mono">{n.hits.toLocaleString()}</td>
                <td className="mono dim">{n.ttl_days || '∞'}</td>
                <td className="mono dim">{n.newest ? new Date(n.newest + 'Z').toLocaleString() : ''}</td>
                <td><button className="ghost red" onClick={async () => {
                  const r = await api.cacheClear(n.namespace)
                  toast('success', `Cleared ${r.cleared} ${n.namespace} entries`)
                  load()
                }}>Clear</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function LlmPanel({ s, save, toast }: any) {
  const [provider, setProvider] = useState(s.llm?.provider || 'off')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(s.llm?.model || '')
  const [baseUrl, setBaseUrl] = useState(s.llm?.base_url || 'http://localhost:11434')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState('')

  const test = async () => {
    setTesting(true)
    setTestResult('')
    try {
      const r = await api.testLlm({ provider, api_key: apiKey, model, base_url: baseUrl })
      setTestResult(r.ok ? `✓ Connected (${r.model})` : `✗ ${r.error}`)
    } catch (e: any) {
      setTestResult(`✗ ${String(e.message || e)}`)
    } finally {
      setTesting(false)
    }
  }

  const apply = () => {
    const llm: any = { provider, model, base_url: baseUrl }
    if (apiKey) llm.api_key = apiKey
    save({ llm }, 'LLM settings saved — applies to the next run')
    setApiKey('')
  }

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>LLM-assisted matching</h2>
      <div className="dim" style={{ fontSize: 13, marginBottom: 12 }}>
        Descriptions that rule-based matching can't identify are sent (batched + cached) to the
        LLM with the base portfolio. Off = pure rule-based, identical numbers to the original module.
      </div>
      <div className="filters">
        <select value={provider} onChange={e => setProvider(e.target.value)}>
          <option value="off">Off (rule-based only)</option>
          <option value="anthropic">Anthropic (Claude)</option>
          <option value="gemini">Google Gemini</option>
          <option value="ollama">Ollama (local)</option>
        </select>
        {provider !== 'off' && provider !== 'ollama' && (
          <input type="password" placeholder={s.llm?.has_api_key ? 'API key saved — paste to replace' : 'API key'}
            value={apiKey} onChange={e => setApiKey(e.target.value)} style={{ width: 280 }} />
        )}
        {provider !== 'off' && (
          <input type="text" placeholder="Model (blank = provider default)" value={model}
            onChange={e => setModel(e.target.value)} style={{ width: 240 }} />
        )}
        {provider === 'ollama' && (
          <input type="text" placeholder="Base URL" value={baseUrl}
            onChange={e => setBaseUrl(e.target.value)} style={{ width: 240 }} />
        )}
        <button className="secondary" disabled={testing || provider === 'off'} onClick={test}>
          {testing ? 'Testing…' : 'Test connection'}
        </button>
        <button onClick={apply}>Save</button>
      </div>
      {testResult && (
        <div className={testResult.startsWith('✓') ? 'success' : 'error'} style={{ marginTop: 6 }}>{testResult}</div>
      )}
    </div>
  )
}

function WeightsPanel({ s, save, runId, toast }: any) {
  const [w, setW] = useState<Record<string, number>>({ ...s.weights })
  const [tierA, setTierA] = useState<number>(s.tier_a_min)
  const [tierB, setTierB] = useState<number>(s.tier_b_min)
  const [preview, setPreview] = useState<any>(null)
  const [previewing, setPreviewing] = useState(false)

  const total = DIMS.reduce((acc, d) => acc + (Number(w[d]) || 0), 0)
  const ok = Math.abs(total - 1) < 0.001
  const dirty = JSON.stringify(w) !== JSON.stringify(s.weights) || tierA !== s.tier_a_min || tierB !== s.tier_b_min

  const runPreview = async () => {
    if (!runId) { toast('error', 'No completed run to preview against'); return }
    setPreviewing(true)
    try {
      setPreview(await api.previewWeights(runId, { weights: w, tier_a_min: tierA, tier_b_min: tierB }))
    } catch (e: any) {
      toast('error', String(e.message || e))
    } finally {
      setPreviewing(false)
    }
  }

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>Scoring weights &amp; tier cutoffs</h2>
      <div className="dim" style={{ fontSize: 13, marginBottom: 12 }}>
        Weights must sum to 1.0. Applies to future runs — use the preview to see how the
        active run's rankings would reshuffle before saving.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '0 28px' }}>
        {DIMS.map(d => (
          <div className="weight-row" key={d}>
            <span style={{ textTransform: 'capitalize' }}>{d}</span>
            <input type="range" min={0} max={0.5} step={0.01} value={w[d] ?? 0}
              onChange={e => setW({ ...w, [d]: Number(e.target.value) })} />
            <input type="number" min={0} max={1} step={0.01} value={w[d] ?? 0}
              onChange={e => setW({ ...w, [d]: Number(e.target.value) })} />
          </div>
        ))}
      </div>
      <div className="filters" style={{ marginTop: 12 }}>
        <span className={ok ? 'success' : 'error'}>Σ = {total.toFixed(2)}</span>
        <label className="dim">Tier A ≥</label>
        <input type="number" value={tierA} min={0} max={100} style={{ width: 80 }}
          onChange={e => setTierA(Number(e.target.value))} />
        <label className="dim">Tier B ≥</label>
        <input type="number" value={tierB} min={0} max={100} style={{ width: 80 }}
          onChange={e => setTierB(Number(e.target.value))} />
        <button className="secondary" disabled={!ok || previewing} onClick={runPreview}>
          {previewing ? 'Computing…' : 'Preview impact'}
        </button>
        <button disabled={!ok || !dirty}
          onClick={() => save({ weights: w, tier_a_min: tierA, tier_b_min: tierB },
            'Scoring settings saved — applies to future runs')}>
          Save
        </button>
        <button className="ghost" onClick={() => { setW({ ...s.weights }); setTierA(s.tier_a_min); setTierB(s.tier_b_min); setPreview(null) }}>
          Reset
        </button>
      </div>

      {preview && (
        <div style={{ marginTop: 14, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
          <strong>Impact on active run:</strong>{' '}
          <span className="dim">
            tiers A/B/C {preview.old_tiers.A ?? 0}/{preview.old_tiers.B ?? 0}/{preview.old_tiers.C ?? 0}
            {' → '}{preview.new_tiers.A ?? 0}/{preview.new_tiers.B ?? 0}/{preview.new_tiers.C ?? 0}
            {' · '}{preview.tier_changes} chemicals change tier
          </span>
          <table style={{ marginTop: 8 }}>
            <thead><tr><th>Chemical</th><th>ATT</th><th>Δ</th><th>Rank</th><th>Tier</th></tr></thead>
            <tbody>
              {preview.movers.slice(0, 10).map((m: any) => (
                <tr key={m.chemical}>
                  <td style={{ fontWeight: 600 }}>{m.chemical}</td>
                  <td className="mono">{m.old_att.toFixed(1)} → {m.new_att.toFixed(1)}</td>
                  <td className={m.delta >= 0 ? 'delta-up' : 'delta-down'}>{m.delta > 0 ? '+' : ''}{m.delta.toFixed(1)}</td>
                  <td className="mono dim">{m.old_rank} → {m.new_rank}</td>
                  <td className="dim">{m.old_tier === m.new_tier ? m.old_tier : `${m.old_tier} → ${m.new_tier}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function GeneralPanel({ s, save }: any) {
  const [retention, setRetention] = useState<number>(s.retention_days ?? 0)
  const [trendExclude, setTrendExclude] = useState((s.trend_exclude_default || []).join(', '))

  const saveRetention = () => {
    if (retention > 0) {
      const ok = window.confirm(
        `This will PERMANENTLY delete every run older than ${retention} day(s) — including its ` +
        `chemical/battery scores, raw shipment rows, and geo/regulatory logs — on a recurring ` +
        `background check. This cannot be undone. Continue?`)
      if (!ok) return
    }
    save({ retention_days: retention })
  }

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>General</h2>
      <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <label className="dim" style={{ display: 'block', marginBottom: 4 }}>
            Auto-delete runs older than (days, 0 = keep forever)
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="number" min={0} value={retention} style={{ width: 110 }}
              onChange={e => setRetention(Number(e.target.value))} />
            <button className="secondary" disabled={retention === s.retention_days}
              onClick={saveRetention}>Save</button>
          </div>
        </div>
        <div>
          <label className="dim" style={{ display: 'block', marginBottom: 4 }}>
            Default trend-excluded months (comma-separated YYYY-MM)
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" value={trendExclude} style={{ width: 280 }}
              onChange={e => setTrendExclude(e.target.value)} />
            <button className="secondary"
              onClick={() => save({ trend_exclude_default: trendExclude.split(',').map((m: string) => m.trim()).filter(Boolean) })}>
              Save
            </button>
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap', marginTop: 16 }}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input type="checkbox" checked={!!s.feedback_adjustment}
            onChange={e => save({ feedback_adjustment: e.target.checked },
              e.target.checked ? 'Feedback adjustments ON for future runs' : 'Feedback adjustments OFF for future runs')} />
          <span>Trader feedback adjusts future scores (bounded ±5, shown in the Fb adj column)</span>
        </label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input type="checkbox" checked={s.show_feedback_page !== false}
            onChange={e => save({ show_feedback_page: e.target.checked })} />
          <span>Show Feedback page in the sidebar</span>
        </label>
      </div>
    </div>
  )
}

function SecurityPanel({ s, save }: any) {
  const [pinCode, setPinCode] = useState('')
  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>Security</h2>
      <div className="dim" style={{ fontSize: 13, marginBottom: 10 }}>
        On the office LAN this can stay off. Enable the shared 4-digit PIN if the platform is ever
        exposed beyond the office network (e.g. a cloud VM) — every browser must then enter it once.
        Locked out after 5 wrong attempts within 5 minutes.
      </div>
      <div className="filters">
        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input type="checkbox" checked={!!s.pin_enabled}
            onChange={e => save({ pin_enabled: e.target.checked },
              e.target.checked ? 'PIN gate ENABLED' : 'PIN gate disabled')} />
          <span>Require team PIN</span>
        </label>
        <input type="password" placeholder={s.pin_code ? '4-digit PIN — type to replace' : 'Set 4-digit PIN'}
          maxLength={4} inputMode="numeric" pattern="[0-9]*"
          value={pinCode} onChange={e => setPinCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
          style={{ width: 180 }} />
        <button className="secondary" disabled={pinCode.length !== 4}
          onClick={() => { save({ pin_code: pinCode }, 'PIN updated'); setPinCode('') }}>
          Save PIN
        </button>
      </div>
    </div>
  )
}
