# EPR Analytical Engine v2 — Implementation Plan

**Status:** PROPOSAL — do not implement until the decision points in
[EPR_ENGINE_PROBLEMS.md](EPR_ENGINE_PROBLEMS.md) are answered.
**Scope:** `backend/epr.py` + new scoring module, `backend/db.py`, `backend/settings.py`,
EPR frontend pages, and every downstream consumer of `priority_score`.

> **Reality check first.** The change description that referenced `dashboard.php`,
> `company.php` and `inc/scoring_engine.php` does **not** match this repository —
> ATT_Platform is a Python/FastAPI + React app and contains no PHP and no existing
> Z-score engine for EPR. The current engine is one line:
> `priority = target_tons × 1.0 + credits × 0.5` (raw magnitudes, single
> target/credits pair per company, no materials dimension). This plan therefore
> covers the **full** build: per-material data model, Z-score normalization, and
> auto-normalizing weights — implemented in the actual codebase.

---

## 1. Target formula (formal spec)

For each **material** m (Lithium, Cobalt, Nickel, Manganese, … — extensible) let
C(m) be the set of companies that have data for m.

```
μT(m), σT(m)  = mean / std-dev of target_tons over C(m)
μC(m), σC(m)  = mean / std-dev of credits     over C(m)

zT(c,m) = (target(c,m) − μT(m)) / σT(m)        (σ = 0 ⇒ z = 0)
zC(c,m) = (credits(c,m) − μC(m)) / σC(m)

S(z)    = mapping of a Z-score onto the 1–100 scale      ← Decision D4

MaterialScore(c,m) = S(zT)·wT + S(zC)·wC
                     where wT + wC are the admin "target/credit" weights,
                     normalized so wT + wC = 1              ← Decision D5

M(c)    = set of materials company c has data for
Wn(m,c) = W(m) / Σ W(m′) over m′ ∈ M(c)        (auto-renormalized per company;
                                                default: uniform)

PriorityScore(c) = Σ over m ∈ M(c) of  MaterialScore(c,m) × Wn(m,c)
```

Properties: every MaterialScore is 1–100; the per-company weights sum to 1, so
PriorityScore is always on a 1–100 scale with **no global curving step**.
(Whether that makes it an "absolute grade" is challenged in the problems doc —
see P1.)

The bracket correction from the discussion is applied: the overall material
weight multiplies the **whole** material score, outside the target/credit
bracket:
`Σ [ (S(zT)·wT + S(zC)·wC) × Wn(m) ]` — not `S(zT)·wT·Wn + …` distributed inside.

---

## 2. Database changes (`backend/db.py`)

### New table `epr_materials`
| column | type | notes |
|---|---|---|
| id | Integer PK | |
| name | String unique | "Lithium", "Cobalt", "Nickel", "Manganese" seeded |
| slug | String unique | `lithium`, `cobalt`, … used in API params |
| overall_weight | Float default 1.0 | admin-set; renormalized at scoring time |
| active | Integer default 1 | soft-disable a material without deleting data |
| display_order | Integer default 0 | |

### New table `epr_company_materials`
| column | type | notes |
|---|---|---|
| id | Integer PK | |
| company_id | Integer FK→epr_companies, indexed | |
| material_id | Integer FK→epr_materials, indexed | |
| target_tons | Float, **nullable** | NULL = "no data", 0.0 = "reported zero" (see D6) |
| credits | Float, nullable | |
| import_qty | Float, nullable | |
| source_file / uploaded_by / created_at / updated_at | | provenance per material upload |
| | | `UniqueConstraint(company_id, material_id)` |

### `epr_companies`
Keeps identity fields only (name, registration, address, email, state,
battery_chemistry, other_json, provenance). The legacy `target_tons`,
`credits`, `import_qty` columns **stay in place** (SQLite/Postgres additive
migration style already used in `_migrate()`), but the engine stops reading
them once migration runs.

### Migration (added to `_migrate()` pattern)
1. `CREATE TABLE` both new tables via `Base.metadata.create_all`.
2. Seed the 4 default materials if `epr_materials` is empty.
3. One-time copy: for every existing company with `target_tons or credits`,
   insert an `epr_company_materials` row attached to the **legacy material**
   chosen in Decision D2 (options: map to Lithium / a "Li-ion (legacy)" bucket /
   drop and re-upload).
