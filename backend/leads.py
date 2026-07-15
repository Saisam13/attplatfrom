"""Universal lead tracker — one pipeline for chemical, EPR, battery and other
leads, tagged by user/type/stage, with a timestamped event timeline that links
snapshots of the data the lead came from. Everything is also exposed through
the read-only external API (/api/v1/leads, X-API-Key protected).
"""
import json
import secrets
from datetime import datetime, date

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .db import SessionLocal, Lead, LeadEvent, ApiKey

router = APIRouter(prefix='/api/leads', tags=['leads'])
keys_router = APIRouter(prefix='/api/keys', tags=['api-keys'])
v1_router = APIRouter(prefix='/api/v1', tags=['external-v1'])

LEAD_TYPES = ('chemical', 'epr', 'battery', 'other')
STAGES = ('new', 'contacted', 'in_talks', 'deal', 'dead')


# ── internal CRUD ─────────────────────────────────────────────────────────
class LeadIn(BaseModel):
    name: str
    lead_type: str = 'other'
    stage: str = 'new'
    owner: str = ''
    tags: str = ''
    source: str = 'manual'
    entity_kind: str = ''
    entity_ref: str = ''
    hsn_code: str = ''
    country: str = ''
    contact_name: str = ''
    contact_email: str = ''
    contact_phone: str = ''
    next_followup: str = ''
    data: dict = {}          # snapshot of the row/company this lead came from
    user_name: str = ''


class LeadPatch(BaseModel):
    stage: str = ''
    owner: str = ''
    tags: str = ''
    next_followup: str = ''
    contact_name: str = ''
    contact_email: str = ''
    contact_phone: str = ''
    country: str = ''
    user_name: str = ''


class EventIn(BaseModel):
    kind: str = 'note'       # note | link
    text: str = ''
    data: dict = {}
    user_name: str = ''


def _lead_dict(l, events=None):
    d = {'id': l.id, 'name': l.name, 'lead_type': l.lead_type, 'stage': l.stage,
         'owner': l.owner, 'tags': l.tags, 'source': l.source,
         'entity_kind': l.entity_kind, 'entity_ref': l.entity_ref,
         'hsn_code': l.hsn_code, 'country': l.country,
         'contact_name': l.contact_name, 'contact_email': l.contact_email,
         'contact_phone': l.contact_phone, 'next_followup': l.next_followup,
         'data': json.loads(l.data_json or '{}'), 'created_by': l.created_by,
         'created_at': l.created_at.isoformat() if l.created_at else '',
         'updated_at': l.updated_at.isoformat() if l.updated_at else ''}
    if events is not None:
        d['events'] = [_event_dict(e) for e in events]
    return d


def _event_dict(e):
    return {'id': e.id, 'kind': e.kind, 'text': e.text,
            'data': json.loads(e.data_json or '{}'), 'user_name': e.user_name,
            'created_at': e.created_at.isoformat() if e.created_at else ''}


def _add_event(session, lead_id, kind, text, data=None, user=''):
    session.add(LeadEvent(lead_id=lead_id, kind=kind, text=text,
                          data_json=json.dumps(data or {}), user_name=user.strip()))


@router.get('')
def list_leads(lead_type: str = '', stage: str = '', owner: str = '', tag: str = '',
               search: str = '', due: str = '', sort: str = 'updated_at',
               order: str = 'desc', limit: int = Query(500, le=5000), offset: int = 0):
    session = SessionLocal()
    try:
        q = session.query(Lead)
        if lead_type:
            q = q.filter(Lead.lead_type == lead_type)
        if stage:
            q = q.filter(Lead.stage == stage)
        if owner:
            q = q.filter(Lead.owner.ilike(f'%{owner}%'))
        if tag:
            q = q.filter(Lead.tags.ilike(f'%{tag}%'))
        if search:
            q = q.filter(Lead.name.ilike(f'%{search}%'))
        if due == 'today':
            q = q.filter(Lead.next_followup == date.today().isoformat())
        elif due == 'overdue':
            q = q.filter(Lead.next_followup != '', Lead.next_followup < date.today().isoformat(),
                         Lead.stage.notin_(('deal', 'dead')))
        elif due == 'upcoming':
            q = q.filter(Lead.next_followup >= date.today().isoformat())
        total = q.count()
        col = getattr(Lead, sort, Lead.updated_at)
        q = q.order_by(col.desc() if order == 'desc' else col.asc())
        rows = q.offset(offset).limit(limit).all()
        return {'total': total, 'items': [_lead_dict(l) for l in rows]}
    finally:
        session.close()


