"""Configuration constants, geopolitical events, regulatory database,
noise/unit/synonym lookups. Ported verbatim from trading_module.py v2.0."""
import re

WEIGHTS = {
    'volume': 0.15, 'price': 0.20, 'buyers': 0.15, 'suppliers': 0.10,
    'trend': 0.10, 'structure': 0.10, 'freedom': 0.10, 'barrier': 0.10,
}
NLP_DIRECT_THRESHOLD = 0.60
NLP_NEAR_THRESHOLD = 0.40
TIER_A_MIN = 70
TIER_B_MIN = 40
OUTLIER_IQR_MULT = 1.5
WINSORIZE_LO = 5   # percentile
WINSORIZE_HI = 95

# Default months excluded from trend regression (configurable per run)
DEFAULT_TREND_EXCLUDE = ['2026-04', '2026-05', '2026-06']

# ══════════════════════════════════════════════════════════════
# ANCHOR BANDS — v2 scoring engine (log-anchor transform)
# floor -> score 0, ceiling -> score 100, log-linear between, clamped outside.
# Seeded from real percentiles in the live data — see
# docs/PLATFORM_REDESIGN_PLAN.md §2.3. Admin-editable via Settings
# (att_anchor_bands / battery_anchor_bands), these are just the fallback.
# ══════════════════════════════════════════════════════════════
ATT_ANCHOR_BANDS = {
    # Derived from real production data: 107,251 EXIM rows across all runs
    # (n=985 chemicals scored). Anchors set at p95 for ceiling so the top
    # 5% of chemicals still have room to differentiate (p99 would compress them).
    'volume': {'floor': 10, 'ceiling': 1_306_605},       # p95=1.3M kg;  max=353M kg
    'price':  {'floor': 1_000, 'ceiling': 11_836_965},   # p95=11.8M USD; max=763M USD
    'buyers_n':         {'floor': 0, 'ceiling': 580},
    'buyers_countries': {'floor': 0, 'ceiling': 76},
    'suppliers_n':      {'floor': 0, 'ceiling': 430},
}
BATTERY_ANCHOR_BANDS = {
    # Derived from real battery run data: 13,255 entities
    'volume':      {'floor': 1, 'ceiling': 15_000},   # p95=15,000 kg; max=1.2B kg (extreme outlier)
    'reliability': {'floor': 0, 'ceiling': 15},       # p95=15 shipments; max=609
}
ENGINE_VERSION = 2

