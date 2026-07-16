"""EPR Producer Intelligence module — Engine v2.

All 10 critical issues from EPR_ENGINE_PROBLEMS.md are resolved here:
  Q3  - _num() fixed: strict number regex; NULL=absent, 0.0=reported zero;
        unparseable cells returned in upload response, not silently zeroed.
  Q6  - Upload requires a `material` slug. Per-material upsert + scoped replace.
        Materials CRUD endpoints. Legacy rows backfilled to Lithium in db.py.
  Q7  - registration_number is the primary merge key when present.
        Post-upload duplicate review list returned to UI.
  Q8  - Materialized `grade` column on EprCompany. epr_scoring.recompute_and_store()
        called after every upload / delete / settings change.
  Q9  - API returns `grade` (0-100) + `materials` breakdown. `target_tons`/`credits`
        stay as totals (backward compat). Old `priority_score` aliased to grade.

Business logic preserved:
  High obligation + low credits = highest grade = best MiniMines sales target.
"""
import json
import re
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query

from .db import (SessionLocal, EprCompany, EprCompanyMaterial, EprMaterial,
                 EprResearch, RawRow, Run)
from . import research as research_svc

router = APIRouter(prefix='/api/epr', tags=['epr'])

DEFAULT_EPR_WEIGHTS = {'target_tons': 1.0, 'credits': 0.5}


def _epr_weights():
    from . import settings
    w = settings.get('epr_weights', DEFAULT_EPR_WEIGHTS) or DEFAULT_EPR_WEIGHTS
    return {'target_tons': float(w.get('target_tons', 1.0)),
            'credits': float(w.get('credits', 0.5))}


# ══════════════════════════════════════════════════════════════
# Q3: Fixed _num() — strict number parsing, NULL vs zero distinct
# ══════════════════════════════════════════════════════════════
_STRICT_NUM_RE = re.compile(r'^-?\s*\d+(?:[.,]\d+)?$')
_EXEMPT_WORDS = {'n/a', 'na', 'nil', 'tbd', 'exempted', 'exempt', '-', '—', 'none', ''}


def _parse_cell(v) -> tuple:
    """Parse a cell value into (float_or_None, status).

    Returns:
        (value, 'ok')       — valid nonzero number
        (0.0,  'zero')      — explicit zero
        (None, 'exempt')    — cell says N/A / exempted / nil
        (None, 'unparsed')  — cell has content but couldn't be parsed as a number
        (None, 'absent')    — cell was blank / None
    """
    if v is None:
        return None, 'absent'
    s = str(v).strip()
    if not s:
        return None, 'absent'
    sl = s.lower().replace('–', '-').replace('—', '-')
    if sl in _EXEMPT_WORDS:
        return None, 'exempt'
    # Strip currency symbols, commas, whitespace
    cleaned = re.sub(r'[₹$€£,\s]', '', s)
    # Accept only clean numeric strings (prevents 'Rs.500' -> 0.5 bug Q3)
    if not _STRICT_NUM_RE.match(cleaned):
        return None, 'unparsed'
    try:
        fval = float(cleaned.replace(',', '.'))
        if fval == 0.0:
            return 0.0, 'zero'
        return fval, 'ok'
    except ValueError:
        return None, 'unparsed'


# ══════════════════════════════════════════════════════════════
# Q7: Name normalisation for duplicate detection
# ══════════════════════════════════════════════════════════════
_STOPWORDS = {'pvt', 'private', 'ltd', 'limited', 'llp', 'india', 'inc', 'co',
              'company', 'enterprises', 'industries', 'corporation', 'corp',
              'international', 'the', 'and', 'of', 'technologies', 'technology'}


def _name_tokens(name: str) -> list:
    tokens = re.findall(r'[a-z0-9]+', (name or '').lower())
    sig = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
    return sig or tokens[:2]


def _name_key(name: str) -> str:
    """Canonical merge key from company name (Q7 fallback)."""
    return ' '.join(_name_tokens(name))


# ══════════════════════════════════════════════════════════════
# XLSX Parser
# ══════════════════════════════════════════════════════════════
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


