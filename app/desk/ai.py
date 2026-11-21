"""AI providers for the long-form workflow: Claude, ChatGPT (OpenAI), Gemini, OpenRouter or any OpenAI-compatible
endpoint (e.g. Ollama on your PC). Keys are pasted by you, stored only in this device's private config folder, and
sent only to the provider they belong to.

Claude is called through the official Anthropic Python SDK (streaming, with server-side refusal fallbacks on the
models that support them). The other providers are called through their own REST APIs.

Note: consumer subscriptions (ChatGPT Plus, Claude Pro, Gemini Advanced) cannot be used by other apps; these
providers only offer API keys for that. "Get API key" opens the provider's sign-in page where you create one.
"""
import json, os, re
from pathlib import Path

PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)", "key_url": "https://platform.claude.com/settings/keys",
               "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"], "default": "claude-opus-5-5"},
    "openai": {"label": "ChatGPT (OpenAI)", "key_url": "https://platform.openai.com/api-keys",
               "base": "https://api.openai.com/v1", "models": [], "default": ""},
    "gemini": {"label": "Gemini (Google)", "key_url": "https://aistudio.google.com/apikey",
               "base": "https://generativelanguage.googleapis.com/v1beta", "models": [], "default": ""},
    "openrouter": {"label": "OpenRouter (many models, one key)", "key_url": "https://openrouter.ai/keys",
                   "base": "https://openrouter.ai/api/v1", "models": [], "default": ""},
    "custom": {"label": "Custom / local (OpenAI-compatible, e.g. Ollama)", "key_url": "",
               "base": "http://localhost:11434/v1", "models": [], "default": ""},
}
ELEVEN_KEY_URL = "https://elevenlabs.io/app/settings/api-keys"
# Claude models that accept server-side refusal fallbacks (Haiku has none)
_FALLBACK_OK = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1")


class AIError(Exception):
    pass


# ---------------------------------------------------------------- config (private, on this device)

def config_path():
    p = os.environ.get("VICE_AI_CONFIG")
    if p:
        return Path(p)
    from desk.core import config_dir
    return config_dir() / "ai.json"


def load():
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        return {"provider": "claude", "models": {}, "keys": {}, "base_url": "", "eleven_key": "", "voice_id": ""}


def save(cfg):
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def update(provider=None, key=None, model=None, base_url=None, eleven_key=None, voice_id=None):
    cfg = load()
    cfg.setdefault("keys", {}); cfg.setdefault("models", {})
    if provider:
        if provider not in PROVIDERS:
            raise AIError(f"unknown provider {provider}")
        cfg["provider"] = provider
    prov = cfg.get("provider") or "claude"
    if key is not None and key.strip():
        cfg["keys"][prov] = key.strip()
    if model is not None and model.strip():
        cfg["models"][prov] = model.strip()
    if base_url is not None:
        cfg["base_url"] = base_url.strip()
    if eleven_key is not None and eleven_key.strip():
        cfg["eleven_key"] = eleven_key.strip()
    if voice_id is not None:
        cfg["voice_id"] = voice_id.strip()
    save(cfg)
    return public(cfg)


def forget(what):
    cfg = load()
    if what == "eleven":
        cfg["eleven_key"] = ""
    else:
        cfg.get("keys", {}).pop(what, None)
    save(cfg)
    return public(cfg)


def public(cfg=None):
    """What the UI may see: never the keys themselves."""
    cfg = cfg or load()
    prov = cfg.get("provider") or "claude"
    return {"provider": prov, "model": current_model(cfg), "base_url": cfg.get("base_url", ""),
            "has_key": {p: bool(cfg.get("keys", {}).get(p)) for p in PROVIDERS},
            "has_eleven": bool(cfg.get("eleven_key")), "voice_id": cfg.get("voice_id", ""),
            "providers": {k: {"label": v["label"], "key_url": v["key_url"], "models": v["models"]} for k, v in PROVIDERS.items()},
            "eleven_key_url": ELEVEN_KEY_URL}


def current_model(cfg=None):
    cfg = cfg or load()
    prov = cfg.get("provider") or "claude"
    return cfg.get("models", {}).get(prov) or PROVIDERS[prov]["default"]


def _key(cfg, prov):
    k = cfg.get("keys", {}).get(prov, "")
    if not k and prov != "custom":
        raise AIError(f"No API key for {PROVIDERS[prov]['label']}. Add one in Long-form > AI model.")
    return k


def _base(cfg, prov):
    return (cfg.get("base_url") if prov == "custom" and cfg.get("base_url") else PROVIDERS[prov].get("base", "")).rstrip("/")


# ---------------------------------------------------------------- models

