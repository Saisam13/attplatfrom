"""Web search (Tavily -> Firecrawl fallback) + the MiniMines sourcing-agent
research pipeline, ported from eprintelligence inc/research.php.

Search results are cached in app_cache namespace 'web_search'; the finished
company research report is stored in epr_research (kept until force refresh).

Apify (optional): a configured actor is run per company as an extra context
source specifically aimed at individuals' names/contacts — its raw dataset
items are handed to the extraction LLM alongside the search results rather
than parsed with a fixed schema, since actor output shape varies by actor.
"""
import json
import time
from datetime import datetime, timedelta

from .llm import _http_json
from . import ai
from . import cache as cache_svc

DEFAULT_RESEARCH_TIMEOUT = 90
DEFAULT_RATE_LIMIT_PER_HOUR = 20


class RateLimitError(RuntimeError):
    """Raised by run_company_research() when the hourly research cap is hit."""


def _search_config():
    from . import settings
    return settings.get('ai_providers', {}) or {}


def _tavily(query, api_key, max_results=5, timeout=40):
    out = _http_json('https://api.tavily.com/search',
                     {'api_key': api_key, 'query': query,
                      'search_depth': 'advanced', 'max_results': max_results},
                     {}, timeout=timeout)
    if out.get('error') or not out.get('results'):
        raise RuntimeError(f"tavily: {out.get('error', 'no results')}")
    return [{'url': r.get('url', ''), 'content': r.get('content', '')}
            for r in out['results']]


def _firecrawl(query, api_key, max_results=5, timeout=50):
    out = _http_json('https://api.firecrawl.dev/v1/search',
                     {'query': query, 'limit': max_results},
                     {'Authorization': f'Bearer {api_key}'}, timeout=timeout)
    data = out.get('data') or []
    if not data:
        raise RuntimeError('firecrawl: no results')
    return [{'url': r.get('url', ''), 'content': r.get('description', '') or r.get('markdown', '')[:1500]}
            for r in data]


def web_search(query, max_results=5, use_cache=True, timeout=None):
    """Returns {'results': [{url, content}], 'provider': str}. Cached 7 days."""
    key = json.dumps({'q': query, 'n': max_results})
    if use_cache:
        hit = cache_svc.get('web_search', key)
        if hit is not None:
            return {**hit, 'cached': True}
    cfg = _search_config()
    errors = []
    for provider in (cfg.get('search_order') or ['tavily', 'firecrawl']):
        api_key = cfg.get(f'{provider}_key', '')
        if not api_key:
            continue
        try:
            if provider == 'tavily':
                results = _tavily(query, api_key, max_results, timeout=timeout or 40)
            else:
                results = _firecrawl(query, api_key, max_results, timeout=timeout or 50)
            out = {'results': results, 'provider': provider}
            cache_svc.set('web_search', key, out, meta=provider)
            return {**out, 'cached': False}
        except Exception as e:
            errors.append(f'{provider}: {e}')
    raise RuntimeError('No search provider available — add a Tavily or Firecrawl key in Settings'
                       + (f' ({" | ".join(errors)})' if errors else ''))


def _apify_contacts(company_name, api_key, actor_id, input_template, timeout=60):
    """Run a configured Apify actor and return its raw dataset items as text.
    Actor output schema is not assumed — the extraction LLM reads it as context."""
    template = input_template or '{"query": "{company}"}'
    try:
        # Replace the quoted placeholder with a properly JSON-escaped string first
        # (handles quotes/backslashes in company names); fall back to a raw-text
        # replace of any remaining bare placeholder.
        rendered = template.replace('"{company}"', json.dumps(company_name))
        if '{company}' in rendered:
            rendered = rendered.replace('{company}', json.dumps(company_name)[1:-1])
        body = json.loads(rendered)
    except Exception:
        body = {'query': company_name}
    url = f'https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?token={api_key}'
    items = _http_json(url, body, {}, timeout=timeout)
    if not items:
        raise RuntimeError('apify: no dataset items returned')
    return json.dumps(items)[:8000]


def _enforce_rate_limit(cfg):
    """App-wide cap on run_company_research() calls per rolling hour, to protect
    paid AI/search/Apify credits. 0 = unlimited."""
    limit = cfg.get('research_rate_limit_per_hour', DEFAULT_RATE_LIMIT_PER_HOUR)
    try:
        limit = int(limit)
    except Exception:
        limit = DEFAULT_RATE_LIMIT_PER_HOUR
    if limit <= 0:
        return
    now = datetime.utcnow()
    window_start = now - timedelta(hours=1)
    log = cache_svc.get('rate_limit', 'research_calls') or []
    log = [t for t in log if datetime.fromisoformat(t) > window_start]
    if len(log) >= limit:
        raise RateLimitError(
            f'Research rate limit reached ({limit}/hour) — try again later or raise '
            f'"research_rate_limit_per_hour" in Settings')
    log.append(now.isoformat())
    cache_svc.set('rate_limit', 'research_calls', log)


