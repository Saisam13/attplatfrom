"""EPR Producer Intelligence module (ported from the eprintelligence PHP app).

Upload CPCB 'EPR Targets for Producers' xlsx -> ranked companies by priority
score -> per-company AI sourcing-agent research -> fuzzy cross-link to the
EXIM trade data already in the platform.
"""
import json
import re
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query

from .db import SessionLocal, EprCompany, EprResearch, RawRow, Run
from . import research as research_svc

router = APIRouter(prefix='/api/epr', tags=['epr'])

DEFAULT_EPR_WEIGHTS = {'target_tons': 1.0, 'credits': 0.5}

# Column-header keywords -> field (header row is auto-detected)
_HEADER_MAP = [
    (('producer name', 'company name', 'company', 'producer'), 'company_name'),
    (('registration',), 'registration_number'),
    (('address',), 'address'),
    (('email', 'e-mail'), 'email'),
    (('state',), 'state'),
    (('chemistry',), 'battery_chemistry'),
    (('target',), 'target_tons'),
    (('credit',), 'credits'),
    (('import',), 'import_qty'),
]
_NUMERIC_FIELDS = {'target_tons', 'credits', 'import_qty'}


def _epr_weights():
    from . import settings
    w = settings.get('epr_weights', DEFAULT_EPR_WEIGHTS) or DEFAULT_EPR_WEIGHTS
    return {'target_tons': float(w.get('target_tons', 1.0)),
            'credits': float(w.get('credits', 0.5))}