def list_models(provider=None, key=None, base_url=None):
    import requests
    cfg = load()
    prov = provider or cfg.get("provider") or "claude"
    k = (key or "").strip() or cfg.get("keys", {}).get(prov, "")
    if prov == "claude":
        try:
            import anthropic
        except ImportError:  # Android
            r = requests.get("https://api.anthropic.com/v1/models", timeout=30,
                             headers={"x-api-key": k, "anthropic-version": "2023-06-01"})
            _raise(r, prov)
            return [m["id"] for m in r.json().get("data", [])]
        client = anthropic.Anthropic(api_key=k)
        try:
            return [m.id for m in client.models.list()]
        except anthropic.AuthenticationError:
            raise AIError("Claude rejected this API key")
        except anthropic.APIConnectionError:
            raise AIError("Could not reach the Claude API (check the internet connection)")
    if prov == "gemini":
        r = requests.get(f"{PROVIDERS['gemini']['base']}/models", headers={"x-goog-api-key": k}, timeout=30)
        _raise(r, prov)
        return [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    base = (base_url or "").strip().rstrip("/") if prov == "custom" and base_url else _base(cfg, prov)
    r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {k}"} if k else {}, timeout=30)
    _raise(r, prov)
    return sorted(m["id"] for m in r.json().get("data", []))


def _raise(r, prov):
    if r.status_code in (401, 403):
        raise AIError(f"{PROVIDERS[prov]['label']} rejected this API key")
    if r.status_code >= 400:
        raise AIError(f"{PROVIDERS[prov]['label']} error {r.status_code}: {r.text[:200]}")


# ---------------------------------------------------------------- generation

def generate(system, prompt, max_tokens=16000, effort="high"):
    """One prompt in, text out, with the configured provider and model. Returns (text, usage dict)."""
    cfg = load()
    prov = cfg.get("provider") or "claude"
    model = current_model(cfg)
    if not model:
        raise AIError("Choose a model in Long-form > AI model (Load models).")
    if prov == "claude":
        return _claude(cfg, model, system, prompt, max_tokens, effort)
    if prov == "gemini":
        return _gemini(cfg, model, system, prompt)
    return _openai_compatible(cfg, prov, model, system, prompt)


def _claude(cfg, model, system, prompt, max_tokens, effort):
    try:
        import anthropic
    except ImportError:  # Android: the SDK's compiled dependencies are not available there
        return _claude_http(cfg, model, system, prompt, max_tokens, effort)
    client = anthropic.Anthropic(api_key=_key(cfg, "claude"))
    kwargs = dict(model=model, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": effort})
    try:
        if model in _FALLBACK_OK:
            # a safety decline is retried server-side on Anthropic's recommended fallback model
            with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs) as stream:
                msg = stream.get_final_message()
        else:
            with client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise AIError("Claude rejected the API key")
    except anthropic.NotFoundError:
        raise AIError(f"Claude model not found: {model}")
    except anthropic.RateLimitError:
        raise AIError("Claude rate limit reached: wait a minute and press Retry")
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude API error {e.status_code}: {str(e.message)[:200]}")
    except anthropic.APIConnectionError:
        raise AIError("Could not reach the Claude API (check the internet connection)")
    if msg.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    text = "".join(b.text for b in msg.content if b.type == "text")
    u = msg.usage
    return text, {"input": u.input_tokens, "output": u.output_tokens, "model": msg.model}


def _claude_http(cfg, model, system, prompt, max_tokens, effort):
    """Same Messages API request as _claude(), over HTTPS. Used only where the SDK cannot be installed (Android)."""
    import requests
    headers = {"x-api-key": _key(cfg, "claude"), "anthropic-version": "2023-06-01", "content-type": "application/json"}
    body = {"model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": prompt}], "output_config": {"effort": effort}}
    if model in _FALLBACK_OK:
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
        body["fallbacks"] = "default"
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=body, timeout=900)
    except requests.RequestException:
        raise AIError("Could not reach the Claude API (check the internet connection)")
    if r.status_code == 401:
        raise AIError("Claude rejected the API key")
    if r.status_code == 404:
        raise AIError(f"Claude model not found: {model}")
    if r.status_code == 429:
        raise AIError("Claude rate limit reached: wait a minute and press Retry")
    if r.status_code >= 400:
        raise AIError(f"Claude API error {r.status_code}: {r.text[:200]}")
    msg = r.json()
    if msg.get("stop_reason") == "refusal":
        raise AIError("Claude declined this request")
    text = "".join(b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text")
    u = msg.get("usage", {})
    return text, {"input": u.get("input_tokens"), "output": u.get("output_tokens"), "model": msg.get("model", model)}


def _gemini(cfg, model, system, prompt):
    import requests
    r = requests.post(f"{PROVIDERS['gemini']['base']}/models/{model}:generateContent",
                      headers={"x-goog-api-key": _key(cfg, "gemini")}, timeout=600,
                      json={"systemInstruction": {"parts": [{"text": system}]},
                            "contents": [{"role": "user", "parts": [{"text": prompt}]}]})
    _raise(r, "gemini")
    j = r.json()
    try:
        parts = j["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise AIError(f"Gemini returned no text ({str(j.get('promptFeedback') or j)[:200]})")
    u = j.get("usageMetadata", {})
    return "".join(p.get("text", "") for p in parts), {"input": u.get("promptTokenCount"), "output": u.get("candidatesTokenCount"), "model": model}


def _openai_compatible(cfg, prov, model, system, prompt):
    import requests
    k = cfg.get("keys", {}).get(prov, "")
    if not k and prov != "custom":
        _key(cfg, prov)
    headers = {"Authorization": f"Bearer {k}"} if k else {}
    r = requests.post(f"{_base(cfg, prov)}/chat/completions", headers=headers, timeout=600,
                      json={"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    _raise(r, prov)
    j = r.json()
    try:
        text = j["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        raise AIError(f"{PROVIDERS[prov]['label']} returned no text: {str(j)[:200]}")
    u = j.get("usage") or {}
    return text, {"input": u.get("prompt_tokens"), "output": u.get("completion_tokens"), "model": model}


def generate_json(system, prompt, **kw):
    """generate() and parse the first JSON object/array in the reply (models sometimes wrap it in prose or fences)."""
    text, usage = generate(system + "\nReply with valid JSON only, no commentary.", prompt, **kw)
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    body = m.group(1) if m else text
    starts = [i for i in (body.find("{"), body.find("[")) if i >= 0]
    if not starts:
        raise AIError("the model did not return JSON")
    try:
        return json.JSONDecoder().raw_decode(body[min(starts):])[0], usage
    except ValueError:
        raise AIError("could not parse the model's JSON reply")
