# GRIM Oracle

A market-feedback panel you run locally. It reads a pitch, convenes a small
panel, and is **required** to return a real objection with a testable condition
for changing its mind.

Everything stays on your machine: no account, no hosted product, no key in the
browser. Stdlib only.

```bash
python3 grim_serve.py --open              # Groq (default), http://127.0.0.1:8787/
python3 grim_serve.py --provider gemini
python3 grim_serve.py --provider offline  # canned demo, no network, no key
python3 grim_serve.py --mode cannibal     # hostile panel + fallacy audit
```

## Why it exists

Every "AI market research" tool returns five personas who politely like your
idea. That output is worse than nothing, because it looks like validation. This
one is built to disagree, and it proves it in code rather than in a prompt.

## Three rules enforced in code, not asked for in a prompt

1. **Dissent is graded.** `strong`, `weak`, or `missing`. An objection that
   says "needs more research" is `weak` and costs a retry. A condition nobody
   can check ("when it feels trustworthy") is `weak`. If the panel cannot
   object, the run says `missing` — it never fabricates agreement.
2. **Fallacy quotes are verified.** In cannibal mode each fallacy must quote
   the artifact word for word. Quotes that are not in your text are discarded
   and counted in `meta.dropped_fallacies`. A model that invents a citation
   gets caught instead of published.
3. **The score is computed here.** Persona scores are clamped and averaged
   server-side; the model's own aggregate is thrown away.

## Modes

- **civil** — professional panel: skeptics, pragmatists, budget owners.
- **cannibal** — hostile panel: the pedant, the regulator, the bad-faith
  reader, the competitor's marketer. Adds a fallacy ledger over your own text,
  drawn from a fixed vocabulary (`unfalsifiable_claim`, `equivocation`,
  `survivor_ship_bias`-style names, and so on) so a model cannot invent a
  fallacy and have it stick.

## Reproducible seeds

Same seed + same mode convenes the same archetypes, so two people can compare
runs. What those people say can still differ; the seed narrows the panel, it
does not freeze the output.

## Files

- `oracle.py` — all pure logic: casts, prompts, parsing, dissent grading,
  fallacy verification, aggregation. No I/O.
- `providers.py` — Groq, Gemini, and the offline replay. Keys from env or
  `~/.concierge/vault.json`. Never returned to a caller.
- `grim_serve.py` — HTTP shell. Binds `127.0.0.1`, refuses non-local POSTs.
- `compare_seeds.py` — one pitch at two seeds, with a verdict-stability check.
- `Grim/grim_market_sim.html` — the page.
- `demo/offline_run.json` — canned runs for `--provider offline`.
- `eval/` — labeled fallacy pitches and a scorer (live run).
- `branding/PROMPTS.md` — copy-paste image prompts for concept art.
- `tests/` — 85 offline tests.

## Doctor

```bash
python3 grim_serve.py --doctor    # sends nothing, costs nothing
```

Prints key-pool size per provider, the model ladder, registry age, and warnings.
Exit 1 if anything needs attention, so a script can gate on it.

## Key pool

The vault stores one key or a comma-separated pool (`GROQ_API_KEY=a,b,c` also
works). The pool is used, not just stored:

- **429 / quota** — rotate to the next key before waiting. A pool that sits idle
  while one key is throttled is not a pool.
- **401 / 403** — drop that key for the rest of the process and try the next.
- Every key throttled — back off, then retry.

Right now every provider in the vault holds **exactly one key**, so rotation is
the fallback path rather than the normal one. Adding keys needs a human with an
account; see MRD.

## Model fallback and call log

A provider is asked for a model, not told one. `providers.model_candidates()`
returns a ladder: verified ids first, then anything usable from
`~/RootBase/model_registry.json` (written by `~/bin/model_scout.py`).

- **503 / 404** — the model is unavailable here, so the next candidate is tried.
- **429** — the account is throttled, so it backs off and retries the *same*
  model. Switching models on a rate limit only spreads the throttle.
- **anything else** — stops immediately; retrying cannot fix a bad key.

The run reports `meta.model_actual`, so a fallback is visible rather than
silent.

Every attempt is appended to `logs/calls.jsonl`: provider, requested and actual
model, mode, ok/error, latency, prompt length and a prompt hash — **never the
prompt text**. Disable with `--no-log` or `GRIM_NO_LOG=1`. The log rotates at
5 MB.

## Seed comparison

```bash
python3 compare_seeds.py --file pitch.txt --seeds 42,7 --mode cannibal
```

Same seed, same cast; different seed, different cast. If the verdict flips on
cast alone, the pitch is fragile — which is worth knowing before rewriting copy.
The page has a **COMPARE SEEDS** button that does the same thing.

## Limits, stated plainly

- Synthetic reactions are not research. Every export should keep the label.
- Cannibal mode's fallacy ledger only checks that a quote exists, not that the
  fallacy label is correct. It is an argument starter, not a verdict.
- Gemini on a free-tier account may only serve `gemini-flash-lite-latest`,
  which has produced confidently fabricated specifics. Groq is the default for
  that reason.
- The offline demo ignores your input by design.
- `strong` dissent means the condition is checkable in form, not that it is
  real. A Groq run satisfied it by citing "Contradiction Benchmark v2 (10,000
  test cases)", which does not exist. Read the objection before you believe it.
- Fallacy quotes are checked for existence; the *label* attached to a real
  quote is not checked.

## For a client (the frozen contract)

```bash
python3 grim_serve.py --port 8787          # then, from any local client:
curl -s localhost:8787/api/ask -d '{"prompt":"why does this fail?"}' \
  -H 'Content-Type: application/json'
```

Every answer carries `prompt`, `response_text`, `model_used`, `routing_reason`
and `offline_text`. When no provider can answer the response is still `200`,
`model_used` is `offline`, and the text says plainly that no model wrote it.
Failover walks Groq -> DeepSeek -> Gemini -> floor and says which rung answered.
