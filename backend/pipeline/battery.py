"""Battery-scrap / feedstock procurement pipeline.

Parses EXIM trade data uploaded on the Battery Procurement page, classifies
each row into a feedstock category (Black Mass, Li-ion Battery Scrap, Spent
Catalyst, Magnet Scrap, …), then builds a PROCUREMENT-centric view: suppliers
ranked by how attractive they are to buy feedstock from (volume, price
competitiveness, consistency, reliability, geography), with a secondary buyer
view showing who else is competing for the same material.
"""
from statistics import median
from collections import Counter, defaultdict

from .engine import parse_exim_files, _clean_prices, _log_anchor_score
from .constants import EASE, BATTERY_ANCHOR_BANDS

# Minimum priced shipments an entity needs in a category before its
# price_index for that category is trusted (R4a) — below this, and for
# entities with no usable price data at all, price_index is None ("insufficient
# data") rather than the old silent default of 1.0 ("exactly market price").
MIN_PRICED_SHIPMENTS = 3

# Ordered rules — first match wins. (keywords are checked against the raw
# UPPER-CASE description; hsn prefixes against the full HSN code.)
SCRAP_WORDS = ('SCRAP', 'WASTE', 'SPENT', 'USED', 'END OF LIFE', 'END-OF-LIFE', 'EOL', 'RECYCL')
# R4b: real EXIM descriptions for this HSN family are dominated by
# machine-translated Spanish ("BATERIA OF IONS OF LITHIUM", "ACCUMULATORS OF
# IONS OF LITHIUM") that the original keyword list never matched, and even
# where it did match (e.g. "LITHIUM-ION BATTERIES...") the require_scrap gate
# still routed it to the generic Mixed/Other bucket because genuine
# lithium-ion battery/cell/accumulator descriptions rarely use the word
# "scrap" at all. On the live run-6 data this reclassifies ~25,000 of 49,708
# Mixed/Other rows (~50%) into a chemistry-identified category, which is what
# makes price_index (R4a) comparable instead of blending $69/kg li-ion with
# $0.85/kg e-waste under one "market median".
CATEGORY_RULES = [
    ('Black Mass', {'keywords': ['BLACK MASS', 'BLACKMASS', 'BATTERY MASS', 'CATHODE POWDER WASTE']}),
    ('Li-ion Battery Scrap', {'keywords': ['LITHIUM ION', 'LITHIUM-ION', 'LI-ION', 'LI ION', 'LIB ', 'NMC', 'LFP', 'LCO',
                                          'LITHIUM BATTER', 'IONS OF LITHIUM', 'ION LITHIUM', 'DE LITIO',
                                          'ACCUMULATORS OF IONS', 'ACCUMULATEUR']}),
    ('Lead-Acid Battery Scrap', {'keywords': ['LEAD ACID', 'LEAD-ACID', 'DRAINED LEAD', 'LEAD BATTERY'],
                                 'require_scrap': True}),
    ('Battery Scrap (Mixed/Other)', {'keywords': ['BATTERY', 'BATTERIES', 'ACCUMULATOR', 'CELL SCRAP'],
                                     'require_scrap': True}),
    ('Electrode / Cathode-Anode Scrap', {'keywords': ['CATHODE', 'ANODE', 'ELECTRODE', 'COPPER FOIL', 'ALUMINIUM FOIL'],
                                         'require_scrap': True}),
    ('Spent Catalyst', {'keywords': ['CATALYST'], 'require_scrap': True}),
    ('Magnet Scrap (NdFeB / Rare Earth)', {'keywords': ['NDFEB', 'ND-FE-B', 'NEODYMIUM MAGNET', 'MAGNET SCRAP', 'PERMANENT MAGNET', 'RARE EARTH MAGNET']}),
    ('E-Waste / PCB Scrap', {'keywords': ['E-WASTE', 'E WASTE', 'ELECTRONIC WASTE', 'PCB', 'PRINTED CIRCUIT', 'MOTHERBOARD', 'WEEE']}),
    ('Metal Residues / Tailings', {'keywords': ['TAILING', 'SLAG', 'ASH', 'RESIDUE', 'DROSS', 'SLUDGE']}),
]
# HSN fallbacks when the description has no keyword hit
HSN_CATEGORIES = [
    ('854810', 'Battery Scrap (Mixed/Other)'),
    ('8549', 'E-Waste / PCB Scrap'),
    ('2620', 'Metal Residues / Tailings'),
    ('2621', 'Metal Residues / Tailings'),
    ('8507', 'Battery Scrap (Mixed/Other)'),
]
FALLBACK_CATEGORY = 'Other Feedstock'


def categorize_row(desc_raw, hsn_raw):
    desc = desc_raw or ''
    has_scrap_word = any(w in desc for w in SCRAP_WORDS)
    for cat, rule in CATEGORY_RULES:
        if rule.get('require_scrap') and not has_scrap_word:
            continue
        if any(kw in desc for kw in rule['keywords']):
            return cat
    for prefix, cat in HSN_CATEGORIES:
        if (hsn_raw or '').startswith(prefix):
            return cat
    return FALLBACK_CATEGORY


