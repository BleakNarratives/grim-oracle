"""The page must stay provider-agnostic and credential-free."""
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "Grim" / "grim_market_sim.html"


class Page(unittest.TestCase):
    def setUp(self):
        self.html = PAGE.read_text(encoding="utf-8")

    def test_no_direct_provider_call(self):
        self.assertNotIn("api.anthropic.com", self.html)
        self.assertIsNone(re.search(r"fetch\(\s*['\"]https?://", self.html))

    def test_posts_to_the_local_endpoint(self):
        self.assertIn("fetch('/api/simulate'", self.html)

    def test_carries_no_key_looking_string(self):
        self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|"
                                    r"hf_[A-Za-z0-9]{20,}", self.html))

    def test_exposes_both_modes(self):
        self.assertIn('value="civil"', self.html)
        self.assertIn('value="cannibal"', self.html)

    def test_sends_the_selected_mode(self):
        self.assertIn("mode: document.getElementById('mode').value", self.html)

    def test_shows_an_offline_demo_warning(self):
        self.assertIn("OFFLINE DEMO", self.html)

    def test_shows_dissent_quality(self):
        self.assertIn("dissent_quality", self.html)

    def test_renders_the_fallacy_ledger(self):
        self.assertIn("FALLACY LEDGER", self.html)

    def test_does_not_promise_real_research(self):
        self.assertNotIn("Simulation uses Claude", self.html)


if __name__ == "__main__":
    unittest.main()