@router.get('/summary')
def leads_summary():
    session = SessionLocal()
    try:
        rows = session.query(Lead).all()
        today = date.today().isoformat()
        by_stage, by_type, by_owner = {}, {}, {}
        due_today = overdue = 0
        for l in rows:
            by_stage[l.stage] = by_stage.get(l.stage, 0) + 1
            by_type[l.lead_type] = by_type.get(l.lead_type, 0) + 1
            if l.owner:
                by_owner[l.owner] = by_owner.get(l.owner, 0) + 1
            if l.next_followup and l.stage not in ('deal', 'dead'):
                if l.next_followup == today:
                    due_today += 1
                elif l.next_followup < today:
                    overdue += 1
        return {'total': len(rows), 'by_stage': by_stage, 'by_type': by_type,
                'by_owner': by_owner, 'due_today': due_today, 'overdue': overdue}
    finally:
        session.close()


@router.post('')
def create_lead(body: LeadIn):
    if body.lead_type not in LEAD_TYPES:
        raise HTTPException(400, f'lead_type must be one of {LEAD_TYPES}')
    if body.stage not in STAGES:
        raise HTTPException(400, f'stage must be one of {STAGES}')
    session = SessionLocal()
    try:
        dup = (session.query(Lead)
               .filter(Lead.name == body.name.strip(), Lead.lead_type == body.lead_type)
               .first())
        if dup:
            return {'id': dup.id, 'existing': True}
        l = Lead(name=body.name.strip(), lead_type=body.lead_type, stage=body.stage,
                 owner=(body.owner or body.user_name).strip(), tags=body.tags.strip(),
                 source=body.source, entity_kind=body.entity_kind,
                 entity_ref=str(body.entity_ref), hsn_code=body.hsn_code,
                 country=body.country, contact_name=body.contact_name,
                 contact_email=body.contact_email, contact_phone=body.contact_phone,
                 next_followup=body.next_followup,
                 data_json=json.dumps(body.data or {}),
                 created_by=body.user_name.strip())
        session.add(l)
        session.flush()
        _add_event(session, l.id, 'created',
                   f'Lead created from {body.source}', body.data, body.user_name)
        session.commit()
        return {'id': l.id, 'existing': False}
    finally:
        session.close()


@router.get('/{lead_id}')
def get_lead(lead_id: int):
    session = SessionLocal()
    try:
        l = session.get(Lead, lead_id)
        if not l:
            raise HTTPException(404, 'Lead not found')
        events = (session.query(LeadEvent).filter(LeadEvent.lead_id == lead_id)
                  .order_by(LeadEvent.id.desc()).all())
        return _lead_dict(l, events)
    finally:
        session.close()


@router.patch('/{lead_id}')
def update_lead(lead_id: int, body: LeadPatch):
    session = SessionLocal()
    try:
        l = session.get(Lead, lead_id)
        if not l:
            raise HTTPException(404, 'Lead not found')
        if body.stage and body.stage != l.stage:
            if body.stage not in STAGES:
                raise HTTPException(400, f'stage must be one of {STAGES}')
            _add_event(session, l.id, 'stage_change',
                       f'{l.stage} → {body.stage}', user=body.user_name)
            l.stage = body.stage
        if body.next_followup != l.next_followup and (body.next_followup or l.next_followup):
            _add_event(session, l.id, 'followup',
                       f'Follow-up set to {body.next_followup or "none"}', user=body.user_name)
            l.next_followup = body.next_followup
        for f in ('owner', 'tags', 'contact_name', 'contact_email', 'contact_phone', 'country'):
            v = getattr(body, f)
            if v:
                setattr(l, f, v.strip())
        l.updated_at = datetime.utcnow()
        session.commit()
        return _lead_dict(l)
    finally:
        session.close()


@router.delete('/{lead_id}')
def delete_lead(lead_id: int):
    session = SessionLocal()
    try:
        l = session.get(Lead, lead_id)
        if not l:
            raise HTTPException(404, 'Lead not found')
        session.query(LeadEvent).filter(LeadEvent.lead_id == lead_id).delete()
        session.delete(l)
        session.commit()
        return {'ok': True}
    finally:
        session.close()


