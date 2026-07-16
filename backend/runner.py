"""Background pipeline execution: runs stages 1-7 in a worker thread,
streams progress into the runs table, persists all results to SQLite,
and writes the export workbook to disk. Handles both run kinds:
'chemical' (ATT scoring) and 'battery' (feedstock procurement)."""
import hashlib
import json
import os
import shutil
import threading
import traceback
from statistics import median
from collections import Counter

from .db import (
    SessionLocal, Run, ChemicalScore, MonthlyTrend, GeoLog, RegLog, RawRow,
    Feedback, BatteryEntity, BatteryCategory, DATA_DIR,
)
from . import settings
from .llm import LlmMatcher
from .pipeline import engine as pipe
from .pipeline.constants import ENGINE_VERSION
from .pipeline.export import stage7_output
from .pipeline.battery import run_battery_pipeline
from .pipeline.battery_export import write_battery_workbook

_lock = threading.Lock()


def _row_hash(date, hsn6, seller, buyer, qty_kg, value_usd):
    """Identifies the same physical shipment across separate run uploads
    (overlapping monthly extracts, accidental re-uploads) so cross-run
    aggregation (EPR trade cross-links, future dashboards) can dedupe instead
    of multiplying counts (R7)."""
    key = f'{date}|{hsn6}|{seller}|{buyer}|{round(qty_kg, 1)}|{round(value_usd, 1)}'
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def run_dir(run_id):
    d = os.path.join(DATA_DIR, 'uploads', str(run_id))
    os.makedirs(d, exist_ok=True)
    return d


def _update_run(run_id, **fields):
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        for k, v in fields.items():
            setattr(run, k, v)
        session.commit()
    finally:
        session.close()


def start_run(run_id, exim_files, base_file, config, llm_config):
    t = threading.Thread(
        target=_execute, args=(run_id, exim_files, base_file, config, llm_config),
        daemon=True)
    t.start()


def _execute(run_id, exim_files, base_file, config, llm_config):
    log_lines = []

    def log(msg):
        log_lines.append(str(msg))
        print(f"[run {run_id}] {msg}")

    def progress(stage, pct):
        _update_run(run_id, stage=stage, progress=pct, status='running')

    try:
        _update_run(run_id, status='running', stage='Starting', progress=1)
        trend_exclude = set(config.get('trend_exclude') or [])

        matcher = LlmMatcher(llm_config, SessionLocal, log)
        llm_matcher = matcher if matcher.enabled and config.get('use_llm', True) else None

        st = settings.get_all()
        res = pipe.run_pipeline(exim_files, base_file, log=log, progress=progress,
                                llm_matcher=llm_matcher,
                                weights=st.get('weights'),
                                tier_a=st.get('tier_a_min'), tier_b=st.get('tier_b_min'),
                                trend_exclude=trend_exclude,
                                anchor_bands=st.get('att_anchor_bands'))

        progress('Saving results to database', 80)
        _persist(run_id, res, trend_exclude)

        progress('Writing export workbook', 92)
        out_path = os.path.join(run_dir(run_id), 'ATT_Results.xlsx')
        stage7_output(res['base_chems'], res['base_scores'],
                      res['opp_chems'], res['opp_scores'],
                      res['geo_log'], res['reg_log'], res['exim_rows'],
                      out_path, trend_exclude)

        tiers = Counter()
        for s in list(res['base_scores'].values()) + list(res['opp_scores'].values()):
            tiers[s['tier']] += 1
        stats = {
            'total_rows': len(res['exim_rows']),
            'base_chemicals': len(res['base_chems']),
            'opportunity_chemicals': len(res['opp_chems']),
            'match_stats': res['match_stats'],
            'tiers': dict(tiers),
            'skipped_files': res['skipped_files'],
            'geo_anomalies': len(res['geo_log']),
            'llm_used': bool(llm_matcher),
        }
        _update_run(run_id, status='done', stage='Complete', progress=100,
                    stats_json=json.dumps(stats))
        log("COMPLETE")
    except Exception as e:
        traceback.print_exc()
        _update_run(run_id, status='error', stage='Failed',
                    error=f'{type(e).__name__}: {e}')


TIER_TARGET = {'A': 85, 'B': 55, 'C': 20}