4. Works on both SQLite (`data/att.db`) and Postgres (`DATABASE_URL`), same as
   the existing `_migrate_llm_cache()` dual-dialect approach.

---

## 3. New scoring module `backend/epr_scoring.py`

All math extracted here (mirrors the role `inc/scoring_engine.php` played in the
described PHP design). Public API:

```python
def compute_scores(session) -> dict:
    """Returns {
      company_id: {
        'priority_score': float,             # 1–100
        'materials': {
          'lithium': {'target': .., 'credits': .., 'z_target': ..,
                      'z_credit': .., 'scaled_target': .., 'scaled_credit': ..,
                      'material_score': .., 'weight_used': ..,  # renormalized
                      'points': ..},          # material_score × weight_used
          ...
        },
      }, ...
    }"""
```

Implementation notes:
- One pass: load all `epr_company_materials` joined to active materials,
  group by material → compute μ/σ (population σ; see D7) → per-company scores.
  CPCB files are a few thousand rows at most; this is O(n·m) and cheap enough
  to compute per request. An in-process cache keyed on
  `max(updated_at) + settings-version` can be added later if needed (P9).
- Guards: σ=0 ⇒ z=0 for everyone (all-equal case); a material with only one
  company ⇒ z=0; company row where both target and credits are NULL is treated
  as "no data" and excluded from M(c) and from μ/σ.
- Z→scale mapping `S(z)` implemented behind a single function so the choice in
  D4 (linear clamp vs normal CDF vs logistic) is a one-line swap.
- Weight renormalization: `active` materials with data for the company only;
  if all admin weights are 0, fall back to uniform.

`epr.py` keeps `_priority()` as a thin wrapper calling the engine (digest.py
imports it today).

---

## 4. Upload flow (`backend/epr.py` + `EprPage.tsx`)

- `/api/epr/upload` gains a required `material` form field (slug). The parser
  (`parse_epr_xlsx`) is unchanged — one file = one material's targets/credits.
- **merge** mode: upsert companies by name (as today), then upsert that
  company's `epr_company_materials` row **for that material only**.
- **replace** mode semantics change: replaces **that material's** rows only
  (delete from `epr_company_materials WHERE material_id = X`, then insert;
  companies left with no material rows at all are pruned or kept per D3).
  A separate explicit "wipe everything" action can remain for full resets.
- Upload UI: material dropdown next to the file picker (populated from
  `GET /api/epr/materials`); the toast reports material + created/updated.

---

## 5. Settings (`backend/settings.py` + `SettingsPage.tsx`)

- `epr_weights` keeps `{target_tons, credits}` — now interpreted as the
  **within-material** pair, normalized to sum 1 at scoring time (D5).
- New setting is **not** added for material weights — they live on the
  `epr_materials` rows (single source of truth, admin-editable), managed via new
  endpoints:
  - `GET /api/epr/materials` — list with weights,
  - `PUT /api/epr/materials/{id}` — update weight / active,
  - `POST /api/epr/materials` — add a new material (extensibility requirement).
- `EprWeightsPanel` in Settings grows: target/credit pair (existing) + a
  material table with weight inputs, live "normalized share" preview
  (weights displayed as % of sum), and an "equalize" button (default uniform).
- Every change flows through the existing `SettingsLog` audit for the pair
  weights; material-weight edits get logged to `SettingsLog` too (key
  `epr_material_weights`) so the audit trail stays complete.

---

## 6. API contract changes (`backend/epr.py`)

- `GET /api/epr/companies`:
  - each item keeps every existing field (raw `target_tons`/`credits` become
    **totals across materials** so the UI stays backward compatible);
  - adds `materials: {slug: {target, credits, material_score, points}}` and
    `score_breakdown` metadata;
  - new query params: `material=<slug>` (filter to companies with data for it +
    sort by that material), `sort=material_score` valid only with `material`.
- `GET /api/epr/summary`: totals stay; adds per-material totals + company counts.
- `GET /api/epr/companies/{id}`: adds full per-material breakdown (z-scores,
  scaled values, weight used, points) to power the company-page table.
