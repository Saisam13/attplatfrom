"""Shared AI gateway (/api/v1/ai/*) — the same provider-routed, cached AI layer
this platform uses internally, exposed for other internal tools. All endpoints
require an X-API-Key (created on the Settings page), same as /api/v1/leads.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import ai
from . import research as research_svc
from .leads import require_api_key

router = APIRouter(prefix='/api/v1/ai', tags=['external-ai'])


class CompleteIn(BaseModel):
    prompt: str
    system: str = ''
    json_mode: bool = False
    use_cache: bool = True


@router.post('/complete')
def v1_complete(request: Request, body: CompleteIn):
    """Generic provider-routed completion (Groq -> Gemini -> Anthropic fallback,
    answers cached in the unified app cache)."""
    require_api_key(request)
    try:
        return ai.complete(body.prompt, json_mode=body.json_mode, system=body.system,
                           cache_ns='ai_complete' if body.use_cache else '',
                           use_cache=body.use_cache)
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class SearchIn(BaseModel):
    query: str
    max_results: int = 5


@router.post('/search')
def v1_search(request: Request, body: SearchIn):
    """Web search through the configured providers (Tavily -> Firecrawl)."""
    require_api_key(request)
    try:
        return research_svc.web_search(body.query, max_results=min(body.max_results, 10))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class ResearchIn(BaseModel):
    company: str
    target_tons: float = 0


@router.post('/research')
def v1_research(request: Request, body: ResearchIn):
    """Full sourcing-agent company research (search + extraction), uncached —
    use the EPR module endpoints for cached per-company research."""
    require_api_key(request)
    try:
        data, meta = research_svc.run_company_research(body.company, body.target_tons)
        return {'research': data, 'meta': meta}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class MatchIn(BaseModel):
    descriptions: list[str]
    portfolio: list[str]


@router.post('/match')
def v1_match(request: Request, body: MatchIn):
    """Chemical description -> portfolio matching, same engine + cache the
    trading pipeline uses (namespace llm_match)."""
    require_api_key(request)
    if len(body.descriptions) > 500:
        raise HTTPException(400, 'Max 500 descriptions per call')
    from .llm import LlmMatcher
    from .db import SessionLocal
    from . import settings
    m = LlmMatcher(settings.get('llm', {}), SessionLocal, log=lambda *_: None)
    if not m.enabled:
        raise HTTPException(502, 'Matching LLM not configured (Settings → LLM matching)')
    return m(body.descriptions, body.portfolio)
