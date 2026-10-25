"""The eval metric must be hard to fool. These tests try to fool it."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))
import score  # noqa: E402


class Overlap(unittest.TestCase):
    def test_identical_quote_matches(self):
        self.assertTrue(score.quote_overlap("no account required", "no account required"))

    def test_containment_matches(self):
        self.assertTrue(score.quote_overlap("no account",
                                            "it runs with no account required"))

    def test_punctuation_and_case_are_ignored(self):
        self.assertTrue(score.quote_overlap("No Account, Required!",
                                            "no account required"))

    def test_unrelated_quote_does_not_match(self):
        self.assertFalse(score.quote_overlap("trusted by every team",
                                             "no competitor can match us"))

    def test_empty_quote_never_matches(self):
        self.assertFalse(score.quote_overlap("", "anything"))


class Scoring(unittest.TestCase):
    LABELED = [{"fallacy": "appeal_to_popularity",
                "quote": "trusted by every serious engineering team"}]

    def test_exact_detection_is_a_hit(self):
        r = score.score_run([{"fallacy": "appeal_to_popularity",
                              "quote": "trusted by every serious engineering team"}],
                            self.LABELED)
        self.assertEqual(r["recall"], 1.0)
        self.assertEqual(r["precision"], 1.0)

    def test_right_quote_wrong_name_is_a_miss(self):
        r = score.score_run([{"fallacy": "equivocation",
                              "quote": "trusted by every serious engineering team"}],
                            self.LABELED)
        self.assertEqual(r["recall"], 0.0)
        self.assertEqual(len(r["false_positives"]), 1)

    def test_right_name_wrong_quote_is_a_miss(self):
        r = score.score_run([{"fallacy": "appeal_to_popularity",
                              "quote": "we are very good"}], self.LABELED)
        self.assertEqual(r["recall"], 0.0)

    def test_spraying_every_fallacy_tanks_precision(self):
        detected = [{"fallacy": f, "quote": "trusted by every serious engineering team"}
                    for f in oracle_names()]
        r = score.score_run(detected, self.LABELED)
        self.assertEqual(r["recall"], 1.0)
        self.assertLess(r["precision"], 0.2)

    def test_also_accept_covers_a_genuinely_ambiguous_label(self):
        labeled = [{"fallacy": "appeal_to_popularity",
                    "also_accept": ["appeal_to_authority"],
                    "quote": "trusted by every team"}]
        r = score.score_run([{"fallacy": "appeal_to_authority",
                              "quote": "trusted by every team"}], labeled)
        self.assertEqual(r["recall"], 1.0)

    def test_also_accept_does_not_widen_to_unrelated_names(self):
        labeled = [{"fallacy": "appeal_to_popularity",
                    "also_accept": ["appeal_to_authority"],
                    "quote": "trusted by every team"}]
        r = score.score_run([{"fallacy": "equivocation",
                              "quote": "trusted by every team"}], labeled)
        self.assertEqual(r["recall"], 0.0)

    def test_empty_detection_scores_zero_recall(self):
        r = score.score_run([], self.LABELED)
        self.assertEqual(r["recall"], 0.0)
        self.assertEqual(r["precision"], 0.0)

    def test_pooled_aggregate_adds_up(self):
        one = score.score_run([{"fallacy": "appeal_to_popularity",
                                "quote": "trusted by every serious engineering team"}],
                              self.LABELED)
        two = score.score_run([], self.LABELED)
        agg = score.aggregate([one, two])
        self.assertEqual(agg["hits"], 1)
        self.assertEqual(agg["labeled"], 2)
        self.assertEqual(agg["recall"], 0.5)


def oracle_names():
    sys.path.insert(0, str(REPO))
    import oracle
    return sorted(oracle.FALLACIES)


if __name__ == "__main__":
    unittest.main()
