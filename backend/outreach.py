"""Outreach module: reusable pitch templates + AI-generated personalized
drafts (email / call script / WhatsApp) grounded in the lead's linked data,
EPR research and trade history. Every draft/send is logged onto the lead's
timeline so the tracker shows full touch history. Sending stays manual.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .db import SessionLocal, PitchTemplate, Lead, LeadEvent, EprCompany, EprResearch
from . import ai

router = APIRouter(prefix='/api/outreach', tags=['outreach'])

CHANNELS = ('email', 'call', 'whatsapp')

DEFAULT_TEMPLATES = [
    {'name': 'EPR credit shortfall intro', 'lead_type': 'epr', 'channel': 'email',
     'body': ('Introduce MiniMines (patented HHM™ battery recycling). They have an EPR target of '
              '{target_tons} tons with {credits} tons of credits procured — highlight the {gap_tons} '
              'ton gap, our ability to generate EPR certificates from their feed, and propose a call.')},
    {'name': 'Battery scrap procurement', 'lead_type': 'battery', 'channel': 'email',
     'body': ('We buy battery scrap / black mass at fair market prices with fast payment. Reference '
              'their shipment history where available and propose a recurring supply arrangement.')},
    {'name': 'Chemical trade opener', 'lead_type': 'chemical', 'channel': 'email',
     'body': ('Introduce our chemical trading desk. Reference the specific product/HSN they trade, '
              'volumes seen in the market, and offer a competitive quote.')},
    {'name': 'WhatsApp quick intro', 'lead_type': 'any', 'channel': 'whatsapp',
     'body': ('Very short, friendly, professional Indian B2B WhatsApp intro (3-4 sentences max), '
              'name-dropping MiniMines and the specific opportunity, ending with a question.')},
]


def seed_templates():
    session = SessionLocal()
    try:
        if session.query(PitchTemplate).first() is None:
            for t in DEFAULT_TEMPLATES:
                session.add(PitchTemplate(**t, created_by='seed'))
            session.commit()
    finally:
        session.close()


class TemplateIn(BaseModel):
    name: str
    lead_type: str = 'any'
    channel: str = 'email'
    body: str = ''
    user_name: str = ''


@router.get('/templates')
def list_templates(lead_type: str = '', channel: str = ''):
    session = SessionLocal()
    try:
        q = session.query(PitchTemplate)
        if lead_type:
            q = q.filter(PitchTemplate.lead_type.in_((lead_type, 'any')))
        if channel:
            q = q.filter(PitchTemplate.channel == channel)
        return [{'id': t.id, 'name': t.name, 'lead_type': t.lead_type,
                 'channel': t.channel, 'body': t.body, 'created_by': t.created_by,
                 'updated_at': t.updated_at.isoformat() if t.updated_at else ''}
                for t in q.order_by(PitchTemplate.name).all()]
    finally:
        session.close()


@router.post('/templates')
def create_template(body: TemplateIn):
    session = SessionLocal()
    try:
        t = PitchTemplate(name=body.name.strip(), lead_type=body.lead_type,
                          channel=body.channel, body=body.body,
                          created_by=body.user_name.strip())
        session.add(t)
        session.commit()
        return {'id': t.id}
    finally:
        session.close()


@router.put('/templates/{template_id}')
def update_template(template_id: int, body: TemplateIn):
    session = SessionLocal()
    try:
        t = session.get(PitchTemplate, template_id)
        if not t:
            raise HTTPException(404, 'Template not found')
        t.name, t.lead_type, t.channel, t.body = (body.name.strip(), body.lead_type,
                                                  body.channel, body.body)
        session.commit()
        return {'ok': True}
    finally:
        session.close()


@router.delete('/templates/{template_id}')
def delete_template(template_id: int):
    session = SessionLocal()
    try:
        t = session.get(PitchTemplate, template_id)
        if not t:
            raise HTTPException(404, 'Template not found')
        session.delete(t)
        session.commit()
        return {'ok': True}
    finally:
        session.close()


# ── AI draft generation ───────────────────────────────────────────────────
class DraftIn(BaseModel):
    lead_id: int
    channel: str = 'email'
    template_id: int = 0
    extra_instructions: str = ''
    user_name: str = ''


def _lead_context(session, lead):
    """Assemble everything we know about the lead for the prompt."""
    parts = [f'LEAD: {lead.name} (type: {lead.lead_type}, stage: {lead.stage}, '
             f'country: {lead.country or "India"})']
    if lead.contact_name:
        parts.append(f'Contact: {lead.contact_name} {lead.contact_email} {lead.contact_phone}')
    if lead.hsn_code:
        parts.append(f'HSN code of interest: {lead.hsn_code}')
    data = json.loads(lead.data_json or '{}')
    if data:
        parts.append('Linked data snapshot: ' + json.dumps(data)[:2000])
    # EPR research if this lead is an EPR company
    if lead.entity_kind == 'epr_company' and lead.entity_ref:
        try:
            c = session.get(EprCompany, int(lead.entity_ref))
            if c:
                parts.append(f'EPR: target {c.target_tons} tons, credits {c.credits} tons, '
                             f'gap {max(0, (c.target_tons or 0) - (c.credits or 0)):.1f} tons, '
                             f'state {c.state}')
                r = (session.query(EprResearch)
                     .filter(EprResearch.company_id == c.id).first())
                if r:
                    parts.append('AI research: ' + (r.research_json or '{}')[:3000])
        except (ValueError, TypeError):
            pass
    # recent notes
    notes = (session.query(LeadEvent)
             .filter(LeadEvent.lead_id == lead.id, LeadEvent.kind == 'note')
             .order_by(LeadEvent.id.desc()).limit(3).all())
    if notes:
        parts.append('Recent notes: ' + ' | '.join(n.text[:200] for n in notes))
    return '\n'.join(parts)


_DRAFT_SPECS = {
    'email': 'a professional B2B outreach EMAIL (subject line + body, under 180 words)',
    'call': 'a CALL SCRIPT (opener, 3 discovery questions, value pitch, objection handler, close — bullet style)',
    'whatsapp': 'a short WhatsApp message (max 4 sentences, friendly-professional, ends with a question)',
}


@router.post('/draft')
def generate_draft(body: DraftIn):
    if body.channel not in CHANNELS:
        raise HTTPException(400, f'channel must be one of {CHANNELS}')
    session = SessionLocal()
    try:
        lead = session.get(Lead, body.lead_id)
        if not lead:
            raise HTTPException(404, 'Lead not found')
        context = _lead_context(session, lead)
        template = session.get(PitchTemplate, body.template_id) if body.template_id else None
        lead_name, lead_phone = lead.name, lead.contact_phone
    finally:
        session.close()

    prompt = (f'You are a sales copywriter for MiniMines, an Indian battery-recycling and '
              f'chemical trading company (patented HHM™ hydrometallurgy process).\n\n'
              f'{context}\n\n'
              + (f'TEMPLATE / ANGLE to follow:\n{template.body}\n\n' if template else '')
              + (f'Extra instructions: {body.extra_instructions}\n\n' if body.extra_instructions else '')
              + f'Write {_DRAFT_SPECS[body.channel]}. Ground every claim in the data above — '
                f'never invent numbers or contacts. Use plain text, no markdown headers.')
    try:
        res = ai.complete(prompt, cache_ns='ai_draft', use_cache=False)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    draft = res['text'].strip()
    session = SessionLocal()
    try:
        session.add(LeadEvent(
            lead_id=body.lead_id, kind='outreach',
            text=f'{body.channel} draft generated'
                 + (f' (template: {template.name})' if template else ''),
            data_json=json.dumps({'channel': body.channel, 'draft': draft,
                                  'provider': res['provider']}),
            user_name=body.user_name.strip()))
        session.commit()
    finally:
        session.close()

    out = {'draft': draft, 'channel': body.channel, 'provider': res['provider']}
    if body.channel == 'whatsapp' and lead_phone:
        import urllib.parse
        digits = ''.join(ch for ch in lead_phone if ch.isdigit())
        out['wa_link'] = f'https://wa.me/{digits}?text=' + urllib.parse.quote(draft[:800])
    return out


class LogIn(BaseModel):
    lead_id: int
    channel: str = 'email'
    text: str = ''
    user_name: str = ''


@router.post('/log')
def log_outreach(body: LogIn):
    """Manually log an outreach touch (sent email / call made / WhatsApp sent)."""
    session = SessionLocal()
    try:
        lead = session.get(Lead, body.lead_id)
        if not lead:
            raise HTTPException(404, 'Lead not found')
        session.add(LeadEvent(lead_id=body.lead_id, kind='outreach',
                              text=f'{body.channel} sent: {body.text[:300]}',
                              data_json=json.dumps({'channel': body.channel, 'sent': True}),
                              user_name=body.user_name.strip()))
        from datetime import datetime
        lead.updated_at = datetime.utcnow()
        if lead.stage == 'new':
            lead.stage = 'contacted'
            session.add(LeadEvent(lead_id=body.lead_id, kind='stage_change',
                                  text='new → contacted (auto, outreach logged)',
                                  user_name=body.user_name.strip()))
        session.commit()
        return {'ok': True}
    finally:
        session.close()