- `GET /api/epr/cross-links`: unchanged shape; `priority_score` now 1–100.
- New: `GET /api/epr/materials`, `PUT/POST` as in §5.

---

## 7. Frontend changes

### `EprPage.tsx`
- Raw Target/Credits/Gap columns stay (now totals). Priority column becomes the
  1–100 grade, tooltip: "Z-score-normalized absolute grade, weighted by
  admin material weights".
- New "Rank by" selector: **Overall | Lithium | Cobalt | Nickel | Manganese**
  (drives the `material` query param) — this is the feature that lets a
  0-lithium/200t-cobalt company rank first when cobalt is the focus.
- Upload row gains the material dropdown (§4).
- Subtitle formula text updated.

### `EprCompanyPage.tsx`
- New "Material breakdown" table: per material — raw target, raw credits,
  scaled target, scaled credits, material score, normalized weight, and
  **points contributed** to the final grade (matching the "Global Points"
  concept from the design discussion).

### `SettingsPage.tsx`
- `EprWeightsPanel` extended per §5.

### `api.ts`
- Extend `EprCompany` interface with `materials` + breakdown types; add
  `eprMaterials` / `eprMaterialUpdate` client calls.

---

## 8. Downstream consumers (must not silently break)

| Consumer | Today | Change |
|---|---|---|
| `backend/digest.py` | imports `_epr_weights`, `_priority` for weekly PDF | switch to `epr_scoring.compute_scores`; PDF table adds grade /100 label |
| `backend/outreach.py` | pitch context uses `c.target_tons`, `c.credits` | use per-material rows; context string lists each material's target/credit |
| `backend/research.py` | AI prompt uses single `target_tons` | pass total target + per-material detail in the prompt |
| Leads snapshots (`AddLeadButton` in `EprPage`) | stores target/credits/priority in `data_json` | store totals + grade; old snapshots untouched (timestamped by design) |
| `HomePage` cross-links | shows `priority_score` raw number | no code change needed; number is now 1–100 |
| External read-only API `/api/v1/*` | may expose EPR data | audit during implementation; version note in response if shape changes |

---

## 9. Implementation order

1. **DB layer**: models + migration + seeds (§2). Verify on both SQLite and Postgres.
2. **Scoring engine** `epr_scoring.py` with unit tests: σ=0, n=1, single-material
   company, missing-vs-zero, outlier company, weights-all-zero, renormalization
   correctness (Σ weights = 1 for every M(c) combination).
3. **Upload path** (§4) + materials endpoints (§5/6).
4. **List/summary/detail endpoints** (§6) on the new engine.
5. **Downstream consumers** (§8).
6. **Frontend** (§7).
7. **Verification**: upload two real CPCB files as two materials, confirm the
   cobalt-focus scenario (0-lithium company ranking first under cobalt weight),
   confirm grade stability when a new small company is added (see P1 — it will
   *not* be perfectly stable; measure how much it moves).

**Effort estimate:** backend ~1.5 days, frontend ~1 day, migration/testing ~0.5 day.

---

## 10. Open decisions (blocking)

Answered in [EPR_ENGINE_PROBLEMS.md](EPR_ENGINE_PROBLEMS.md) (Q-numbers there):

- **D1** — Is "absolute grade" the right promise, given Z-scores are relative by construction? (Q1)
- **D2** — Where does existing single-pair legacy data go? (Q6)
- **D3** — Replace-mode scope: per material or whole table? Prune companies with no rows left? (Q6)
- **D4** — Scale mapping: raw Z is unusable on the real 89 %-zero distribution — log/robust/percentile/anchor-band choice. (Q2 + Q10)
- **D5** — Normalize target/credit weights to sum 1 inside each material? (required for a true /100 grade) (Q10)
- **D6** — Zero vs missing: is a blank/0 cell "no data" or "reported zero"? (Q3)
- **D7** — Standard-deviation guards: σ = 0, n = 1, minimum-n threshold for tiny materials. (Q5)
- **D8** — Coverage policy: single-material companies vs 4-material companies — renormalize, penalize, or dampen? (Q4)
- **New from audit** — merge key (Q7), materialized-vs-live compute (Q8), API/contract migration (Q9).
