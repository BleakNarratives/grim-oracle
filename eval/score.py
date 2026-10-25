"""score.py -- compare detected fallacies to labeled ones. Pure, no I/O.

A detection counts as a hit only when the fallacy name matches AND the quote
overlaps the labeled quote. Name-only matching would let a model that labels
everything "equivocation" score well; quote-only matching would let it find the
right sentence for the wrong reason.
"""
from __future__ import annotations

import re

_PUNCT = re.compile(r"[^a-z0-9\s]")


def _norm(s: str) -> str:
    return " ".join(_PUNCT.sub(" ", str(s).lower()).split())


def quote_overlap(detected: str, labeled: str, threshold: float = 0.6) -> bool:
    """True when one quote contains the other or their tokens mostly agree."""
    a, b = _norm(detected), _norm(labeled)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def score_run(detected: list[dict], labeled: list[dict]) -> dict:
    """Match detections to labels; return counts plus what was missed and invented."""
    remaining = list(detected)
    hits, missed = [], []
    for lab in labeled:
        # `also_accept` exists for genuine adjudication only (two fallacy names
        # that both fit the same sentence, e.g. popularity vs authority). It must
        # be declared in the label file, so it can be reviewed rather than
        # quietly widening the metric.
        accept = {str(lab.get("fallacy"))} | {str(x) for x in lab.get("also_accept", [])}
        match = next((d for d in remaining
                      if str(d.get("fallacy")) in accept
                      and quote_overlap(d.get("quote", ""), lab.get("quote", ""))), None)
        if match is None:
            missed.append(lab)
        else:
            hits.append({"labeled": lab, "detected": match})
            remaining.remove(match)
    n_lab, n_det = len(labeled), len(detected)
    return {
        "hits": hits,
        "missed": missed,
        "false_positives": remaining,
        "recall": round(len(hits) / n_lab, 3) if n_lab else 1.0,
        "precision": round(len(hits) / n_det, 3) if n_det else (1.0 if not n_lab else 0.0),
    }


def aggregate(results: list[dict]) -> dict:
    """Pooled precision and recall across runs, plus per-run rows."""
    tp = sum(len(r["hits"]) for r in results)
    lab = tp + sum(len(r["missed"]) for r in results)
    det = tp + sum(len(r["false_positives"]) for r in results)
    return {
        "runs": len(results),
        "hits": tp,
        "labeled": lab,
        "detected": det,
        "recall": round(tp / lab, 3) if lab else 0.0,
        "precision": round(tp / det, 3) if det else 0.0,
        "rows": results,
    }
