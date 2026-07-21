"""ATT Platform — FastAPI backend + static frontend server.

Single process, single port (default 8000, bind 0.0.0.0 for LAN access).
"""
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import (
    init_db, SessionLocal, Run, ChemicalScore, MonthlyTrend, GeoLog, RegLog,
    RawRow, Feedback, BatteryEntity, BatteryCategory, DATA_DIR, ROOT,
)
from . import runner
from . import settings
from . import cache as cache_svc
from .llm import LlmMatcher
from .pipeline.constants import DEFAULT_TREND_EXCLUDE

DEFAULT_BASE = os.path.join(DATA_DIR, 'default_base_portfolio.xlsx')
FRONTEND_DIST = os.path.join(ROOT, 'frontend', 'dist')

app = FastAPI(title='MiniMines Sales Hub', version='3.0')
# R10: allow_origins=['*'] let ANY web page an employee visits silently call
# mutating endpoints (DELETE /api/runs/{id}, PUT /api/settings, ...) on this
# host with zero cross-origin restriction — on the default no-PIN LAN
# deployment that's drive-by data destruction from one malicious ad. The
# frontend is served same-origin by this same app (see the SPA mount below),
# so wildcard CORS was never needed for the real use case; only the dev-mode
# Vite server (a different origin/port) needs an explicit allowance. For a
# LAN deployment reached under another hostname/IP, set CORS_ALLOWED_ORIGINS
# (comma-separated) in the environment.
_cors_env = os.environ.get('CORS_ALLOWED_ORIGINS', '')
_cors_origins = ([o.strip() for o in _cors_env.split(',') if o.strip()] if _cors_env
                 else ['http://localhost:5173', 'http://127.0.0.1:5173'])
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=['*'], allow_headers=['*'])
init_db()

# ── module routers ────────────────────────────────────────────
from . import epr, hsn, leads, outreach, ai_api, digest  # noqa: E402

app.include_router(epr.router)
app.include_router(hsn.router)
app.include_router(leads.router)
app.include_router(leads.keys_router)
app.include_router(leads.v1_router)
app.include_router(outreach.router)
app.include_router(ai_api.router)
app.include_router(digest.router)

hsn.ensure_directory()      # load bundled HSN dataset on first boot
outreach.seed_templates()   # default pitch templates on first boot


# ══════════════════════════════════════════════════════════════
# Optional shared-PIN gate (for internet-facing deployments)
# ══════════════════════════════════════════════════════════════
# R10: the PIN endpoint had no rate limit or lockout — a 4-6 digit PIN falls
# to brute force in seconds without one. Simple in-memory sliding-window
# limiter keyed by client IP; a single process is enough here since this gate
# only matters for small internet-facing deployments, not a clustered one.
_PIN_MAX_ATTEMPTS = 5
_PIN_WINDOW_SECONDS = 300
_pin_failures = {}


def _pin_rate_limited(ip):
    now = time.time()
    attempts = [t for t in _pin_failures.get(ip, []) if now - t < _PIN_WINDOW_SECONDS]
    _pin_failures[ip] = attempts
    return len(attempts) >= _PIN_MAX_ATTEMPTS


def _record_pin_failure(ip):
    _pin_failures.setdefault(ip, []).append(time.time())


@app.middleware('http')
async def pin_gate(request: Request, call_next):
    # /api/v1/* is the external API — it carries its own X-API-Key auth
    if request.url.path.startswith('/api') and request.url.path != '/api/auth/verify' \
            and not request.url.path.startswith('/api/v1/') \
            and request.method != 'OPTIONS':
        s = settings.get_all()
        if s.get('pin_enabled') and s.get('pin_code'):
            ip = request.client.host if request.client else 'unknown'
            if _pin_rate_limited(ip):
                return JSONResponse({'detail': 'too_many_attempts'}, status_code=429)
            supplied = request.headers.get('x-att-pin', '')
            if not settings.verify_pin(supplied, s['pin_code']):
                _record_pin_failure(ip)
                return JSONResponse({'detail': 'pin_required'}, status_code=401)
    return await call_next(request)


class PinIn(BaseModel):
    pin: str


@app.post('/api/auth/verify')
def verify_pin(body: PinIn, request: Request):
    s = settings.get_all()
    if not s.get('pin_enabled') or not s.get('pin_code'):
        return {'ok': True, 'pin_required': False}
    ip = request.client.host if request.client else 'unknown'
    if _pin_rate_limited(ip):
        raise HTTPException(429, 'Too many attempts — try again later')
    ok = settings.verify_pin(body.pin, s['pin_code'])
    if not ok:
        _record_pin_failure(ip)
    return {'ok': ok, 'pin_required': True}