# ══════════════════════════════════════════════════════════════
# GEOPOLITICAL EVENTS DATABASE
# ══════════════════════════════════════════════════════════════
GEO_EVENTS = [
    {'start': '2022-02', 'end': '2026-12', 'event': 'Russia-Ukraine war — energy crisis, sanctions on Russian metals/chemicals',
     'countries': {'RUSSIA', 'UKRAINE', 'BELARUS'}, 'keywords': {'palladium', 'platinum', 'rhodium', 'ruthenium', 'iridium', 'nickel', 'alumin', 'pgm', 'catalyst'}},
    {'start': '2023-11', 'end': '2026-06', 'event': 'Red Sea / Houthi shipping crisis — rerouting via Cape of Good Hope, +25-40% Asia-Europe rates',
     'countries': {'YEMEN', 'IRAN', 'EGYPT'}, 'keywords': {'shipping', 'freight', 'transit', 'suez'}},
    {'start': '2023-12', 'end': '2026-12', 'event': 'China rare earth export controls — banned extraction tech, restricted 12+ rare earth elements',
     'countries': {'CHINA'}, 'keywords': {'rare earth', 'cerium', 'lanthanum', 'yttrium', 'neodymium', 'praseodymium', 'dysprosium', 'terbium', 'gadolinium', 'europium', 'samarium', 'erbium'}},
    {'start': '2024-08', 'end': '2026-12', 'event': 'China antimony export ban — exports fell 97%, prices doubled',
     'countries': {'CHINA'}, 'keywords': {'antimony', 'sb2o3', 'antimony trioxide'}},
    {'start': '2024-12', 'end': '2026-12', 'event': 'China banned gallium/germanium/antimony exports to US',
     'countries': {'CHINA', 'UNITED STATES'}, 'keywords': {'gallium', 'germanium', 'antimony', 'superhard'}},
    {'start': '2025-04', 'end': '2025-07', 'event': 'US reciprocal tariffs — 26% on Indian chemicals (from ~3%), disrupted India-US flows',
     'countries': {'INDIA', 'UNITED STATES'}, 'keywords': {'tariff', 'duty', 'organic chemical'}},
    {'start': '2025-08', 'end': '2026-02', 'event': 'US-India trade crisis — 50% combined tariffs on Indian exports',
     'countries': {'INDIA', 'UNITED STATES'}, 'keywords': {'tariff', 'duty'}},
    {'start': '2026-02', 'end': '2026-12', 'event': 'US-India trade deal — tariff reduced to 18%, removal pending on some goods',
     'countries': {'INDIA', 'UNITED STATES'}, 'keywords': {'tariff', 'trade deal'}},
    {'start': '2026-02', 'end': '2026-12', 'event': 'Strait of Hormuz disruption — US-Iran conflict, naphtha/LPG feedstock flows impacted',
     'countries': {'IRAN', 'SAUDI ARABIA', 'UAE', 'QATAR', 'OMAN', 'BAHRAIN', 'KUWAIT'}, 'keywords': {'hormuz', 'naphtha', 'lpg', 'petrochemical'}},
    {'start': '2024-04', 'end': '2026-12', 'event': 'UK/US sanctions on Russian PGM metals via LME/CME exchanges',
     'countries': {'RUSSIA'}, 'keywords': {'palladium', 'platinum', 'rhodium', 'pgm', 'catalyst'}},
    {'start': '2026-05', 'end': '2026-12', 'event': 'US 109% countervailing duty on Russian palladium',
     'countries': {'RUSSIA', 'UNITED STATES'}, 'keywords': {'palladium'}},
]

# ══════════════════════════════════════════════════════════════
# EXPANDED REGULATORY DATABASE
# ══════════════════════════════════════════════════════════════
REGULATORY = {}
# Banned (factor 0.0) — severe toxicity / global bans
for name in ['mercury chloride', 'mercury sulphate', 'mercury sulfate', 'mercury nitrate', 'mercury oxide',
             'arsenic trioxide', 'arsenic pentoxide', 'thallium sulphate', 'thallium sulfate',
             'dimethyl mercury', 'methyl mercury chloride']:
    REGULATORY[name] = 0.0

# Restricted (factor 0.3) — REACH SVHC / heavy metals / carcinogens
for name in ['cadmium chloride', 'cadmium nitrate', 'cadmium sulphate', 'cadmium sulfate',
             'cadmium oxide', 'cadmium acetate', 'cadmium bromide', 'cadmium fluoride',
             'cadmium chloride anhydrous', 'cadmium hydroxide', 'cadmium carbonate',
             'lead chloride', 'lead nitrate', 'lead acetate', 'lead sulphate', 'lead sulfate',
             'lead chromate', 'lead oxide', 'lead(ii) sulfate',
             'chromium trioxide', 'potassium dichromate', 'sodium dichromate', 'chromium(vi) oxide',
             'beryllium oxide', 'beryllium chloride', 'beryllium fluoride', 'beryllium sulphate',
             'osmium tetroxide', 'selenium dioxide', 'selenium oxide',
             'cobalt dichloride', 'cobalt sulphate', 'cobalt sulfate', 'cobalt nitrate',
             'nickel sulphate', 'nickel sulfate', 'nickel chloride', 'nickel nitrate',
             'barium chloride', 'barium carbonate', 'barium chromate',
             'strontium chromate', 'zinc chromate', 'lead chromate']:
    REGULATORY[name] = 0.3

