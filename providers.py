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
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
VAULT = Path.home() / ".concierge" / "vault.json"
DEMO_RUN = REPO / "demo" / "offline_run.json"
MODEL_REGISTRY = Path.home() / "RootBase" / "model_registry.json"
CALL_LOG = REPO / "logs" / "calls.jsonl"
LOG_MAX_BYTES = 5_000_000

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
        if model:
            return lambda p: groq_text(p, model)
        return lambda p: ask_with_fallback(p, "groq", groq_text)
    if provider == "gemini":
        if model:
            return lambda p: gemini_text(p, model)
        return lambda p: ask_with_fallback(p, "gemini", gemini_text)
    raise ValueError(f"unknown provider: {provider}")


# Ordered fallback ladders. A model that answers 503/404 is unavailable on this
# account (a real case: gemini-3.1-flash-lite is listed but 503s, while
# gemini-flash-lite-latest works), so the next candidate is tried instead of
# failing the run. Tested-first, because an untested id wastes a call.
# Only ids observed answering on this account go in the trusted order. The
# Groq key cannot list models (the /models endpoint answers 403), and guessed
# ids returned 404, so Groq has one trusted entry plus whatever the registry
# supplies. Gemini's extras are unordered guesses kept only as a last resort.
MODEL_LADDERS = {
    "groq": (DEFAULT_GROQ,),
    "gemini": (DEFAULT_GEMINI, "gemini-3.1-flash-lite", "gemini-flash-latest",
               "gemini-2.5-flash"),
}

_last = threading.local()


def last_model_used() -> str:
    """Model that actually answered on this thread, for honest metadata."""
    return getattr(_last, "model", "")


def registry_candidates(provider: str) -> list[str]:
    """Extra model ids from ~/RootBase/model_registry.json, best effort.

    The registry is produced by ~/bin/model_scout.py. Its shape is not ours to
    depend on, so this walks it defensively and returns nothing on any surprise.
    """
    try:
        blob = json.loads(MODEL_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entry = (blob.get("providers") or {}).get(provider)
    if not isinstance(entry, dict):
        return []
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            status = str(node.get("status") or "").lower()
            if status not in ("dead", "paid", "unavailable", "retired"):
                for key in ("id", "model", "name"):
                    val = node.get(key)
                    if isinstance(val, str) and len(val) > 2:
                        found.append(val)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(entry)
    return [m for m in dict.fromkeys(found) if " " not in m][:8]


def model_candidates(provider: str) -> list[str]:
    """Ordered candidates: the tested ladder first, registry extras after."""
    env = os.environ.get("GRIM_MODEL", "").strip()
    base = [env] if env else list(MODEL_LADDERS.get(provider, ()))
    return list(dict.fromkeys(base + registry_candidates(provider)))


def log_call(record: dict) -> None:
    """Append one JSON line to logs/calls.jsonl. Never logs prompts or keys.

    The point is cost, latency, and failure history -- enough to build an eval
    set later. Raw prompt text is deliberately not stored; only a hash and a
    length, so the log can be shared without leaking the artifact.
    """
    if os.environ.get("GRIM_NO_LOG"):
        return
    try:
        CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        if CALL_LOG.is_file() and CALL_LOG.stat().st_size > LOG_MAX_BYTES:
            CALL_LOG.replace(CALL_LOG.with_suffix(".jsonl.1"))
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  **record}
        with CALL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass  # logging must never break a run


def _log_attempt(provider: str, model: str, mode: str, prompt: str,
                 started: float, ok: bool, error: str = "",
                 response_chars: int = 0) -> None:
    log_call({"provider": provider, "model_requested": model,
              "model_used": model if ok else "", "mode": mode, "ok": ok,
              "error": error[:160], "response_chars": response_chars,
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:16],
              "prompt_chars": len(prompt),
              "latency_ms": int((time.monotonic() - started) * 1000)})


def ask_with_fallback(prompt: str, provider: str, fn, mode: str = "",
                      sleep=None, backoff=(2, 4, 8)) -> str:
    """Call `fn(prompt, model)`, recovering from the two different failures.

    - 429 means the account is busy, not that the model is wrong. Back off and
      retry the SAME model; switching models on a rate limit just spreads the
      throttling across the ladder and loses the good model.
    - 503/404 mean the model is unavailable here. Move to the next candidate.
    - Anything else (bad key, malformed request) stops immediately: retrying
      cannot fix it.

    Records every attempt, and `last_model_used()` reports the model that
    actually answered.
    """
    sleep = sleep or time.sleep
    candidates = model_candidates(provider)
    if not candidates:
        raise ValueError(f"no models known for provider {provider}")
    errors = []
    for model in candidates:
        for pause in (0, *backoff):
            if pause:
                sleep(pause)
            started = time.monotonic()
            try:
                text = fn(prompt, model)
            except RuntimeError as e:
                msg = str(e)
                errors.append(f"{model}: {msg}")
                _log_attempt(provider, model, mode, prompt, started, False, msg)
                if "429" in msg:
                    continue  # same model, after a pause
                if "503" not in msg and "404" not in msg:
                    raise
                break  # unavailable: next model
            else:
                _last.model = model
                _log_attempt(provider, model, mode, prompt, started, True,
                             response_chars=len(text or ""))
                return text
    raise RuntimeError("every model candidate failed: " + " | ".join(errors[-4:]))


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