# ══════════════════════════════════════════════════════════════
# Retention auto-cleanup (runs older than retention_days; 0 = keep forever)
# ══════════════════════════════════════════════════════════════
def _cleanup_old_runs():
    days = settings.get('retention_days', 0)
    if not days:
        return
    cutoff = datetime.utcnow() - timedelta(days=int(days))
    session = SessionLocal()
    try:
        old = (session.query(Run)
               .filter(Run.created_at < cutoff, Run.status != 'running').all())
        ids = [r.id for r in old]
    finally:
        session.close()
    for rid in ids:
        print(f'[retention] deleting run {rid} (older than {days} days)')
        runner.delete_run(rid)


def _cleanup_loop():
    while True:
        try:
            _cleanup_old_runs()
        except Exception as e:
            print(f'[retention] cleanup failed: {e}')
        time.sleep(6 * 3600)


threading.Thread(target=_cleanup_loop, daemon=True).start()


# ══════════════════════════════════════════════════════════════
# Runs (kind = chemical | battery)
# ══════════════════════════════════════════════════════════════
async def _save_uploads(run_id, exim_files):
    import hashlib
    rdir = runner.run_dir(run_id)
    paths, hashes = [], []
    for f in exim_files:
        content = await f.read()
        dest = os.path.join(rdir, os.path.basename(f.filename or 'exim.xlsx'))
        with open(dest, 'wb') as out:
            out.write(content)
        paths.append(dest)
        hashes.append(hashlib.sha256(content).hexdigest())
    return paths, hashes


def _check_duplicate_files(session, hashes, exclude_run_id):
    """R7: warn (never block) when an uploaded file's content exactly matches
    a file already used in a prior run — the user may still intend a
    correction re-run, so this is informational only."""
    hashes_set = set(hashes)
    if not hashes_set:
        return None
    matches = []
    for r in (session.query(Run).filter(Run.id != exclude_run_id,
                                        Run.file_hashes.isnot(None),
                                        Run.file_hashes != '[]').all()):
        existing = set(json.loads(r.file_hashes or '[]'))
        overlap = hashes_set & existing
        if overlap:
            matches.append({'run_id': r.id, 'run_name': r.name,
                            'created_at': r.created_at.isoformat() if r.created_at else '',
                            'overlap_count': len(overlap)})
    if not matches:
        return None
    return {'message': f'{len(matches)} prior run(s) already contain at least one identical '
                       f'source file — re-uploading may double-count those shipments.',
            'runs': matches}


@app.post('/api/runs')
async def create_run(
    name: str = Form(...),
    trend_exclude: str = Form(''),
    use_llm: bool = Form(True),
    exim_files: list[UploadFile] = File(...),
    base_file: Optional[UploadFile] = File(None),
):
    session = SessionLocal()
    try:
        if not trend_exclude.strip():
            trend_exclude = ','.join(settings.get('trend_exclude_default', DEFAULT_TREND_EXCLUDE))
        exclude = [m.strip() for m in trend_exclude.split(',') if m.strip()]
        config = {'trend_exclude': exclude, 'use_llm': use_llm,
                  'files': [f.filename for f in exim_files],
                  'base_file': base_file.filename if base_file else 'default'}
        run = Run(name=name, kind='chemical', status='queued', stage='Queued', progress=0,
                  config_json=json.dumps(config))
        session.add(run)
        session.commit()
        run_id = run.id

        paths, hashes = await _save_uploads(run_id, exim_files)
        dup_warning = _check_duplicate_files(session, hashes, exclude_run_id=run_id)
        run.file_hashes = json.dumps(hashes)
        session.commit()
        if base_file is not None:
            base_path = os.path.join(runner.run_dir(run_id), 'base_portfolio.xlsx')
            with open(base_path, 'wb') as out:
                out.write(await base_file.read())
        else:
            base_path = DEFAULT_BASE

        llm_config = settings.get('llm', {})
        runner.start_run(run_id, paths, base_path, config, llm_config)
        return {'run_id': run_id, 'duplicate_warning': dup_warning}
    finally:
        session.close()


