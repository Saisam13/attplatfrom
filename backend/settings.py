"""App settings stored in SQLite with a change log.

Settings are seeded from pipeline constants / config.json on first read so the
platform keeps producing identical numbers until someone edits them in the UI.
"""
import hashlib
import json
import os
import secrets

from .db import SessionLocal, AppSetting, SettingsLog, ROOT
from .pipeline.constants import (
    WEIGHTS, TIER_A_MIN, TIER_B_MIN, DEFAULT_TREND_EXCLUDE,
    ATT_ANCHOR_BANDS, BATTERY_ANCHOR_BANDS,
)

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
    'retention_days': 0,             # 0 = keep runs forever (R10: was 180 — auto-deleting
                                      # a sales team's run history by default is the wrong
                                      # default; require an explicit, confirmed opt-in instead)
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
    # Anchor-band floor/ceiling for the v2 scoring engine's log-scale dimensions.
    # floor -> score 0, ceiling -> score 100 (clamped), log-linear between.
    'att_anchor_bands': {k: dict(v) for k, v in ATT_ANCHOR_BANDS.items()},
    'battery_anchor_bands': {k: dict(v) for k, v in BATTERY_ANCHOR_BANDS.items()},
    # Q10: EPR log1p anchor bands — derived from real CPCB lithium data
    # 756 companies with nonzero targets: p75=0.2t, p90=1.8t, p95=7.8t, p99=101.9t, max=82,481t
    # Ceiling at p99 (101.9t) so top producers differentiate; TMB (82,481t) will correctly score 100.
    'epr_anchor_bands': {
        'target':  {'floor': 0.01, 'ceiling': 101.9},
        'credits': {'floor': 0.01, 'ceiling': 101.9},
    },
}

def hash_pin(pin: str) -> str:
    """R10: PIN stored as salt:sha256(salt+pin), never plaintext. A 4-6 digit
    PIN's tiny keyspace means hashing alone can't stop brute force — rate
    limiting (see main.py pin_gate) is the actual defense; this only protects
    against a copied/leaked DB file directly revealing the PIN."""
    salt = secrets.token_hex(8)
    digest = hashlib.sha256((salt + pin).encode('utf-8')).hexdigest()
    return f'{salt}:{digest}'


def verify_pin(supplied: str, stored: str) -> bool:
    if not stored:
        return False
    if ':' not in stored:
        # legacy plaintext value saved before hashing was added — compare
        # directly so an already-configured PIN doesn't suddenly lock everyone
        # out; it gets hashed automatically the next time it's changed in Settings
        return supplied == stored
    salt, digest = stored.split(':', 1)
    return hashlib.sha256((salt + supplied).encode('utf-8')).hexdigest() == digest


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
    epr_affected = False
    session = SessionLocal()
    try:
        for key, new_val in changes.items():
            if key not in DEFAULTS:
                continue
            if key == 'pin_code' and isinstance(new_val, str) and new_val:
                new_val = hash_pin(new_val)
            if isinstance(DEFAULTS[key], dict) and isinstance(new_val, dict):
                merged = {**current.get(key, {}), **new_val}
                new_val = merged
            # Q10: normalize epr_weights target+credit to sum 1 (prevents max grade > 100)
            if key == 'epr_weights' and isinstance(new_val, dict):
                wT = max(0.0, float(new_val.get('target_tons', 1.0)))
                wC = max(0.0, float(new_val.get('credits', 0.5)))
                total = wT + wC
                if total > 0:
                    new_val = {'target_tons': round(wT / total, 6),
                               'credits': round(wC / total, 6)}
                epr_affected = True
            if key == 'epr_anchor_bands':
                epr_affected = True
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
        # Q8/Q10: trigger EPR grade recompute if EPR-relevant settings changed
        if epr_affected:
            try:
                from . import epr
                epr._trigger_recompute(session)
            except Exception as exc:
                print(f'[settings] EPR recompute warning: {exc}')
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
