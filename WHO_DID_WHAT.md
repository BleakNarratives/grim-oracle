# WHO_DID_WHAT — GRIM Oracle

Append-only. Add entries at the bottom; never rewrite earlier ones.

- 2026-10-25 — Extracted from `turd-merger-tools`, where the market sim had
  lived as `Grim/`. It had outgrown that repo: its own server, page, and
  invariants, none of which belong to the safety-bus toolkit.
- 2026-10-25 — Rewrote the page off `api.anthropic.com`, which only worked
  where a hosted product proxied the request. Now `grim_serve.py` holds the key
  and the browser talks to 127.0.0.1.
- 2026-10-25 — Added guaranteed dissent graded as strong/weak/missing, with one
  strict retry and an honest `missing` result.
- 2026-10-25 — Added cannibal mode: hostile cast plus a fallacy ledger whose
  quotes are verified against the artifact.
- 2026-10-25 — Added offline mode replaying `demo/offline_run.json`.
- 2026-10-25 — Verified Gemini: only `gemini-flash-lite-latest` is available on
  this account; stronger models 503. Reported, not hidden.