@app.post('/api/battery-runs')
async def create_battery_run(
    name: str = Form(...),
    exim_files: list[UploadFile] = File(...),
):
    session = SessionLocal()
    try:
        config = {'files': [f.filename for f in exim_files]}
        run = Run(name=name, kind='battery', status='queued', stage='Queued', progress=0,
                  config_json=json.dumps(config))
        session.add(run)
        session.commit()
        run_id = run.id
        paths, hashes = await _save_uploads(run_id, exim_files)
        dup_warning = _check_duplicate_files(session, hashes, exclude_run_id=run_id)
        run.file_hashes = json.dumps(hashes)
        session.commit()
        runner.start_battery_run(run_id, paths, config)
        return {'run_id': run_id, 'duplicate_warning': dup_warning}
    finally:
        session.close()


@app.get('/api/runs')
def list_runs(kind: str = ''):
    session = SessionLocal()
    try:
        q = session.query(Run).order_by(Run.id.desc())
        if kind in ('chemical', 'battery'):
            q = q.filter(Run.kind == kind)
        return [_run_dict(r) for r in q.all()]
    finally:
        session.close()


@app.get('/api/runs/{run_id}')
def get_run(run_id: int):
    session = SessionLocal()
    try:
        r = session.get(Run, run_id)
        if not r:
            raise HTTPException(404, 'Run not found')
        return _run_dict(r)
    finally:
        session.close()


class RunPatch(BaseModel):
    name: str


@app.patch('/api/runs/{run_id}')
def rename_run(run_id: int, body: RunPatch):
    session = SessionLocal()
    try:
        r = session.get(Run, run_id)
        if not r:
            raise HTTPException(404, 'Run not found')
        r.name = body.name.strip() or r.name
        session.commit()
        return _run_dict(r)
    finally:
        session.close()


@app.delete('/api/runs/{run_id}')
def delete_run(run_id: int):
    session = SessionLocal()
    try:
        r = session.get(Run, run_id)
        if not r:
            raise HTTPException(404, 'Run not found')
        if r.status == 'running':
            raise HTTPException(400, 'Cannot delete a running run')
    finally:
        session.close()
    runner.delete_run(run_id)
    return {'ok': True}


def _run_dict(r):
    return {
        'id': r.id, 'name': r.name, 'kind': r.kind or 'chemical',
        'status': r.status, 'progress': r.progress,
        'stage': r.stage, 'error': r.error,
        'created_at': r.created_at.isoformat() if r.created_at else None,
        'config': json.loads(r.config_json or '{}'),
        'stats': json.loads(r.stats_json or '{}'),
    }


# ══════════════════════════════════════════════════════════════
# Chemicals / rankings
# ══════════════════════════════════════════════════════════════
@app.get('/api/runs/{run_id}/chemicals')
def list_chemicals(run_id: int, pool: str = '', tier: str = '', search: str = '',
                   sort: str = 'att_final', order: str = 'desc',
                   include_detail: bool = False,
                   limit: int = Query(2000, le=10000), offset: int = 0):
    session = SessionLocal()
    try:
        q = session.query(ChemicalScore).filter(ChemicalScore.run_id == run_id)
        if pool in ('base', 'opportunity'):
            q = q.filter(ChemicalScore.pool == pool)
        if tier in ('A', 'B', 'C'):
            q = q.filter(ChemicalScore.tier == tier)
        if search:
            q = q.filter(ChemicalScore.chemical.ilike(f'%{search}%'))
        total = q.count()
        col = getattr(ChemicalScore, sort, ChemicalScore.att_final)
        q = q.order_by(col.desc() if order == 'desc' else col.asc())
        rows = q.offset(offset).limit(limit).all()
        return {'total': total, 'items': [_chem_dict(c, detail=include_detail) for c in rows]}
    finally:
        session.close()


def _chem_dict(c, detail=False):
    d = {
        'chemical': c.chemical, 'pool': c.pool, 'hsn_codes': c.hsn_codes,
        'shipments': c.shipments, 'total_qty_kg': c.total_qty_kg,
        'total_value_usd': c.total_value_usd,
        'scores': {
            'volume': c.volume_norm, 'price': c.price_norm, 'buyers': c.buyers_norm,
            'suppliers': c.suppliers_norm, 'trend': c.trend_adjusted,
            'structure': c.structure_norm, 'freedom': c.freedom_norm,
            'barrier': c.barrier_norm,
        },
        'variance_type': c.variance_type, 'variance_mod': c.variance_mod,
        'reg_factor': c.reg_factor, 'reg_status': c.reg_status,
        'att_base': c.att_base, 'att_final': c.att_final, 'att_india': c.att_india,
        'rodtep_bonus': c.rodtep_bonus, 'drawback_bonus': c.drawback_bonus,
        'feedback_adj': c.feedback_adj or 0,
        'tier': c.tier, 'trend_direction': c.trend_direction,
        'growth_rate': c.growth_rate, 'reasoning': c.reasoning,
    }
    if detail:
        d['detail'] = json.loads(c.detail_json or '{}')
        d['raw'] = json.loads(c.raw_json or '{}')
    return d


