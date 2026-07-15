"""Weekly sales digest — in-app JSON + branded PDF export.

Covers the last 7 days: pipeline changes, follow-ups due, new hot EPR
companies, biggest ATT movers, battery price watch and outreach activity.
"""
import json
import tempfile
from datetime import datetime, timedelta, date

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .db import (SessionLocal, Lead, LeadEvent, EprCompany, EprResearch,
                 Run, ChemicalScore, BatteryCategory)

router = APIRouter(prefix='/api/digest', tags=['digest'])


def _movers(session, run_a, run_b, limit=8):
    a = {c.chemical: c for c in session.query(ChemicalScore)
         .filter(ChemicalScore.run_id == run_a).all()}
    b = {c.chemical: c for c in session.query(ChemicalScore)
         .filter(ChemicalScore.run_id == run_b).all()}
    out = [{'chemical': n, 'att_a': a[n].att_final, 'att_b': b[n].att_final,
            'delta': round(a[n].att_final - b[n].att_final, 2),
            'tier_a': a[n].tier, 'tier_b': b[n].tier}
           for n in set(a) & set(b)]
    out.sort(key=lambda m: -abs(m['delta']))
    return out[:limit]


def build_digest():
    session = SessionLocal()
    try:
        week_ago = datetime.utcnow() - timedelta(days=7)
        today = date.today().isoformat()

        leads = session.query(Lead).all()
        new_leads = [l for l in leads if l.created_at and l.created_at >= week_ago]
        events = (session.query(LeadEvent)
                  .filter(LeadEvent.created_at >= week_ago).all())
        stage_changes = [e for e in events if e.kind == 'stage_change']
        outreach = [e for e in events if e.kind == 'outreach']
        deals = [l for l in leads if l.stage == 'deal']

        followups = {}
        for l in leads:
            if l.next_followup and l.stage not in ('deal', 'dead'):
                bucket = ('overdue' if l.next_followup < today
                          else 'today' if l.next_followup == today else None)
                if bucket:
                    followups.setdefault(l.owner or 'unassigned', {'overdue': [], 'today': []})[
                        bucket].append({'id': l.id, 'name': l.name, 'lead_type': l.lead_type,
                                        'next_followup': l.next_followup, 'stage': l.stage})

        # top EPR companies (weights inline to avoid import cycle)
        from .epr import _epr_weights, _priority
        w = _epr_weights()
        companies = session.query(EprCompany).all()
        researched = {r.company_id for r in session.query(EprResearch.company_id).all()}
        top_epr = sorted(({'id': c.id, 'company_name': c.company_name,
                           'priority_score': _priority(c, w),
                           'target_tons': c.target_tons, 'credits': c.credits,
                           'gap_tons': round(max(0, (c.target_tons or 0) - (c.credits or 0)), 1),
                           'has_research': c.id in researched,
                           'is_new': bool(c.created_at and c.created_at >= week_ago)}
                          for c in companies), key=lambda d: -d['priority_score'])[:10]

        # ATT movers from the two latest completed chemical runs
        chem_runs = (session.query(Run)
                     .filter(Run.kind == 'chemical', Run.status == 'done')
                     .order_by(Run.id.desc()).limit(2).all())
        movers = (_movers(session, chem_runs[0].id, chem_runs[1].id)
                  if len(chem_runs) == 2 else [])

        # battery price watch: category medians, latest vs previous battery run
        bat_runs = (session.query(Run)
                    .filter(Run.kind == 'battery', Run.status == 'done')
                    .order_by(Run.id.desc()).limit(2).all())
        price_watch = []
        if bat_runs:
            latest = {c.category: c for c in session.query(BatteryCategory)
                      .filter(BatteryCategory.run_id == bat_runs[0].id).all()}
            prev = ({c.category: c for c in session.query(BatteryCategory)
                     .filter(BatteryCategory.run_id == bat_runs[1].id).all()}
                    if len(bat_runs) == 2 else {})
            for cat, c in sorted(latest.items(), key=lambda kv: -kv[1].value_usd):
                p = prev.get(cat)
                price_watch.append({
                    'category': cat, 'median_price': c.median_price,
                    'prev_price': p.median_price if p else None,
                    'change_pct': (round((c.median_price - p.median_price) / p.median_price * 100, 1)
                                   if p and p.median_price else None),
                    'shipments': c.shipments})

        return {
            'generated_at': datetime.utcnow().isoformat(),
            'period_days': 7,
            'pipeline': {
                'total_leads': len(leads),
                'new_leads': len(new_leads),
                'stage_changes': len(stage_changes),
                'outreach_touches': len(outreach),
                'deals': len(deals),
                'new_lead_items': [{'id': l.id, 'name': l.name, 'lead_type': l.lead_type,
                                    'owner': l.owner, 'stage': l.stage} for l in new_leads[:15]],
                'stage_change_items': [{'lead_id': e.lead_id, 'text': e.text,
                                        'user_name': e.user_name,
                                        'at': e.created_at.isoformat() if e.created_at else ''}
                                       for e in stage_changes[:15]],
            },
            'followups': followups,
            'top_epr': top_epr,
            'movers': movers,
            'movers_runs': [r.name for r in chem_runs],
            'price_watch': price_watch,
        }
    finally:
        session.close()


