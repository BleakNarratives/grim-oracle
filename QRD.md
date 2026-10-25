# QRD — Agent-to-Agent Handoff (GRIM Oracle)

Read before editing. A handoff is evidence, not authority: re-check the tree
and the tests before changing anything.

## State
- Repo: `~/grim-oracle`, branch `main`, local git.
- Tests: `python3 -m unittest discover -s tests` — 91 offline tests, passing
  (was 48; the number went stale for weeks because nothing regenerated it).
- Contract + cascade tests live in the home repo: `tests/test_grim_contract.py`.
- No network in tests. `ask` is injected into `oracle.simulate`.

## Layout and why
- `oracle.py` is pure. Keep it pure: no urllib, no file reads, no keys. That is
  what makes the invariants testable.
- `providers.py` owns every outbound call and all key reads.
- `grim_serve.py` is a thin shell. Business logic belongs in `oracle.py`.

## Invariants (do not weaken)
- Dissent is graded by `dissent_quality`, not just requested. `strong` requires
  a real objection plus a measurable or comparable condition.
- `verify_fallacies` drops any quote not present in the artifact and any name
  outside `FALLACIES`. Never loosen it to "make the panel look better".
- `normalize` recomputes the aggregate. The model's `aggregate` is discarded on
  purpose.
- The offline provider replays `demo/offline_run.json` against `DEMO_PITCH` and
  sets `demo=True`. Its quotes must remain substrings of `DEMO_PITCH`; a test
  enforces that.
- POSTs with a non-local `Origin` are refused.

## Verified
- Offline mode end to end: demo labeled, `strong` dissent, 3 fallacies kept,
  0 dropped.
- Groq end to end (civil): verdict HOLD, strong dissent, server aggregate.
- Gemini end to end: works on `gemini-flash-lite-latest` only. Returned a
  fabricated failure mode ("100% of test runs"); the grader marked it `weak`.
  Documented, not fixed, because it is a model-quality issue.

## New since the first handoff
- `providers.ask_with_fallback`: 503/404 -> next model, 429 -> backoff and retry
  the same model, anything else -> stop. Groq has ONE trusted id because
  guessed ids returned 404 and `/models` answers 403 for this key.
- `logs/calls.jsonl`: never stores prompt text, only a hash and length.
- `eval/`: recall 1.00, precision 0.63 on 5 pitches (Groq). Two labels were
  adjudicated with `also_accept`, each with a written reason in pitches.json.
- `compare_seeds.py`: first live run flipped verdict HOLD -> NEEDS-REVIEW on
  cast alone.

## Key pool
- `key_pool()` returns every key for a provider; `_key()` still returns the first.
- `ask_with_fallback(prompt, provider, fn)` calls `fn(prompt, model, key)`.
  Changing that arity breaks every caller: update `groq_text`/`gemini_text`
  (they take an optional `key`) and the tests together.
- 429/quota rotates key, 401/403 drops key, 503/404 moves model, anything else
  raises. Do not collapse these branches; a 503 retried as if it were a 429
  cost 84 seconds in a test run before it was fixed.

## Not verified
- The form check is not a truth check. Groq in cannibal mode returned `strong`
  by citing "Contradiction Benchmark v2 (10,000 test cases)", a benchmark that
  does not exist. `strong` means checkable-in-form only. Do not build a
  benchmark-existence detector on a hunch; if this matters, ship a labeled
  eval instead.
- Any model's fallacy labels being correct. Existence of the quote is checked;
  the reasoning behind the label is not.
- Behaviour on mobile browsers / Termux.
- Rate-limit behaviour under repeated runs.

## Next smallest action
Build a labeled eval (like `turd-merger-tools/eval/`) with pitches whose
fallacies a human has tagged, then measure label agreement. Until that exists,
the fallacy ledger is an argument starter and nothing more.

## Client contract (2026-10-25)

`POST /api/ask` is the only surface a client should use, and the shape is
frozen: `prompt`, `response_text`, `model_used`, `routing_reason`,
`offline_text`. `validate_contract()` returns problems rather than guessing.

Two invariants, both enforced in `tests/test_grim_contract.py` (16 tests):

1. **It answers 200 even when every model fails.** The floor is part of the
   payload, not an error path, so a client never has to choose between
   rendering an error and rendering nothing. `model_used == "offline"` and the
   reason string are how a reader knows the text was not generated.
2. **It never claims a model it did not get.** `routing_reason` records the
   providers it fell through and why (HTTP 402/429, timeout, empty response).

Cascade order is `groq -> deepseek -> gemini -> floor`, built by `build_asks()`
which only includes providers whose `provider_status()["ready"]` is true. The
order lives in `CASCADE_ORDER`; the floor lives in `offline_text()` in
`grim_serve.py`, mirrored deliberately in `turd-merger-tools/grimoire_tui.py`.

Do not let a client import this module. A client that imports the server cannot
tell you whether the server is up; that is why the field list is duplicated and
asserted equal in test.

`/api/simulate` is unchanged and still serves the market page.
