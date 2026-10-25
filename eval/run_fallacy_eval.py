#!/usr/bin/env python3
"""Measure the fallacy ledger against labeled pitches. Live: calls a provider.

This is the only way to know whether the labels are right. Quote existence is
already enforced in code; this measures whether the NAME attached to a real
quote matches what a human would say.

Usage:  python3 eval/run_fallacy_eval.py [--provider groq] [--only p1_popularity]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REPO = EVAL.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(EVAL))

import oracle  # noqa: E402
import providers  # noqa: E402
import score  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score the cannibal fallacy ledger.")
    ap.add_argument("--provider", default="groq", choices=["groq", "gemini"])
    ap.add_argument("--model", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(EVAL / "results"))
    a = ap.parse_args(argv)

    data = json.loads((EVAL / "pitches.json").read_text(encoding="utf-8"))
    pitches = data["pitches"]
    if a.only:
        pitches = [p for p in pitches if p["id"] == a.only]

    ask = providers.get_ask(a.provider, a.model)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in pitches:
        try:
            run = oracle.simulate({"pitch": p["text"], "mode": "cannibal", "count": 3,
                                   "seed": 7, "_provider": a.provider,
                                   "_model": a.model or providers.default_model(a.provider)},
                                  ask)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            print(f"{p['id']:18} ERROR {e}", file=sys.stderr)
            rows.append({"id": p["id"], "error": str(e)})
            continue
        sc = score.score_run(run["fallacies"], p["labeled"])
        rows.append({"id": p["id"], **sc,
                     "dissent_quality": run["dissent_quality"],
                     "dropped_fallacies": run["meta"]["dropped_fallacies"]})
        (out_dir / f"{p['id']}.txt").write_text(p["text"], encoding="utf-8")
        (out_dir / f"{p['id']}.json").write_text(
            json.dumps({"detected": run["fallacies"], "score": sc,
                        "dissent": run["dissent"]}, indent=2), encoding="utf-8")
        print(f"{p['id']:18} recall={sc['recall']:.2f} "
              f"precision={sc['precision']:.2f} "
              f"missed={len(sc['missed'])} invented={len(sc['false_positives'])}")
        time.sleep(1.0)

    ok = [r for r in rows if "error" not in r]
    total = score.aggregate(ok)
    print(f"\npooled: recall={total['recall']:.2f} "
          f"({total['hits']}/{total['labeled']}) "
          f"precision={total['precision']:.2f} ({total['hits']}/{total['detected']}) "
          f"runs={total['runs']}")
    (EVAL / "last_fallacy_run.json").write_text(json.dumps(rows, indent=2),
                                               encoding="utf-8")
    print(f"evidence: {out_dir}")
    return 0 if len(ok) == len(pitches) else 1


if __name__ == "__main__":
    sys.exit(main())
