"""HSN Explorer module.

- Bundled open-licensed WCO Harmonized System directory (data/hsn_harmonized_system.csv,
  from the public datasets/harmonized-system repo) loaded into hsn_directory:
  2-digit chapters -> 4-digit headings -> 6-digit subheadings.
- Search codes by number or keyword; AI-assisted suggestions for mapping.
- Drill-down: picking a code lists its sub-types; selecting one shows OUR data
  (aggregated from uploaded EXIM rows) and the EXTERNAL directory info, badged.
- hsn_map: curated code -> chemical / battery / other product mapping.
- Ranked buyer/supplier lead lists per code.
"""
import csv
import json
import os
import re
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .db import SessionLocal, HsnCode, HsnMap, RawRow, Run, ChemicalScore, DATA_DIR

router = APIRouter(prefix='/api/hsn', tags=['hsn'])

CSV_PATH = os.path.join(DATA_DIR, 'hsn_harmonized_system.csv')


def import_directory():
    """(Re)load the bundled CSV into hsn_directory. Returns row count."""
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f'Bundled dataset missing: {CSV_PATH}')
    session = SessionLocal()
    try:
        session.query(HsnCode).delete()
        n = 0
        with open(CSV_PATH, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                session.add(HsnCode(
                    hscode=row['hscode'].strip(),
                    description=row['description'].strip(),
                    section=row.get('section', ''),
                    parent=row.get('parent', ''),
                    level=int(row.get('level') or len(row['hscode'].strip())),
                ))
                n += 1
        session.commit()
        return n
    finally:
        session.close()


def ensure_directory():
    session = SessionLocal()
    try:
        if session.query(HsnCode).first() is None:
            try:
                n = import_directory()
                print(f'[hsn] loaded {n} codes from bundled dataset')
            except Exception as e:
                print(f'[hsn] directory load failed: {e}')
    finally:
        session.close()


def _latest_run_ids(session, per_kind=1):
    """Latest completed run id per kind — avoids double-counting shipments
    that appear in several historical runs."""
    ids = []
    for kind in ('chemical', 'battery'):
        r = (session.query(Run).filter(Run.status == 'done', Run.kind == kind)
             .order_by(Run.id.desc()).first())
        if r:
            ids.append(r.id)
    return ids


def _our_codes(session, run_ids):
    """Set of 6-digit codes present in our uploaded data + shipment counts."""
    from sqlalchemy import func
    if not run_ids:
        return {}
    rows = (session.query(RawRow.hsn6, func.count(RawRow.id))
            .filter(RawRow.run_id.in_(run_ids))
            .group_by(RawRow.hsn6).all())
    return {(c or '').strip()[:6]: n for c, n in rows if c}


def _code_dict(row, our, maps):
    code = row.hscode
    return {'hscode': code, 'description': row.description, 'level': row.level,
            'section': row.section, 'parent': row.parent,
            'in_our_data': code in our, 'our_shipments': our.get(code, 0),
            'mapped': maps.get(code, [])}


def _maps_by_code(session):
    out = defaultdict(list)
    for m in session.query(HsnMap).all():
        out[m.hscode].append({'id': m.id, 'label': m.label, 'map_type': m.map_type,
                              'is_our_product': bool(m.is_our_product), 'notes': m.notes})
    return out


@router.get('/search')
def search(q: str = '', limit: int = Query(60, le=300)):
    """Search by code prefix (digits) or keyword (text). Results flagged with
    whether they appear in OUR uploaded data and any product mappings."""
    session = SessionLocal()
    try:
        query = session.query(HsnCode)
        q = q.strip()
        if q:
            if re.fullmatch(r'\d{1,8}', q):
                query = query.filter(HsnCode.hscode.like(f'{q[:6]}%'))
            else:
                for word in q.split()[:4]:
                    query = query.filter(HsnCode.description.ilike(f'%{word}%'))
        rows = query.order_by(HsnCode.hscode).limit(limit).all()
        our = _our_codes(session, _latest_run_ids(session))
        maps = _maps_by_code(session)
        return [_code_dict(r, our, maps) for r in rows]
    finally:
        session.close()


@router.get('/tree')
def tree(code: str = ''):
    """Drill-down: no code -> 2-digit chapters; a code -> its children
    (each flagged in_our_data so 'ours vs external' is visible at every level)."""
    session = SessionLocal()
    try:
        code = code.strip()
        if not code:
            rows = session.query(HsnCode).filter(HsnCode.level == 2).order_by(HsnCode.hscode).all()
            node = None
        else:
            node = session.query(HsnCode).filter(HsnCode.hscode == code).first()
            rows = (session.query(HsnCode).filter(HsnCode.parent == code)
                    .order_by(HsnCode.hscode).all())
        our = _our_codes(session, _latest_run_ids(session))
        # roll shipment counts up to parents
        rolled = dict(our)
        for c6, n in our.items():
            for plen in (4, 2):
                rolled[c6[:plen]] = rolled.get(c6[:plen], 0) + n
        maps = _maps_by_code(session)
        def d(r):
            out = _code_dict(r, our, maps)
            out['in_our_data'] = rolled.get(r.hscode, 0) > 0
            out['our_shipments'] = rolled.get(r.hscode, 0)
            return out
        return {'node': d(node) if node else None, 'children': [d(r) for r in rows]}
    finally:
        session.close()


@router.get('/code/{code}/data')
def code_data(code: str):
    """Everything about one code: EXTERNAL directory info (badged 'external')
    + OUR data (badged 'ours'): monthly trends, top buyers/suppliers, prices."""
    code = code.strip()
    session = SessionLocal()
    try:
        node = session.query(HsnCode).filter(HsnCode.hscode == code).first()
        run_ids = _latest_run_ids(session)
        q = session.query(RawRow).filter(RawRow.run_id.in_(run_ids)) if run_ids else None
        rows = (q.filter(RawRow.hsn6.like(f'{code}%')).all() if q is not None else [])

        monthly = defaultdict(lambda: {'shipments': 0, 'qty_kg': 0.0, 'value_usd': 0.0})
        buyers = defaultdict(lambda: {'shipments': 0, 'qty_kg': 0.0, 'value_usd': 0.0, 'country': ''})
        sellers = defaultdict(lambda: {'shipments': 0, 'qty_kg': 0.0, 'value_usd': 0.0, 'country': ''})
        prices = []
        for r in rows:
            month = (r.date or '')[:7]
            if month:
                m = monthly[month]
                m['shipments'] += 1
                m['qty_kg'] += r.qty_kg or 0
                m['value_usd'] += r.value_usd or 0
            if r.buyer:
                b = buyers[r.buyer]
                b['shipments'] += 1; b['qty_kg'] += r.qty_kg or 0
                b['value_usd'] += r.value_usd or 0; b['country'] = r.buyer_country or b['country']
            if r.seller:
                s = sellers[r.seller]
                s['shipments'] += 1; s['qty_kg'] += r.qty_kg or 0
                s['value_usd'] += r.value_usd or 0; s['country'] = r.seller_country or s['country']
            if r.unit_price:
                prices.append(r.unit_price)
        prices.sort()
        maps = _maps_by_code(session)
        top = lambda d: sorted(({'name': k, **v} for k, v in d.items()),
                               key=lambda x: -x['value_usd'])[:15]
        return {
            'external': ({'hscode': node.hscode, 'description': node.description,
                          'section': node.section, 'level': node.level,
                          'source': 'WCO Harmonized System (bundled open dataset)'}
                         if node else None),
            'mapped': maps.get(code, []),
            'ours': {
                'shipments': len(rows),
                'qty_kg': round(sum(r.qty_kg or 0 for r in rows), 1),
                'value_usd': round(sum(r.value_usd or 0 for r in rows), 0),
                'median_price': prices[len(prices) // 2] if prices else 0,
                'monthly': [{'month': k, **v} for k, v in sorted(monthly.items())],
                'top_buyers': top(buyers),
                'top_suppliers': top(sellers),
            },
        }
    finally:
        session.close()


@router.get('/code/{code}/leads')
def code_leads(code: str, role: str = 'buyer', limit: int = Query(50, le=500)):
    """Ranked counterparty lead list for one HSN code (exportable, add-as-lead)."""
    session = SessionLocal()
    try:
        run_ids = _latest_run_ids(session)
        if not run_ids:
            return {'items': []}
        rows = (session.query(RawRow)
                .filter(RawRow.run_id.in_(run_ids), RawRow.hsn6.like(f'{code.strip()}%'))
                .all())
        agg = defaultdict(lambda: {'shipments': 0, 'qty_kg': 0.0, 'value_usd': 0.0,
                                   'country': '', 'last_date': ''})
        for r in rows:
            name = r.buyer if role == 'buyer' else r.seller
            if not name:
                continue
            a = agg[name]
            a['shipments'] += 1
            a['qty_kg'] += r.qty_kg or 0
            a['value_usd'] += r.value_usd or 0
            a['country'] = (r.buyer_country if role == 'buyer' else r.seller_country) or a['country']
            a['last_date'] = max(a['last_date'], r.date or '')
        items = sorted(({'name': k, **v, 'value_usd': round(v['value_usd']),
                         'qty_kg': round(v['qty_kg'], 1)} for k, v in agg.items()),
                       key=lambda x: -x['value_usd'])[:limit]
        return {'code': code, 'role': role, 'items': items}
    finally:
        session.close()


# ── mapping CRUD + seeding + AI suggestion ────────────────────────────────
class MapIn(BaseModel):
    hscode: str
    label: str
    map_type: str = 'chemical'   # chemical | battery | other
    is_our_product: bool = True
    notes: str = ''
    user_name: str = ''


@router.get('/map')
def list_map(map_type: str = '', q: str = ''):
    session = SessionLocal()
    try:
        query = session.query(HsnMap)
        if map_type:
            query = query.filter(HsnMap.map_type == map_type)
        if q:
            query = query.filter((HsnMap.label.ilike(f'%{q}%')) | (HsnMap.hscode.like(f'{q}%')))
        rows = query.order_by(HsnMap.label).all()
        codes = {r.hscode for r in rows}
        descs = {c.hscode: c.description for c in
                 session.query(HsnCode).filter(HsnCode.hscode.in_(codes)).all()} if codes else {}
        return [{'id': m.id, 'hscode': m.hscode, 'label': m.label,
                 'map_type': m.map_type, 'is_our_product': bool(m.is_our_product),
                 'notes': m.notes, 'created_by': m.created_by,
                 'description': descs.get(m.hscode, '')} for m in rows]
    finally:
        session.close()


@router.post('/map')
def add_map(body: MapIn):
    if body.map_type not in ('chemical', 'battery', 'other'):
        raise HTTPException(400, 'map_type must be chemical | battery | other')
    session = SessionLocal()
    try:
        m = HsnMap(hscode=body.hscode.strip(), label=body.label.strip(),
                   map_type=body.map_type, is_our_product=int(body.is_our_product),
                   notes=body.notes, created_by=body.user_name.strip())
        session.add(m)
        session.commit()
        return {'id': m.id}
    finally:
        session.close()


@router.delete('/map/{map_id}')
def delete_map(map_id: int):
    session = SessionLocal()
    try:
        m = session.get(HsnMap, map_id)
        if not m:
            raise HTTPException(404, 'Mapping not found')
        session.delete(m)
        session.commit()
        return {'ok': True}
    finally:
        session.close()


@router.post('/map/seed')
def seed_map(user_name: str = ''):
    """Seed chemical mappings from the latest run's per-chemical HSN codes."""
    session = SessionLocal()
    try:
        run = (session.query(Run).filter(Run.status == 'done', Run.kind == 'chemical')
               .order_by(Run.id.desc()).first())
        if not run:
            raise HTTPException(404, 'No completed chemical run to seed from')
        existing = {(m.hscode, m.label) for m in session.query(HsnMap).all()}
        added = 0
        for c in (session.query(ChemicalScore)
                  .filter(ChemicalScore.run_id == run.id, ChemicalScore.pool == 'base').all()):
            for code in (c.hsn_codes or '').split(','):
                code = code.strip()[:6]
                if code and (code, c.chemical) not in existing:
                    session.add(HsnMap(hscode=code, label=c.chemical, map_type='chemical',
                                       is_our_product=1, created_by=user_name.strip() or 'seed'))
                    existing.add((code, c.chemical))
                    added += 1
        session.commit()
        return {'added': added, 'from_run': run.id}
    finally:
        session.close()


@router.get('/suggest')
def suggest(q: str):
    """AI-assisted 'find the HSN code for X' — keyword-matches the directory
    first, then asks the configured LLM to pick the best codes. Cached."""
    from . import ai
    q = q.strip()
    if not q:
        raise HTTPException(400, 'q required')
    session = SessionLocal()
    try:
        words = [w for w in re.findall(r'[a-z]+', q.lower()) if len(w) > 2][:4]
        query = session.query(HsnCode).filter(HsnCode.level == 6)
        cands = []
        for w in words:
            cands += query.filter(HsnCode.description.ilike(f'%{w}%')).limit(40).all()
        seen, candidates = set(), []
        for c in cands:
            if c.hscode not in seen:
                seen.add(c.hscode)
                candidates.append(c)
    finally:
        session.close()
    if not candidates:
        return {'suggestions': [], 'note': 'No directory keyword matches'}
    listing = '\n'.join(f'{c.hscode}: {c.description}' for c in candidates[:80])
    prompt = (f"Which Harmonized System (HSN) codes best match the product '{q}'?\n"
              f"Choose ONLY from this list:\n{listing}\n\n"
              'Reply with a JSON object: {"codes": [{"hscode": "...", "reason": "one short sentence"}]} '
              'with at most 5 codes, best first.')
    try:
        data, meta = ai.complete_json(prompt, cache_ns='hsn_external')
        valid = {c.hscode: c.description for c in candidates}
        out = [{'hscode': s.get('hscode', ''), 'reason': s.get('reason', ''),
                'description': valid.get(s.get('hscode', ''), '')}
               for s in (data.get('codes') or []) if s.get('hscode') in valid]
        return {'suggestions': out, 'provider': meta.get('provider', ''),
                'fallback': [{'hscode': c.hscode, 'description': c.description}
                             for c in candidates[:10]]}
    except RuntimeError:
        return {'suggestions': [], 'note': 'No AI provider configured — showing keyword matches',
                'fallback': [{'hscode': c.hscode, 'description': c.description}
                             for c in candidates[:15]]}


@router.post('/import')
def reimport():
    try:
        n = import_directory()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {'imported': n}