# Conditional (factor 0.7) — need license / special handling
for name in ['hydrofluoric acid', 'hydrogen fluoride', 'sodium cyanide', 'potassium cyanide',
             'phosphorus trichloride', 'phosphorus pentachloride', 'thionyl chloride',
             'phosgene', 'chlorosulfonic acid', 'oleum', 'fuming sulfuric acid',
             'acrolein', 'allyl alcohol', 'methyl isocyanate', 'ethylene oxide', 'propylene oxide',
             'dimethyl sulfate', 'diethyl sulfate', 'epichlorohydrin',
             'chromium sulphate', 'chromium sulfate', 'chromic acid',
             'vanadium pentoxide', 'vanadium oxide', 'antimony trioxide',
             'ferric chloride', 'ferrous chloride', 'manganese chloride', 'manganese sulphate',
             'copper chloride', 'copper sulphate', 'copper sulfate', 'zinc chloride', 'zinc sulphate']:
    if name not in REGULATORY:
        REGULATORY[name] = 0.7

# ══════════════════════════════════════════════════════════════
# METHODOLOGY TEXTS (for each export sheet)
# ══════════════════════════════════════════════════════════════
METHODOLOGY = {
    'Rankings': 'METHODOLOGY: Each chemical scored on 8 dimensions (Volume, Price, Buyers, Suppliers, Trend, Structure, Freedom, Barrier) normalized to 0-100 via percentile rank. ATT = weighted sum × regulatory factor + variance modifier. Tier A>=70, B=40-69, C<40. Base chemicals listed first, then opportunity chemicals (unmatched EXIM rows grouped by extracted name). Price outliers trimmed at IQR×1.5 and winsorized at 5th/95th percentile.',
    'Price Deep Dive': 'METHODOLOGY: Prices filtered for outliers using IQR×1.5 (excluded from stats) then winsorized at 5th/95th percentile. CV% = coefficient of variation. Variance classified as Opportunity (geographic price differences dominate — arbitrage potential, +5 bonus) or Risk (temporal swings dominate — instability, -10 penalty). Country prices use median of >=2 transactions.',
    'Buyer Intel': 'METHODOLOGY: Buyer analysis counts unique buyer entities and countries from EXIM records. Repeat buyers = buyers with >1 shipment. HHI (Herfindahl-Hirschman Index) measures concentration — lower HHI = more fragmented = healthier market.',
    'Supplier Intel': 'METHODOLOGY: Supplier analysis counts unique seller entities and origin countries. India % = share of shipments from Indian sellers. Higher India presence = easier sourcing for MC trading wing.',
    'Time Trends': 'METHODOLOGY: Monthly shipment counts displayed for all months with trade activity. Trend direction based on 12-month rolling average comparison: last 6 months avg vs prior 6 months avg. Growth >5% = Growing, <-5% = Declining, else Stable.',
    'Opportunity Map': 'METHODOLOGY: Chemicals not matched to the base portfolio. Grouped by NLP-extracted name from EXIM product descriptions. Scored with same 8-dimension ATT formula. Assessment based on: trade value, shipment frequency, buyer diversity, and price stability. These represent market gaps — chemicals actively traded but not yet in our portfolio.',
    'India Incentives': 'METHODOLOGY: ATT India = ATT Final + RoDTEP bonus (0-5, scaled from avg RoDTEP rate) + Drawback bonus (0-5, from avg drawback rate). These are additive, not in the base score. India Supply % = share of shipments with Indian sellers.',
    'Regulatory + Geo Log': 'METHODOLOGY: Regulatory factors from REACH SVHC list, DGFT restrictions, and hazmat classification in EXIM descriptions. Geo adjustment detects statistical anomalies (>2 std dev from mean) in monthly trade volumes, then correlates with known geopolitical events (sanctions, tariffs, shipping disruptions) by matching date ranges, countries, and chemical keywords.',
    'Raw Parsed Data': 'METHODOLOGY: Every EXIM row parsed and matched. Match types: direct (>=60% NLP score), near (40-60%, flagged), none (<40%, excluded from base scoring but included in opportunity analysis). Qty KG is estimated from unit conversion (MT=1000, DRUM=200, BAG=25, LB=0.4536).',
}

