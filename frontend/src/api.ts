export interface Run {
  id: number
  name: string
  kind: 'chemical' | 'battery'
  status: string
  progress: number
  stage: string
  error: string
  created_at: string | null
  config: Record<string, any>
  stats: Record<string, any>
}

export interface DimScores {
  volume: number; price: number; buyers: number; suppliers: number
  trend: number; structure: number; freedom: number; barrier: number
}

export interface Chemical {
  chemical: string
  pool: 'base' | 'opportunity'
  hsn_codes: string
  shipments: number
  total_qty_kg: number
  total_value_usd: number
  scores: DimScores
  variance_type: string
  variance_mod: number
  reg_factor: number
  reg_status: string
  att_base: number
  att_final: number
  att_india: number
  rodtep_bonus: number
  drawback_bonus: number
  feedback_adj: number
  tier: 'A' | 'B' | 'C'
  trend_direction: string
  growth_rate: number
  reasoning: string
  detail?: any
  raw?: any
  monthly?: { month: string; shipments: number; qty_kg: number; value_usd: number; excluded: boolean }[]
  geo_anomalies?: { month: string; direction: string; z_score: number; deviation_pct: number; adj_factor: number; event: string }[]
  regulatory?: { status: string; factor: number; note: string }
}

export interface FeedbackItem {
  id: number; run_id: number; chemical: string; user_name: string
  verdict: string; suggested_tier: string; expected_duration: string
  comment: string; created_at: string
}

export interface DuplicateWarning {
  message: string
  runs: { run_id: number; run_name: string; created_at: string; overlap_count: number }[]
}

export interface BatteryEntity {
  name: string; country: string; categories: string
  shipments: number; qty_kg: number; value_usd: number
  median_price: number; price_index: number | null
  months_active: number; first_month: string; last_month: string
  consistency: number; geo_ease: number; proc_score: number; tier: 'A' | 'B' | 'C'
  detail: {
    category_breakdown?: { category: string; shipments: number; median_price: number; market_median: number }[]
    top_counterparties?: [string, number][]
    counterparty_countries?: [string, number][]
    monthly_shipments?: Record<string, number>
  }
}

export interface BatteryCategory {
  category: string; shipments: number; qty_kg: number; value_usd: number
  median_price: number; n_suppliers: number; n_buyers: number
  top_countries: [string, number][]
  monthly: { month: string; shipments: number; qty_kg: number; value_usd: number }[]
}

export interface RawRow {
  date: string; hsn6: string; desc_clean: string; chemical: string
  match_type: string; match_score: number
  seller: string; seller_country: string; buyer: string; buyer_country: string
  qty: number; qty_kg: number; value_usd: number; unit_price: number; file: string
}

export interface Mover {
  chemical: string; pool: string; att_a: number; att_b: number; delta: number
  tier_a: string; tier_b: string; rank_a: number; rank_b: number; rank_delta: number
}

// ── per-user login (session cookie, set by the server on login/setup) ──
export interface AuthUser {
  id: number; username: string; display_name: string
  created_at: string; last_login_at: string
}

// App.tsx calls this whenever the logged-in user changes, so calls below that
// stamp who made a change (leads, outreach, settings) have a name to send
// without every page having to thread it through explicitly.
let _currentUserName = ''
export const setCurrentUserName = (n: string) => { _currentUserName = n }

async function f(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, init)
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('att-auth-required'))
    throw new Error('login required')
  }
  return res
}