@router.post('/{lead_id}/events')
def add_lead_event(lead_id: int, body: EventIn):
    if body.kind not in ('note', 'link'):
        raise HTTPException(400, 'kind must be note | link')
    session = SessionLocal()
    try:
        l = session.get(Lead, lead_id)
        if not l:
            raise HTTPException(404, 'Lead not found')
        _add_event(session, lead_id, body.kind, body.text, body.data, body.user_name)
        l.updated_at = datetime.utcnow()
        session.commit()
        return {'ok': True}
    finally:
        session.close()


# ── API keys management (internal) ────────────────────────────────────────
class KeyIn(BaseModel):
    label: str = ''
    user_name: str = ''


@keys_router.get('')
def list_keys():
    session = SessionLocal()
    try:
        rows = session.query(ApiKey).order_by(ApiKey.id.desc()).all()
        return [{'id': k.id, 'label': k.label,
                 'key_preview': k.key[:8] + '…', 'scopes': k.scopes,
                 'created_by': k.created_by, 'revoked': bool(k.revoked),
                 'created_at': k.created_at.isoformat() if k.created_at else '',
                 'last_used_at': k.last_used_at.isoformat() if k.last_used_at else ''}
                for k in rows]
    finally:
        session.close()


@keys_router.post('')
def create_key(body: KeyIn):
    session = SessionLocal()
    try:
        key = 'mmk_' + secrets.token_urlsafe(32)
        session.add(ApiKey(key=key, label=body.label.strip(),
                           created_by=body.user_name.strip()))
        session.commit()
        # full key is returned exactly once
        return {'key': key, 'label': body.label}
    finally:
        session.close()


@keys_router.delete('/{key_id}')
def revoke_key(key_id: int):
    session = SessionLocal()
    try:
        k = session.get(ApiKey, key_id)
        if not k:
            raise HTTPException(404, 'Key not found')
        k.revoked = 1
        session.commit()
        return {'ok': True}
    finally:
        session.close()


# ── external read-only API v1 ─────────────────────────────────────────────
def require_api_key(request: Request):
    supplied = request.headers.get('x-api-key', '') or request.query_params.get('api_key', '')
    if not supplied:
        raise HTTPException(401, 'X-API-Key header required')
    session = SessionLocal()
    try:
        k = session.query(ApiKey).filter(ApiKey.key == supplied, ApiKey.revoked == 0).first()
        if not k:
            raise HTTPException(403, 'Invalid or revoked API key')
        k.last_used_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()


@v1_router.get('/leads')
def v1_leads(request: Request, lead_type: str = '', stage: str = '', owner: str = '',
             tag: str = '', updated_since: str = '',
             limit: int = Query(500, le=5000), offset: int = 0):
    """Read-only external endpoint: full lead records incl. linked data snapshots
    and timestamps. Auth: X-API-Key header (create keys on the Settings page)."""
    require_api_key(request)
    session = SessionLocal()
    try:
        q = session.query(Lead)
        if lead_type:
            q = q.filter(Lead.lead_type == lead_type)
        if stage:
            q = q.filter(Lead.stage == stage)
        if owner:
            q = q.filter(Lead.owner.ilike(f'%{owner}%'))
        if tag:
            q = q.filter(Lead.tags.ilike(f'%{tag}%'))
        if updated_since:
            try:
                q = q.filter(Lead.updated_at >= datetime.fromisoformat(updated_since))
            except ValueError:
                raise HTTPException(400, 'updated_since must be ISO 8601')
        total = q.count()
        rows = q.order_by(Lead.updated_at.desc()).offset(offset).limit(limit).all()
        ids = [l.id for l in rows]
        events = {}
        if ids:
            for e in (session.query(LeadEvent).filter(LeadEvent.lead_id.in_(ids))
                      .order_by(LeadEvent.id).all()):
                events.setdefault(e.lead_id, []).append(e)
        return {'total': total,
                'items': [_lead_dict(l, events.get(l.id, [])) for l in rows]}
    finally:
        session.close()


@v1_router.get('/leads/{lead_id}')
def v1_lead(request: Request, lead_id: int):
    require_api_key(request)
    session = SessionLocal()
    try:
        l = session.get(Lead, lead_id)
        if not l:
            raise HTTPException(404, 'Lead not found')
        events = (session.query(LeadEvent).filter(LeadEvent.lead_id == lead_id)
                  .order_by(LeadEvent.id).all())
        return _lead_dict(l, events)
    finally:
        session.close()