def _num(v):
    if v is None:
        return 0.0
    s = re.sub(r'[^0-9.\-]', '', str(v))
    try:
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def parse_epr_xlsx(path):
    """Header-detecting parser: finds the row containing a company/producer-name
    header, maps columns by keyword, yields dict rows."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Score every candidate row and keep the one that maps the MOST fields —
    # title rows like 'Status of EPR Targets for Producers…' match one keyword
    # but a real header row maps several columns.
    header_idx, col_map, best_score = None, {}, 0
    for i, row in enumerate(rows[:12]):
        cells = [str(c).strip().lower() if c is not None else '' for c in row]
        mapping = {}
        for ci, cell in enumerate(cells):
            if not cell:
                continue
            for keywords, field in _HEADER_MAP:
                if field not in mapping.values() and any(k in cell for k in keywords):
                    mapping[ci] = field
                    break
        if 'company_name' in mapping.values() and len(mapping) > best_score:
            header_idx, col_map, best_score = i, mapping, len(mapping)
    if header_idx is None or best_score < 2:
        raise ValueError("Could not find a header row with a 'Producer/Company Name' column")

    out = []
    for row in rows[header_idx + 1:]:
        rec, extra = {}, {}
        for ci, field in col_map.items():
            v = row[ci] if ci < len(row) else None
            rec[field] = _num(v) if field in _NUMERIC_FIELDS else (str(v).strip() if v is not None else '')
        name = rec.get('company_name', '')
        if not name or name.lower() in ('legal name', 'producer name', 'company name', 'none'):
            continue
        if re.fullmatch(r'[\d.\s-]+', name):
            continue  # pure-numeric cell (repeated SNo header blocks etc.)
        # keep unmapped non-empty cells for reference
        for ci, v in enumerate(row):
            if ci not in col_map and v not in (None, ''):
                extra[f'col_{ci}'] = str(v)[:200]
        rec['other_json'] = json.dumps(extra) if extra else '{}'
        out.append(rec)
    return out


@router.post('/upload')
async def upload_epr(file: UploadFile = File(...), mode: str = Form('merge'),
                     user_name: str = Form('')):
    """mode: merge (upsert by company name) | replace (wipe table first)."""
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    tmp.write(await file.read())
    tmp.close()
    try:
        records = parse_epr_xlsx(tmp.name)
    except Exception as e:
        raise HTTPException(400, f'Could not parse file: {e}')
    finally:
        os.unlink(tmp.name)
    if not records:
        raise HTTPException(400, 'No producer rows found in the file')

    session = SessionLocal()
    try:
        if mode == 'replace':
            session.query(EprCompany).delete()
        existing = {c.company_name.strip().lower(): c
                    for c in session.query(EprCompany).all()}
        created = updated = 0
        for rec in records:
            key = rec['company_name'].strip().lower()
            row = existing.get(key)
            if row is None:
                row = EprCompany(company_name=rec['company_name'])
                session.add(row)
                existing[key] = row
                created += 1
            else:
                updated += 1
            for f in ('registration_number', 'address', 'email', 'state',
                      'battery_chemistry'):
                if rec.get(f):
                    setattr(row, f, rec[f])
            for f in ('target_tons', 'credits', 'import_qty'):
                if f in rec:
                    setattr(row, f, rec[f])
            row.other_json = rec.get('other_json', '{}')
            row.source_file = file.filename or ''
            row.uploaded_by = user_name.strip()
        session.commit()
        return {'created': created, 'updated': updated, 'total_in_file': len(records)}
    finally:
        session.close()


def _priority(c, w):
    return round((c.target_tons or 0) * w['target_tons'] + (c.credits or 0) * w['credits'], 2)


def _company_dict(c, w, research=None):
    d = {
        'id': c.id, 'company_name': c.company_name,
        'registration_number': c.registration_number, 'address': c.address,
        'email': c.email, 'state': c.state, 'battery_chemistry': c.battery_chemistry,
        'target_tons': c.target_tons, 'credits': c.credits, 'import_qty': c.import_qty,
        'priority_score': _priority(c, w),
        'gap_tons': round(max(0, (c.target_tons or 0) - (c.credits or 0)), 2),
        'source_file': c.source_file, 'uploaded_by': c.uploaded_by,
        'created_at': c.created_at.isoformat() if c.created_at else '',
        'has_research': research is not None,
    }
    if research is not None:
        d['research'] = json.loads(research.research_json or '{}')
        d['research_meta'] = {
            'search_provider': research.search_provider,
            'llm_provider': research.llm_provider,
            'updated_at': research.updated_at.isoformat() if research.updated_at else '',
        }
    return d


@router.get('/companies')
def list_companies(search: str = '', state: str = '', sort: str = 'priority_score',
                   order: str = 'desc', limit: int = Query(500, le=5000), offset: int = 0):
    w = _epr_weights()
    session = SessionLocal()
    try:
        q = session.query(EprCompany)
        if search:
            q = q.filter(EprCompany.company_name.ilike(f'%{search}%'))
        if state:
            q = q.filter(EprCompany.state.ilike(f'%{state}%'))
        total = q.count()
        rows = q.all()
        researched = {r.company_id for r in session.query(EprResearch.company_id).all()}
        items = [{**_company_dict(c, w), 'has_research': c.id in researched} for c in rows]
        key = sort if sort in ('company_name', 'target_tons', 'credits', 'priority_score',
                               'gap_tons', 'import_qty') else 'priority_score'
        items.sort(key=lambda d: (d[key] if isinstance(d[key], (int, float)) else str(d[key]).lower()),
                   reverse=(order == 'desc'))
        return {'total': total, 'weights': w, 'items': items[offset:offset + limit]}
    finally:
        session.close()


@router.get('/summary')
def epr_summary():
    w = _epr_weights()
    session = SessionLocal()
    try:
        rows = session.query(EprCompany).all()
        researched = {r.company_id for r in session.query(EprResearch.company_id).all()}
        items = sorted(({**_company_dict(c, w), 'has_research': c.id in researched}
                        for c in rows), key=lambda d: -d['priority_score'])
        return {
            'total_companies': len(rows),
            'total_target_tons': round(sum(c.target_tons or 0 for c in rows), 1),
            'total_credits': round(sum(c.credits or 0 for c in rows), 1),
            'total_gap_tons': round(sum(max(0, (c.target_tons or 0) - (c.credits or 0))
                                        for c in rows), 1),
            'researched': len(researched),
            'top': items[:10],
        }
    finally:
        session.close()


@router.get('/companies/{company_id}')
def get_company(company_id: int):
    w = _epr_weights()
    session = SessionLocal()
    try:
        c = session.get(EprCompany, company_id)
        if not c:
            raise HTTPException(404, 'Company not found')
        r = (session.query(EprResearch)
             .filter(EprResearch.company_id == company_id).first())
        return _company_dict(c, w, research=r)
    finally:
        session.close()


@router.delete('/companies/{company_id}')
def delete_company(company_id: int):
    session = SessionLocal()
    try:
        c = session.get(EprCompany, company_id)
        if not c:
            raise HTTPException(404, 'Company not found')
        session.query(EprResearch).filter(EprResearch.company_id == company_id).delete()
        session.delete(c)
        session.commit()
        return {'ok': True}
    finally:
        session.close()


@router.post('/companies/{company_id}/research')
def research_company(company_id: int, refresh: bool = False):
    session = SessionLocal()
    try:
        c = session.get(EprCompany, company_id)
        if not c:
            raise HTTPException(404, 'Company not found')
        existing = (session.query(EprResearch)
                    .filter(EprResearch.company_id == company_id).first())
        if existing and not refresh:
            return {'research': json.loads(existing.research_json or '{}'),
                    'cached': True,
                    'meta': {'search_provider': existing.search_provider,
                             'llm_provider': existing.llm_provider,
                             'updated_at': existing.updated_at.isoformat() if existing.updated_at else ''}}
        name, target = c.company_name, c.target_tons or 0
    finally:
        session.close()

    try:
        data, meta = research_svc.run_company_research(name, target)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    session = SessionLocal()
    try:
        row = (session.query(EprResearch)
               .filter(EprResearch.company_id == company_id).first())
        if row is None:
            row = EprResearch(company_id=company_id)
            session.add(row)
        row.research_json = json.dumps(data)
        row.search_provider = meta['search_provider']
        row.llm_provider = meta['llm_provider']
        row.updated_at = datetime.utcnow()
        session.commit()
        return {'research': data, 'cached': False, 'meta': meta}
    finally:
        session.close()


# ── EPR <-> EXIM trade cross-link (fuzzy company-name match) ──────────────
_STOPWORDS = {'pvt', 'private', 'ltd', 'limited', 'llp', 'india', 'inc', 'co',
              'company', 'enterprises', 'industries', 'corporation', 'corp',
              'international', 'the', 'and', 'of', 'technologies', 'technology'}


def _name_tokens(name):
    tokens = re.findall(r'[a-z0-9]+', (name or '').lower())
    sig = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
    return sig or tokens[:2]


def trade_matches(session, company_name, limit=50):
    """Shipment rows in the most recent completed runs whose buyer or seller
    contains the significant tokens of the company name. Deduped by row_hash
    (R7) — the same physical shipment can appear in more than one of the last
    4 runs (overlapping monthly extracts, accidental re-uploads) and would
    otherwise be double/triple/quadruple counted here and in the cross-links
    summary."""
    tokens = _name_tokens(company_name)[:3]
    if not tokens:
        return []
    run_ids = [r.id for r in (session.query(Run)
                              .filter(Run.status == 'done')
                              .order_by(Run.id.desc()).limit(4).all())]
    if not run_ids:
        return []
    q = session.query(RawRow).filter(RawRow.run_id.in_(run_ids))
    for t in tokens:
        q = q.filter((RawRow.buyer.ilike(f'%{t}%')) | (RawRow.seller.ilike(f'%{t}%')))
    # over-fetch then dedupe — up to 4x the rows could be the same shipment
    rows = q.order_by(RawRow.run_id.desc()).limit(limit * 4).all()
    seen, deduped = set(), []
    for r in rows:
        key = r.row_hash or f'id:{r.id}'  # rows predating the row_hash backfill degrade to no-dedup
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
        if len(deduped) >= limit:
            break
    return [{'run_id': r.run_id, 'date': r.date, 'hsn6': r.hsn6,
             'desc_clean': (r.desc_clean or '')[:160], 'chemical': r.chemical,
             'seller': r.seller, 'seller_country': r.seller_country,
             'buyer': r.buyer, 'buyer_country': r.buyer_country,
             'qty_kg': r.qty_kg, 'value_usd': r.value_usd,
             'unit_price': r.unit_price} for r in deduped]


@router.get('/companies/{company_id}/trade')
def company_trade(company_id: int, limit: int = Query(50, le=500)):
    session = SessionLocal()
    try:
        c = session.get(EprCompany, company_id)
        if not c:
            raise HTTPException(404, 'Company not found')
        rows = trade_matches(session, c.company_name, limit)
        return {'company': c.company_name, 'matches': len(rows), 'items': rows}
    finally:
        session.close()


@router.get('/cross-links')
def cross_links(limit: int = Query(8, le=25)):
    """Top-priority EPR companies that also appear in the trade data — the
    'both worlds' section shown on the home dashboard and in the EPR module."""
    w = _epr_weights()
    session = SessionLocal()
    try:
        companies = sorted(session.query(EprCompany).all(),
                           key=lambda c: -_priority(c, w))
        out = []
        for c in companies[:60]:
            rows = trade_matches(session, c.company_name, limit=5)
            if rows:
                out.append({'id': c.id, 'company_name': c.company_name,
                            'priority_score': _priority(c, w),
                            'target_tons': c.target_tons, 'credits': c.credits,
                            'trade_shipments': len(rows), 'sample': rows[:3]})
            if len(out) >= limit:
                break
        return out
    finally:
        session.close()