def _feedback_adjustments(session):
    """Aggregate trader feedback across ALL past runs into a bounded per-chemical
    adjustment. R9: 'confirm' means "this score looks right" and must not
    itself change the score — only 'challenge' (-2) and 'correct' (±2.5 toward
    the suggested tier) vote. Anonymous feedback (no user_name) is displayed
    but excluded from scoring, since it can't be deduped by identity and
    anonymous stacking was the actual abuse vector (three anonymous
    'challenge' votes could otherwise move a score by half a tier width from
    one unaccountable source). Clamped to ±5 so feedback nudges but never
    overrides the pipeline."""
    by_chem = {}
    for f in session.query(Feedback).filter(Feedback.user_name != '').all():
        by_chem.setdefault(f.chemical, []).append(f)

    def adj_for(chemical, att_final):
        total = 0.0
        for f in by_chem.get(chemical, []):
            if f.verdict == 'challenge':
                total -= 2.0
            elif f.verdict == 'correct':
                target = TIER_TARGET.get(f.suggested_tier, 55)
                total += 2.5 if target > att_final else (-2.5 if target < att_final else 0)
            # 'confirm' intentionally contributes 0 — see docstring
        return max(-5.0, min(5.0, total))

    return adj_for


def _persist(run_id, res, trend_exclude):
    session = SessionLocal()
    try:
        # wipe any previous partial data for this run
        for model in (ChemicalScore, MonthlyTrend, GeoLog, RegLog, RawRow):
            session.query(model).filter(model.run_id == run_id).delete()
        session.commit()

        st = settings.get_all()
        fb_enabled = bool(st.get('feedback_adjustment', True))
        tier_a, tier_b = st.get('tier_a_min', 70), st.get('tier_b_min', 40)
        adj_for = _feedback_adjustments(session) if fb_enabled else (lambda c, a: 0.0)

        reg_by_chem = {r['chemical']: r for r in res['reg_log']}

        for pool, chems, scores in (('base', res['base_chems'], res['base_scores']),
                                    ('opportunity', res['opp_chems'], res['opp_scores'])):
            for cid, s in scores.items():
                c = chems[cid]
                direction, growth = pipe.compute_trend_direction(c, trend_exclude)
                pstats = pipe.price_stats(c)
                detail = {
                    'price_stats': pstats,
                    'top_buyers': c['buyers'].most_common(10),
                    'top_suppliers': c['sellers'].most_common(10),
                    'top_buyer_countries': c['buyer_countries'].most_common(10),
                    'top_seller_countries': c['seller_countries'].most_common(10),
                    'india_shipments': c['seller_countries'].get('INDIA', 0),
                    'india_pct': round(c['seller_countries'].get('INDIA', 0) / max(c['shipment_count'], 1) * 100, 1),
                    'match_types': dict(c['match_types']),
                    'monthly_price_medians': {m: round(median(pp), 2)
                                              for m, pp in sorted(c['price_by_month'].items()) if pp},
                }

                att_final = s.get('att_final', 0)
                fb_adj = round(adj_for(cid, att_final), 2)
                att_final_adj = max(0, min(100, att_final + fb_adj))
                att_india_adj = att_final_adj + s.get('rodtep_bonus', 0) + s.get('drawback_bonus', 0)
                tier_adj = ('A' if att_final_adj >= tier_a else
                            ('B' if att_final_adj >= tier_b else 'C'))
                raw = {k: s.get(k) for k in ('volume', 'price', 'buyers', 'suppliers',
                                             'trend', 'structure', 'freedom', 'barrier',
                                             'geo_adj')}
                session.add(ChemicalScore(
                    run_id=run_id, chemical=cid, pool=pool,
                    hsn_codes=', '.join(sorted(c['hsn_codes'])),
                    shipments=c['shipment_count'],
                    total_qty_kg=round(c['total_qty_kg'], 1),
                    total_value_usd=round(c['total_value_usd'], 1),
                    volume_norm=round(s.get('volume_norm', 0), 2),
                    price_norm=round(s.get('price_norm', 0), 2),
                    buyers_norm=round(s.get('buyers_norm', 0), 2),
                    suppliers_norm=round(s.get('suppliers_norm', 0), 2),
                    trend_norm=round(s.get('trend_norm', 0), 2),
                    trend_adjusted=round(s.get('trend_adjusted', 50), 2),
                    structure_norm=round(s.get('structure_norm', 0), 2),
                    freedom_norm=round(s.get('freedom_norm', 0), 2),
                    barrier_norm=round(s.get('barrier_norm', 0), 2),
                    raw_json=json.dumps(raw),
                    variance_type=s.get('variance_type', 'neutral'),
                    variance_mod=s.get('variance_mod', 0),
                    reg_factor=s.get('reg_factor', 1.0),
                    reg_status=reg_by_chem.get(cid, {}).get('status', 'clear'),
                    att_base=s.get('att_base', 0),
                    att_final=round(att_final_adj, 2),
                    att_india=round(att_india_adj, 2),
                    rodtep_bonus=s.get('rodtep_bonus', 0),
                    drawback_bonus=s.get('drawback_bonus', 0),
                    feedback_adj=fb_adj,
                    tier=tier_adj,
                    trend_direction=direction,
                    growth_rate=growth,
                    reasoning=pipe.opportunity_reasoning(c, s),
                    detail_json=json.dumps(detail),
                    engine_version=ENGINE_VERSION,
                ))
                for month in sorted(c['monthly_shipments'].keys()):
                    session.add(MonthlyTrend(
                        run_id=run_id, chemical=cid, month=month,
                        shipments=c['monthly_shipments'][month],
                        qty_kg=round(c['monthly_qty'][month], 1),
                        value_usd=round(c['monthly_value'][month], 1),
                        excluded=1 if month in trend_exclude else 0,
                    ))
        session.commit()

        for g in res['geo_log']:
            session.add(GeoLog(run_id=run_id, chemical=g['chemical'], month=g['month'],
                               direction=g['direction'], z_score=g['z_score'],
                               deviation_pct=g['deviation_pct'], raw_value=g['raw_value'],
                               avg_value=g['avg_value'], adj_factor=g['adj_factor'],
                               event=g['event']))
        for rg in res['reg_log']:
            session.add(RegLog(run_id=run_id, chemical=rg['chemical'], factor=rg['factor'],
                               status=rg['status'], note=rg['note']))
        session.commit()

        # raw rows — bulk insert in chunks
        buf = []
        for rx in res['exim_rows']:
            buf.append(dict(
                run_id=run_id, date=rx['date'], hsn6=rx['hsn6'],
                desc_clean=rx['desc_clean'][:500], chemical=rx.get('chemical_id', ''),
                match_type=rx.get('match_type', ''), match_score=round(rx.get('match_score', 0), 3),
                seller=rx['seller'], seller_country=rx['seller_country'],
                buyer=rx['buyer'], buyer_country=rx['buyer_country'],
                qty=rx['qty'], qty_kg=round(rx['qty_kg'], 1),
                value_usd=round(rx['value_usd'], 1), unit_price=rx['unit_price'],
                file=rx['file'],
                row_hash=_row_hash(rx['date'], rx['hsn6'], rx['seller'], rx['buyer'],
                                   rx['qty_kg'], rx['value_usd']),
            ))
            if len(buf) >= 2000:
                session.bulk_insert_mappings(RawRow, buf)
                buf = []
        if buf:
            session.bulk_insert_mappings(RawRow, buf)
        session.commit()
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Battery procurement runs
# ══════════════════════════════════════════════════════════════
def start_battery_run(run_id, exim_files, config):
    t = threading.Thread(target=_execute_battery, args=(run_id, exim_files, config),
                         daemon=True)
    t.start()


