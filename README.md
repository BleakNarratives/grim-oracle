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
- `Grim/grim_market_sim.html` — the page.
- `demo/offline_run.json` — canned runs for `--provider offline`.
- `tests/` — 48 offline tests.

## Limits, stated plainly

- Synthetic reactions are not research. Every export should keep the label.
- Cannibal mode's fallacy ledger only checks that a quote exists, not that the
  fallacy label is correct. It is an argument starter, not a verdict.
- Gemini on a free-tier account may only serve `gemini-flash-lite-latest`,
  which has produced confidently fabricated specifics. Groq is the default for
  that reason.
- The offline demo ignores your input by design.
