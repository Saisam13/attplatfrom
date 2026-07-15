"""App settings stored in SQLite with a change log.

Settings are seeded from pipeline constants / config.json on first read so the
platform keeps producing identical numbers until someone edits them in the UI.
"""
import json
import os

from .db import SessionLocal, AppSetting, SettingsLog, ROOT
from .pipeline.constants import WEIGHTS, TIER_A_MIN, TIER_B_MIN, DEFAULT_TREND_EXCLUDE

CONFIG_PATH = os.path.join(ROOT, 'config.json')


def _config_json():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


DEFAULTS = {
    'weights': dict(WEIGHTS),
    'tier_a_min': TIER_A_MIN,
    'tier_b_min': TIER_B_MIN,
    'trend_exclude_default': list(DEFAULT_TREND_EXCLUDE),
    'retention_days': 180,          # 0 = keep runs forever
    'feedback_adjustment': True,    # trader feedback nudges future ATT scores (±5)
    'show_feedback_page': True,
    'pin_enabled': False,
    'pin_code': '',
    'llm': {'provider': 'off', 'api_key': '', 'model': '',
            'base_url': 'http://localhost:11434'},
    # Shared AI provider pool for research / drafts / HSN suggestions / /api/v1/ai
    # (all keys optional; fallback follows llm_order / search_order)
    'ai_providers': {
        'groq_key': '', 'groq_model': '',
        'gemini_key': '', 'gemini_model': '',
        'anthropic_key': '', 'anthropic_model': '',
        'tavily_key': '', 'firecrawl_key': '',
        'ollama_model': '', 'ollama_base_url': '',
        'llm_order': ['groq', 'gemini', 'anthropic'],
        'search_order': ['tavily', 'firecrawl'],
    },
    'epr_weights': {'target_tons': 1.0, 'credits': 0.5},
    'cache_ttl_days': {},           # per-namespace override, 0 = keep forever
}

SECRET_KEYS = {'pin_code'}          # returned masked
MASKED_SUBKEYS = {
    'llm': ['api_key'],
    'ai_providers': ['groq_key', 'gemini_key', 'anthropic_key',
                     'tavily_key', 'firecrawl_key'],
}


def _seed_defaults():
    d = dict(DEFAULTS)
    cfg_llm = _config_json().get('llm')
    if cfg_llm:
        d['llm'] = {**DEFAULTS['llm'], **cfg_llm}
    return d


def get_all():
    """Full settings dict (secrets included) — for internal use."""
    out = _seed_defaults()
    session = SessionLocal()
    try:
        for row in session.query(AppSetting).all():
            try:
                out[row.key] = json.loads(row.value_json)
            except Exception:
                pass
    finally:
        session.close()
    return out


def get(key, default=None):
    return get_all().get(key, default if default is not None else DEFAULTS.get(key))


def public_view():
    """Settings dict safe to send to the browser (secrets masked)."""
    s = get_all()
    out = {}
    for k, v in s.items():
        if k in SECRET_KEYS:
            out[k] = bool(v)
            continue
        if k in MASKED_SUBKEYS and isinstance(v, dict):
            v = dict(v)
            for sub in MASKED_SUBKEYS[k]:
                v[f'has_{sub}'] = bool(v.get(sub))
                v.pop(sub, None)
        out[k] = v
    return out


def _mask_for_log(key, value):
    if key in SECRET_KEYS:
        return '***' if value else ''
    if key in MASKED_SUBKEYS and isinstance(value, dict):
        value = dict(value)
        for sub in MASKED_SUBKEYS[key]:
            if value.get(sub):
                value[sub] = '***'
    return json.dumps(value)


def update(changes: dict, user_name: str = ''):
    """Apply {key: new_value} changes; every real change is logged (who/old/new)."""
    current = get_all()
    session = SessionLocal()
    try:
        for key, new_val in changes.items():
            if key not in DEFAULTS:
                continue
            # allow partial dict updates (e.g. llm without re-sending api_key)
            if isinstance(DEFAULTS[key], dict) and isinstance(new_val, dict):
                merged = {**current.get(key, {}), **new_val}
                new_val = merged
            if current.get(key) == new_val:
                continue
            session.add(SettingsLog(
                user_name=user_name.strip(),
                key=key,
                old_value=_mask_for_log(key, current.get(key)),
                new_value=_mask_for_log(key, new_val),
            ))
            row = session.get(AppSetting, key)
            if row is None:
                row = AppSetting(key=key)
                session.add(row)
            row.value_json = json.dumps(new_val)
        session.commit()
    finally:
        session.close()


def change_log(limit=200):
    session = SessionLocal()
    try:
        rows = (session.query(SettingsLog).order_by(SettingsLog.id.desc())
                .limit(limit).all())
        return [{'id': r.id, 'user_name': r.user_name, 'key': r.key,
                 'old_value': r.old_value, 'new_value': r.new_value,
                 'created_at': r.created_at.isoformat() if r.created_at else ''}
                for r in rows]
    finally:
        session.close()
