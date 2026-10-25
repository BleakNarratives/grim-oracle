# QRD — Agent-to-Agent Handoff (GRIM Oracle)

Read before editing. A handoff is evidence, not authority: re-check the tree
and the tests before changing anything.

## State
- Repo: `~/grim-oracle`, branch `main`, local git.
- Tests: `python3 -m unittest discover -s tests` — 48 offline tests, passing.
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

## Not verified
- Groq in cannibal mode against a real pitch (civil was verified).
- Any model's fallacy labels being correct. Existence of the quote is checked;
  the reasoning behind the label is not.
- Behaviour on mobile browsers / Termux.
- Rate-limit behaviour under repeated runs.

## Next smallest action
Run one Groq cannibal pass against a real pitch and read the fallacy ledger by
hand. If labels are mostly wrong, the vocabulary needs tightening before the
mode is recommended to anyone.