@app.get('/api/runs/{run_id}/chemicals/{chemical}')
def chemical_detail(run_id: int, chemical: str):
    session = SessionLocal()
    try:
        c = (session.query(ChemicalScore)
             .filter(ChemicalScore.run_id == run_id, ChemicalScore.chemical == chemical)
             .first())
        if not c:
            raise HTTPException(404, 'Chemical not found in this run')
        d = _chem_dict(c, detail=True)
        trends = (session.query(MonthlyTrend)
                  .filter(MonthlyTrend.run_id == run_id, MonthlyTrend.chemical == chemical)
                  .order_by(MonthlyTrend.month).all())
        d['monthly'] = [{'month': t.month, 'shipments': t.shipments, 'qty_kg': t.qty_kg,
                         'value_usd': t.value_usd, 'excluded': bool(t.excluded)} for t in trends]
        geo = (session.query(GeoLog)
               .filter(GeoLog.run_id == run_id, GeoLog.chemical == chemical).all())
        d['geo_anomalies'] = [{'month': g.month, 'direction': g.direction, 'z_score': g.z_score,
                               'deviation_pct': g.deviation_pct, 'adj_factor': g.adj_factor,
                               'event': g.event} for g in geo]
        reg = (session.query(RegLog)
               .filter(RegLog.run_id == run_id, RegLog.chemical == chemical).first())
        d['regulatory'] = ({'status': reg.status, 'factor': reg.factor, 'note': reg.note}
                           if reg else {'status': 'clear', 'factor': 1.0, 'note': ''})
        return d
    finally:
        session.close()


@app.get('/api/chemicals/history')
def chemical_history(name: str):
    """ATT score/tier of one chemical across all completed chemical runs."""
    session = SessionLocal()
    try:
        rows = (session.query(ChemicalScore, Run)
                .join(Run, Run.id == ChemicalScore.run_id)
                .filter(ChemicalScore.chemical == name, Run.status == 'done',
                        Run.kind == 'chemical')
                .order_by(Run.id).all())
        return [{'run_id': r.id, 'run_name': r.name,
                 'created_at': r.created_at.isoformat() if r.created_at else '',
                 'att_final': c.att_final, 'att_india': c.att_india,
                 'tier': c.tier, 'feedback_adj': c.feedback_adj or 0}
                for c, r in rows]
    finally:
        session.close()


@app.get('/api/runs/{run_id}/raw')
def raw_rows(run_id: int, chemical: str = '', search: str = '', match_type: str = '',
             buyer: str = '', seller: str = '',
             limit: int = Query(100, le=1000), offset: int = 0):
    session = SessionLocal()
    try:
        q = session.query(RawRow).filter(RawRow.run_id == run_id)
        if chemical:
            q = q.filter(RawRow.chemical == chemical)
        if match_type:
            q = q.filter(RawRow.match_type == match_type)
        if buyer:
            q = q.filter(RawRow.buyer.ilike(f'%{buyer}%'))
        if seller:
            q = q.filter(RawRow.seller.ilike(f'%{seller}%'))
        if search:
            q = q.filter(RawRow.desc_clean.ilike(f'%{search}%'))
        total = q.count()
        rows = q.offset(offset).limit(limit).all()
        return {'total': total, 'items': [{
            'date': r.date, 'hsn6': r.hsn6, 'desc_clean': r.desc_clean,
            'chemical': r.chemical, 'match_type': r.match_type, 'match_score': r.match_score,
            'seller': r.seller, 'seller_country': r.seller_country,
            'buyer': r.buyer, 'buyer_country': r.buyer_country,
            'qty': r.qty, 'qty_kg': r.qty_kg, 'value_usd': r.value_usd,
            'unit_price': r.unit_price, 'file': r.file,
        } for r in rows]}
    finally:
        session.close()


