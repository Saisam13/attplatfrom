"""SQLite persistence via SQLAlchemy."""
import os
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, Text, DateTime, Index,
    UniqueConstraint, ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
os.makedirs(os.path.join(DATA_DIR, 'uploads'), exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'att.db')

DB_URL = os.environ.get('DATABASE_URL', f'sqlite:///{DB_PATH}')
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DB_URL.startswith("sqlite"):
    # busy_timeout: a writer (bulk RawRow insert during a run) waits instead
    # of immediately raising "database is locked" when a reader collides with it.
    connect_args = {'check_same_thread': False, 'timeout': 30}

engine = create_engine(DB_URL, connect_args=connect_args)

if DB_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, 'connect')
    def _sqlite_pragmas(dbapi_conn, _record):
        # R10: WAL lets readers (dashboard requests) proceed concurrently with
        # a writer (a background run bulk-inserting raw_rows) instead of
        # blocking behind SQLite's default single-writer-exclusive journal.
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=30000')
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Run(Base):
    __tablename__ = 'runs'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, default='chemical')  # chemical | battery
    status = Column(String, default='queued')  # queued|running|done|error
    progress = Column(Integer, default=0)      # 0-100
    stage = Column(String, default='Queued')
    error = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    config_json = Column(Text, default='{}')   # trend_exclude, llm mode, files
    stats_json = Column(Text, default='{}')    # row counts, match stats, tiers
    file_hashes = Column(Text, default='[]')   # sha256 of each uploaded source file (dup-upload warning)


class ChemicalScore(Base):
    __tablename__ = 'chemical_scores'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    chemical = Column(String, nullable=False)
    pool = Column(String, nullable=False)  # base | opportunity
    hsn_codes = Column(String, default='')
    shipments = Column(Integer, default=0)
    total_qty_kg = Column(Float, default=0)
    total_value_usd = Column(Float, default=0)
    # normalized dimension scores (0-100)
    volume_norm = Column(Float, default=0)
    price_norm = Column(Float, default=0)
    buyers_norm = Column(Float, default=0)
    suppliers_norm = Column(Float, default=0)
    trend_norm = Column(Float, default=0)
    trend_adjusted = Column(Float, default=50)
    structure_norm = Column(Float, default=0)
    freedom_norm = Column(Float, default=0)
    barrier_norm = Column(Float, default=0)
    # raw metrics + modifiers
    raw_json = Column(Text, default='{}')      # raw dim values, geo_adj etc.
    variance_type = Column(String, default='neutral')
    variance_mod = Column(Float, default=0)
    reg_factor = Column(Float, default=1.0)
    reg_status = Column(String, default='clear')
    att_base = Column(Float, default=0)
    att_final = Column(Float, default=0)
    att_india = Column(Float, default=0)
    rodtep_bonus = Column(Float, default=0)
    drawback_bonus = Column(Float, default=0)
    feedback_adj = Column(Float, default=0)    # bounded trader-feedback adjustment applied to att_final
    tier = Column(String, default='C')
    trend_direction = Column(String, default='')
    growth_rate = Column(Float, default=0)
    reasoning = Column(Text, default='')
    detail_json = Column(Text, default='{}')   # price stats, top buyers/suppliers/countries
    engine_version = Column(Integer, default=1)  # 1=percentile-rank (legacy), 2=anchor-band

    __table_args__ = (Index('ix_scores_run_chem', 'run_id', 'chemical'),)


class MonthlyTrend(Base):
    __tablename__ = 'monthly_trends'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    chemical = Column(String, nullable=False)
    month = Column(String, nullable=False)   # YYYY-MM
    shipments = Column(Integer, default=0)
    qty_kg = Column(Float, default=0)
    value_usd = Column(Float, default=0)
    excluded = Column(Integer, default=0)    # 1 if excluded from trend regression

    __table_args__ = (Index('ix_trends_run_chem', 'run_id', 'chemical'),)


class GeoLog(Base):
    __tablename__ = 'geo_log'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    chemical = Column(String, nullable=False)
    month = Column(String)
    direction = Column(String)
    z_score = Column(Float)
    deviation_pct = Column(Float)
    raw_value = Column(Float)
    avg_value = Column(Float)
    adj_factor = Column(Float)
    event = Column(Text)


class RegLog(Base):
    __tablename__ = 'reg_log'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    chemical = Column(String, nullable=False)
    factor = Column(Float)
    status = Column(String)
    note = Column(Text)


