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
- 2026-10-25 — Added a model ladder: 503/404 moves to the next candidate,
  429 backs off and retries the same one, other errors stop. Reports
  meta.model_actual so a fallback is visible. Registry extras come from
  ~/RootBase/model_registry.json when present.
- 2026-10-25 — Added logs/calls.jsonl (provider, models, mode, latency, prompt
  hash and length; never prompt text) with --no-log and 5MB rotation.
- 2026-10-25 — Added eval/: 5 labeled pitches, a strict scorer, live runner.
  Groq result: recall 1.00 (5/5), precision 0.63 (5/8) after adjudicating two
  genuinely ambiguous labels.
- 2026-10-25 — Added compare_seeds.py and a COMPARE SEEDS button. First live
  comparison flipped HOLD -> NEEDS-REVIEW on cast alone.
- 2026-10-25 — Added branding/PROMPTS.md for concept art.
