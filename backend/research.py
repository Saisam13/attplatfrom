"""Web search (Tavily -> Firecrawl fallback) + the MiniMines sourcing-agent
research pipeline, ported from eprintelligence inc/research.php.

Search results are cached in app_cache namespace 'web_search'; the finished
company research report is stored in epr_research (kept until force refresh).
"""
import json

from .llm import _http_json
from . import ai
from . import cache as cache_svc


def _search_config():
    from . import settings
    return settings.get('ai_providers', {}) or {}


def _tavily(query, api_key, max_results=5):
    out = _http_json('https://api.tavily.com/search',
                     {'api_key': api_key, 'query': query,
                      'search_depth': 'advanced', 'max_results': max_results},
                     {}, timeout=40)
    if out.get('error') or not out.get('results'):
        raise RuntimeError(f"tavily: {out.get('error', 'no results')}")
    return [{'url': r.get('url', ''), 'content': r.get('content', '')}
            for r in out['results']]


def _firecrawl(query, api_key, max_results=5):
    out = _http_json('https://api.firecrawl.dev/v1/search',
                     {'query': query, 'limit': max_results},
                     {'Authorization': f'Bearer {api_key}'}, timeout=50)
    data = out.get('data') or []
    if not data:
        raise RuntimeError('firecrawl: no results')
    return [{'url': r.get('url', ''), 'content': r.get('description', '') or r.get('markdown', '')[:1500]}
            for r in data]


def web_search(query, max_results=5, use_cache=True):
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
            results = _tavily(query, api_key, max_results) if provider == 'tavily' \
                else _firecrawl(query, api_key, max_results)
            out = {'results': results, 'provider': provider}
            cache_svc.set('web_search', key, out, meta=provider)
            return {**out, 'cached': False}
        except Exception as e:
            errors.append(f'{provider}: {e}')
    raise RuntimeError('No search provider available — add a Tavily or Firecrawl key in Settings'
                       + (f' ({" | ".join(errors)})' if errors else ''))


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
    """Search the web + extract the sourcing report. Returns (report_dict, meta)."""
    query = (f'{company_name} battery recycling EPR targets EV business deals '
             f'executives management team LinkedIn email')
    try:
        search = web_search(query)
        context = '\n\n'.join(f"Source URL: {r['url']}\nContent: {r['content']}"
                              for r in search['results'])[:15000]
        search_provider = search['provider']
    except RuntimeError:
        context = f'No significant search results found for {company_name}.'
        search_provider = 'none'

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
                                  cache_ns='', use_cache=False)
    if not data:
        raise RuntimeError('AI extraction returned no parseable JSON')
    return data, {'search_provider': search_provider,
                  'llm_provider': meta.get('provider', ''), 'model': meta.get('model', '')}
