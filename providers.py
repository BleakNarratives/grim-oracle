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
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_GROQ = "openai/gpt-oss-120b"
DEFAULT_GEMINI = "gemini-flash-lite-latest"
DEFAULT_DEEPSEEK = "deepseek-chat"

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


def key_pool(provider: str) -> list[str]:
    """Every usable key for a provider, in order. Never returned to a caller.

    The vault stores either one key or a comma-separated pool. Keeping the pool
    means a throttled key can be skipped instead of ending the run.
    """
    env = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider)
    if env and os.environ.get(env):
        return [k.strip() for k in os.environ[env].split(",") if k.strip()]
    entry = (_vault().get("keys") or {}).get(provider)
    if not isinstance(entry, dict) or entry.get("status") in ("dead", "revoked"):
        return []
    return [k.strip() for k in str(entry.get("key") or "").split(",") if k.strip()]


def _key(provider: str) -> str:
    pool = key_pool(provider)
    return pool[0] if pool else ""


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


def groq_text(prompt: str, model: str = DEFAULT_GROQ, key: str = "") -> str:
    key = key or _key("groq")
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


def gemini_text(prompt: str, model: str = DEFAULT_GEMINI, key: str = "") -> str:
    key = key or _key("gemini")
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


def deepseek_text(prompt: str, model: str = DEFAULT_DEEPSEEK, key: str = "") -> str:
    """OpenAI-compatible chat call. Not the primary path: it is the rung the
    cascade steps onto when Groq throttles, because its key is verified live
    and its wire format costs nothing extra to support."""
    key = key or _key("deepseek")
    if not key:
        raise RuntimeError("no deepseek key in env or vault; nothing sent")
    data = _post(DEEPSEEK_URL,
                 {"model": model, "max_tokens": 2048,
                  "messages": [{"role": "user", "content": prompt[:15000]}]},
                 {"Content-Type": "application/json",
                  "Authorization": f"Bearer {key}",
                  "User-Agent": "grim-oracle/1.0"}, "deepseek", model)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("no text in deepseek response") from None


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
    if provider == "deepseek":
        if model:
            return lambda p: deepseek_text(p, model)
        return lambda p: ask_with_fallback(p, "deepseek", deepseek_text)
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
    "deepseek": (DEFAULT_DEEPSEEK,),
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
            dead_lane = status in ("dead", "paid", "unavailable", "retired")
            # model_scout records catalogs as `models: ["id", ...]`, while
            # OpenRouter rows are dicts. Handle both or half the registry is
            # invisible, which is how Gemini stayed out of the ladder.
            models = node.get("models")
            if isinstance(models, list) and not dead_lane:
                for m in models:
                    if isinstance(m, str) and len(m) > 2:
                        found.append(m)
                    elif isinstance(m, dict):
                        walk(m)
            if not dead_lane:
                for key in ("id", "model", "name"):
                    val = node.get(key)
                    if isinstance(val, str) and len(val) > 2:
                        found.append(val)
            for k, v in node.items():
                if k != "models":
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
    """Call `fn(prompt, model, key)`, recovering from three kinds of failure.

    - 429 / quota: the KEY is throttled. Try the next key in the pool before
      waiting. Waiting on one key while others sit idle is the whole point of a
      pool.
    - 503 / 404: the MODEL is unavailable here. Move to the next candidate.
    - 401 / 403: this key is not accepted. Drop it for the rest of the process
      and try the next one.
    - Anything else stops immediately; retrying cannot fix a malformed request.

    Records every attempt. `last_model_used()` reports what actually answered.
    """
    sleep = sleep or time.sleep
    candidates = model_candidates(provider)
    if not candidates:
        raise ValueError(f"no models known for provider {provider}")
    pool = key_pool(provider)
    if not pool:
        raise RuntimeError(f"no {provider} key in env or vault; nothing sent")
    usable = list(pool)
    errors = []

    for model in candidates:
        unavailable = False
        for pause in (0, *backoff):
            if unavailable:
                break  # 503/404 is about the model, not the timing
            if pause:
                sleep(pause)
            for key in list(usable):
                started = time.monotonic()
                try:
                    text = fn(prompt, model, key)
                except RuntimeError as e:
                    msg = str(e)
                    errors.append(f"{model}: {msg}")
                    _log_attempt(provider, model, mode, prompt, started, False, msg)
                    if any(code in msg for code in ("429", "quota")):
                        continue  # another key may still have room
                    if any(code in msg for code in ("401", "403")):
                        if len(usable) > 1:
                            usable = [k for k in usable if k != key]
                        continue
                    if "503" in msg or "404" in msg:
                        unavailable = True
                        break
                    raise
                else:
                    _last.model = model
                    _log_attempt(provider, model, mode, prompt, started, True,
                                 response_chars=len(text or ""))
                    return text
    raise RuntimeError("every model and key candidate failed: "
                       + " | ".join(errors[-4:]))


def default_model(provider: str) -> str:
    return {"groq": DEFAULT_GROQ, "gemini": DEFAULT_GEMINI,
            "offline": "canned"} .get(provider, "")


def registry_age_days() -> float | None:
    """How stale ~/RootBase/model_registry.json is, in days. None if absent."""
    try:
        blob = json.loads(MODEL_REGISTRY.read_text(encoding="utf-8"))
        stamp = str(blob.get("generated_at") or "")
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - when).total_seconds() / 86400, 1)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def doctor(providers_to_check=None) -> dict:
    """One honest readiness report. No calls, no cost, no key material."""
    names = providers_to_check or ["groq", "gemini", "offline"]
    out = {"registry": {"path": str(MODEL_REGISTRY),
                        "age_days": registry_age_days()},
           "providers": {}}
    for name in names:
        status = provider_status(name)
        status["ladder"] = model_candidates(name) if name != "offline" else []
        out["providers"][name] = status
    age = out["registry"]["age_days"]
    out["warnings"] = []
    if age is None:
        out["warnings"].append("no model registry; ladders fall back to built-ins")
    elif age > 14:
        out["warnings"].append(f"registry is {age:.0f} days old; run ~/bin/model_scout.py")
    for name, st in out["providers"].items():
        if not st["ready"]:
            out["warnings"].append(f"{name} is not ready: {st['note']}")
    return out


def provider_status(provider: str) -> dict:
    """Enough to tell the user why a run will fail, without leaking the key."""
    if provider == "offline":
        return {"provider": "offline", "ready": DEMO_RUN.is_file(),
                "note": "canned demo data, not a model"}
    if provider not in ("groq", "gemini"):
        return {"provider": provider, "ready": False, "note": "unknown provider"}
    pool = key_pool(provider)
    return {"provider": provider, "ready": bool(pool),
            "keys_in_pool": len(pool),
            "note": f"{len(pool)} key(s) in pool" if pool else "no key in env or vault"}