class RawRow(Base):
    __tablename__ = 'raw_rows'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    date = Column(String)
    hsn6 = Column(String)
    desc_clean = Column(Text)
    chemical = Column(String, index=True)
    match_type = Column(String)
    match_score = Column(Float)
    seller = Column(String)
    seller_country = Column(String)
    buyer = Column(String)
    buyer_country = Column(String)
    qty = Column(Float)
    qty_kg = Column(Float)
    value_usd = Column(Float)
    unit_price = Column(Float)
    file = Column(String)
    row_hash = Column(String, index=True, default='')  # dedupe the same shipment across runs


class Feedback(Base):
    __tablename__ = 'feedback'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    chemical = Column(String, nullable=False)
    user_name = Column(String, default='')
    verdict = Column(String, nullable=False)  # confirm | challenge | correct
    suggested_tier = Column(String, default='')
    expected_duration = Column(String, default='')
    comment = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


class LlmCache(Base):
    __tablename__ = 'llm_cache'
    id = Column(Integer, primary_key=True)
    desc = Column(String, unique=True, index=True, nullable=False)
    matched = Column(String, default='')  # base chemical name, '' = NONE
    provider = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


class BatteryEntity(Base):
    """Supplier or buyer of battery-scrap / feedstock, aggregated per run."""
    __tablename__ = 'battery_entities'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    role = Column(String, nullable=False)        # supplier | buyer
    name = Column(String, nullable=False)
    country = Column(String, default='')
    categories = Column(String, default='')      # comma-separated feedstock categories
    shipments = Column(Integer, default=0)
    qty_kg = Column(Float, default=0)
    value_usd = Column(Float, default=0)
    median_price = Column(Float, default=0)
    price_index = Column(Float, default=1.0)     # vs category market median; <1 = cheaper
    months_active = Column(Integer, default=0)
    first_month = Column(String, default='')
    last_month = Column(String, default='')
    consistency = Column(Float, default=0)       # active months / span months (0-1)
    geo_ease = Column(Float, default=60)
    proc_score = Column(Float, default=0)        # 0-100 procurement attractiveness
    tier = Column(String, default='C')
    detail_json = Column(Text, default='{}')     # per-category stats, counterparties, monthly
    engine_version = Column(Integer, default=1)  # 1=percentile-rank (legacy), 2=anchor-band

    __table_args__ = (Index('ix_battery_run_role', 'run_id', 'role'),)


class BatteryCategory(Base):
    """Per-run summary of one feedstock category (Black Mass, Li-ion Scrap, …)."""
    __tablename__ = 'battery_categories'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True, nullable=False)
    category = Column(String, nullable=False)
    shipments = Column(Integer, default=0)
    qty_kg = Column(Float, default=0)
    value_usd = Column(Float, default=0)
    median_price = Column(Float, default=0)
    n_suppliers = Column(Integer, default=0)
    n_buyers = Column(Integer, default=0)
    top_countries = Column(Text, default='[]')   # [[country, shipments], ...]


class AppCache(Base):
    """Unified cache for all modules (LLM matching, EPR research, web search,
    AI drafts, external HSN lookups). Namespaced, content-hash keyed, optional
    per-namespace TTL enforced by backend.cache.CacheService."""
    __tablename__ = 'app_cache'
    id = Column(Integer, primary_key=True)
    namespace = Column(String, nullable=False)
    key_hash = Column(String, nullable=False)
    key_preview = Column(String, default='')     # first 200 chars, for inspection
    value_json = Column(Text, default='null')
    meta = Column(String, default='')            # e.g. provider used
    hits = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index('ix_cache_ns_key', 'namespace', 'key_hash', unique=True),)


