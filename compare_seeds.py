#!/usr/bin/env python3
"""compare_seeds.py -- run one pitch at two seeds and show what moved.

The seed picks the cast, so two seeds are two panels, not two samples of one
panel. The point is to see whether a verdict is stable across who happens to be
in the room. If the verdict flips on cast alone, the pitch is fragile and that
is worth knowing before you rewrite the pitch.

Usage:  python3 compare_seeds.py --file pitch.txt --seeds 42,7
        python3 compare_seeds.py --text "our pitch" --seeds 1,2 --mode cannibal
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import oracle  # noqa: E402
import providers  # noqa: E402


def col(value, width: int = 26) -> str:
    """Pad or truncate for the two-column print. Long cast names must not merge."""
    s = str(value)
    if len(s) >= width:
        return s[: width - 1] + " "
    return s.ljust(width)


def diff_runs(a: dict, b: dict) -> dict:
    """What changed between two runs. Pure."""
    fa = {f["fallacy"] for f in a.get("fallacies", [])}
    fb = {f["fallacy"] for f in b.get("fallacies", [])}
    reactions = {}
    for pa, pb in zip(a.get("personas", []), b.get("personas", [])):
        reactions[f"{pa['archetype']} -> {pb['archetype']}"] = (pa["reaction"], pb["reaction"])
    return {
        "verdict": (a["verdict"], b["verdict"]),
        "verdict_changed": a["verdict"] != b["verdict"],
        "mean": (a["mean"], b["mean"]),
        "mean_delta": round(b["mean"] - a["mean"], 2),
        "dissent_quality": (a["dissent_quality"], b["dissent_quality"]),
        "cast": (a["meta"]["archetypes"], b["meta"]["archetypes"]),
        "fallacies_only_in_a": sorted(fa - fb),
        "fallacies_only_in_b": sorted(fb - fa),
        "fallacies_shared": sorted(fa & fb),
        "reactions": reactions,
    }


def _run(text: str, seed: int, args, ask) -> dict:
    return oracle.simulate({"pitch": text, "mode": args.mode, "count": args.count,
                            "seed": seed, "segment": args.segment, "focus": args.focus,
                            "_provider": args.provider,
                            "_model": args.model or providers.default_model(args.provider)},
                           ask)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare one pitch at two seeds.")
    ap.add_argument("--file", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--seeds", default="42,7")
    ap.add_argument("--mode", default="civil", choices=list(oracle.MODES))
    ap.add_argument("--provider", default="groq",
                    choices=["groq", "gemini", "offline"])
    ap.add_argument("--model", default="")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--segment", default="dev-tools")
    ap.add_argument("--focus", default="general")
    a = ap.parse_args(argv)

    text = Path(a.file).expanduser().read_text(encoding="utf-8") if a.file else a.text
    if not text.strip():
        print("compare_seeds: need --file or --text", file=sys.stderr)
        return 2
    try:
        s1, s2 = [int(x) for x in a.seeds.split(",")[:2]]
    except ValueError:
        print("compare_seeds: --seeds wants two integers, e.g. 42,7", file=sys.stderr)
        return 2
    if a.provider == "offline":
        print("compare_seeds: offline replays canned data, so seeds will not differ.",
              file=sys.stderr)

    ask = providers.get_ask(a.provider, a.model)
    try:
        ra, rb = _run(text, s1, a, ask), _run(text, s2, a, ask)
    except (RuntimeError, ValueError) as e:
        print(f"compare_seeds: {e}", file=sys.stderr)
        return 1

    d = diff_runs(ra, rb)
    print(f"pitch: {text.strip()[:70]}...")
    print(f"mode:  {a.mode}\n")
    print(f"{'':14}{col('seed ' + str(s1))}{'seed ' + str(s2)}")
    print(f"{'cast':14}{col(', '.join(d['cast'][0]))}{', '.join(d['cast'][1])}")
    print(f"{'verdict':14}{col(d['verdict'][0])}{d['verdict'][1]}"
          f"{'   <- CHANGED' if d['verdict_changed'] else ''}")
    print(f"{'mean':14}{col(d['mean'][0])}{d['mean'][1]}   ({d['mean_delta']:+.2f})")
    print(f"{'dissent':14}{col(d['dissent_quality'][0])}{d['dissent_quality'][1]}")
    if a.mode == "cannibal":
        print(f"\nfallacies shared: {', '.join(d['fallacies_shared']) or 'none'}")
        print(f"only seed {s1}: {', '.join(d['fallacies_only_in_a']) or 'none'}")
        print(f"only seed {s2}: {', '.join(d['fallacies_only_in_b']) or 'none'}")
    print("\nobjections:")
    for label, run in ((f"seed {s1}", ra), (f"seed {s2}", rb)):
        obj = str(run["dissent"].get("objection", ""))[:200]
        print(f"  {label}: {obj or '(none)'}")
    print("\nverdict is stable across casts." if not d["verdict_changed"]
          else "\nverdict flipped on cast alone; the pitch is fragile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
