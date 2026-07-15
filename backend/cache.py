"""Unified cache service used by every module.

One SQLite table (app_cache), namespaced + content-hash keyed:
  llm_match     — chemical description -> portfolio chemical (kept forever)
  epr_research  — company research JSON (kept until force refresh)
  web_search    — Tavily/Firecrawl search results
  ai_complete   — generic /api/v1/ai/complete answers
  ai_draft      — outreach drafts
  hsn_external  — external HSN lookups

TTLs come from settings 'cache_ttl_days' ({namespace: days}); 0 = keep forever.
Clearable per-namespace from the Settings page.
"""
import hashlib
import json
from datetime import datetime, timedelta

from .db import SessionLocal, AppCache

DEFAULT_TTL_DAYS = {
    'llm_match': 0,
    'epr_research': 0,
    'web_search': 7,
    'ai_complete': 30,
    'ai_draft': 0,
    'hsn_external': 90,
}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _ttl_days(namespace: str) -> int:
    from . import settings
    ttls = settings.get('cache_ttl_days', {}) or {}
    if namespace in ttls:
        try:
            return int(ttls[namespace])
        except Exception:
            pass
    return DEFAULT_TTL_DAYS.get(namespace, 30)


def get(namespace: str, key: str):
    """Return the cached value or None (expired entries are treated as misses)."""
    session = SessionLocal()
    try:
        row = (session.query(AppCache)
               .filter(AppCache.namespace == namespace, AppCache.key_hash == _hash(key))
               .first())
        if row is None:
            return None
        days = _ttl_days(namespace)
        if days and row.created_at and row.created_at < datetime.utcnow() - timedelta(days=days):
            session.delete(row)
            session.commit()
            return None
        row.hits = (row.hits or 0) + 1
        session.commit()
        return json.loads(row.value_json)
    except Exception:
        return None
    finally:
        session.close()


def set(namespace: str, key: str, value, meta: str = ''):
    session = SessionLocal()
    try:
        h = _hash(key)
        row = (session.query(AppCache)
               .filter(AppCache.namespace == namespace, AppCache.key_hash == h)
               .first())
        if row is None:
            row = AppCache(namespace=namespace, key_hash=h, key_preview=key[:200])
            session.add(row)
        row.value_json = json.dumps(value)
        row.meta = meta
        row.created_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()


def delete(namespace: str, key: str):
    session = SessionLocal()
    try:
        (session.query(AppCache)
         .filter(AppCache.namespace == namespace, AppCache.key_hash == _hash(key))
         .delete())
        session.commit()
    finally:
        session.close()


def clear(namespace: str = ''):
    """Clear one namespace, or everything when namespace is ''. Returns rows removed."""
    session = SessionLocal()
    try:
        q = session.query(AppCache)
        if namespace:
            q = q.filter(AppCache.namespace == namespace)
        n = q.delete()
        session.commit()
        return n
    finally:
        session.close()


def stats():
    """Per-namespace entry counts + total hits, for the Settings page."""
    from sqlalchemy import func
    session = SessionLocal()
    try:
        rows = (session.query(AppCache.namespace,
                              func.count(AppCache.id),
                              func.coalesce(func.sum(AppCache.hits), 0),
                              func.max(AppCache.created_at))
                .group_by(AppCache.namespace).all())
        return [{'namespace': ns, 'entries': n, 'hits': int(h),
                 'newest': newest.isoformat() if newest else '',
                 'ttl_days': _ttl_days(ns)} for ns, n, h, newest in rows]
    finally:
        session.close()