def _make_entity():
    return {
        'shipments': 0, 'qty_kg': 0.0, 'value_usd': 0.0,
        'countries': Counter(), 'categories': Counter(),
        'months': Counter(), 'prices': [], 'prices_by_cat': defaultdict(list),
        'counterparties': Counter(), 'counterparty_countries': Counter(),
    }


def _month_span(months):
    """Number of calendar months between first and last active month, inclusive."""
    if not months:
        return 0
    first, last = min(months), max(months)
    fy, fm = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    return (ly - fy) * 12 + (lm - fm) + 1


def run_battery_pipeline(exim_files, log=print, progress=None,
                         tier_a=70, tier_b=40, anchor_bands=None):
    def _p(stage, pct):
        if progress:
            progress(stage, pct)

    _p('Ingesting battery EXIM files', 5)
    log('BATTERY STAGE 1 — Ingesting data...')
    rows, skipped = parse_exim_files(exim_files, log)
    log(f'  Total rows: {len(rows)}')

    _p('Classifying feedstock categories', 25)
    cat_counts = Counter()
    for r in rows:
        r['category'] = categorize_row(r['desc_raw'], r.get('hsn_raw', r['hsn6']))
        cat_counts[r['category']] += 1
    log('BATTERY STAGE 2 — Categories: ' +
        ', '.join(f'{c}={n}' for c, n in cat_counts.most_common()))

    _p('Aggregating suppliers and buyers', 45)
    suppliers = defaultdict(_make_entity)
    buyers = defaultdict(_make_entity)
    cat_prices = defaultdict(list)
    cat_stats = defaultdict(lambda: {'shipments': 0, 'qty_kg': 0.0, 'value_usd': 0.0,
                                     'suppliers': set(), 'buyers': set(),
                                     'countries': Counter(),
                                     'monthly_shipments': Counter(),
                                     'monthly_qty': Counter(),
                                     'monthly_value': Counter()})
    for r in rows:
        cat = r['category']
        cs = cat_stats[cat]
        cs['shipments'] += 1
        cs['qty_kg'] += r['qty_kg']
        cs['value_usd'] += r['value_usd']
        cs['countries'][r['seller_country'] or '?'] += 1
        cs['monthly_shipments'][r['date']] += 1
        cs['monthly_qty'][r['date']] += r['qty_kg']
        cs['monthly_value'][r['date']] += r['value_usd']
        if r['unit_price'] > 0:
            cat_prices[cat].append(r['unit_price'])

        for role, entities, name, country, counterparty, cp_country in (
                ('supplier', suppliers, r['seller'], r['seller_country'], r['buyer'], r['buyer_country']),
                ('buyer', buyers, r['buyer'], r['buyer_country'], r['seller'], r['seller_country'])):
            if not name or name == 'N/A':
                continue
            e = entities[name]
            e['shipments'] += 1
            e['qty_kg'] += r['qty_kg']
            e['value_usd'] += r['value_usd']
            if country:
                e['countries'][country] += 1
            e['categories'][cat] += 1
            e['months'][r['date']] += 1
            if r['unit_price'] > 0:
                e['prices'].append(r['unit_price'])
                e['prices_by_cat'][cat].append(r['unit_price'])
            if counterparty and counterparty != 'N/A':
                e['counterparties'][counterparty] += 1
            if cp_country:
                e['counterparty_countries'][cp_country] += 1
            if role == 'supplier':
                cs['suppliers'].add(name)
            else:
                cs['buyers'].add(name)

    # market median price per category (outlier-cleaned)
    cat_median = {}
    for cat, prices in cat_prices.items():
        clean, _ = _clean_prices(prices)
        if clean:
            cat_median[cat] = median(clean)

    _p('Scoring suppliers', 65)

    def build_items(entities):
        items = []
        for name, e in entities.items():
            clean, _ = _clean_prices(e['prices'])
            med = median(clean) if clean else 0
            # price index: qty-weighted vs the category market median (<1 = cheaper).
            # R4a: only trust categories where this entity has >= MIN_PRICED_SHIPMENTS
            # priced shipments; entities with no usable price data get price_index
            # = None ("insufficient data") instead of the old silent default of 1.0
            # ("exactly market price").
            idx_parts, idx_weights = [], []
            for cat, pp in e['prices_by_cat'].items():
                if cat in cat_median and cat_median[cat] > 0 and len(pp) >= MIN_PRICED_SHIPMENTS:
                    idx_parts.append(median(pp) / cat_median[cat])
                    idx_weights.append(len(pp))
            price_index = (sum(p * w for p, w in zip(idx_parts, idx_weights)) /
                           sum(idx_weights)) if idx_parts else None
            months_active = len(e['months'])
            span = _month_span(list(e['months'].keys()))
            # R3: a single active month (span=1) used to score a perfect 1.0 —
            # better than a supplier active 10 of 14 months. Flooring the
            # denominator at 6 months requires genuine multi-month track record
            # to reach 1.0; a one-shipment, one-month entity now scores 1/6.
            consistency = months_active / max(span, 6) if span else 0
            country = e['countries'].most_common(1)[0][0] if e['countries'] else ''
            geo = EASE.get(country, 60)
            items.append({
                'name': name, 'country': country,
                'categories': ', '.join(c for c, _ in e['categories'].most_common()),
                'shipments': e['shipments'], 'qty_kg': round(e['qty_kg'], 1),
                'value_usd': round(e['value_usd'], 1),
                'median_price': round(med, 2),
                'price_index': round(price_index, 3) if price_index is not None else None,
                'months_active': months_active,
                'first_month': min(e['months']) if e['months'] else '',
                'last_month': max(e['months']) if e['months'] else '',
                'consistency': round(consistency, 3), 'geo_ease': geo,
                'detail': {
                    'category_breakdown': [
                        {'category': c, 'shipments': n,
                         'median_price': round(median(e['prices_by_cat'][c]), 2) if e['prices_by_cat'].get(c) else 0,
                         'market_median': round(cat_median.get(c, 0), 2)}
                        for c, n in e['categories'].most_common()],
                    'top_counterparties': e['counterparties'].most_common(8),
                    'counterparty_countries': e['counterparty_countries'].most_common(8),
                    'monthly_shipments': dict(sorted(e['months'].items())),
                },
                # raw scoring inputs (internal — consumed by score_items only)
                '_volume': e['qty_kg'] if e['qty_kg'] > 0 else e['value_usd'],
                '_price_index': price_index,   # None = unknown, dropped + renormalized
                '_consistency': consistency,
                '_reliability': e['shipments'],
                '_geo': geo,
            })
        return items

    def score_items(items, weights):
        """v2: absolute per-entity scoring — no percentile ranking. _geo and
        _consistency are already bounded (0-100 / 0-1) by construction and
        used directly; _volume and _reliability are open-ended and run
        through the log-anchor transform (same helper as the chemical
        engine); _price_index becomes a direct formula (market price = 50,
        cheaper = higher, pricier = lower) and — per R4a — is DROPPED, not
        defaulted to a neutral score, for entities with no usable price data:
        the remaining weights renormalize to sum 1 for that entity."""
        bands = anchor_bands or BATTERY_ANCHOR_BANDS
        for it in items:
            dim_scores = {
                '_volume': _log_anchor_score(it['_volume'], **bands['volume']),
                '_consistency': max(0.0, min(100.0, it['_consistency'] * 100)),
                '_reliability': _log_anchor_score(it['_reliability'], **bands['reliability']),
                '_geo': max(0.0, min(100.0, it['_geo'])),
            }
            if it['_price_index'] is not None:
                # index 1.0 (market price) -> 50; 0.5 (half market) -> 75; 2.0 (double) -> 0
                dim_scores['_price_inv'] = max(0.0, min(100.0, 100 - (it['_price_index'] - 1) * 50))

            active = {k: w for k, w in weights.items() if w > 0 and k in dim_scores}
            total_w = sum(active.values())
            score = (sum((w / total_w) * dim_scores[k] for k, w in active.items())
                     if total_w > 0 else 0.0)
            it['proc_score'] = round(score, 2)
            it['tier'] = 'A' if score >= tier_a else ('B' if score >= tier_b else 'C')
        items.sort(key=lambda x: -x['proc_score'])
        return items

    # Procurement view: cheap, consistent, high-volume, reliable, easy-geography sellers
    supplier_items = score_items(build_items(suppliers), {
        '_volume': 0.30, '_price_inv': 0.25, '_consistency': 0.20,
        '_reliability': 0.15, '_geo': 0.10,
    })
    # Buyer view: who competes hardest for the same feedstock
    buyer_items = score_items(build_items(buyers), {
        '_volume': 0.40, '_reliability': 0.25, '_consistency': 0.20, '_geo': 0.15,
        '_price_inv': 0.0,
    })

    log(f'BATTERY STAGE 3 — Scored {len(supplier_items)} suppliers, {len(buyer_items)} buyers')

    categories = []
    for cat, cs in sorted(cat_stats.items(), key=lambda kv: -kv[1]['value_usd']):
        categories.append({
            'category': cat, 'shipments': cs['shipments'],
            'qty_kg': round(cs['qty_kg'], 1), 'value_usd': round(cs['value_usd'], 1),
            'median_price': round(cat_median.get(cat, 0), 2),
            'n_suppliers': len(cs['suppliers']), 'n_buyers': len(cs['buyers']),
            'top_countries': cs['countries'].most_common(8),
            'monthly_shipments': dict(sorted(cs['monthly_shipments'].items())),
            'monthly_qty': {k: round(v, 1) for k, v in sorted(cs['monthly_qty'].items())},
            'monthly_value': {k: round(v, 1) for k, v in sorted(cs['monthly_value'].items())},
        })

    return {
        'rows': rows, 'suppliers': supplier_items, 'buyers': buyer_items,
        'categories': categories, 'skipped_files': skipped,
        'cat_counts': dict(cat_counts),
    }