def _execute_battery(run_id, exim_files, config):
    def log(msg):
        print(f"[battery run {run_id}] {msg}")

    def progress(stage, pct):
        _update_run(run_id, stage=stage, progress=pct, status='running')

    try:
        _update_run(run_id, status='running', stage='Starting', progress=1)
        st = settings.get_all()
        res = run_battery_pipeline(exim_files, log=log, progress=progress,
                                   tier_a=st.get('tier_a_min', 70),
                                   tier_b=st.get('tier_b_min', 40),
                                   anchor_bands=st.get('battery_anchor_bands'))

        progress('Saving results to database', 80)
        _persist_battery(run_id, res)

        progress('Writing battery workbook', 92)
        write_battery_workbook(res, os.path.join(run_dir(run_id), 'Battery_Results.xlsx'))

        stats = {
            'total_rows': len(res['rows']),
            'suppliers': len(res['suppliers']),
            'buyers': len(res['buyers']),
            'categories': res['cat_counts'],
            'skipped_files': res['skipped_files'],
            'tiers': dict(Counter(s['tier'] for s in res['suppliers'])),
        }
        _update_run(run_id, status='done', stage='Complete', progress=100,
                    stats_json=json.dumps(stats))
        log("COMPLETE")
    except Exception as e:
        traceback.print_exc()
        _update_run(run_id, status='error', stage='Failed',
                    error=f'{type(e).__name__}: {e}')