@app.get('/api/runs/{run_id}/geo')
def geo_log(run_id: int, chemical: str = ''):
    session = SessionLocal()
    try:
        q = session.query(GeoLog).filter(GeoLog.run_id == run_id)
        if chemical:
            q = q.filter(GeoLog.chemical.ilike(f'%{chemical}%'))
        rows = q.order_by(GeoLog.month).all()
        return [{'chemical': g.chemical, 'month': g.month, 'direction': g.direction,
                 'z_score': g.z_score, 'deviation_pct': g.deviation_pct,
                 'adj_factor': g.adj_factor, 'event': g.event} for g in rows]
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Dashboard summary + run comparison
# ══════════════════════════════════════════════════════════════
def _prev_done_run(session, run):
    return (session.query(Run)
            .filter(Run.kind == run.kind, Run.status == 'done', Run.id < run.id)
            .order_by(Run.id.desc()).first())


def _movers(session, run_a_id, run_b_id, limit=15):
    """Chemicals in both runs, biggest |ATT delta| first. a = current, b = previous."""
    a = {c.chemical: c for c in session.query(ChemicalScore)
         .filter(ChemicalScore.run_id == run_a_id).all()}
    b = {c.chemical: c for c in session.query(ChemicalScore)
         .filter(ChemicalScore.run_id == run_b_id).all()}
    rank_a = {name: i + 1 for i, name in enumerate(
        sorted(a, key=lambda n: -a[n].att_final))}
    rank_b = {name: i + 1 for i, name in enumerate(
        sorted(b, key=lambda n: -b[n].att_final))}
    common = set(a) & set(b)
    out = []
    for name in common:
        out.append({
            'chemical': name, 'pool': a[name].pool,
            'att_a': a[name].att_final, 'att_b': b[name].att_final,
            'delta': round(a[name].att_final - b[name].att_final, 2),
            'tier_a': a[name].tier, 'tier_b': b[name].tier,
            'rank_a': rank_a[name], 'rank_b': rank_b[name],
            'rank_delta': rank_b[name] - rank_a[name],
        })
    out.sort(key=lambda m: -abs(m['delta']))
    new = [{'chemical': n, 'att_a': a[n].att_final, 'tier_a': a[n].tier, 'pool': a[n].pool}
           for n in sorted(set(a) - set(b), key=lambda n: -a[n].att_final)]
    dropped = [{'chemical': n, 'att_b': b[n].att_final, 'tier_b': b[n].tier, 'pool': b[n].pool}
               for n in sorted(set(b) - set(a), key=lambda n: -b[n].att_final)]
    return out[:limit] if limit else out, new, dropped


@app.get('/api/runs/{run_id}/summary')
def run_summary(run_id: int):
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(404, 'Run not found')
        top = (session.query(ChemicalScore)
               .filter(ChemicalScore.run_id == run_id)
               .order_by(ChemicalScore.att_final.desc()).limit(10).all())
        fb_count = session.query(Feedback).filter(Feedback.run_id == run_id).count()
        prev = _prev_done_run(session, run)
        movers, new, dropped = ([], [], [])
        if prev and run.kind == 'chemical':
            movers, new, dropped = _movers(session, run_id, prev.id, limit=8)
        return {
            'run': _run_dict(run),
            'top': [_chem_dict(c) for c in top],
            'feedback_count': fb_count,
            'prev_run': _run_dict(prev) if prev else None,
            'movers': movers,
            'new_chemicals': len(new), 'dropped_chemicals': len(dropped),
        }
    finally:
        session.close()


@app.get('/api/compare')
def compare_runs(a: int, b: int):
    """a = current run, b = baseline/previous run."""
    session = SessionLocal()
    try:
        ra, rb = session.get(Run, a), session.get(Run, b)
        if not ra or not rb:
            raise HTTPException(404, 'Run not found')
        movers, new, dropped = _movers(session, a, b, limit=0)
        return {'run_a': _run_dict(ra), 'run_b': _run_dict(rb),
                'movers': movers, 'new': new[:50], 'dropped': dropped[:50]}
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Battery procurement
# ══════════════════════════════════════════════════════════════
@app.get('/api/runs/{run_id}/battery/entities')
def battery_entities(run_id: int, role: str = 'supplier', search: str = '',
                     category: str = '', tier: str = '',
                     sort: str = 'proc_score', order: str = 'desc',
                     limit: int = Query(2000, le=10000), offset: int = 0):
    session = SessionLocal()
    try:
        q = session.query(BatteryEntity).filter(
            BatteryEntity.run_id == run_id,
            BatteryEntity.role == ('buyer' if role == 'buyer' else 'supplier'))
        if search:
            q = q.filter(BatteryEntity.name.ilike(f'%{search}%'))
        if category:
            q = q.filter(BatteryEntity.categories.ilike(f'%{category}%'))
        if tier in ('A', 'B', 'C'):
            q = q.filter(BatteryEntity.tier == tier)
        total = q.count()
        col = getattr(BatteryEntity, sort, BatteryEntity.proc_score)
        q = q.order_by(col.desc() if order == 'desc' else col.asc())
        rows = q.offset(offset).limit(limit).all()
        return {'total': total, 'items': [{
            'name': e.name, 'country': e.country, 'categories': e.categories,
            'shipments': e.shipments, 'qty_kg': e.qty_kg, 'value_usd': e.value_usd,
            'median_price': e.median_price, 'price_index': e.price_index,
            'months_active': e.months_active, 'first_month': e.first_month,
            'last_month': e.last_month, 'consistency': e.consistency,
            'geo_ease': e.geo_ease, 'proc_score': e.proc_score, 'tier': e.tier,
            'detail': json.loads(e.detail_json or '{}'),
        } for e in rows]}
    finally:
        session.close()