class EprMaterial(Base):
    """Active EPR-regulated battery material (Lithium, Cobalt, Nickel, Manganese).
    Extensible: admin can add new materials. overall_weight is the material's
    contribution to the final company grade (auto-normalized at scoring time)."""
    __tablename__ = 'epr_materials'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)     # 'Lithium'
    slug = Column(String, unique=True, nullable=False)     # 'lithium'
    overall_weight = Column(Float, default=1.0)            # admin-set; normalized per company
    target_weight = Column(Float, default=0.5)             # within-material: target vs credits
    credit_weight = Column(Float, default=0.5)             # within-material: target vs credits
    active = Column(Integer, default=1)                    # soft-disable without deleting data
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class EprCompanyMaterial(Base):
    """Per-material target/credits data for one EPR company.
    NULL = absent (no data for this material); 0.0 = reported zero.
    This distinction is critical: a company with NULL lithium is excluded from
    the lithium scoring pool; a company with 0.0 is included and scores bottom."""
    __tablename__ = 'epr_company_materials'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('epr_companies.id', ondelete='CASCADE'),
                        index=True, nullable=False)
    material_id = Column(Integer, ForeignKey('epr_materials.id', ondelete='CASCADE'),
                         index=True, nullable=False)
    target_tons = Column(Float, nullable=True)      # NULL = no data (Q3)
    credits = Column(Float, nullable=True)
    import_qty = Column(Float, nullable=True)
    parse_status = Column(String, default='ok')     # ok | zero | exempt | unparsed
    source_file = Column(String, default='')
    uploaded_by = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint('company_id', 'material_id',
                                       name='uq_company_material'),)


class EprCompany(Base):
    """Producer row from a CPCB 'EPR Targets' upload (lithium battery producers).
    identity fields only — per-material data lives in EprCompanyMaterial.
    Legacy flat target_tons/credits stay in place for backward compatibility
    but grade + grade_breakdown_json are the canonical scores (v2 engine)."""
    __tablename__ = 'epr_companies'
    id = Column(Integer, primary_key=True)
    company_name = Column(String, nullable=False, index=True)
    registration_number = Column(String, default='', index=True)  # Q7: primary merge key
    address = Column(String, default='')
    email = Column(String, default='')
    state = Column(String, default='')
    battery_chemistry = Column(String, default='')
    # Legacy flat fields (kept for backward compat; engine v2 uses epr_company_materials)
    target_tons = Column(Float, default=0)
    credits = Column(Float, default=0)
    import_qty = Column(Float, default=0)
    other_json = Column(Text, default='{}')
    source_file = Column(String, default='')
    uploaded_by = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Q8/Q9: materialized grade columns
    grade = Column(Float, default=0.0)            # 0-100; replaces priority_score
    grade_label = Column(String, default='None')  # Top|High|Medium|Low|None
    scores_version = Column(Integer, default=0)   # 0=unscored, 2=engine_v2
    grade_breakdown_json = Column(Text, default='{}')


class EprResearch(Base):
    """AI sourcing-agent research result for one EPR company (cached until refresh)."""
    __tablename__ = 'epr_research'
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, index=True, unique=True, nullable=False)
    research_json = Column(Text, default='{}')
    search_provider = Column(String, default='')
    llm_provider = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HsnCode(Base):
    """Bundled open WCO Harmonized System directory (2/4/6-digit hierarchy)."""
    __tablename__ = 'hsn_directory'
    id = Column(Integer, primary_key=True)
    hscode = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text, default='')
    section = Column(String, default='')
    parent = Column(String, index=True, default='')
    level = Column(Integer, default=6)


class HsnMap(Base):
    """Curated mapping of HSN codes to our chemicals / battery categories / other
    products, so sales can find codes and filter to 'our products'."""
    __tablename__ = 'hsn_map'
    id = Column(Integer, primary_key=True)
    hscode = Column(String, index=True, nullable=False)
    label = Column(String, nullable=False)       # chemical / product name
    map_type = Column(String, default='chemical')  # chemical | battery | other
    is_our_product = Column(Integer, default=1)
    notes = Column(Text, default='')
    created_by = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


class Lead(Base):
    """Universal lead across all modules (chemical, EPR, battery, other)."""
    __tablename__ = 'leads'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # company / entity name
    lead_type = Column(String, default='other', index=True)  # chemical|epr|battery|other
    stage = Column(String, default='new', index=True)  # new|contacted|in_talks|deal|dead
    owner = Column(String, default='', index=True)
    tags = Column(String, default='')              # comma-separated
    source = Column(String, default='manual')      # module that created it
    entity_kind = Column(String, default='')       # epr_company|chemical|battery_entity|hsn_buyer|raw_row
    entity_ref = Column(String, default='')        # id or name in that module
    hsn_code = Column(String, default='')
    country = Column(String, default='')
    contact_name = Column(String, default='')
    contact_email = Column(String, default='')
    contact_phone = Column(String, default='')
    next_followup = Column(String, default='')     # YYYY-MM-DD
    data_json = Column(Text, default='{}')         # linked snapshot data (timestamped)
    created_by = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LeadEvent(Base):
    """Timestamped timeline for a lead: notes, stage changes, outreach, data links."""
    __tablename__ = 'lead_events'
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, index=True, nullable=False)
    kind = Column(String, default='note')  # note|stage_change|outreach|link|created|followup
    text = Column(Text, default='')
    data_json = Column(Text, default='{}')
    user_name = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


