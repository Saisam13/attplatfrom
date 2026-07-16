# EPR Analytical Engine v2 — Problems & Decisions

**Status:** AWAITING ANSWERS — fill in every `➡ YOUR ANSWER:` slot, then the
implementation changes file (`EPR_ENGINE_CHANGES.md`) will be generated from
your answers.
**Companion:** [EPR_ENGINE_PLAN.md](EPR_ENGINE_PLAN.md) (the build plan these
decisions gate).

**Evidence base:** a devil's-advocate audit ran against the actual codebase and
the **live production table** (`data/att.db` → `epr_companies`): 6,982 companies
from one real CPCB lithium file. Every number below is computed from that real
data. Key facts about the real distribution:

- **89.2 % of targets are exactly 0; 98.4 % of credits are 0**
- mean target = 13.2 t, σ = 990 t, median = 0
- top company (TMB, 82,481 t) is **13×** the runner-up (Eastman, 6,299 t) and
  single-handedly dominates the standard deviation

## Executive summary — two load-bearing claims fail on real data

1. **"Absolute grade that stays stable" is mathematically false for Z-scores.**
   Z-scores are relative by construction. On the real data, uploading the file
   containing TMB moved an unrelated company from grade **100 → 61.6**.
2. **On a distribution that is 89 % zeros with a 13× outlier, raw Z-scores give
   99.6 % of companies the same grade (~50)** — including companies with zero
   obligations, which read as "medium priority."

Both are fixable — but only through the decisions below.

---

## Issue 1 — The "absolute grade out of 100" is mathematically relative: one upload rescores the entire book
**Category:** Analytical/Mathematical · **Severity: CRITICAL**

Every score depends on the global mean and σ, so adding, deleting, or correcting
**any** company moves **every** company's grade. Computed on the real data
(linear clamp mapping):

| Company | Grade before TMB's file is uploaded | After | Δ |
|---|---|---|---|
| Luxury Personified (677 t) | 100.0 | 61.6 | −38.4 |
| Luminous (646 t) | 100.0 | 61.1 | −38.9 |
| Xiaomi (117 t) | 75.6 | 52.2 | −23.4 |

A salesperson who quoted "Luminous is a 100/100 priority" on Monday finds it at
61 on Tuesday because an *unrelated* company appeared in a new upload. Deleting
a company triggers the same reshuffle in reverse. Lead snapshots freeze grades
that stop being reproducible the moment the cohort changes.

