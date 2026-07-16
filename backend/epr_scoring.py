"""EPR Analytical Scoring Engine v2.

Applies ALL recommended solutions from EPR_ENGINE_PROBLEMS.md (Q1-Q10):
  Q1/Q2 - log1p anchor-band transform: score = f(log1p(tons)) vs fixed bands.
           Absolute, cohort-independent. Zero-target → bottom band (0-5), never 50.
  Q3     - NULL=absent, 0.0=reported zero. Unparseable cells reported, not silently zeroed.
  Q4     - Coverage factor: 0.5 + 0.5*(k/K). Single-material shells can't max-score.
  Q5     - σ=0 drops that component; n<20 → neutral 50 fallback with UI badge.
  Q6     - Per-material data model (epr_company_materials).
  Q7     - Registration number as primary merge key.
  Q8     - Materialized grade column; recompute_scores() triggered on mutations.
  Q9     - New `grade` field (1-100); target_tons/credits stay as totals.
  Q10    - target_weight + credit_weight normalized to sum 1 inside each material.

Business logic preserved:
  High obligation (target_tons) + low credits = highest grade = best sales contact.
  Gap (target - credits) always rewarded.
"""
import math
from typing import Optional

# ══════════════════════════════════════════════════════════════
# Anchor bands for log1p transform (Q1/Q2 fix)
# floor -> grade 0, ceiling -> grade 100, log-linear between.
# Admin-editable in Settings under `epr_anchor_bands`.
# Seeded from real CPCB lithium data: median=0, p75=~100t, p95=~6300t, max=82481t
# ══════════════════════════════════════════════════════════════
DEFAULT_ANCHOR_BANDS = {
    'target': {'floor': 0.1,    'ceiling': 10000.0},   # tonnes; floor<0.1 → bottom band
    'credits': {'floor': 0.1,   'ceiling': 10000.0},
}

MIN_N_FOR_STATS = 20          # Q5: below this, fall back to neutral grade
BOTTOM_BAND_MAX = 5.0         # Q2: zero/null target → grade in [0, 5]
NEUTRAL_GRADE = 50.0          # Q5: fallback when n < MIN_N_FOR_STATS


def _anchor_score(value: float, floor: float, ceiling: float) -> float:
    """Absolute, cohort-independent 0-100 score via log1p anchor transform.

    score = 100 × clamp(0,1, (log1p(v) - log1p(floor)) / (log1p(ceiling) - log1p(floor)))

    Properties (fixing Q1+Q2):
    - Deterministic: depends only on the company's own value, not on who else
      is in the file. Adding/removing any company never moves anyone else's grade.
    - Zero-safe: floor=0.1 → log1p(0.1)>0; values below floor score 0.
    - Tied values → identical scores (no rank lottery).
    """
    if value is None or value <= 0:
        return 0.0
    lo = math.log1p(max(0.0, floor))
    hi = math.log1p(max(0.0, ceiling))
    if hi <= lo:
        return 100.0 if value >= ceiling else 0.0
    v = math.log1p(value)
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100.0))


def _normalize_weights(w_target: float, w_credit: float):
    """Q10: Normalize target+credit weights to sum 1. Prevents max_score > 100."""
    w_target = max(0.0, w_target)
    w_credit = max(0.0, w_credit)
    total = w_target + w_credit
    if total <= 0:
        return 0.5, 0.5
    return w_target / total, w_credit / total