def _persist_battery(run_id, res):
    session = SessionLocal()
    try:
        for model in (BatteryEntity, BatteryCategory, MonthlyTrend, RawRow):
            session.query(model).filter(model.run_id == run_id).delete()
        session.commit()

        buf_entities = []
        for role, items in (('supplier', res['suppliers']), ('buyer', res['buyers'])):
            for it in items:
                buf_entities.append(dict(
                    run_id=run_id, role=role, name=it['name'], country=it['country'],
                    categories=it['categories'], shipments=it['shipments'],
                    qty_kg=it['qty_kg'], value_usd=it['value_usd'],
                    median_price=it['median_price'], price_index=it['price_index'],
                    months_active=it['months_active'], first_month=it['first_month'],
                    last_month=it['last_month'], consistency=it['consistency'],
                    geo_ease=it['geo_ease'], proc_score=it['proc_score'], tier=it['tier'],
                    detail_json=json.dumps(it['detail']),
                    engine_version=ENGINE_VERSION,
                ))
        if buf_entities:
            session.bulk_insert_mappings(BatteryEntity, buf_entities)

        buf_cats = []
        buf_trends = []
        for c in res['categories']:
            buf_cats.append(dict(
                run_id=run_id, category=c['category'], shipments=c['shipments'],
                qty_kg=c['qty_kg'], value_usd=c['value_usd'],
                median_price=c['median_price'], n_suppliers=c['n_suppliers'],
                n_buyers=c['n_buyers'], top_countries=json.dumps(c['top_countries']),
            ))
            for month, n in c['monthly_shipments'].items():
                buf_trends.append(dict(
                    run_id=run_id, chemical=c['category'], month=month, shipments=n,
                    qty_kg=c['monthly_qty'].get(month, 0),
                    value_usd=c['monthly_value'].get(month, 0), excluded=0,
                ))
        if buf_cats:
            session.bulk_insert_mappings(BatteryCategory, buf_cats)
        if buf_trends:
            session.bulk_insert_mappings(MonthlyTrend, buf_trends)
        session.commit()

        buf = []
        for rx in res['rows']:
            buf.append(dict(
                run_id=run_id, date=rx['date'], hsn6=rx['hsn6'],
                desc_clean=rx['desc_clean'][:500], chemical=rx['category'],
                match_type='category', match_score=1.0,
                seller=rx['seller'], seller_country=rx['seller_country'],
                buyer=rx['buyer'], buyer_country=rx['buyer_country'],
                qty=rx['qty'], qty_kg=round(rx['qty_kg'], 1),
                value_usd=round(rx['value_usd'], 1), unit_price=rx['unit_price'],
                file=rx['file'],
                row_hash=_row_hash(rx['date'], rx['hsn6'], rx['seller'], rx['buyer'],
                                   rx['qty_kg'], rx['value_usd']),
            ))
            if len(buf) >= 2000:
                session.bulk_insert_mappings(RawRow, buf)
                buf = []
        if buf:
            session.bulk_insert_mappings(RawRow, buf)
        session.commit()
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Run deletion (UI + retention auto-cleanup)
# ══════════════════════════════════════════════════════════════
def delete_run(run_id):
    """Remove a run's DB rows and its uploads directory. Feedback is
    intentionally NOT deleted here (R9) — it's aggregated across ALL runs by
    chemical name (_feedback_adjustments) and should keep influencing future
    scores even after the run it was originally logged against is gone;
    deleting it silently on retention cleanup was the actual bug (scores
    shifting for no reason a user could see in any log)."""
    session = SessionLocal()
    try:
        for model in (ChemicalScore, MonthlyTrend, GeoLog, RegLog, RawRow,
                      BatteryEntity, BatteryCategory):
            session.query(model).filter(model.run_id == run_id).delete()
        run = session.get(Run, run_id)
        if run:
            session.delete(run)
        session.commit()
    finally:
        session.close()
    shutil.rmtree(os.path.join(DATA_DIR, 'uploads', str(run_id)), ignore_errors=True)
