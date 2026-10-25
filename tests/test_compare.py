"""Diff logic for compare_seeds. Pure: no provider calls."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import compare_seeds as cs  # noqa: E402


def run(verdict="HOLD", mean=5.5, quality="strong", cast=None, fallacies=None,
        reactions=("skeptical",)):
    return {
        "verdict": verdict, "mean": mean, "dissent_quality": quality,
        "fallacies": [{"fallacy": f, "quote": "q", "why": "w"} for f in (fallacies or [])],
        "personas": [{"archetype": a, "reaction": r}
                     for a, r in zip(cast or ["a"], reactions)],
        "meta": {"archetypes": cast or ["a"]},
    }


class Columns(unittest.TestCase):
    def test_short_value_is_padded(self):
        self.assertEqual(cs.col("HOLD"), "HOLD" + " " * 22)

    def test_long_value_is_truncated_with_a_space(self):
        out = cs.col("the bad-faith reader", width=10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith(" "), "must not merge into the next column")


class Diff(unittest.TestCase):
    def test_identical_runs_change_nothing(self):
        d = cs.diff_runs(run(), run())
        self.assertFalse(d["verdict_changed"])
        self.assertEqual(d["mean_delta"], 0)

    def test_verdict_flip_is_flagged(self):
        d = cs.diff_runs(run(verdict="HOLD"), run(verdict="KILL"))
        self.assertTrue(d["verdict_changed"])

    def test_mean_delta_is_signed_and_rounded(self):
        d = cs.diff_runs(run(mean=6.0), run(mean=4.444))
        self.assertEqual(d["mean_delta"], -1.56)

    def test_fallacy_sets_are_split_three_ways(self):
        d = cs.diff_runs(run(fallacies=["equivocation", "false_dilemma"]),
                         run(fallacies=["false_dilemma", "appeal_to_novelty"]))
        self.assertEqual(d["fallacies_shared"], ["false_dilemma"])
        self.assertEqual(d["fallacies_only_in_a"], ["equivocation"])
        self.assertEqual(d["fallacies_only_in_b"], ["appeal_to_novelty"])

    def test_cast_difference_is_reported(self):
        d = cs.diff_runs(run(cast=["the pedant"]), run(cast=["the regulator"]))
        self.assertNotEqual(d["cast"][0], d["cast"][1])

    def test_reaction_pairs_follow_position_not_identity(self):
        d = cs.diff_runs(run(cast=["a"], reactions=("positive",)),
                         run(cast=["b"], reactions=("negative",)))
        self.assertEqual(list(d["reactions"].values()), [("positive", "negative")])

    def test_missing_fallacies_key_does_not_crash(self):
        a = run()
        a.pop("fallacies")
        d = cs.diff_runs(a, run(fallacies=["equivocation"]))
        self.assertEqual(d["fallacies_only_in_b"], ["equivocation"])


if __name__ == "__main__":
    unittest.main()