@router.get('')
def get_digest():
    return build_digest()


@router.get('/pdf')
def digest_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from .report import TITLE, SUB, H2, BODY, _table, _kpi_row, NAVY
    from reportlab.lib import colors

    d = build_digest()
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp.close()
    doc = SimpleDocTemplate(tmp.name, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            title='Weekly Sales Digest')
    story = [Paragraph('WEEKLY SALES DIGEST', TITLE),
             Paragraph(f'MiniMines Sales Hub · last {d["period_days"]} days · '
                       f'generated {datetime.now().strftime("%d %b %Y %H:%M")}', SUB)]
    p = d['pipeline']
    story.append(_kpi_row([
        (str(p['total_leads']), 'TOTAL LEADS'),
        (str(p['new_leads']), 'NEW THIS WEEK'),
        (str(p['stage_changes']), 'STAGE CHANGES'),
        (str(p['outreach_touches']), 'OUTREACH TOUCHES'),
        (str(p['deals']), 'DEALS'),
    ]))

    overdue_rows = []
    for owner, buckets in d['followups'].items():
        for item in buckets['overdue'] + buckets['today']:
            overdue_rows.append([owner, item['name'][:40], item['lead_type'],
                                 item['stage'], item['next_followup']])
    if overdue_rows:
        story.append(Paragraph('Follow-ups due / overdue', H2))
        story.append(_table(['Owner', 'Lead', 'Type', 'Stage', 'Due'],
                            overdue_rows[:20],
                            widths=[30 * mm, 62 * mm, 22 * mm, 24 * mm, 28 * mm]))

    if d['top_epr']:
        story.append(Paragraph('Top EPR producers by priority', H2))
        rows = [[c['company_name'][:44], f"{c['target_tons']:.1f}", f"{c['credits']:.1f}",
                 f"{c['gap_tons']:.1f}", f"{c['priority_score']:.1f}",
                 'NEW' if c['is_new'] else ('✓' if c['has_research'] else '—')]
                for c in d['top_epr']]
        story.append(_table(['Company', 'Target (t)', 'Credits (t)', 'Gap (t)', 'Priority', 'Research'],
                            rows, widths=[62 * mm, 21 * mm, 21 * mm, 19 * mm, 20 * mm, 23 * mm]))

    if d['movers']:
        story.append(Paragraph('Biggest ATT movers', H2))
        rows = [[m['chemical'][:46], f"{m['att_b']:.1f}", f"{m['att_a']:.1f}",
                 f"{m['delta']:+.1f}", f"{m['tier_b']} → {m['tier_a']}"] for m in d['movers']]
        story.append(_table(['Chemical', 'Prev ATT', 'Current ATT', 'Δ', 'Tier'],
                            rows, widths=[70 * mm, 24 * mm, 26 * mm, 18 * mm, 28 * mm]))

    if d['price_watch']:
        story.append(Paragraph('Battery feedstock price watch', H2))
        rows = [[c['category'][:40], f"${c['median_price']:.2f}",
                 (f"${c['prev_price']:.2f}" if c['prev_price'] else '—'),
                 (f"{c['change_pct']:+.1f}%" if c['change_pct'] is not None else '—'),
                 str(c['shipments'])] for c in d['price_watch']]
        story.append(_table(['Category', 'Median $/kg', 'Previous', 'Change', 'Shipments'],
                            rows, widths=[62 * mm, 26 * mm, 26 * mm, 24 * mm, 26 * mm]))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        'Generated by MiniMines Sales Hub. Lead data, EPR intelligence and market movers are '
        'live on the platform; this digest reflects the state at generation time.', BODY))

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, A4[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(20 * mm, 3.2 * mm,
                          'MiniMines Cleantech Solutions Pvt. Ltd. — Sales Hub (internal)')
        canvas.drawRightString(A4[0] - 20 * mm, 3.2 * mm, f'Page {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return FileResponse(tmp.name, filename=f'Sales_Digest_{date.today().isoformat()}.pdf',
                        media_type='application/pdf')
