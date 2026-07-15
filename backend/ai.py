"""Shared AI completion layer for every module (and the /api/v1/ai gateway).

Providers (keys live in settings 'ai_providers', all optional):
  groq      — OpenAI-compatible chat completions (free tier), default llama-3.3-70b-versatile
  gemini    — Google generative language API, default gemini-2.5-flash
  anthropic — Claude, default claude-haiku-4-5-20251001
  ollama    — local

complete() walks the configured fallback order until one provider answers.
Answers are cached in the unified app_cache (namespace passed by the caller).
"""
import json
import re

from .llm import _http_json
from . import cache as cache_svc

DEFAULT_MODELS = {
    'groq': 'llama-3.3-70b-versatile',
    'gemini': 'gemini-2.5-flash',
    'anthropic': 'claude-haiku-4-5-20251001',
    'ollama': 'llama3.1',
}
DEFAULT_ORDER = ['groq', 'gemini', 'anthropic']


def _providers_config():
    from . import settings
    return settings.get('ai_providers', {}) or {}


def _call_groq(prompt, api_key, model, json_mode=False, system=''):
    body = {
        'model': model,
        'messages': ([{'role': 'system', 'content': system}] if system else [])
                    + [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
    }
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    out = _http_json('https://api.groq.com/openai/v1/chat/completions', body,
                     {'Authorization': f'Bearer {api_key}'})
    return out['choices'][0]['message']['content']


def _call_gemini(prompt, api_key, model, json_mode=False, system=''):
    body = {'contents': [{'parts': [{'text': (system + '\n\n' if system else '') + prompt}]}],
            'generationConfig': {'temperature': 0.1}}
    if json_mode:
        body['generationConfig']['responseMimeType'] = 'application/json'
    out = _http_json(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',
        body, {})
    cands = out.get('candidates', [])
    if not cands:
        raise RuntimeError('gemini: empty candidates')
    return ''.join(p.get('text', '') for p in cands[0].get('content', {}).get('parts', []))


def _call_anthropic(prompt, api_key, model, json_mode=False, system=''):
    body = {'model': model, 'max_tokens': 4096,
            'messages': [{'role': 'user', 'content': prompt}]}
    if system or json_mode:
        body['system'] = (system + ' ' if system else '') + \
            ('Respond with ONLY a valid JSON object, no other text.' if json_mode else '')
    out = _http_json('https://api.anthropic.com/v1/messages', body,
                     {'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
    return ''.join(b.get('text', '') for b in out.get('content', []))


def _call_ollama(prompt, base_url, model, json_mode=False, system=''):
    body = {'model': model, 'prompt': (system + '\n\n' if system else '') + prompt,
            'stream': False}
    if json_mode:
        body['format'] = 'json'
    out = _http_json(f'{(base_url or "http://localhost:11434").rstrip("/")}/api/generate',
                     body, {}, timeout=600)
    return out.get('response', '')


def available_providers():
    """Providers that currently have a key configured, in fallback order."""
    cfg = _providers_config()
    order = cfg.get('llm_order') or DEFAULT_ORDER
    out = []
    for p in order:
        if p == 'ollama' and cfg.get('ollama_model'):
            out.append(p)
        elif cfg.get(f'{p}_key'):
            out.append(p)
    return out


def complete(prompt, json_mode=False, system='', cache_ns='ai_complete', use_cache=True):
    """Provider-routed completion with fallback. Returns {'text', 'provider', 'model', 'cached'}.
    Raises RuntimeError if no provider is configured or all fail."""
    cache_key = json.dumps({'p': prompt, 's': system, 'j': json_mode})
    if use_cache and cache_ns:
        hit = cache_svc.get(cache_ns, cache_key)
        if hit is not None:
            return {**hit, 'cached': True}

    cfg = _providers_config()
    providers = available_providers()
    if not providers:
        raise RuntimeError('No AI provider configured — add a Groq/Gemini/Anthropic key in Settings')

    errors = []
    for p in providers:
        model = cfg.get(f'{p}_model') or DEFAULT_MODELS[p]
        try:
            if p == 'groq':
                text = _call_groq(prompt, cfg['groq_key'], model, json_mode, system)
            elif p == 'gemini':
                text = _call_gemini(prompt, cfg['gemini_key'], model, json_mode, system)
            elif p == 'anthropic':
                text = _call_anthropic(prompt, cfg['anthropic_key'], model, json_mode, system)
            elif p == 'ollama':
                text = _call_ollama(prompt, cfg.get('ollama_base_url', ''), model, json_mode, system)
            else:
                continue
            result = {'text': text, 'provider': p, 'model': model}
            if use_cache and cache_ns:
                cache_svc.set(cache_ns, cache_key, result, meta=p)
            return {**result, 'cached': False}
        except Exception as e:
            errors.append(f'{p}: {type(e).__name__}: {e}')
    raise RuntimeError('All AI providers failed — ' + ' | '.join(errors))


def complete_json(prompt, system='', cache_ns='ai_complete', use_cache=True):
    """complete() + robust JSON extraction. Returns (data_dict, result_meta)."""
    res = complete(prompt, json_mode=True, system=system, cache_ns=cache_ns, use_cache=use_cache)
    text = res['text'] or ''
    try:
        return json.loads(text), res
    except Exception:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0)), res
            except Exception:
                pass
    return {}, res
