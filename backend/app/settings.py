"""BYOK provider settings, persisted to data/settings.json (gitignored).

Single-user, local machine: the API key is stored in plaintext in a
gitignored file with 0600 semantics (data/ is excluded from git). The GET
endpoint never returns the full key — only a mask + presence flag.

Provider presets:
  deepseek -> https://api.deepseek.com, thinking-disabled ON
              (v4-flash is a reasoning model; without the flag it burns the
              whole output budget on reasoning and never answers)
  openai   -> https://api.openai.com/v1, thinking-disabled OFF
              (unknown request params are rejected by OpenAI-compatible APIs)
  custom   -> user-supplied base_url (ollama, groq, local proxies...), OFF
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORE_PATH = DATA_DIR / "settings.json"

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "disable_thinking": True},
    "openai": {"base_url": "https://api.openai.com/v1", "disable_thinking": False},
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "disable_thinking": False,
    },
    "custom": {"base_url": "", "disable_thinking": False},
}

DEFAULTS = {
    "provider": "deepseek",
    "base_url": PROVIDERS["deepseek"]["base_url"],
    "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    "api_key": "",
    "price_in_per_m": None,  # USD per 1M input tokens (user-set; 0/None = no estimate)
    "price_out_per_m": None,
    "disable_thinking": True,
}

ALLOWED_KEYS = {"provider", "base_url", "model", "api_key", "price_in_per_m", "price_out_per_m"}


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:3] + "••••" + key[-4:]


def load_settings() -> dict:
    data = {}
    if STORE_PATH.exists():
        try:
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save_settings(payload: dict) -> dict:
    """Merge payload into stored settings. An empty/absent api_key keeps the
    existing key (the UI never sends the full key back); an explicit
    `clear_api_key: true` removes it. Provider presets force base_url +
    disable_thinking unless base_url is explicitly given."""
    current = load_settings()
    merged = dict(current)
    updates = {k: v for k, v in payload.items() if k in ALLOWED_KEYS}
    if payload.get("clear_api_key"):
        merged["api_key"] = ""
    elif not updates.get("api_key"):
        updates.pop("api_key", None)  # keep existing
    merged.update(updates)
    if not merged.get("api_key") and not payload.get("clear_api_key"):
        merged["api_key"] = current.get("api_key", "")

    preset = PROVIDERS.get(merged.get("provider", "deepseek"))
    if preset:
        # provider switch must override a stale base_url unless the user
        # explicitly sent one in this payload
        if "base_url" not in updates or not updates.get("base_url"):
            merged["base_url"] = preset["base_url"]
        merged["disable_thinking"] = preset["disable_thinking"]
    if not merged.get("model"):
        merged["model"] = DEFAULTS["model"]

    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    return merged


def public_settings() -> dict:
    s = load_settings()
    key = s.pop("api_key", "")
    return {
        **s,
        "api_key_present": bool(key),
        "api_key_masked": _mask(key),
        # true when a key is available from any source (settings or env fallback)
        "provider_configured": bool(key or os.environ.get("DEEPSEEK_API_KEY")),
    }


def test_connection(base_url: str, api_key: str, model: str | None = None,
                    http=None) -> dict:
    """Validate a key with one cheap call. Tries the OpenAI-compatible
    /models endpoint; if that 404s (e.g. Gemini's compat layer), falls back
    to a minimal chat completion. `http` is injectable for tests."""
    import httpx

    hx = http or httpx
    headers = {"Authorization": f"Bearer {api_key}"}
    base = base_url.rstrip("/")
    try:
        r = hx.get(f"{base}/models", headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        return {"ok": True, "models": models[:10]}
    except Exception:
        pass  # fall back to a trivial completion
    try:
        model = model or "deepseek-v4-flash"
        r = hx.post(
            f"{base}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=15,
        )
        r.raise_for_status()
        return {"ok": True, "models": [model], "via": "completion"}
    except Exception as e:
        raise RuntimeError(f"{e}") from e