class PitchTemplate(Base):
    __tablename__ = 'pitch_templates'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lead_type = Column(String, default='any')   # chemical|epr|battery|any
    channel = Column(String, default='email')   # email|call|whatsapp
    body = Column(Text, default='')
    created_by = Column(String, default='')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiKey(Base):
    """Static keys for the external read-only API (/api/v1/*). `key` stores a
    SHA256 hash, never the raw key — the raw key is shown exactly once at
    creation time (see leads.create_key) and cannot be retrieved afterward."""
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True, nullable=False)  # sha256 hash
    key_preview = Column(String, default='')  # first ~12 chars of the raw key, display only
    label = Column(String, default='')
    scopes = Column(String, default='read')
    created_by = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)
    revoked = Column(Integer, default=0)


class User(Base):
    """A teammate's login account. Replaces the shared PIN — each person gets
    their own username/password instead of one secret the whole team shares."""
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, default='')
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token = Column(String, primary_key=True)  # opaque, random — the session cookie's value
    user_id = Column(Integer, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = 'app_settings'
    key = Column(String, primary_key=True)
    value_json = Column(Text, default='null')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SettingsLog(Base):
    __tablename__ = 'settings_log'
    id = Column(Integer, primary_key=True)
    user_name = Column(String, default='')
    key = Column(String, nullable=False)
    old_value = Column(Text, default='')
    new_value = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.utcnow)


def _migrate():
    """Additive column migrations for databases created before these columns existed."""
    from sqlalchemy import text
    added = {
        'runs': [('kind', "VARCHAR DEFAULT 'chemical'"),
                 ('file_hashes', "TEXT DEFAULT '[]'")],
        'chemical_scores': [('feedback_adj', 'FLOAT DEFAULT 0'),
                            ('engine_version', 'INTEGER DEFAULT 1')],
        'battery_entities': [('engine_version', 'INTEGER DEFAULT 1')],
        'raw_rows': [('row_hash', 'VARCHAR DEFAULT \'\'')],
        'api_keys': [('key_preview', 'VARCHAR DEFAULT \'\'')],
        # Q8/Q9: materialized grade columns on epr_companies
        'epr_materials': [
            ('target_weight', 'FLOAT DEFAULT 0.5'),
            ('credit_weight', 'FLOAT DEFAULT 0.5'),
        ],
        'epr_companies': [
            ('grade', 'FLOAT DEFAULT 0.0'),
            ('grade_label', "VARCHAR DEFAULT 'None'"),
            ('scores_version', 'INTEGER DEFAULT 0'),
            ('grade_breakdown_json', "TEXT DEFAULT '{}'"),
            ('registration_number', "VARCHAR DEFAULT ''"),
        ],
    }
    with engine.connect() as conn:
        for table, cols in added.items():
            if DB_URL.startswith("sqlite"):
                existing = {r[1] for r in conn.execute(text(f'PRAGMA table_info({table})'))}
            else:
                existing = {r[0] for r in conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"))}
            if not existing:
                continue
            for col, ddl in cols:
                if col not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}'))
        conn.commit()