# ══════════════════════════════════════════════════════════════
# NOISE / UNIT / SYNONYM LOOKUPS
# ══════════════════════════════════════════════════════════════
NOISE_RE = re.compile(
    r'\b(?:UN\s*\d{4}|CLASS\s*[\d.]+|PG\s*:?\s*[IVX]+|PACKING\s+GROUP|'
    r'IMO[\s-]*CLASS|DG\s+CARGO|HAZARD|HAZ\s+CARGO|DETAILS?\s*:|'
    r'HS\s*(?:CODE)?\s*\d{4,8}|HARMONIZED\s+TARIFF|'
    r'TOTAL\s+\d+\s+(?:DRUMS?|BAGS?|PALLETS?|PACKAGES?|CONTAINERS?|CARTONS?)|'
    r'\d+\s*X\s*\d+|FCL\s+CONTAINER|'
    r'STC\s*:?|SHIPPER\s*S?\s*LOAD|SAID\s+TO\s+CONTAIN|'
    r'FREIGHT\s+(?:PREPAID|COLLECT)|INVOICE\s+NO|PO\s*(?:NUMBER|NO|#)?|'
    r'NET\s+WT|GROSS\s+WT|TARE\s+WT)\b', re.IGNORECASE)

UNIT_TO_KG = {
    'KG': 1, 'KGS': 1, 'KILOGRAM': 1, 'KILOGRAMS': 1,
    'MT': 1000, 'TON': 1000, 'TONS': 1000, 'TONNE': 1000, 'TONNES': 1000,
    'LB': 0.4536, 'LBS': 0.4536, 'POUND': 0.4536, 'POUNDS': 0.4536,
    'G': 0.001, 'GM': 0.001, 'GRAM': 0.001, 'GRAMS': 0.001,
    'L': 1.0, 'LT': 1.0, 'LITER': 1.0, 'LITRE': 1.0,
}

SYNONYMS = {
    'zncl2': 'zinc chloride', 'cucl2': 'copper chloride', 'nicl2': 'nickel chloride',
    'cocl2': 'cobalt chloride', 'mncl2': 'manganese chloride', 'cdcl2': 'cadmium chloride',
    'crcl3': 'chromium chloride', 'pbcl2': 'lead chloride', 'fecl3': 'ferric chloride',
    'fecl2': 'ferrous chloride', 'cecl3': 'cerium chloride', 'lacl3': 'lanthanum chloride',
    'zn(no3)2': 'zinc nitrate', 'cu(no3)2': 'copper nitrate', 'ni(no3)2': 'nickel nitrate',
    'co(no3)2': 'cobalt nitrate', 'mn(no3)2': 'manganese nitrate', 'pb(no3)2': 'lead nitrate',
    'znso4': 'zinc sulphate', 'cuso4': 'copper sulphate', 'niso4': 'nickel sulphate',
    'coso4': 'cobalt sulphate', 'mnso4': 'manganese sulphate', 'cdso4': 'cadmium sulphate',
    'crso4': 'chromium sulphate',
    'ceo2': 'cerium oxide', 'la2o3': 'lanthanum oxide', 'y2o3': 'yttrium oxide',
    'pdcl2': 'palladium chloride', 'pd(oac)2': 'palladium acetate',
    'pd/c': 'palladium on carbon', 'pt/c': 'platinum on carbon',
    'rhcl3': 'rhodium chloride', 'rucl3': 'ruthenium chloride',
    'grignard': 'grignard reagent', 'organomet': 'organometallic',
}
SPELLING = {'sulphate': 'sulfate', 'sulphite': 'sulfite', 'aluminium': 'aluminum', 'caesium': 'cesium'}

EASE = {
    'CHINA': 70, 'INDIA': 95, 'UNITED STATES': 85, 'GERMANY': 90, 'JAPAN': 88,
    'SOUTH KOREA': 85, 'UNITED KINGDOM': 90, 'FRANCE': 88, 'ITALY': 85,
    'NETHERLANDS': 90, 'BELGIUM': 88, 'CANADA': 90, 'AUSTRALIA': 88,
    'SINGAPORE': 92, 'THAILAND': 80, 'VIETNAM': 78, 'BRAZIL': 75, 'MEXICO': 78,
    'TAIWAN': 82, 'MALAYSIA': 82, 'INDONESIA': 75, 'TURKEY': 72, 'SAUDI ARABIA': 78,
    'RUSSIA': 30, 'BELARUS': 25, 'IRAN': 15, 'NORTH KOREA': 5,
    'MYANMAR': 40, 'SYRIA': 10, 'VENEZUELA': 35,
}