export const auth = {
  needsSetup: () => fetch('/api/auth/needs-setup').then(r => j<{ needs_setup: boolean }>(r)),
  setup: (username: string, password: string, display_name: string) =>
    fetch('/api/auth/setup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, display_name }),
    }).then(r => j<{ ok: boolean; user: AuthUser }>(r)),
  login: (username: string, password: string) =>
    fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }).then(r => j<{ ok: boolean; user: AuthUser }>(r)),
  logout: () => fetch('/api/auth/logout', { method: 'POST' }).then(r => j<{ ok: boolean }>(r)),
  me: () => fetch('/api/auth/me').then(r => j<AuthUser>(r)),
  listUsers: () => f('/api/auth/users').then(r => j<AuthUser[]>(r)),
  createUser: (username: string, password: string, display_name: string) =>
    f('/api/auth/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, display_name }),
    }).then(r => j<AuthUser>(r)),
  deleteUser: (id: number) => f(`/api/auth/users/${id}`, { method: 'DELETE' }).then(r => j<{ ok: boolean }>(r)),
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

/** Fetch as a blob so the session cookie rides along, then trigger a save. */
export async function download(url: string, filename: string) {
  const res = await f(url)
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

export const api = {
  listRuns: (kind = '') => f(`/api/runs${kind ? `?kind=${kind}` : ''}`).then(r => j<Run[]>(r)),
  getRun: (id: number) => f(`/api/runs/${id}`).then(r => j<Run>(r)),
  createRun: (form: FormData) =>
    f('/api/runs', { method: 'POST', body: form }).then(r => j<{ run_id: number; duplicate_warning: DuplicateWarning | null }>(r)),
  createBatteryRun: (form: FormData) =>
    f('/api/battery-runs', { method: 'POST', body: form }).then(r => j<{ run_id: number; duplicate_warning: DuplicateWarning | null }>(r)),
  renameRun: (id: number, name: string) =>
    f(`/api/runs/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }).then(r => j<Run>(r)),
  deleteRun: (id: number) =>
    f(`/api/runs/${id}`, { method: 'DELETE' }).then(r => j<{ ok: boolean }>(r)),
  chemicals: (runId: number, params: Record<string, string>) =>
    f(`/api/runs/${runId}/chemicals?` + new URLSearchParams(params)).then(r =>
      j<{ total: number; items: Chemical[] }>(r)),
  chemicalDetail: (runId: number, chemical: string) =>
    f(`/api/runs/${runId}/chemicals/${encodeURIComponent(chemical)}`).then(r => j<Chemical>(r)),
  chemicalHistory: (name: string) =>
    f(`/api/chemicals/history?name=${encodeURIComponent(name)}`).then(r =>
      j<{ run_id: number; run_name: string; created_at: string; att_final: number; att_india: number; tier: string; feedback_adj: number }[]>(r)),
  raw: (runId: number, params: Record<string, string>) =>
    f(`/api/runs/${runId}/raw?` + new URLSearchParams(params)).then(r =>
      j<{ total: number; items: RawRow[] }>(r)),
  geo: (runId: number, chemical = '') =>
    f(`/api/runs/${runId}/geo${chemical ? `?chemical=${encodeURIComponent(chemical)}` : ''}`).then(r => j<any[]>(r)),
  summary: (runId: number) => f(`/api/runs/${runId}/summary`).then(r => j<any>(r)),
  compare: (a: number, b: number) =>
    f(`/api/compare?a=${a}&b=${b}`).then(r =>
      j<{ run_a: Run; run_b: Run; movers: Mover[]; new: any[]; dropped: any[] }>(r)),
  batteryEntities: (runId: number, params: Record<string, string>) =>
    f(`/api/runs/${runId}/battery/entities?` + new URLSearchParams(params)).then(r =>
      j<{ total: number; items: BatteryEntity[] }>(r)),
  batteryCategories: (runId: number) =>
    f(`/api/runs/${runId}/battery/categories`).then(r => j<BatteryCategory[]>(r)),
  feedback: (runId: number) => f(`/api/runs/${runId}/feedback`).then(r => j<FeedbackItem[]>(r)),
  addFeedback: (body: object) =>
    f('/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => j<{ id: number }>(r)),
  config: () => f('/api/config').then(r => j<any>(r)),
  settings: () => f('/api/settings').then(r => j<any>(r)),
  saveSettings: (changes: object) =>
    f('/api/settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ changes, user_name: _currentUserName }),
    }).then(r => j<any>(r)),
  settingsLog: () => f('/api/settings/log').then(r => j<any[]>(r)),
  testLlm: (body: object) =>
    f('/api/settings/test-llm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => j<{ ok: boolean; model?: string; error?: string }>(r)),
  previewWeights: (runId: number, body: object) =>
    f(`/api/runs/${runId}/preview-weights`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => j<any>(r)),
  // ── EPR Producer Intel ─────────────────────────────────────
  eprUpload: (form: FormData) =>
    f('/api/epr/upload', { method: 'POST', body: form }).then(r => j<any>(r)),
  eprCompanies: (params: Record<string, string>) =>
    f('/api/epr/companies?' + new URLSearchParams(params)).then(r =>
      j<{ total: number; weights: any; items: EprCompany[] }>(r)),
  eprCompany: (id: number) => f(`/api/epr/companies/${id}`).then(r => j<EprCompany>(r)),
  eprDelete: (id: number) => f(`/api/epr/companies/${id}`, { method: 'DELETE' }).then(r => j<any>(r)),
  eprResearch: (id: number, refresh = false) =>
    f(`/api/epr/companies/${id}/research${refresh ? '?refresh=true' : ''}`, { method: 'POST' })
      .then(r => j<{ research: any; cached: boolean; meta: any }>(r)),
  eprTrade: (id: number) => f(`/api/epr/companies/${id}/trade`).then(r => j<any>(r)),
  eprSummary: () => f('/api/epr/summary').then(r => j<any>(r)),
  eprCrossLinks: () => f('/api/epr/cross-links').then(r => j<any[]>(r)),
  eprMaterials: () => f('/api/epr/materials').then(r => j<EprMaterial[]>(r)),
  eprUpdateMaterial: (id: number, body: object) =>
    f(`/api/epr/materials/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => j<any>(r)),
  eprCreateMaterial: (body: object) =>
    f('/api/epr/materials', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => j<any>(r)),

  // ── HSN Explorer ───────────────────────────────────────────
  hsnSearch: (q: string) => f(`/api/hsn/search?q=${encodeURIComponent(q)}`).then(r => j<HsnEntry[]>(r)),
  hsnTree: (code = '') => f(`/api/hsn/tree?code=${code}`).then(r =>
    j<{ node: HsnEntry | null; children: HsnEntry[] }>(r)),
  hsnData: (code: string) => f(`/api/hsn/code/${code}/data`).then(r => j<any>(r)),
  hsnLeads: (code: string, role = 'buyer') =>
    f(`/api/hsn/code/${code}/leads?role=${role}`).then(r => j<any>(r)),
  hsnMap: (params: Record<string, string> = {}) =>
    f('/api/hsn/map?' + new URLSearchParams(params)).then(r => j<any[]>(r)),
  hsnAddMap: (body: object) =>
    f('/api/hsn/map', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) }).then(r => j<any>(r)),
  hsnDeleteMap: (id: number) => f(`/api/hsn/map/${id}`, { method: 'DELETE' }).then(r => j<any>(r)),
  hsnSeedMap: () => f('/api/hsn/map/seed', { method: 'POST' }).then(r => j<any>(r)),
  hsnSuggest: (q: string) => f(`/api/hsn/suggest?q=${encodeURIComponent(q)}`).then(r => j<any>(r)),

  // ── Leads ──────────────────────────────────────────────────
  leads: (params: Record<string, string>) =>
    f('/api/leads?' + new URLSearchParams(params)).then(r =>
      j<{ total: number; items: Lead[] }>(r)),
  lead: (id: number) => f(`/api/leads/${id}`).then(r => j<Lead>(r)),
  leadsSummary: () => f('/api/leads/summary').then(r => j<any>(r)),
  createLead: (body: object) =>
    f('/api/leads', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, user_name: _currentUserName }) })
      .then(r => j<{ id: number; existing: boolean }>(r)),
  updateLead: (id: number, body: object) =>
    f(`/api/leads/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, user_name: _currentUserName }) }).then(r => j<Lead>(r)),
  deleteLead: (id: number) => f(`/api/leads/${id}`, { method: 'DELETE' }).then(r => j<any>(r)),
  transferLeadToCrm: (id: number) =>
    f(`/api/leads/${id}/transfer-to-crm`, { method: 'POST' }).then(r => j<{ ok: boolean; twenty_id: string }>(r)),
  addLeadEvent: (id: number, body: object) =>
    f(`/api/leads/${id}/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, user_name: _currentUserName }) }).then(r => j<any>(r)),

  // ── Outreach ───────────────────────────────────────────────
  templates: (params: Record<string, string> = {}) =>
    f('/api/outreach/templates?' + new URLSearchParams(params)).then(r => j<any[]>(r)),
  saveTemplate: (body: object, id = 0) =>
    f(id ? `/api/outreach/templates/${id}` : '/api/outreach/templates', {
      method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, user_name: _currentUserName }) }).then(r => j<any>(r)),
  deleteTemplate: (id: number) =>
    f(`/api/outreach/templates/${id}`, { method: 'DELETE' }).then(r => j<any>(r)),
  draft: (body: object) =>
    f('/api/outreach/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, user_name: _currentUserName }) })
      .then(r => j<{ draft: string; channel: string; provider: string; wa_link?: string }>(r)),
  logOutreach: (body: object) =>
    f('/api/outreach/log', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, user_name: _currentUserName }) }).then(r => j<any>(r)),

  // ── Digest / cache / keys / AI test ────────────────────────
  digest: () => f('/api/digest').then(r => j<any>(r)),
  cacheStats: () => f('/api/cache/stats').then(r => j<any[]>(r)),
  cacheClear: (namespace = '') =>
    f(`/api/cache/clear?namespace=${namespace}`, { method: 'POST' }).then(r => j<any>(r)),
  apiKeys: () => f('/api/keys').then(r => j<any[]>(r)),
  createApiKey: (label: string) =>
    f('/api/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, user_name: _currentUserName }) }).then(r => j<{ key: string }>(r)),
  revokeApiKey: (id: number) => f(`/api/keys/${id}`, { method: 'DELETE' }).then(r => j<any>(r)),
  testAi: (kind: 'llm' | 'search') =>
    f('/api/settings/test-ai', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind }) }).then(r => j<any>(r)),
}