def _seed_epr_materials():
    """Q6: Seed the 4 default EPR materials if the table is empty.
    Backfill legacy epr_companies rows (battery_chemistry='') into Lithium."""
    from sqlalchemy import text
    DEFAULT_MATERIALS = [
        {'name': 'Lithium',   'slug': 'lithium',   'overall_weight': 1.0, 'display_order': 1},
        {'name': 'Cobalt',    'slug': 'cobalt',    'overall_weight': 1.0, 'display_order': 2},
        {'name': 'Nickel',    'slug': 'nickel',    'overall_weight': 1.0, 'display_order': 3},
        {'name': 'Manganese', 'slug': 'manganese', 'overall_weight': 1.0, 'display_order': 4},
    ]
    session = SessionLocal()
    try:
        existing_count = session.query(EprMaterial).count()
        if existing_count == 0:
            for m in DEFAULT_MATERIALS:
                session.add(EprMaterial(**m))
            session.commit()
            print('[migrate] seeded 4 default EPR materials')

        # Q6: backfill legacy flat rows into epr_company_materials as Lithium
        lithium = session.query(EprMaterial).filter(EprMaterial.slug == 'lithium').first()
        if not lithium:
            return
        existing_mat_ids = {r.company_id for r in
                           session.query(EprCompanyMaterial.company_id)
                           .filter(EprCompanyMaterial.material_id == lithium.id).all()}
        legacy = session.query(EprCompany).filter(
            EprCompany.id.notin_(existing_mat_ids),
            (EprCompany.target_tons > 0) | (EprCompany.credits > 0)
        ).all()
        count = 0
        for c in legacy:
            session.add(EprCompanyMaterial(
                company_id=c.id,
                material_id=lithium.id,
                target_tons=c.target_tons if (c.target_tons or 0) > 0 else None,
                credits=c.credits if (c.credits or 0) > 0 else None,
                import_qty=c.import_qty if (c.import_qty or 0) > 0 else None,
                parse_status='migrated',
                source_file=c.source_file,
                uploaded_by='migration',
            ))
            count += 1
        if count:
            session.commit()
            print(f'[migrate] backfilled {count} legacy EPR rows into epr_company_materials (Lithium)')
    finally:
        session.close()


def _migrate_llm_cache():
    """One-time copy of the legacy llm_cache table into the unified app_cache
    (namespace 'llm_match'), so old matches survive the cache rework."""
    import hashlib
    from sqlalchemy import text
    with engine.connect() as conn:
        if DB_URL.startswith("sqlite"):
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        else:
            tables = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))}
            
        if 'llm_cache' not in tables or 'app_cache' not in tables:
            return
        already = conn.execute(text(
            "SELECT COUNT(*) FROM app_cache WHERE namespace='llm_match'")).scalar()
        if already:
            return
        rows = conn.execute(text('SELECT "desc", matched, provider FROM llm_cache')).fetchall()
        
        insert_sql = 'INSERT OR IGNORE INTO app_cache ' if DB_URL.startswith("sqlite") else 'INSERT INTO app_cache '
        on_conflict = '' if DB_URL.startswith("sqlite") else ' ON CONFLICT (namespace, key_hash) DO NOTHING'
        
        for desc, matched, provider in rows:
            h = hashlib.sha256((desc or '').encode('utf-8')).hexdigest()
            conn.execute(text(
                insert_sql +
                '(namespace, key_hash, key_preview, value_json, meta, hits, created_at) '
                f"VALUES ('llm_match', :h, :p, :v, :m, 0, CURRENT_TIMESTAMP){on_conflict}"),
                {'h': h, 'p': (desc or '')[:200],
                 'v': json_dumps(matched or ''), 'm': provider or ''})
        conn.commit()
        if rows:
            print(f'[migrate] copied {len(rows)} llm_cache rows into app_cache')


def _migrate_api_keys():
    """One-time hash-at-rest migration (R10): rows created before hashing was
    added still have the raw key sitting in the `key` column (key_preview
    empty is the tell) — hash it in place and save a display-only preview
    before any code starts comparing against hashes."""
    import hashlib
    from sqlalchemy import text
    with engine.connect() as conn:
        if DB_URL.startswith("sqlite"):
            tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        else:
            tables = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))}
        if 'api_keys' not in tables:
            return
        rows = conn.execute(text(
            "SELECT id, key FROM api_keys WHERE key_preview IS NULL OR key_preview = ''")).fetchall()
        if not rows:
            return
        for kid, raw_key in rows:
            preview = (raw_key or '')[:12] + '…'
            hashed = hashlib.sha256((raw_key or '').encode('utf-8')).hexdigest()
            conn.execute(text('UPDATE api_keys SET "key" = :h, key_preview = :p WHERE id = :id'),
                        {'h': hashed, 'p': preview, 'id': kid})
        conn.commit()
        print(f'[migrate] hashed {len(rows)} existing api_keys at rest')


def json_dumps(v):
    import json
    return json.dumps(v)


def init_db():
    Base.metadata.create_all(engine)
    _migrate()
    _migrate_llm_cache()
    _migrate_api_keys()
    _seed_epr_materials()