@app.get('/api/runs/{run_id}/battery/categories')
def battery_categories(run_id: int):
    session = SessionLocal()
    try:
        rows = (session.query(BatteryCategory)
                .filter(BatteryCategory.run_id == run_id)
                .order_by(BatteryCategory.value_usd.desc()).all())
        trends = (session.query(MonthlyTrend)
                  .filter(MonthlyTrend.run_id == run_id)
                  .order_by(MonthlyTrend.month).all())
        by_cat = {}
        for t in trends:
            by_cat.setdefault(t.chemical, []).append(
                {'month': t.month, 'shipments': t.shipments,
                 'qty_kg': t.qty_kg, 'value_usd': t.value_usd})
        return [{'category': c.category, 'shipments': c.shipments, 'qty_kg': c.qty_kg,
                 'value_usd': c.value_usd, 'median_price': c.median_price,
                 'n_suppliers': c.n_suppliers, 'n_buyers': c.n_buyers,
                 'top_countries': json.loads(c.top_countries or '[]'),
                 'monthly': by_cat.get(c.category, [])} for c in rows]
    finally:
        session.close()


@app.get('/api/runs/{run_id}/battery/export')
def battery_export(run_id: int):
    path = os.path.join(runner.run_dir(run_id), 'Battery_Results.xlsx')
    if not os.path.exists(path):
        raise HTTPException(404, 'Battery workbook not found — run may not be complete')
    return FileResponse(path, filename=f'Battery_Procurement_Run{run_id}.xlsx',
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ══════════════════════════════════════════════════════════════
# Feedback
# ══════════════════════════════════════════════════════════════
class FeedbackIn(BaseModel):
    run_id: int
    chemical: str
    verdict: str            # confirm | challenge | correct
    user_name: str = ''
    suggested_tier: str = ''
    expected_duration: str = ''
    comment: str = ''


@app.post('/api/feedback')
def add_feedback(fb: FeedbackIn):
    if fb.verdict not in ('confirm', 'challenge', 'correct'):
        raise HTTPException(400, 'verdict must be confirm | challenge | correct')
    session = SessionLocal()
    try:
        user_name = fb.user_name.strip()
        # R9: one active vote per (user, chemical) — a named user's new vote
        # replaces their prior vote for this chemical instead of stacking
        # indefinitely (previously the same person could submit "challenge"
        # repeatedly and each one kept counting).
        if user_name:
            (session.query(Feedback)
             .filter(Feedback.chemical == fb.chemical, Feedback.user_name == user_name)
             .delete())
        row = Feedback(run_id=fb.run_id, chemical=fb.chemical, verdict=fb.verdict,
                       user_name=user_name, suggested_tier=fb.suggested_tier,
                       expected_duration=fb.expected_duration, comment=fb.comment)
        session.add(row)
        session.commit()
        return {'id': row.id}
    finally:
        session.close()


@app.get('/api/runs/{run_id}/feedback')
def list_feedback(run_id: int):
    session = SessionLocal()
    try:
        rows = (session.query(Feedback).filter(Feedback.run_id == run_id)
                .order_by(Feedback.id.desc()).all())
        return [_fb_dict(f) for f in rows]
    finally:
        session.close()


def _fb_dict(f):
    return {'id': f.id, 'run_id': f.run_id, 'chemical': f.chemical,
            'user_name': f.user_name, 'verdict': f.verdict,
            'suggested_tier': f.suggested_tier, 'expected_duration': f.expected_duration,
            'comment': f.comment,
            'created_at': f.created_at.isoformat() if f.created_at else ''}


@app.get('/api/runs/{run_id}/feedback/export')
def export_feedback(run_id: int):
    from .pipeline.export import write_feedback_workbook
    session = SessionLocal()
    try:
        rows = session.query(Feedback).filter(Feedback.run_id == run_id).all()
        data = [{'chemical': f.chemical, 'verdict': f.verdict, 'user_name': f.user_name,
                 'suggested_tier': f.suggested_tier, 'expected_duration': f.expected_duration,
                 'comment': f.comment,
                 'created_at': f.created_at.strftime('%Y-%m-%d %H:%M') if f.created_at else ''}
                for f in rows]
    finally:
        session.close()
    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    tmp.close()
    write_feedback_workbook(data, tmp.name)
    return FileResponse(tmp.name, filename=f'ATT_Feedback_Run{run_id}.xlsx',
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ══════════════════════════════════════════════════════════════
# Exports (workbook + PDF report)
# ══════════════════════════════════════════════════════════════
@app.get('/api/runs/{run_id}/export')
def export_run(run_id: int):
    path = os.path.join(runner.run_dir(run_id), 'ATT_Results.xlsx')
    if not os.path.exists(path):
        raise HTTPException(404, 'Export workbook not found — run may not be complete')
    return FileResponse(path, filename=f'ATT_Results_Run{run_id}.xlsx',
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.get('/api/runs/{run_id}/report.pdf')
def export_pdf(run_id: int):
    from .report import build_pdf_report
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if not run or run.status != 'done':
            raise HTTPException(404, 'Run not found or not complete')
        chems = (session.query(ChemicalScore)
                 .filter(ChemicalScore.run_id == run_id)
                 .order_by(ChemicalScore.att_final.desc()).all())
        prev = _prev_done_run(session, run)
        movers, prev_name = [], ''
        if prev and run.kind == 'chemical':
            movers, _, _ = _movers(session, run_id, prev.id, limit=12)
            prev_name = f'#{prev.id} {prev.name}'
        out = os.path.join(runner.run_dir(run_id), 'ATT_Summary.pdf')
        build_pdf_report(run, chems, movers, prev_name, out)
    finally:
        session.close()
    return FileResponse(out, filename=f'ATT_Summary_Run{run_id}.pdf',
                        media_type='application/pdf')


# ══════════════════════════════════════════════════════════════
# Settings + changelog + weight preview + LLM test
# ══════════════════════════════════════════════════════════════
@app.get('/api/config')
def get_config():
    """Legacy endpoint kept for the upload page."""
    llm = settings.get('llm', {})
    return {'llm': {'provider': llm.get('provider', 'off'),
                    'model': llm.get('model', ''),
                    'has_key': bool(llm.get('api_key'))},
            'default_trend_exclude': settings.get('trend_exclude_default', DEFAULT_TREND_EXCLUDE)}


@app.get('/api/settings')
def get_settings():
    return settings.public_view()


class SettingsIn(BaseModel):
    changes: dict
    user_name: str = ''


@app.put('/api/settings')
def put_settings(body: SettingsIn):
    weights = body.changes.get('weights')
    if weights is not None:
        try:
            total = sum(float(v) for v in weights.values())
        except Exception:
            raise HTTPException(400, 'weights must be numeric')
        if abs(total - 1.0) > 0.001:
            raise HTTPException(400, f'weights must sum to 1.0 (got {total:.3f})')
    settings.update(body.changes, body.user_name)
    return settings.public_view()


@app.get('/api/settings/log')
def settings_log():
    return settings.change_log()


class LlmTestIn(BaseModel):
    provider: str = ''
    api_key: str = ''
    model: str = ''
    base_url: str = ''


@app.post('/api/settings/test-llm')
def test_llm(body: LlmTestIn):
    cfg = settings.get('llm', {})
    merged = {
        'provider': body.provider or cfg.get('provider', 'off'),
        'api_key': body.api_key or cfg.get('api_key', ''),
        'model': body.model or cfg.get('model', ''),
        'base_url': body.base_url or cfg.get('base_url', 'http://localhost:11434'),
    }
    m = LlmMatcher(merged, SessionLocal)
    if not m.enabled:
        return {'ok': False, 'error': 'Provider off or API key missing'}
    try:
        text = m._complete('Reply with exactly: OK')
        ok = 'OK' in (text or '').upper()
        return {'ok': ok, 'model': m.model,
                'error': '' if ok else f'Unexpected reply: {(text or "")[:120]}'}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


class AiTestIn(BaseModel):
    kind: str = 'llm'    # llm | search


@app.post('/api/settings/test-ai')
def test_ai(body: AiTestIn):
    """Test the shared AI provider pool (Groq/Gemini/Anthropic) or web search
    (Tavily/Firecrawl) with the currently saved keys."""
    try:
        if body.kind == 'search':
            from . import research as research_svc
            out = research_svc.web_search('MiniMines battery recycling India',
                                          max_results=2, use_cache=False)
            return {'ok': True, 'provider': out['provider'],
                    'results': len(out['results'])}
        from . import ai
        out = ai.complete('Reply with exactly: OK', use_cache=False, cache_ns='')
        return {'ok': 'OK' in (out['text'] or '').upper(),
                'provider': out['provider'], 'model': out['model']}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


# ══════════════════════════════════════════════════════════════
# Unified cache management
# ══════════════════════════════════════════════════════════════
@app.get('/api/cache/stats')
def cache_stats():
    return cache_svc.stats()


@app.post('/api/cache/clear')
def cache_clear(namespace: str = ''):
    return {'cleared': cache_svc.clear(namespace)}


class WeightPreviewIn(BaseModel):
    weights: dict
    tier_a_min: float = 70
    tier_b_min: float = 40


@app.post('/api/runs/{run_id}/preview-weights')
def preview_weights(run_id: int, body: WeightPreviewIn):
    """Live impact preview: recompute ATT from stored dimension norms with the
    proposed weights and return tier shifts + biggest movers — nothing is saved."""
    dims = ['volume', 'price', 'buyers', 'suppliers', 'trend', 'structure', 'freedom', 'barrier']
    w = {d: float(body.weights.get(d, 0)) for d in dims}
    session = SessionLocal()
    try:
        rows = session.query(ChemicalScore).filter(ChemicalScore.run_id == run_id).all()
        if not rows:
            raise HTTPException(404, 'No scores for this run')
        results = []
        for c in rows:
            norms = {'volume': c.volume_norm, 'price': c.price_norm, 'buyers': c.buyers_norm,
                     'suppliers': c.suppliers_norm, 'trend': c.trend_adjusted,
                     'structure': c.structure_norm, 'freedom': c.freedom_norm,
                     'barrier': c.barrier_norm}
            att_base = sum(w[d] * norms[d] for d in dims)
            att = max(0, min(100, att_base * (c.reg_factor or 1.0) + (c.variance_mod or 0)
                             + (c.feedback_adj or 0)))
            new_tier = ('A' if att >= body.tier_a_min else
                        ('B' if att >= body.tier_b_min else 'C'))
            results.append({'chemical': c.chemical, 'pool': c.pool,
                            'old_att': c.att_final, 'new_att': round(att, 2),
                            'old_tier': c.tier, 'new_tier': new_tier,
                            'delta': round(att - c.att_final, 2)})
        old_rank = {r['chemical']: i + 1 for i, r in enumerate(
            sorted(results, key=lambda x: -x['old_att']))}
        new_rank = {r['chemical']: i + 1 for i, r in enumerate(
            sorted(results, key=lambda x: -x['new_att']))}
        for r in results:
            r['old_rank'] = old_rank[r['chemical']]
            r['new_rank'] = new_rank[r['chemical']]
            r['rank_delta'] = old_rank[r['chemical']] - new_rank[r['chemical']]
        from collections import Counter
        old_tiers = Counter(r['old_tier'] for r in results)
        new_tiers = Counter(r['new_tier'] for r in results)
        movers = sorted(results, key=lambda x: -abs(x['delta']))[:20]
        return {'total': len(results),
                'old_tiers': dict(old_tiers), 'new_tiers': dict(new_tiers),
                'tier_changes': sum(1 for r in results if r['old_tier'] != r['new_tier']),
                'movers': movers}
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Static frontend (built React app)
# ══════════════════════════════════════════════════════════════
if os.path.isdir(FRONTEND_DIST):
    app.mount('/assets', StaticFiles(directory=os.path.join(FRONTEND_DIST, 'assets')), name='assets')

    @app.get('/{full_path:path}')
    def spa(full_path: str):
        candidate = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(FRONTEND_DIST, 'index.html'))
else:
    @app.get('/')
    def no_frontend():
        return JSONResponse({'message': 'ATT Platform API running. Frontend not built — run start.bat.'})
