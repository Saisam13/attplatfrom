# Platform-Wide Devil's Advocate Audit — Problems & Decisions (Round 2)

**Scope:** everything EXCEPT the EPR scoring redesign (covered in
[EPR_ENGINE_PROBLEMS.md](EPR_ENGINE_PROBLEMS.md)): chemical/trading ATT
pipeline, battery procurement, trade ingestion & matching, leads/outreach/
digest, and platform operations.
**Status:** AWAITING ANSWERS — fill in every `➡ YOUR ANSWER:` slot (R1–R10).
Together with your Q1–Q10 answers from the EPR doc, these drive the final
`EPR_ENGINE_CHANGES.md` / remediation changes file.

**Evidence base:** the auditor read `backend/pipeline/engine.py`,
`constants.py`, `battery.py`, `runner.py`, `main.py`, `settings.py`,
`leads.py`, `outreach.py`, `digest.py`, `db.py` and the frontend pages, and
computed every claim below against the **live database** (`data/att.db`):
6 runs, **1,675 chemical scores**, **107,251 raw shipment rows**, **16,609
battery entities**, 10 feedback rows, 3 leads, 1 API key.

---

## Issue R1 — Percentile normalization has no tie handling: identical chemicals get arbitrarily different scores (a 10-point ATT lottery)
**Category:** Analytical/Mathematical · **Severity: CRITICAL**

`stage4_analyse` (engine.py ~line 549) normalizes each dimension as
`rank / (n−1) × 100` using `sorted()` — **tied raw values receive consecutive
distinct ranks in arbitrary iteration order**. Measured in the real run 2:

- Base pool: **all 75 chemicals have the identical raw barrier value (100)**,
  yet their `barrier_norm` spans **0.0 → 100.0**. With barrier weighted 0.10,
  that is **10 full ATT points of pure dict-ordering noise** between chemicals
  whose barrier data is byte-identical.
- 732 opportunity chemicals share the identical raw trend fallback (50) yet get
  `trend_norm` from **22.9 to 70.2** (≈4.7 ATT points of lottery).
- The same bug is copy-pasted into the battery module (`_percentile_norm`,
  battery.py ~line 78), randomizing proc_scores across 16,609 entities.

Tier B spans 30 points; the tie lottery alone can move a chemical a third of a
tier. Re-running identical data in a different insertion order reshuffles tiers.

**Fix (no design trade-off — current behavior is simply wrong):** midrank ties
(fractional ranking) in both `stage4_analyse` and `_percentile_norm`.

**➡ YOUR ANSWER (R1)** — approve the midrank fix? Should we re-score existing
runs or only future ones?

---

## Issue R2 — ATT is cohort-relative: cross-run "movers", history charts, and the digest measure dataset composition, not the market
**Category:** Analytical + Logical · **Severity: CRITICAL**

Every dimension is a percentile rank *within one run's chemical set*, so ATT
changes whenever the cohort changes — yet three shipped features present
cross-run deltas as market movement (`_movers`, `/api/chemicals/history`, the
weekly digest). Real numbers:

- Runs 2 vs 4 share 12 chemicals: **6 of 12 flip tier**. Lanthanum Nitrate goes
  **66.2 → 26.6 (B→C)** — not because its trade changed, but because run 4 has
  32 chemicals and run 2 has 1,619.
- Run 3 — one of the "two latest completed chemical runs" the digest's movers
  compares — contains **exactly one chemical, named "Unknown", att 5.0**.
- Tier counts are quasi-forced by construction (run 1: 17 % A; run 2: 7 % A;
  run 4: 3 % A): a run of uniformly excellent chemicals still condemns ~30 %
  to Tier C.
- Base and opportunity pools are normalized **separately** but stored under one
  run_id and interleaved by the UI's default sort — and the opportunity pool's
  average att (49.3) beats the base portfolio's (42.3), so incomparable numbers
  are ranked against each other daily.

### Decision R2 (same fundamental choice as EPR Q1)
- **(a)** Keep percentiles but hard-gate every cross-run comparison to
  same-file-set runs, show cohort size on all deltas, and never auto-compare
  runs whose chemical counts differ by more than ~20 %.