### Decision Q1 — what kind of score do you actually want?
- **(a) Relative, disclosed honestly:** percentile ranks ("top 3 % for
  lithium"), recomputed openly, cohort date shown in the UI.
- **(b) Genuinely absolute:** score against **fixed anchors** — e.g.
  grade = f(log₁₀ tons) with admin-set band edges (1 t / 10 t / 100 t /
  1,000 t / 10,000 t). Stable forever, no cohort dependence, interpretable.
- **(c) Keep Z-score design** and accept/communicate that grades shift with
  every upload (cohort date displayed).

**➡ YOUR ANSWER (Q1):**

---

## Issue 2 — Real CPCB data is a zero-mass + power-law tail; Z-scores collapse 99.6 % of companies onto one grade
**Category:** Analytical/Mathematical · **Severity: CRITICAL**

Z-scores presume rough symmetry. The actual data: 89 % zeros, heavy tail
(median 0, mean 13.2, σ 990). Result: z ranges −0.013 to +83.3; **6,954 of
6,982 companies land within 0.03 grade points of each other** (p50 = 50.28,
p90 = 50.28, p99 = 50.31; 6,226 exact ties). A company with **zero target reads
as "50/100"** — users will read "medium priority" for a company with *no
obligation at all*. The current raw score, whatever its faults, at least ranks
677 t above 117 t above 0 t proportionally.

### Decision Q2 — how should the distribution be handled before scoring?
- **(a) Recommended:** `log1p(tons)` transform + robust stats (median/MAD
  instead of mean/σ), computed **only over companies with a non-zero value**;
  zero-target companies go to an explicit bottom band (grade 0–5 or a
  "No target" label), never mid-scale.
- **(b)** Percentile-of-nonzero mapping (pairs with Q1(a)'s relative framing).
- **(c)** Keep raw Z on raw tonnage (not recommended — the collapse above).

**➡ YOUR ANSWER (Q2):**

---

## Issue 3 — Zero vs. missing is conflated at three layers; the redesign's own acceptance scenario is undecidable
**Category:** Logical (rooted in parsing) · **Severity: CRITICAL**

`_num()` in `backend/epr.py` coerces everything unparseable to `0.0`:
`'N/A'→0.0`, `'TBD'→0.0`, `'Exempted'→0.0`, `'10-20 MT'→0.0`, and — silently
catastrophic — **`'Rs. 500' → 0.5`** (the regex keeps the dot from "Rs.",
producing ".500": a 1000× error that then contaminates the material's mean and
σ for everyone). The DB cannot distinguish "target is genuinely 0" from "cell
was blank/exempt/unparseable."

Your own success criterion — "a company with 0 lithium but 200 t cobalt credits
ranks first when cobalt is weighted highly" — is **undecidable as written**: if
"0 lithium" means a row with value 0, lithium stays in the weighted sum and the
company does *not* cleanly rank first; if it means "no lithium row," it does.
Two different engines satisfy two different readings.

### Decision Q3 — zero vs. missing semantics
- **(a) Recommended:** parse to `NULL` (absent) vs `0` (explicit) distinctly;
  only create a per-material row when a real numeric value was present; add a
  status enum (`target_set / zero / exempt / unparsed`); the upload result
  reports "14 cells could not be read" instead of silently zeroing; fix the
  `Rs.`/range regex with a strict number pattern and a reject-and-report path.
- **(b)** Keep "blank = 0" (status quo) and accept the contamination above.

Also answer: should a company with an explicit **0** in lithium have lithium
**included** in its weighted materials (dragging its grade down) or **excluded**
(treated like no data)?

**➡ YOUR ANSWER (Q3):**

---

## Issue 4 — Auto-renormalized weights reward missing data and invert the admin's intent
**Category:** Analytical + Logical · **Severity: CRITICAL**

Renormalizing over "materials the company has" makes grades **incomparable
across companies with different coverage**. Concrete (uniform weights 0.25):

- Multi-material major: Li = 100, Co = 55, Ni = 50, Mn = 50 → final **63.8**
- Lithium-only shell with identical lithium performance → final **100.0**

The company with *more* obligations across *more* materials ranks below a
single-material shell — absence of data is treated as favorable evidence.
Worse: if the admin sets Li = 0.1 / Co = 0.6 precisely to deprioritize lithium,
every lithium-only company renormalizes to Li = 1.0 — the exact opposite of the
configured intent. The "weights sum to 1.0" constraint becomes cosmetic,
because the engine re-derives different weights per company anyway.

### Decision Q4 — coverage / renormalization policy
- **(a)** No renormalization: a missing material contributes 0 (or neutral
  50 × weight with a visible "no data" flag). Comparable across companies;
  penalizes narrow producers — which may be *correct* for prioritization.
- **(b)** Renormalize **plus** a coverage factor (e.g. × (0.5 + 0.5·k/4) for
  k of 4 materials) or shrinkage toward 50 in proportion to missing coverage;
  always display "grade 74 (2 of 4 materials)."
- **(c)** Pure renormalization as originally specced, accepting the
  shell-company inversion above (badge the coverage in the UI at minimum).

**➡ YOUR ANSWER (Q4):**

---

## Issue 5 — σ = 0, n = 1, and all-zero columns: guaranteed division-by-zero on realistic uploads
**Category:** Analytical/Mathematical · **Severity: HIGH**

Three near-certain triggers:
1. **First upload of a new material** ("extensible" is a requirement): n = 1 →
   σ = 0 → z = 0/0.
2. **All-zero credit column:** credits are 98.4 % zero in the real lithium
   data; a modest cobalt file where *every* credit is 0 gives σ = 0 exactly —
   the credit z-score crashes (or NaN-poisons) that whole material.
3. **Small-n false authority:** a 3-company cobalt file yields
   z = [+1.22, 0, −1.22] → grades **70.7 / 50.5 / 30.3** — a confident-looking
   40-point spread that is pure noise, blended at full weight alongside lithium
   grades estimated from 6,982 points.

### Decision Q5 — small-sample guards
- Minimum-n threshold: below n = ___ (suggest **20**) a material's scores fall
  back to neutral 50 / within-material rank, with a UI badge "insufficient data
  for statistical scoring." Acceptable?
- All-zero (σ = 0) component rule: the component drops out and its weight folds
  into the other component — documented, not accidental. Acceptable?

**➡ YOUR ANSWER (Q5):**

---

## Issue 6 — No "material" exists anywhere in the pipeline: schema, parser, upload API, and replace semantics all break
**Category:** Operational · **Severity: HIGH**

- `EprCompany` has **one** target/credits pair; a child table is required, and
  `_migrate()` only supports additive columns — no data-reshape infrastructure,
  and it must work on SQLite **and** Postgres.
- The upload endpoint has **no material parameter**; the only hint is the
  filename (the real production file is literally
  `Status of EPR Targets for Producers in Lithium____….xlsx`). Filename
  sniffing will misfile data.
- `mode=replace` wipes the **whole table** — under per-material files,
  replacing cobalt would destroy all lithium data.
- The header map binds the **first** column containing "target": CPCB layouts
  with "Target 2024-25" / "Target 2025-26" silently bind to whichever comes
  first.
- All 6,982 existing rows have `battery_chemistry = ''` — backfill can only
  assume they are lithium from the filename.

### Decision Q6 — upload & migration mechanics
- **(a) Recommended:** required material dropdown at upload (reject without
  it); `epr_company_materials` child table; replace scoped to that material;
  legacy 6,982 rows backfilled as `Lithium` (tagged `migrated`); header mapping
  extended for year-qualified columns (pick latest year or ask at upload).
- **(b)** Variations — state yours.

Also answer: the 4th default material — **Manganese or Magnesium?** (The spec
said both at different points; they are different elements and CPCB battery
regulations cover specific chemistries.)
And: companies left with **no** material rows after a scoped replace — prune or
keep as bare identity records?

**➡ YOUR ANSWER (Q6):**

---

## Issue 7 — Merge-by-name across per-material files fragments companies and corrupts the statistics
**Category:** Operational + Logical · **Severity: HIGH**

The upsert key is lower-cased company name. Within the **single** real file
there are already **71 normalized-name collisions** — e.g. `WIPRO GE HEALTHCARE
PRIVATE LIMITED` / `WIPRO GE HEALTHCARE PVT LTD` / `Wipro GE Healthcare Pvt.
Ltd.` (3 rows), `Tata Passenger Electric Mobility` ± `Limited`, `SCHNEIDER
ELECTRIC PRIVATE LIMITED` vs `Schneider Electric India Private Limited`.
Per-material files produced at different times by CPCB *will* spell names
differently. Consequence chain: one real company becomes two DB rows, each
"single-material," each fully renormalized (Issue 4) so both look complete;
n/mean/σ inflated by phantom entities; sales researches and contacts the same
lead twice. (The codebase already owns fuzzy-matching machinery —
`_name_tokens` + stopwords — but only uses it for trade cross-links.)

### Decision Q7 — merge key
- **(a) Recommended:** `registration_number` as primary merge key when present
  (CPCB issues stable registration numbers), normalized name (strip
  Pvt/Ltd/LLP/punctuation, reuse `_name_tokens`) as fallback; post-upload
  "possible duplicates" review list instead of silent merge/split.
- **(b)** Keep name-only merging.

**➡ YOUR ANSWER (Q7):**

---

## Issue 8 — Stale scores vs. per-request recomputation: both paths have traps
**Category:** Operational · **Severity: HIGH**

Today `list_companies` loads all 6,982 rows into Python, sorts in Python, then
slices — on **every** request (and the frontend re-fetches on every search-box
keystroke). Per-material stats computed per request multiply that cost across
`/companies`, `/summary`, `/cross-links` (which already fires up to 60 fuzzy
`ILIKE` queries per call). Cached stats go stale on every upload, delete,
weight change, and new material — miss one invalidation hook and users see
grades no data supports. Dynamic Python-side grades also make DB-level sorting
and pagination impossible.

### Decision Q8 — compute strategy
- **(a) Recommended:** materialize `material_score` and `final_grade` into
  columns, recomputed by one job triggered on upload / delete / settings change
  (all mutations already pass through 3–4 endpoints), stamped with a
  `scores_version`; reads sort/paginate in SQL.
- **(b)** Per-request computation (simpler, no staleness risk, keeps the
  current load-everything pattern and its cost).

**➡ YOUR ANSWER (Q8):**

---

## Issue 9 — The single target/credits contract is woven through the whole product; "only the engine changes" is false
**Category:** Operational · **Severity: MEDIUM**

Flat `target_tons` / `credits` / `priority_score` / `gap_tons` appear in: the
TS interface, table columns and sort keys, summary tiles (`total_target_tons`
sums one column — per-material it either double-counts or silently changes
meaning), `gap_tons = max(0, target − credits)` (per-material gaps summed ≠ gap
of sums — cobalt credits cannot legally offset a lithium target), **lead
snapshots** (old leads carry `priority_score: 82481.1`, new ones would carry
`grade: 74` — two incomparable currencies in one field), and the **AI research
prompt** (`run_company_research(name, target)` — which target now?).

### Decision Q9 — contract migration
- **(a) Recommended:** additive versioning — keep aggregate fields with
  explicit definitions (`target_tons` = sum across materials; gap = **sum of
  per-material gaps**); add `materials: [...]` and a **new field name `grade`**
  (never reuse `priority_score` for the new metric, so historical lead
  snapshots are visibly a different unit); per-material table columns via a
  material filter dropdown; research prompt gets total + per-material detail.
- **(b)** Reuse `priority_score` everywhere and accept mixed units in
  historical data.

**➡ YOUR ANSWER (Q9):**

---

## Issue 10 — The Z→1–100 mapping and the weight scheme are unspecified, and every candidate distorts differently
**Category:** Analytical/Mathematical · **Severity: MEDIUM**

1. **Within-material weights don't sum to 1 today** (target 1.0 / credits 0.5),
   so the material score ranges up to **150**, breaking "grade out of 100."
   And settings validation checks sum-to-1 **only** for the chemical `weights`
   key — `epr_weights` accepts negatives unchecked; dict-merge on save means a
   removed material's weight key **lingers forever**.
2. **Mapping distortion:** linear clamp compresses 99.6 % of companies into
   0.03 points *and* saturates the tail — TMB (82,481 t, z = 83.3) and Eastman
   (6,299 t, z = 6.35) **both grade 100.0**, a 13× real-world difference made
   invisible. Logistic saturates identically (100.00 vs 99.83) while
   amplifying parse-noise among mid-pack companies (~25 grade points per σ).
   Empirical percentile spreads uniformly but is maximally cohort-relative.
3. **The credits knob is dead weight** on current data: with 98.4 % zero
   credits, `scaled_credit` is near-constant — the admin knob does nothing but
   add noise from a handful of companies.

### Decision Q10 — weights hygiene + final mapping
- Normalize within-material weights server-side to sum 1, validate ≥ 0, strip
  unknown material keys on save, one canonical material enum. Acceptable?
- Final mapping (interacts with Q1/Q2) — recommended: **log-transform then
  percentile with tie-aware midranks**, or **fixed log-tonnage anchor bands**
  (Q1(b)). State your pick.
- Keep the credits weight knob despite it being ~dead on current data, or hide
  it until credits data becomes meaningful?

**➡ YOUR ANSWER (Q10):**

---

## Decision map (plan ↔ problems)

| Plan decision | Answered by |
|---|---|
| D1 absolute vs relative | Q1 |
| D2 legacy data destination | Q6 |
| D3 replace-mode scope | Q6 |
| D4 Z→scale mapping | Q2 + Q10 |
| D5 within-material weight normalization | Q10 |
| D6 zero vs missing | Q3 |
| D7 σ/std-dev + small-n guard | Q5 |
| D8 coverage / renormalization policy | Q4 |
| — merge key (new) | Q7 |
| — compute strategy (new) | Q8 |
| — contract migration (new) | Q9 |

## Auditor's verdict (verbatim)

> The two most load-bearing claims of the redesign are both false on the actual
> production data: (1) Z-scores are not and cannot be "absolute grades" — a
> single upload moved a real company from 100 to 61.6; and (2) on a
> distribution that is 89 % zeros with a 13×-runner-up outlier, Z-scores assign
> 99.6 % of companies the *same* grade (~50) — including companies with zero
> obligations. Before any implementation: decide zero-vs-missing semantics
> (Issue 3), decide the renormalization/coverage policy (Issue 4), and replace
> raw Z on raw tonnage with log/robust/anchored scaling (Issues 1–2). The
> per-material data model itself is sound, but it requires an explicit material
> parameter, material-scoped replace, a registration-number merge key, and a
> materialized recompute path — none of which exist in the current code.