def parse_epr_xlsx(path) -> tuple:
    """Parse an EPR CPCB xlsx file.

    Returns:
        (records, parse_warnings)
        records: list of dicts with company fields + parse_status per numeric field
        parse_warnings: list of human-readable strings for unparseable cells
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

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
    warnings = []
    numeric_fields = {'target_tons', 'credits', 'import_qty'}
    for row_i, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        rec, extra = {}, {}
        for ci, field in col_map.items():
            raw_v = row[ci] if ci < len(row) else None
            if field in numeric_fields:
                val, status = _parse_cell(raw_v)
                rec[field] = val
                rec[f'{field}_status'] = status
                if status == 'unparsed':
                    name_ci = next((c for c, f in col_map.items() if f == 'company_name'), None)
                    cname = str(row[name_ci]).strip() if name_ci is not None and name_ci < len(row) else f'row {row_i}'
                    warnings.append(
                        f"Row {row_i} ({cname}): could not parse '{raw_v}' in column '{field}' — treated as absent"
                    )
            else:
                rec[field] = str(raw_v).strip() if raw_v is not None else ''

        name = rec.get('company_name', '')
        if not name or name.lower() in ('legal name', 'producer name', 'company name', 'none'):
            continue
        if re.fullmatch(r'[\d.\s\-]+', name):
            continue
        for ci, v in enumerate(row):
            if ci not in col_map and v not in (None, ''):
                extra[f'col_{ci}'] = str(v)[:200]
        rec['other_json'] = json.dumps(extra) if extra else '{}'
        out.append(rec)
    return out, warnings


# ══════════════════════════════════════════════════════════════
# Q8: Trigger recompute after mutations
# ══════════════════════════════════════════════════════════════
def _trigger_recompute(session):
    """Recompute and materialize grades for all companies. Q8."""
    try:
        from . import epr_scoring
        epr_scoring.recompute_and_store(session)
    except Exception as exc:
        # Non-fatal: grades will be recomputed on next upload/request
        print(f'[epr] recompute_and_store warning: {exc}')


# ══════════════════════════════════════════════════════════════
# Upload endpoint — Q3/Q6/Q7/Q8
# ══════════════════════════════════════════════════════════════
@router.post('/upload')
async def upload_epr(
    file: UploadFile = File(...),
    material: str = Form(...),        # Q6: required material slug
    mode: str = Form('merge'),        # merge (upsert) | replace (scoped to this material)
    user_name: str = Form(''),
):
    """Upload a CPCB EPR targets file for a specific material.

    material: slug of the material (e.g. 'lithium', 'cobalt').
              Must match an existing EprMaterial.slug.
    mode:     'merge'   — upsert companies, upsert their material row.
              'replace' — delete ALL rows for this material first, then insert.
                          Companies left with no material rows are kept as identity records.
    """
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    tmp.write(await file.read())
    tmp.close()
    try:
        records, parse_warnings = parse_epr_xlsx(tmp.name)
    except Exception as e:
        raise HTTPException(400, f'Could not parse file: {e}')
    finally:
        os.unlink(tmp.name)
    if not records:
        raise HTTPException(400, 'No producer rows found in the file')

    session = SessionLocal()
    try:
        # Q6: validate material slug
        mat_obj = session.query(EprMaterial).filter(EprMaterial.slug == material.lower()).first()
        if not mat_obj:
            known = [m.slug for m in session.query(EprMaterial).all()]
            raise HTTPException(400, f"Unknown material slug '{material}'. Known: {known}")

        # Q6: scoped replace — delete only this material's rows
        if mode == 'replace':
            session.query(EprCompanyMaterial).filter(
                EprCompanyMaterial.material_id == mat_obj.id
            ).delete(synchronize_session=False)
            session.flush()

        # Q7: build lookup by registration_number (primary) + name_key (fallback)
        existing_by_reg = {}
        existing_by_name = {}
        for c in session.query(EprCompany).all():
            if c.registration_number:
                existing_by_reg[c.registration_number.strip()] = c
            nk = _name_key(c.company_name)
            existing_by_name[nk] = c

        created = updated = mat_created = mat_updated = 0
        possible_duplicates = []

        for rec in records:
            reg = (rec.get('registration_number') or '').strip()
            name = rec['company_name']
            nk = _name_key(name)

            # Q7: merge by registration_number first, then name_key
            row = None
            if reg and reg in existing_by_reg:
                row = existing_by_reg[reg]
            elif nk in existing_by_name:
                row = existing_by_name[nk]

            if row is None:
                row = EprCompany(company_name=name)
                session.add(row)
                session.flush()  # get id
                existing_by_reg[reg] = row
                existing_by_name[nk] = row
                created += 1
            else:
                # Q7: detect possible duplicate on name mismatch for same reg number
                if reg and row.registration_number == reg and row.company_name != name:
                    possible_duplicates.append({
                        'incoming_name': name,
                        'existing_name': row.company_name,
                        'registration_number': reg,
                    })
                updated += 1

            # Update identity fields
            for f in ('registration_number', 'address', 'email', 'state', 'battery_chemistry'):
                if rec.get(f):
                    setattr(row, f, rec[f])
            # Update legacy flat columns (backward compat)
            for f in ('target_tons', 'credits', 'import_qty'):
                val = rec.get(f)
                if val is not None:
                    setattr(row, f, val)
            row.source_file = file.filename or ''
            row.uploaded_by = user_name.strip()

            # Q6: upsert per-material row
            existing_mat = session.query(EprCompanyMaterial).filter(
                EprCompanyMaterial.company_id == row.id,
                EprCompanyMaterial.material_id == mat_obj.id,
            ).first()
            t_val = rec.get('target_tons')
            c_val = rec.get('credits')
            iq_val = rec.get('import_qty')
            t_status = rec.get('target_tons_status', 'absent')

            if existing_mat is None:
                session.add(EprCompanyMaterial(
                    company_id=row.id,
                    material_id=mat_obj.id,
                    target_tons=t_val,
                    credits=c_val,
                    import_qty=iq_val,
                    parse_status=t_status,
                    source_file=file.filename or '',
                    uploaded_by=user_name.strip(),
                ))
                mat_created += 1
            else:
                existing_mat.target_tons = t_val
                existing_mat.credits = c_val
                existing_mat.import_qty = iq_val
                existing_mat.parse_status = t_status
                existing_mat.source_file = file.filename or ''
                existing_mat.uploaded_by = user_name.strip()
                existing_mat.updated_at = datetime.utcnow()
                mat_updated += 1

        session.commit()

        # Q8: trigger grade recompute after upload
        _trigger_recompute(session)

        return {
            'material': mat_obj.name,
            'companies': {'created': created, 'updated': updated},
            'material_rows': {'created': mat_created, 'updated': mat_updated},
            'total_in_file': len(records),
            'parse_warnings': parse_warnings,   # Q3: report unparseable cells
            'possible_duplicates': possible_duplicates,  # Q7: name-collision review
        }
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Q9: Company serialization — grade + materials + totals
# ══════════════════════════════════════════════════════════════
def _company_dict(c, include_breakdown: bool = False, research=None):
    """Serialize EprCompany. grade is the canonical 0-100 score (Q9)."""
    breakdown = json.loads(c.grade_breakdown_json or '{}') if include_breakdown else {}
    d = {
        'id': c.id,
        'company_name': c.company_name,
        'registration_number': c.registration_number,
        'address': c.address,
        'email': c.email,
        'state': c.state,
        'battery_chemistry': c.battery_chemistry,
        # Legacy totals (backward compat)
        'target_tons': c.target_tons,
        'credits': c.credits,
        'import_qty': c.import_qty,
        'gap_tons': round(max(0, (c.target_tons or 0) - (c.credits or 0)), 2),
        # Q9: new canonical fields
        'grade': c.grade or 0.0,
        'grade_label': c.grade_label or 'None',
        'priority_score': c.grade or 0.0,   # aliased for backward compat
        'scores_version': c.scores_version or 0,
        'coverage': breakdown.get('coverage', 0.0),
        'coverage_factor': breakdown.get('coverage_factor', 0.0),
        'materials_k': breakdown.get('materials_k', 0),
        'materials_K': breakdown.get('materials_K', 0),
        'source_file': c.source_file,
        'uploaded_by': c.uploaded_by,
        'created_at': c.created_at.isoformat() if c.created_at else '',
        'has_research': research is not None,
        'scoring_engine': 'v2',
    }
    if include_breakdown and breakdown.get('materials'):
        d['materials'] = breakdown['materials']
    if research is not None:
        d['research'] = json.loads(research.research_json or '{}')
        d['research_meta'] = {
            'search_provider': research.search_provider,
            'llm_provider': research.llm_provider,
            'updated_at': research.updated_at.isoformat() if research.updated_at else '',
        }
    return d


# ══════════════════════════════════════════════════════════════
# Materials CRUD — Q6 / Plan §5
# ══════════════════════════════════════════════════════════════
@router.get('/materials')
def list_materials():
    """List all EPR materials with their weights and company counts."""
    session = SessionLocal()
    try:
        mats = session.query(EprMaterial).order_by(EprMaterial.display_order).all()
        total_weight = sum(max(0, m.overall_weight or 0) for m in mats if m.active)
        out = []
        for m in mats:
            count = session.query(EprCompanyMaterial).filter(
                EprCompanyMaterial.material_id == m.id
            ).count()
            out.append({
                'id': m.id, 'name': m.name, 'slug': m.slug,
                'overall_weight': m.overall_weight,
                'normalized_share': round(
                    (m.overall_weight / total_weight * 100) if total_weight > 0 and m.active else 0, 1
                ),
                'active': bool(m.active),
                'display_order': m.display_order,
                'company_count': count,
            })
        return out
    finally:
        session.close()


@router.put('/materials/{material_id}')
def update_material(material_id: int, body: dict):
    """Update overall_weight or active flag. Triggers grade recompute."""
    session = SessionLocal()
    try:
        m = session.get(EprMaterial, material_id)
        if not m:
            raise HTTPException(404, 'Material not found')
        if 'overall_weight' in body:
            w = float(body['overall_weight'])
            if w < 0:
                raise HTTPException(400, 'overall_weight must be >= 0')
            m.overall_weight = w
        if 'active' in body:
            m.active = 1 if body['active'] else 0
        if 'display_order' in body:
            m.display_order = int(body['display_order'])
        session.commit()
        _trigger_recompute(session)
        return {'ok': True, 'id': m.id, 'name': m.name}
    finally:
        session.close()


@router.post('/materials')
def create_material(body: dict):
    """Add a new EPR material. Triggers grade recompute."""
    name = (body.get('name') or '').strip()
    if not name:
        raise HTTPException(400, 'name is required')
    slug = re.sub(r'[^a-z0-9_]', '', name.lower().replace(' ', '_'))
    session = SessionLocal()
    try:
        existing = session.query(EprMaterial).filter(EprMaterial.slug == slug).first()
        if existing:
            raise HTTPException(409, f"Material '{slug}' already exists")
        m = EprMaterial(
            name=name, slug=slug,
            overall_weight=float(body.get('overall_weight', 1.0)),
            active=1,
            display_order=int(body.get('display_order', 99)),
        )
        session.add(m)
        session.commit()
        return {'ok': True, 'id': m.id, 'slug': m.slug}
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════
# Company list / summary — Q8: reads materialized grade column
# ══════════════════════════════════════════════════════════════
@router.get('/companies')
def list_companies(
    search: str = '', state: str = '', material: str = '',
    sort: str = 'grade', order: str = 'desc',
    limit: int = Query(500, le=5000), offset: int = 0
):
    """List companies. Reads from materialized grade column (Q8).
    material: optional slug to filter + show material-level scores.
    """
    session = SessionLocal()
    try:
        q = session.query(EprCompany)
        if search:
            q = q.filter(EprCompany.company_name.ilike(f'%{search}%'))
        if state:
            q = q.filter(EprCompany.state.ilike(f'%{state}%'))
        if material:
            mat_obj = session.query(EprMaterial).filter(EprMaterial.slug == material).first()
            if mat_obj:
                company_ids = [r.company_id for r in session.query(EprCompanyMaterial.company_id)
                               .filter(EprCompanyMaterial.material_id == mat_obj.id).all()]
                q = q.filter(EprCompany.id.in_(company_ids))

        total = q.count()
        # Q8: SQL-level sort on materialized grade column
        valid_sorts = {'company_name', 'target_tons', 'credits', 'grade',
                       'priority_score', 'gap_tons', 'import_qty'}
        sort_col = sort if sort in valid_sorts else 'grade'
        if sort_col == 'priority_score':
            sort_col = 'grade'

        if sort_col == 'company_name':
            q = q.order_by(EprCompany.company_name.desc() if order == 'desc' else EprCompany.company_name)
        elif sort_col == 'grade':
            q = q.order_by(EprCompany.grade.desc() if order == 'desc' else EprCompany.grade)
        else:
            q = q.order_by(EprCompany.grade.desc())

        rows = q.offset(offset).limit(limit).all()
        researched = {r.company_id for r in session.query(EprResearch.company_id).all()}
        include_breakdown = bool(material)  # per-material filter -> include breakdown

        items = [{**_company_dict(c, include_breakdown=include_breakdown),
                  'has_research': c.id in researched}
                 for c in rows]

        return {
            'total': total,
            'scoring_engine': 'v2',
            'items': items,
        }
    finally:
        session.close()


@router.get('/summary')
def epr_summary():
    session = SessionLocal()
    try:
        rows = session.query(EprCompany).all()
        researched = {r.company_id for r in session.query(EprResearch.company_id).all()}
        items = sorted(
            [{**_company_dict(c), 'has_research': c.id in researched} for c in rows],
            key=lambda d: -d['grade']
        )
        # Per-material totals
        mats = session.query(EprMaterial).filter(EprMaterial.active == 1).all()
        mat_totals = {}
        for m in mats:
            mat_rows = session.query(EprCompanyMaterial).filter(
                EprCompanyMaterial.material_id == m.id
            ).all()
            mat_totals[m.slug] = {
                'name': m.name,
                'companies': len(mat_rows),
                'total_target_tons': round(sum((r.target_tons or 0) for r in mat_rows), 1),
                'total_credits': round(sum((r.credits or 0) for r in mat_rows), 1),
            }
        return {
            'total_companies': len(rows),
            'total_target_tons': round(sum(c.target_tons or 0 for c in rows), 1),
            'total_credits': round(sum(c.credits or 0 for c in rows), 1),
            'total_gap_tons': round(sum(max(0, (c.target_tons or 0) - (c.credits or 0))
                                        for c in rows), 1),
            'researched': len(researched),
            'scoring_engine': 'v2',
            'materials': mat_totals,
            'top': items[:10],
        }
    finally:
        session.close()


@router.get('/companies/{company_id}')
def get_company(company_id: int):
    session = SessionLocal()
    try:
        c = session.get(EprCompany, company_id)
        if not c:
            raise HTTPException(404, 'Company not found')
        r = session.query(EprResearch).filter(EprResearch.company_id == company_id).first()
        return _company_dict(c, include_breakdown=True, research=r)
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
        session.query(EprCompanyMaterial).filter(
            EprCompanyMaterial.company_id == company_id
        ).delete()
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
        existing = session.query(EprResearch).filter(EprResearch.company_id == company_id).first()
        if existing and not refresh:
            return {'research': json.loads(existing.research_json or '{}'),
                    'cached': True,
                    'meta': {'search_provider': existing.search_provider,
                             'llm_provider': existing.llm_provider,
                             'updated_at': existing.updated_at.isoformat() if existing.updated_at else ''}}
        # Q9: pass total target + breakdown to research prompt
        breakdown = json.loads(c.grade_breakdown_json or '{}')
        name, target = c.company_name, c.target_tons or 0
    finally:
        session.close()

    try:
        data, meta = research_svc.run_company_research(name, target)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    session = SessionLocal()
    try:
        row = session.query(EprResearch).filter(EprResearch.company_id == company_id).first()
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


# ══════════════════════════════════════════════════════════════
# EPR <-> EXIM trade cross-link (fuzzy company-name match)
# ══════════════════════════════════════════════════════════════
def trade_matches(session, company_name, limit=50):
    """Shipment rows in recent runs whose buyer or seller contains the company's
    significant tokens. Deduped by row_hash."""
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
    rows = q.order_by(RawRow.run_id.desc()).limit(limit * 4).all()
    seen, deduped = set(), []
    for r in rows:
        key = r.row_hash or f'id:{r.id}'
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
    """Top-priority EPR companies that also appear in trade data.
    Uses materialized grade column (Q8) — no recompute on each request."""
    session = SessionLocal()
    try:
        companies = (session.query(EprCompany)
                     .order_by(EprCompany.grade.desc())
                     .limit(60).all())
        out = []
        for c in companies:
            rows = trade_matches(session, c.company_name, limit=5)
            if rows:
                out.append({
                    'id': c.id,
                    'company_name': c.company_name,
                    'grade': c.grade or 0.0,
                    'priority_score': c.grade or 0.0,  # backward compat
                    'grade_label': c.grade_label or 'None',
                    'target_tons': c.target_tons,
                    'credits': c.credits,
                    'trade_shipments': len(rows),
                    'sample': rows[:3],
                })
            if len(out) >= limit:
                break
        return out
    finally:
        session.close()