- **(b)** Rebuild dimensions on absolute anchored scales (log-volume bands,
  absolute buyer counts) so scores are comparable across runs by construction —
  the honest fix if "movers" is a feature the sales team acts on.

**➡ YOUR ANSWER (R2):**

---

## Issue R3 — Battery "consistency": one month of activity scores a perfect 1.0 — 71 % of all suppliers
**Category:** Analytical/Mathematical · **Severity: CRITICAL**

`consistency = months_active / span` (battery.py ~line 178). A supplier seen in
exactly one month has span = 1 → **consistency = 1.0, the maximum** — better
than a reliable supplier active 10 of 14 months (0.714). Real run 6:
**7,353 of 10,333 suppliers (71 %) have months_active = 1 and consistency
= 1.0**; 5,473 suppliers have exactly **one shipment ever**, of which **609
were rated Tier A**. Top example: "BILAL INTERNATIONAL" (27 shipments, all in
one month) → proc_score **94.99, Tier A**. The metric meant to measure
reliability actively rewards its absence.

### Decision R3
- **(a)** Minimum-span floor: `consistency = months_active / max(span, 6)` so
  single-month entities score ≤ 0.17 until they build history.
- **(b)** Bayesian shrinkage toward the population mean, weighted by span.
- Either way: badge "1 month of history" prominently in the UI.

**➡ YOUR ANSWER (R3):**

---

## Issue R4 — Battery categorizer dumps 99.4 % of shipments into one bucket, making price_index (25 % of proc_score) meaningless
**Category:** Analytical + Logical · **Severity: HIGH**

Real run 6: **49,708 of 49,997 shipments (99.4 %) fell into "Battery Scrap
(Mixed/Other)"** — the keyword rules almost never fire, so the category median
($13.56/kg) blends materials whose true medians differ by two orders of
magnitude (Li-ion $69.23/kg vs E-Waste $0.85/kg). A fairly-priced e-waste
seller looks 94 % "cheaper than market"; a fairly-priced li-ion seller looks 5×
overpriced. Observed **price_index max = 2,949,852** (a per-ton vs per-kg unit
artifact ranked as real), and **2,405 suppliers with no price data default to
index 1.0** — silently asserted to be exactly market-priced.

