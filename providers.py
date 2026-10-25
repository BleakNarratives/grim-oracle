#!/usr/bin/env python3
"""providers.py -- model calls plus an offline canned mode. Stdlib only.

Keys are read from the environment or ~/.concierge/vault.json and are never
returned to a caller, logged, or put in an error message.

`offline` is not a model. It replays demo/offline_run.json so the UI works with
no network, no key, and no credits. Every response from it is labeled demo=True
upstream, because canned data presented as a model reaction is exactly the kind
of thing this project exists to catch.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
VAULT = Path.home() / ".concierge" / "vault.json"
DEMO_RUN = REPO / "demo" / "offline_run.json"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ = "openai/gpt-oss-120b"
DEFAULT_GEMINI = "gemini-flash-lite-latest"

SECRET_RES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]{0,32}PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{10,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
]


def redact(text: str) -> tuple[str, int]:
    """Mask secret-shaped strings. Returns (clean_text, count). Never returns the secret."""
    n = 0
    for name, rx in SECRET_RES:
        def _sub(m, name=name):
            fp = hashlib.sha256(m.group(0).encode()).hexdigest()[:10]
            return f"[REDACTED:{name}:{fp}]"
        text, hits = rx.subn(_sub, text or "")
        n += hits
    return text, n


def _vault() -> dict:
    try:
        return json.loads(VAULT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _key(provider: str) -> str:
    env = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}[provider]
    if os.environ.get(env):
        return os.environ[env].split(",")[0]
    entry = (_vault().get("keys") or {}).get(provider)
    if not isinstance(entry, dict) or entry.get("status") in ("dead", "revoked"):
        return ""
    return (entry.get("key") or "").split(",")[0]


def _post(url: str, body: dict, headers: dict, provider: str, model: str) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {provider} ({model})") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"request to {provider} failed: {type(e).__name__}") from None


def groq_text(prompt: str, model: str = DEFAULT_GROQ) -> str:
    key = _key("groq")
    if not key:
        raise RuntimeError("no groq key in env or vault; nothing sent")
    data = _post(GROQ_URL,
                 {"model": model, "messages": [{"role": "user", "content": prompt[:15000]}]},
                 {"Content-Type": "application/json",
                  "Authorization": f"Bearer {key}",
                  "User-Agent": "grim-oracle/1.0"}, "groq", model)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("no text in groq response") from None


def gemini_text(prompt: str, model: str = DEFAULT_GEMINI) -> str:
    key = _key("gemini")
    if not key:
        raise RuntimeError("no gemini key in env or vault; nothing sent")
    data = _post(GEMINI_URL.format(model=model),
                 {"contents": [{"parts": [{"text": prompt[:15000]}]}]},
                 {"Content-Type": "application/json", "x-goog-api-key": key},
                 "gemini", model)
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("no text in gemini response") from None


def offline_text(prompt: str) -> str:
    """Replay canned data. No network. The caller must label the result as demo."""
    try:
        blob = json.loads(DEMO_RUN.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"offline demo data unavailable: {type(e).__name__}") from None
    key = "cannibal" if "CANNIBAL MODE" in (prompt or "") else "civil"
    run = blob.get(key)
    if not run:
        raise RuntimeError(f"offline demo has no '{key}' run")
    return json.dumps(run)


def get_ask(provider: str, model: str = ""):
    """Return ask(prompt) -> str for a provider. Raises ValueError if unknown."""
    if provider == "offline":
        return offline_text
    if provider == "groq":
        return lambda p: groq_text(p, model or DEFAULT_GROQ)
    if provider == "gemini":
        return lambda p: gemini_text(p, model or DEFAULT_GEMINI)
    raise ValueError(f"unknown provider: {provider}")


def default_model(provider: str) -> str:
    return {"groq": DEFAULT_GROQ, "gemini": DEFAULT_GEMINI,
            "offline": "canned"} .get(provider, "")


def provider_status(provider: str) -> dict:
    """Enough to tell the user why a run will fail, without leaking the key."""
    if provider == "offline":
        return {"provider": "offline", "ready": DEMO_RUN.is_file(),
                "note": "canned demo data, not a model"}
    if provider not in ("groq", "gemini"):
        return {"provider": provider, "ready": False, "note": "unknown provider"}
    has = bool(_key(provider))
    return {"provider": provider, "ready": has,
            "note": "key found" if has else "no key in env or vault"}