export interface EprCompany {
  id: number; company_name: string; registration_number: string
  address: string; email: string; state: string; battery_chemistry: string
  target_tons: number; credits: number; import_qty: number
  priority_score: number; gap_tons: number
  grade: number; grade_label: string;
  materials?: Record<string, any>;
  source_file: string; uploaded_by: string; created_at: string
  has_research: boolean
  research?: any
  research_meta?: { search_provider: string; llm_provider: string; updated_at: string }
}

export interface EprMaterial {
  id: number; name: string; slug: string;
  overall_weight: number; target_weight: number; credit_weight: number;
  normalized_share: number;
  active: boolean; display_order: number; company_count: number;
}

export interface HsnEntry {
  hscode: string; description: string; level: number; section: string; parent: string
  in_our_data: boolean; our_shipments: number
  mapped: { id: number; label: string; map_type: string; is_our_product: boolean; notes: string }[]
}

export interface Lead {
  id: number; name: string; lead_type: string; stage: string; owner: string
  tags: string; source: string; entity_kind: string; entity_ref: string
  hsn_code: string; country: string
  contact_name: string; contact_email: string; contact_phone: string
  next_followup: string; data: any; created_by: string
  created_at: string; updated_at: string
  events?: { id: number; kind: string; text: string; data: any; user_name: string; created_at: string }[]
}

export const fmt = {
  usd: (v: number) => '$' + Math.round(v).toLocaleString(),
  num: (v: number) => Math.round(v).toLocaleString(),
  score: (v: number) => (v ?? 0).toFixed(1),
}