_RESEARCH_PROMPT = """You are a highly analytical Sourcing Agent for 'MiniMines', a battery recycling company using a patented Hybrid Hydrometallurgy (HHM™) process. Analyze the web search context about '{company}'.
Their official EPR target is {target} Tons.
{math_context}

Context:
{context}

Generate a highly strategic Sourcing Agent Console report.
Rule 1: NEVER hallucinate contact details. If an email or linkedin profile is NOT found in the context, output 'Not Publicly Available'.
Rule 2: ALWAYS provide the 'proof_source_url' for any contact found.

Output a JSON object strictly matching this schema:
{{
  "sourcing_sector": "e.g., EV 2W, EV 4W, Consumer Electronics",
  "chemistry": "e.g., NMC 532, LFP",
  "classification": "e.g., Low-Hanging Fruit, High-Value Target",
  "strategic_summary": "A short paragraph analyzing their EPR liabilities, current partnerships, and urgency.",
  "potential": {{
    "epr_certificates": "Calculated tons of certificates generated",
    "recovery_metals": "Nickel/Cobalt recovery estimates",
    "offset_dependency": "Reduction in raw material import dependency"
  }},
  "contacts": [
    {{
      "name": "Name of executive or key person",
      "role": "Role/Title",
      "email": "Email if available, else 'Not Publicly Available'",
      "linkedin": "LinkedIn URL if available, else 'Not Publicly Available'",
      "proof_source_url": "The exact Source URL from the context where you found this person"
    }}
  ],
  "recent_news_trends": [
    {{
      "date": "YYYY-MM or Recent",
      "headline": "Headline of the news or trend",
      "summary": "1 sentence summary"
    }}
  ]
}}"""


def run_company_research(company_name: str, target_tons: float = 0):
    """Search the web (+ Apify, if configured) and extract the sourcing report.
    Returns (report_dict, meta). Raises RuntimeError if the rate limit is hit."""
    cfg = _search_config()
    _enforce_rate_limit(cfg)

    try:
        max_seconds = int(cfg.get('research_timeout_seconds', DEFAULT_RESEARCH_TIMEOUT))
    except Exception:
        max_seconds = DEFAULT_RESEARCH_TIMEOUT
    deadline = time.monotonic() + max_seconds

    def _remaining(floor_seconds):
        return max(floor_seconds, int(deadline - time.monotonic()))

    query = (f'{company_name} battery recycling EPR targets EV business deals '
             f'executives management team LinkedIn email')
    context_parts = []
    try:
        search = web_search(query, timeout=_remaining(15))
        context_parts.extend(f"Source URL: {r['url']}\nContent: {r['content']}"
                             for r in search['results'])
        search_provider = search['provider']
    except RuntimeError:
        context_parts.append(f'No significant search results found for {company_name}.')
        search_provider = 'none'

    apify_token = cfg.get('apify_token', '')
    apify_actor = cfg.get('apify_actor_id', '')
    if apify_token and apify_actor and _remaining(0) > 10:
        try:
            extra = _apify_contacts(company_name, apify_token, apify_actor,
                                    cfg.get('apify_input_template', ''), timeout=_remaining(10))
            context_parts.append(f"Source: Apify enrichment\nContent: {extra}")
        except Exception as e:
            context_parts.append(f"Source: Apify enrichment\nContent: (lookup failed: {e})")

    context = '\n\n'.join(context_parts)[:15000]

    math_context = ''
    if target_tons and target_tons > 0:
        math_context = (
            f'Given their EPR Target of {target_tons} Tons, if MiniMines secures 100% of this '
            f'feed, we can generate up to {round(target_tons * 0.148, 2)} Tons of EPR Certificates. '
            f'We can recover approx {round(target_tons * 0.1, 2)} Tons of High-Purity Nickel & Cobalt '
            f'via HHM™ process, and refine approx {round(target_tons * 0.08, 2)} Tons of '
            f'Lithium Carbonate equivalent.')

    prompt = _RESEARCH_PROMPT.format(
        company=company_name,
        target=target_tons if target_tons else 'Unknown',
        math_context=math_context, context=context)
    data, meta = ai.complete_json(prompt, system='You output strictly valid JSON.',
                                  cache_ns='', use_cache=False, timeout=_remaining(15))
    if not data:
        raise RuntimeError('AI extraction returned no parseable JSON')
    return data, {'search_provider': search_provider,
                  'llm_provider': meta.get('provider', ''), 'model': meta.get('model', '')}