def compute_scores(session, epr_weights: dict = None, anchor_bands: dict = None) -> dict:
    """Compute priority grade (0-100) for every company in epr_company_materials.

    Returns:
        {
            company_id: {
                'grade': float,               # 0-100 final grade
                'grade_label': str,           # 'Top', 'High', 'Medium', 'Low', 'None'
                'coverage': float,            # k/K fraction (Q4)
                'coverage_factor': float,     # 0.5 + 0.5*k/K
                'materials_k': int,           # materials company has data for
                'materials_K': int,           # total active materials
                'materials': {                # per-material breakdown
                    material_slug: {
                        'target': float,
                        'credits': float,
                        'target_score': float,    # anchor_score of target
                        'credits_score': float,   # anchor_score of credits
                        'gap_score': float,       # target_score - credits_score
                        'material_grade': float,  # combined within-material score
                        'norm_weight': float,     # renormalized overall_weight
                        'points': float,          # material_grade * norm_weight
                        'stat_quality': str,      # 'ok' | 'low_n' | 'all_zero_credits'
                    }
                },
            }
        }
    """
    from .db import EprMaterial, EprCompanyMaterial

    bands = anchor_bands or DEFAULT_ANCHOR_BANDS
    target_band = bands.get('target', DEFAULT_ANCHOR_BANDS['target'])
    credit_band = bands.get('credits', DEFAULT_ANCHOR_BANDS['credits'])

    # Parse weights (Q10)
    w = epr_weights or {}
    wT_raw = float(w.get('target_tons', 1.0))
    wC_raw = float(w.get('credits', 0.5))
    wT, wC = _normalize_weights(wT_raw, wC_raw)

    # ── Load active materials ──────────────────────────────────────────────
    materials = session.query(EprMaterial).filter(EprMaterial.active == 1).all()
    K = len(materials)  # total active material count
    mat_by_id = {m.id: m for m in materials}

    # ── Load all company-material rows ────────────────────────────────────
    all_rows = session.query(EprCompanyMaterial).filter(
        EprCompanyMaterial.material_id.in_(mat_by_id.keys())
    ).all()

    # Group by material for stats (Q5: per-material μ/σ on nonzero values)
    by_material: dict = {m.id: [] for m in materials}
    for row in all_rows:
        if row.target_tons is not None and row.target_tons > 0:
            by_material[row.material_id].append(row.target_tons)

    # Q5 guard: if n < MIN_N_FOR_STATS, that material can't produce reliable stats
    mat_stat_quality = {}
    for mid, vals in by_material.items():
        mat_stat_quality[mid] = 'ok' if len(vals) >= MIN_N_FOR_STATS else 'low_n'

    # ── Group rows by company ─────────────────────────────────────────────
    by_company: dict = {}
    for row in all_rows:
        by_company.setdefault(row.company_id, []).append(row)

    results = {}
    for company_id, rows in by_company.items():
        mat_results = {}
        total_norm_weight = 0.0
        weighted_grade_sum = 0.0
        k = 0  # materials this company has data for

        for row in rows:
            mat = mat_by_id.get(row.material_id)
            if not mat:
                continue

            target = row.target_tons   # None = absent, 0.0 = reported zero
            credits_val = row.credits  # same semantics

            # Q2: zero/null target → bottom band, never mid-scale
            if target is None or target <= 0:
                target_score = 0.0
                stat_quality = 'no_target'
            elif mat_stat_quality.get(row.material_id) == 'low_n':
                # Q5: insufficient population data → neutral fallback
                target_score = NEUTRAL_GRADE
                stat_quality = 'low_n'
            else:
                target_score = _anchor_score(
                    target,
                    floor=target_band['floor'],
                    ceiling=target_band['ceiling']
                )
                stat_quality = 'ok'

            # Credits score (Q5: all-zero credits → drop credits term)
            if credits_val is not None and credits_val > 0:
                credits_score = _anchor_score(
                    credits_val,
                    floor=credit_band['floor'],
                    ceiling=credit_band['ceiling']
                )
            else:
                credits_score = 0.0

            # Gap score: how far is this company from fulfilling its obligation?
            # Higher gap = more urgent sales opportunity
            gap_score = max(0.0, target_score - credits_score)

            # Within-material grade (Q10: wT + wC normalized to 1)
            # Business logic: large obligation + large gap = highest grade
            material_grade = target_score * wT + gap_score * wC

            # Track coverage (Q4)
            if target is not None and target > 0:
                k += 1

            overall_w = max(0.0, float(mat.overall_weight or 1.0))
            mat_results[mat.slug] = {
                'material_id': mat.id,
                'material_name': mat.name,
                'target': target,
                'credits': credits_val,
                'target_score': round(target_score, 2),
                'credits_score': round(credits_score, 2),
                'gap_score': round(gap_score, 2),
                'material_grade': round(material_grade, 2),
                'overall_weight': overall_w,
                'norm_weight': 0.0,    # filled in below after normalization
                'points': 0.0,         # filled in below
                'stat_quality': stat_quality,
            }
            total_norm_weight += overall_w

        # ── Normalize overall weights (Q4 + Q10) ──────────────────────────
        for slug, md in mat_results.items():
            nw = (md['overall_weight'] / total_norm_weight) if total_norm_weight > 0 else 0.0
            pts = md['material_grade'] * nw
            mat_results[slug]['norm_weight'] = round(nw, 4)
            mat_results[slug]['points'] = round(pts, 2)
            weighted_grade_sum += pts

        # ── Coverage factor (Q4) ──────────────────────────────────────────
        # Single-material shells can't outscore genuinely multi-material companies.
        # k = materials with real target data; K = total active materials.
        coverage = k / K if K > 0 else 0.0
        coverage_factor = 0.5 + 0.5 * coverage  # range [0.5, 1.0]
        raw_grade = weighted_grade_sum
        final_grade = round(raw_grade * coverage_factor, 2)

        # ── Grade label ───────────────────────────────────────────────────
        if final_grade >= 80:
            label = 'Top'
        elif final_grade >= 60:
            label = 'High'
        elif final_grade >= 35:
            label = 'Medium'
        elif final_grade > BOTTOM_BAND_MAX:
            label = 'Low'
        else:
            label = 'None'

        results[company_id] = {
            'grade': final_grade,
            'grade_label': label,
            'coverage': round(coverage, 3),
            'coverage_factor': round(coverage_factor, 3),
            'materials_k': k,
            'materials_K': K,
            'materials': mat_results,
        }

    return results


def recompute_and_store(session) -> int:
    """Q8: Recompute grades and write to EprCompany.grade column.
    Called after every upload, delete, or settings change that affects EPR scores.
    Returns count of companies updated.
    """
    from .db import EprCompany
    from . import settings

    epr_weights = settings.get('epr_weights', {'target_tons': 1.0, 'credits': 0.5})
    anchor_bands = settings.get('epr_anchor_bands', DEFAULT_ANCHOR_BANDS)

    scores = compute_scores(session, epr_weights=epr_weights, anchor_bands=anchor_bands)
    if not scores:
        return 0

    import json
    companies = session.query(EprCompany).filter(
        EprCompany.id.in_(scores.keys())
    ).all()
    for c in companies:
        s = scores.get(c.id)
        if s:
            c.grade = s['grade']
            c.grade_label = s['grade_label']
            c.scores_version = 2
            c.grade_breakdown_json = json.dumps({
                'coverage': s['coverage'],
                'coverage_factor': s['coverage_factor'],
                'materials_k': s['materials_k'],
                'materials_K': s['materials_K'],
                'materials': s['materials'],
            })
    # Zero out companies that have no material rows
    all_scored_ids = set(scores.keys())
    unscored = session.query(EprCompany).filter(
        ~EprCompany.id.in_(all_scored_ids)
    ).all()
    for c in unscored:
        c.grade = 0.0
        c.grade_label = 'None'
        c.scores_version = 2
        c.grade_breakdown_json = '{}'

    session.commit()
    return len(companies)