**Proposed fixes:** price_index only within categories where the entity has ≥ k
priced shipments *and* the category price distribution is coherent (CV
threshold); no-price = "unknown" (drop the dimension, renormalize that
entity's weights, UI flag) rather than 1.0; HSN-based sub-categorization for
the 8507/854810 mass; cap/flag index values outside [0.1, 10] as unit errors.

**➡ YOUR ANSWER (R4):**

---

## Issue R5 — The trend-exclusion setting is a scoring no-op: the UI promises months are excluded from the regression, the engine ignores it
**Category:** Logical (product integrity) · **Severity: HIGH**

The run form, Settings ("Default trend-excluded months"), and the exported
methodology all state excluded months are removed from the trend calculation.
In code, `trend_exclude` reaches only the *display label* ("Growing/Declining")
and the `excluded` flag on MonthlyTrend rows. The scored dimension
(`_score_trend`, engine.py ~line 453) regresses over **all** months — it never
receives `trend_exclude`. The default excludes 2026-04/05/06, hard-coded in
constants.py and already going stale. Related trap: a partially-loaded current
month reads as a volume crash — exactly what exclusion was designed to prevent,
exactly where it doesn't work.

**Fix:** pass `trend_exclude` into `_score_trend`, drop excluded months before
the regression, and auto-exclude the incomplete trailing month.

**➡ YOUR ANSWER (R5)** — approve? Also: keep the hard-coded default exclusion
list, or switch to "auto-exclude trailing incomplete month" only?

---

## Issue R6 — Geo anomaly detection mathematically cannot fire for 83 % of chemicals; where it fires, it multiplies a rank by a volume ratio
**Category:** Analytical/Mathematical · **Severity: HIGH**

`stage4b_geo_adjust` flags months with |z| > 2.0 using the *sample* standard
deviation. For n points, max |z| = (n−1)/√n: **1.50 at n=4, 1.79 at n=5 —
detection impossible below 6 active months**. Real run 2: 979 chemicals have
< 4 months (skipped) and **364 more have 4–5 months where the code runs but can
never detect anything** — the stage is provably inert for **1,343 of 1,619
chemicals (83 %)** while the methodology sheet advertises it for every score.
Where it fires, `trend_adjusted = trend_norm × adj_factor` multiplies a
**percentile rank** by a **volume ratio** — dimensionally meaningless; the
product can reach 150, letting one dimension exceed its weight ceiling by 1.5×.

**Fixes:** leave-one-out z-score or median/MAD robust detection (no ceiling);
disclose a minimum-months threshold ("active only with ≥ 6 months"); apply the
adjustment to the *raw* trend input before ranking, never to the rank; clamp to
[0, 100].

**➡ YOUR ANSWER (R6):**

---

## Issue R7 — Ingestion trusts blindly: duplicate files double-count across runs, and unit conversion is guesswork
**Category:** Operational · **Severity: HIGH**

- **Duplicates:** `EXIM_Trade_Analysis_Report_1043510_….xlsx` is in run 1
  **and** run 2 (1,130 identical rows each) — nothing detects re-uploads. The
  EPR trade cross-link searches RawRows across the **last 4 completed runs of
  any kind**, so one physical shipment can appear up to 4× in "trade shipments"
  counts on company pages, the home dashboard, and lead snapshots. Within a
  run, uploading the same file twice would silently double every volume
  (volume + price = 35 % of ATT).
- **Units:** DRUM→200 kg, BAG→25 kg, PALLET→1,000 kg, L→1 kg, PIECE→1 kg are
  hard-coded guesses; unknown units pass through unchanged. Real run 2: 1,858
  rows have qty>0 but qty_kg=0, and **379 rows have a stated unit_price that
  disagrees with value_usd/qty_kg by >50 %** — mass-unit errors feeding the
  volume dimension and every $/kg median.
- **Fixed-position parsing** (`v[0]`…`v[15]`): any column reorder in the EXIM
  export silently maps buyer↔seller or value↔qty rather than failing.

**Fixes:** hash uploaded files, warn/block re-uploads (per run and across
recent runs); dedupe cross-link counts by (date, hsn, buyer, seller, value);
validate qty_kg × unit_price ≈ value_usd per row and quarantine failures;
header-driven column mapping with hard error on mismatch.

**➡ YOUR ANSWER (R7):**

---

## Issue R8 — The Opportunity Map is polluted by garbage NLP names that outrank the real portfolio and destabilize feedback
**Category:** Logical · **Severity: HIGH**

`_extract_chem_name` takes the first 6 words of an unmatched description as a
"chemical". Real run 2 top opportunity chemicals include **"The Demas. The
Demas. Nitrites; Nitrates."** (147 shipments) — machine-translated Spanish
tariff boilerplate ("Los demás" = "the others") presented as a tradeable
chemical. The same substance splits across name variants ("Sulphates; Alum;
Peroxosulphates (Persulphates)" 716 / "Sulphates; Alums;Peroxosulphates" 210 /
"Sulphates" 13), fragmenting volumes and inflating cohort size (which, per R2,
drags every real chemical's percentile down). These fabricated names average
**att 49.3 vs 42.3 for the base portfolio**, so boilerplate ranks above real
products by default. Feedback is keyed to exact strings: the live feedback row
for **"zinc sulf"** will never match any chemical in any future run.

**Fixes:** cluster opportunity rows by HSN6 + normalized token set instead of
raw 6-word prefixes; stoplist tariff boilerplate tokens (demas, heading, nes,
others); label the opportunity pool as unverified and stop interleaving it with
the base pool in the default sort.

**➡ YOUR ANSWER (R8):**

---

## Issue R9 — Feedback: confirming a score changes it, anonymous votes stack forever, and retention deletes them silently
**Category:** Logical · **Severity: MEDIUM**

`_feedback_adjustments` (runner.py ~line 109): confirm = +1, challenge = −2,
correct = ±2.5, summed over **all feedback ever, from all runs, keyed by exact
chemical name**, clamped ±5, applied to every future run. All visible live:

- **"Confirm" means "the score is right" — and it adds +1.** Three anonymous
  confirms plus one "correct → A" on *Bismuth Sub Nitrate Monohydrate* already
  sum to +5.5 → clamped **+5 applied forever**.
- No dedup, no identity: 6 of 10 rows are anonymous; one person can submit
  "challenge" three times (−5, half a tier width) in a minute. **6 of the 32
  chemicals in run 4 sit within ±5 of a tier boundary** — feedback alone flips
  their tier.
- `delete_run` and the 180-day retention loop delete Feedback rows with the
  run — the aggregate adjustment then changes and the next run's scores shift
  with no explanation in any log.

### Decision R9 (competing options)
- **(a)** confirm = 0 effect (recorded, displayed, not scored); one active vote
  per user per chemical; feedback stored independent of run lifetime.
- **(b)** Drop score-mutation entirely — feedback becomes annotations next to
  the score. (The current ±5 with anonymous stacking is the worst of both.)

**➡ YOUR ANSWER (R9):**

---

## Issue R10 — Security & lifecycle: unlimited PIN brute force behind CORS `*`, plaintext secrets, API keys in URLs, and a default that auto-deletes all history at 180 days
**Category:** Operational · **Severity: MEDIUM (HIGH the day it faces the internet, which the Settings page explicitly anticipates)**

- **PIN gate:** `/api/auth/verify` has no rate limit or lockout; the PIN is
  stored plaintext and compared with `!=`. A 4–6 digit PIN falls in seconds;
  the Security panel explicitly markets this gate for "a cloud VM".
- **CORS:** `allow_origins=['*']` with all methods/headers. On the default
  no-PIN LAN deployment, any web page an employee visits can silently call
  `DELETE /api/runs/{id}` or `PUT /api/settings` on the LAN host — drive-by
  data destruction via one malicious ad.
- **API keys:** stored **plaintext** (fully recoverable from the live DB) and
  accepted via `?api_key=` query parameter — landing in proxy logs, browser
  history, referrer headers. Every v1 request does a synchronous
  `last_used_at` write-commit — a write per read on SQLite.
- **Retention:** `retention_days` **defaults to 180**; the cleanup thread
  deletes runs *plus their RawRows and Feedback*. Lead references dangle, EPR
  cross-links and the digest quietly empty, feedback-adjusted scores shift
  (R9). Six months from first use, the platform starts eating its own history
  by default, with only a console print as notice.
- SQLite with threaded background runs and no WAL mode — a 107k-row bulk
  insert while users browse invites "database is locked" errors.

**Fixes:** rate-limit/lock out PIN attempts + hash the PIN; restrict CORS to
the app's own origin; hash API keys at rest + drop query-param auth; retention
default 0 (keep forever) with explicit opt-in and a warning listing what gets
deleted; SQLite WAL + busy_timeout.

**➡ YOUR ANSWER (R10):**

---

## Auditor's verdict (verbatim)

> The two most damaging facts are structural: **(1)** the percentile-rank
> engine at the heart of both the chemical and battery modules is broken twice
> over — ties are ranked by memory order (identical chemicals differ by up to
> 10 ATT points, Issue R1) and scores are cohort-relative while three shipped
> features present them as comparable across runs (Issue R2); **(2)** the
> battery procurement ranking actively inverts its own intent — 71 % of
> suppliers get perfect "consistency" for one month of activity and 609
> single-shipment entities are rated Tier A (Issue R3). Alongside these, two
> advertised features provably do nothing (trend exclusion, R5; geo adjustment
> for 83 % of chemicals, R6). Fixes for R1, R3, and R5 are each a few lines and
> should precede any new feature work; R2 requires a product decision about
> what "score" is supposed to mean across runs — the same decision Round 1
> demanded for the EPR redesign.
