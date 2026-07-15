"""Branded PDF summary report (2-3 pages) for a completed chemical run."""
import json
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

NAVY = colors.HexColor('#001B2E')
PANEL = colors.HexColor('#0F2E45')
TEAL = colors.HexColor('#04AED1')
STEEL = colors.HexColor('#3B6E93')
LIGHT = colors.HexColor('#EAF2F7')
GREY = colors.HexColor('#54595F')

TITLE = ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=22, textColor=NAVY, spaceAfter=2)
SUB = ParagraphStyle('sub', fontName='Helvetica', fontSize=10, textColor=GREY, spaceAfter=14)
H2 = ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=13, textColor=STEEL,
                    spaceBefore=14, spaceAfter=6)
BODY = ParagraphStyle('body', fontName='Helvetica', fontSize=9, textColor=colors.HexColor('#222222'), leading=12)
SMALL = ParagraphStyle('small', fontName='Helvetica', fontSize=7.5, textColor=GREY, leading=10)

TIER_COLORS = {'A': colors.HexColor('#27AE60'), 'B': colors.HexColor('#F39C12'),
               'C': colors.HexColor('#7F8C9B')}


def _table(headers, rows, widths=None, highlight_tier_col=None):
    data = [headers] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F5F8')]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#C7D5DF')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    if highlight_tier_col is not None:
        for i, row in enumerate(rows, 1):
            tier = row[highlight_tier_col]
            if tier in TIER_COLORS:
                style.append(('TEXTCOLOR', (highlight_tier_col, i), (highlight_tier_col, i), TIER_COLORS[tier]))
                style.append(('FONTNAME', (highlight_tier_col, i), (highlight_tier_col, i), 'Helvetica-Bold'))
    t.setStyle(TableStyle(style))
    return t


def _kpi_row(kpis):
    """Row of KPI tiles: [(value, label), ...]"""
    vals = [Paragraph(f'<b>{v}</b>', ParagraphStyle('v', fontName='Helvetica-Bold', fontSize=16,
                                                    textColor=TEAL, alignment=1)) for v, _ in kpis]
    labels = [Paragraph(l, ParagraphStyle('l', fontName='Helvetica', fontSize=7, textColor=colors.white,
                                          alignment=1)) for _, l in kpis]
    t = Table([vals, labels], colWidths=[(A4[0] - 40 * mm) / len(kpis)] * len(kpis))
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PANEL),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 8),
        ('LINEAFTER', (0, 0), (-2, -1), 1, NAVY),
    ]))
    return t


def build_pdf_report(run, chems, movers, prev_run_name, out_path):
    """run: Run ORM object; chems: list of ChemicalScore (sorted by att_final desc);
    movers: list of dicts with chemical/delta/att_a/att_b (may be empty)."""
    doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            title=f'ATT Summary — {run.name}')
    stats = json.loads(run.stats_json or '{}')
    tiers = stats.get('tiers', {})
    story = []

    story.append(Paragraph('ATT PLATFORM — RUN SUMMARY', TITLE))
    story.append(Paragraph(
        f'MiniMines Cleantech Solutions · Run #{run.id} “{run.name}” · '
        f'generated {datetime.now().strftime("%d %b %Y %H:%M")}', SUB))

    story.append(_kpi_row([
        (f"{stats.get('base_chemicals', 0)}", 'BASE CHEMICALS'),
        (f"{stats.get('opportunity_chemicals', 0)}", 'OPPORTUNITY POOL'),
        (f"{tiers.get('A', 0)}", 'TIER A'),
        (f"{tiers.get('B', 0)}", 'TIER B'),
        (f"{(stats.get('total_rows', 0)):,}", 'EXIM ROWS'),
        (f"{stats.get('geo_anomalies', 0)}", 'GEO ANOMALIES'),
    ]))

    story.append(Paragraph('Top chemicals by attractiveness', H2))
    rows = [[i + 1, c.chemical[:46], c.pool, f'{c.att_final:.1f}', f'{c.att_india:.1f}',
             (f'{c.feedback_adj:+.1f}' if c.feedback_adj else '—'), c.tier,
             c.trend_direction or '—']
            for i, c in enumerate(chems[:15])]
    story.append(_table(['#', 'Chemical', 'Pool', 'ATT', 'ATT India', 'Fb adj', 'Tier', 'Trend'],
                        rows, widths=[9 * mm, 62 * mm, 20 * mm, 14 * mm, 17 * mm, 13 * mm, 11 * mm, 20 * mm],
                        highlight_tier_col=6))

    if movers:
        story.append(Paragraph(f'Biggest movers vs previous run ({prev_run_name})', H2))
        mrows = [[m['chemical'][:46], f"{m['att_b']:.1f}", f"{m['att_a']:.1f}",
                  f"{m['delta']:+.1f}", m['tier_b'] + ' → ' + m['tier_a']]
                 for m in movers[:12]]
        story.append(_table(['Chemical', 'Previous ATT', 'Current ATT', 'Δ', 'Tier'],
                            mrows, widths=[70 * mm, 25 * mm, 25 * mm, 18 * mm, 28 * mm]))

    story.append(PageBreak())
    story.append(Paragraph('Top opportunity-pool chemicals', H2))
    opp = [c for c in chems if c.pool == 'opportunity'][:10]
    orows = [[c.chemical[:40], f'{c.att_final:.1f}', c.tier,
              Paragraph((c.reasoning or '')[:220], SMALL)] for c in opp]
    story.append(_table(['Chemical', 'ATT', 'Tier', 'Why it surfaced'],
                        orows, widths=[52 * mm, 14 * mm, 12 * mm, 88 * mm], highlight_tier_col=2))

    story.append(Paragraph('Methodology', H2))
    story.append(Paragraph(
        'Each chemical is scored on 8 dimensions (volume, price, buyers, suppliers, trend, structure, '
        'freedom, barrier), percentile-normalized to 0-100 and combined with configurable weights. '
        'The composite is multiplied by a regulatory factor, adjusted for price-variance signals and '
        'geopolitical anomalies, and optionally nudged (±5) by accumulated trader feedback. '
        'Tier cutoffs and weights are managed on the platform Settings page; every change is logged. '
        'Full detail is available in the 9-tab results workbook exported from the platform.', BODY))

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, A4[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica', 7)
        canvas.drawString(20 * mm, 3.2 * mm,
                          'MiniMines Cleantech Solutions Pvt. Ltd. — ATT Platform (internal)')
        canvas.drawRightString(A4[0] - 20 * mm, 3.2 * mm, f'Page {canvas.getPageNumber()}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path
