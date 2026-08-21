"""Provider-agnostic LLM adapter for HYBRID chemical matching.

Supported providers (config.json -> {"llm": {"provider": ..., "api_key": ..., "model": ...}}):
  - "bharatrouter" (OpenAI-compatible; reuses the key from Settings -> AI providers
    if 'api_key' isn't set here, so it doesn't need to be entered twice)
  - "anthropic" (default model claude-sonnet-5; claude-haiku-4-5-20251001 for cheap)
  - "gemini"    (default model gemini-2.5-flash)
  - "ollama"    (local; model required, base_url optional, default http://localhost:11434)
  - "off"       (default — pipeline runs pure rule-based)

Only descriptions scoring below the 60% direct-match threshold are sent, batched,
with the base chemical list in the prompt. Answers are cached in SQLite so repeat
descriptions are never re-sent. All failures are swallowed -> rule-based fallback.
"""
import json
import re
import urllib.request

DEFAULT_MODELS = {
    'bharatrouter': 'qwen2.5-7b-instruct',
    'anthropic': 'claude-sonnet-5',
    'gemini': 'gemini-2.5-flash',
    'ollama': 'llama3.1',
}
BATCH_SIZE = 40

_PROMPT = """You are a chemical trade-data analyst. Below is a numbered list of noisy product descriptions from export-import shipping records, and a portfolio of base chemical names.

For each description, decide whether it refers to one of the portfolio chemicals. Respond with a JSON object mapping each description number (as a string) to the EXACT portfolio chemical name, or null if it does not match any portfolio chemical. Respond with ONLY the JSON object, no other text.

PORTFOLIO CHEMICALS:
{portfolio}

DESCRIPTIONS:
{descriptions}"""


def _http_json(url, payload, headers, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', **headers}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _call_bharatrouter(prompt, api_key, model):
    out = _http_json(
        'https://api.bharatrouter.com/v1/chat/completions',
        {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
         'temperature': 0.1, 'data_policy': 'india_only', 'optimize': 'auto'},
        {'Authorization': f'Bearer {api_key}'})
    return out['choices'][0]['message']['content']


def _call_anthropic(prompt, api_key, model):
    out = _http_json(
        'https://api.anthropic.com/v1/messages',
        {'model': model, 'max_tokens': 4096,
         'messages': [{'role': 'user', 'content': prompt}]},
        {'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
    return ''.join(b.get('text', '') for b in out.get('content', []))


def _call_gemini(prompt, api_key, model):
    out = _http_json(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
        {'contents': [{'parts': [{'text': prompt}]}]}, {})
    cands = out.get('candidates', [])
    if not cands:
        return ''
    return ''.join(p.get('text', '') for p in cands[0].get('content', {}).get('parts', []))


def _call_ollama(prompt, model, base_url):
    out = _http_json(
        f'{base_url.rstrip("/")}/api/generate',
        {'model': model, 'prompt': prompt, 'stream': False},
        {}, timeout=600)
    return out.get('response', '')


def _extract_json(text):
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


class LlmMatcher:
    """Callable: (descriptions: list[str], base_names: list[str]) -> dict desc -> name|None"""

    def __init__(self, llm_config, session_factory, log=print):
        self.provider = (llm_config or {}).get('provider', 'off')
        self.api_key = (llm_config or {}).get('api_key', '')
        if self.provider == 'bharatrouter' and not self.api_key:
            # Reuse the key from Settings -> AI providers so it isn't entered twice.
            try:
                from . import settings
                self.api_key = settings.get('ai_providers', {}).get('bharatrouter_key', '')
            except Exception:
                pass
        self.model = (llm_config or {}).get('model', '') or DEFAULT_MODELS.get(self.provider, '')
        self.base_url = (llm_config or {}).get('base_url', 'http://localhost:11434')
        self.session_factory = session_factory
        self.log = log

    @property
    def enabled(self):
        if self.provider in ('off', '', None):
            return False
        if self.provider in ('bharatrouter', 'anthropic', 'gemini') and not self.api_key:
            return False
        return self.provider in ('bharatrouter', 'anthropic', 'gemini', 'ollama')

    def _complete(self, prompt):
        if self.provider == 'bharatrouter':
            return _call_bharatrouter(prompt, self.api_key, self.model)
        if self.provider == 'anthropic':
            return _call_anthropic(prompt, self.api_key, self.model)
        if self.provider == 'gemini':
            return _call_gemini(prompt, self.api_key, self.model)
        if self.provider == 'ollama':
            return _call_ollama(prompt, self.model, self.base_url)
        return ''

    def __call__(self, descriptions, base_names):
        from . import cache as cache_svc
        result = {}
        if not self.enabled:
            return result
        # 1. unified-cache lookup (namespace 'llm_match', keyed by description)
        pending = []
        for d in descriptions:
            cached = cache_svc.get('llm_match', d)
            if cached is not None:
                result[d] = cached or None
            else:
                pending.append(d)
        self.log(f"  LLM: {len(descriptions)-len(pending)} cached, {len(pending)} to query ({self.provider}/{self.model})")

        # 2. batched calls
        portfolio = '\n'.join(f'- {n}' for n in base_names)
        valid = set(base_names)
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i:i + BATCH_SIZE]
            desc_block = '\n'.join(f'{j+1}. {d[:300]}' for j, d in enumerate(batch))
            prompt = _PROMPT.format(portfolio=portfolio, descriptions=desc_block)
            try:
                text = self._complete(prompt)
                mapping = _extract_json(text)
            except Exception as e:
                self.log(f"  LLM batch failed ({e}); falling back to rule-based for this batch")
                continue
            for j, d in enumerate(batch):
                hit = mapping.get(str(j + 1))
                name = hit if isinstance(hit, str) and hit in valid else None
                result[d] = name
                cache_svc.set('llm_match', d, name or '', meta=self.provider)
        return result
