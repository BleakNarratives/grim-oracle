"""Model ladder + call log. No network: the model function is injected."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import providers  # noqa: E402


class Ladder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_log = providers.CALL_LOG
        providers.CALL_LOG = Path(self._tmp.name) / "calls.jsonl"

    def tearDown(self):
        providers.CALL_LOG = self._old_log
        self._tmp.cleanup()

    def test_falls_through_on_503(self):
        seen = []

        def fn(prompt, model):
            seen.append(model)
            if model == providers.MODEL_LADDERS["gemini"][0]:
                raise RuntimeError(f"HTTP 503 from gemini ({model})")
            return "ok"

        out = providers.ask_with_fallback("p", "gemini", fn)
        self.assertEqual(out, "ok")
        self.assertEqual(seen, list(providers.MODEL_LADDERS["gemini"][:2]))

    def test_falls_through_on_404(self):
        first = providers.MODEL_LADDERS["gemini"][0]

        def fn(prompt, model):
            if model == first:
                raise RuntimeError("HTTP 404 from gemini")
            return "ok"

        self.assertEqual(providers.ask_with_fallback("p", "gemini", fn), "ok")

    def test_non_retryable_error_stops_immediately(self):
        calls = []

        def fn(prompt, model):
            calls.append(model)
            raise RuntimeError("no groq key in env or vault; nothing sent")

        with self.assertRaises(RuntimeError):
            providers.ask_with_fallback("p", "groq", fn)
        self.assertEqual(len(calls), 1, "must not burn the whole ladder on a key error")

    def test_all_candidates_failing_reports_the_ladder(self):
        def fn(prompt, model):
            raise RuntimeError("HTTP 503 from provider")

        with self.assertRaises(RuntimeError) as ctx:
            providers.ask_with_fallback("p", "gemini", fn)
        self.assertIn("every model candidate failed", str(ctx.exception))

    def test_rate_limit_backs_off_and_retries_the_same_model(self):
        """429 is the account being busy, not the model being wrong."""
        calls, pauses = [], []

        def fn(prompt, model):
            calls.append(model)
            if len(calls) == 1:
                raise RuntimeError("HTTP 429 from groq")
            return "ok"

        out = providers.ask_with_fallback("p", "groq", fn, sleep=pauses.append)
        self.assertEqual(out, "ok")
        self.assertEqual(calls, [providers.DEFAULT_GROQ, providers.DEFAULT_GROQ])
        self.assertEqual(pauses, [2])

    def test_rate_limit_moves_on_only_after_the_backoff_is_spent(self):
        calls = []

        def fn(prompt, model):
            calls.append(model)
            if calls.count(model) <= 3:
                raise RuntimeError("HTTP 429 from groq")
            return "ok"

        providers.ask_with_fallback("p", "groq", fn, sleep=lambda s: None)
        self.assertEqual(calls.count(providers.DEFAULT_GROQ), 4)

    def test_last_model_used_reports_the_fallback_not_the_first_choice(self):
        first = providers.MODEL_LADDERS["gemini"][0]

        def fn(prompt, model):
            if model == first:
                raise RuntimeError("HTTP 503 from gemini")
            return "ok"

        providers.ask_with_fallback("p", "gemini", fn)
        self.assertNotEqual(providers.last_model_used(), first)


class CallLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = providers.CALL_LOG
        providers.CALL_LOG = Path(self._tmp.name) / "calls.jsonl"
        os.environ.pop("GRIM_NO_LOG", None)

    def tearDown(self):
        providers.CALL_LOG = self._old
        os.environ.pop("GRIM_NO_LOG", None)
        self._tmp.cleanup()

    def test_logs_a_line_without_the_prompt(self):
        secret_prompt = "my private launch pitch that must not be stored"
        providers.log_call({"provider": "groq", "model_used": "m", "ok": True})
        line = providers.CALL_LOG.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        self.assertEqual(rec["provider"], "groq")
        self.assertNotIn("pitch", json.dumps(rec))
        self.assertNotIn(secret_prompt, providers.CALL_LOG.read_text(encoding="utf-8"))

    def test_failed_call_is_logged_with_its_error(self):
        def fn(prompt, model):
            raise RuntimeError("HTTP 400 from groq (m)")

        with self.assertRaises(RuntimeError):
            providers.ask_with_fallback("p", "groq", fn)
        recs = [json.loads(l) for l in providers.CALL_LOG.read_text().splitlines()]
        self.assertFalse(recs[0]["ok"])
        self.assertIn("HTTP 400", recs[0]["error"])
        self.assertEqual(recs[0]["model_used"], "")

    def test_no_log_env_disables_writing(self):
        os.environ["GRIM_NO_LOG"] = "1"
        providers.log_call({"provider": "x"})
        self.assertFalse(providers.CALL_LOG.exists())

    def test_log_rotates_instead_of_growing_without_bound(self):
        providers.CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        providers.CALL_LOG.write_text("x" * (providers.LOG_MAX_BYTES + 1))
        providers.log_call({"provider": "y"})
        self.assertTrue(providers.CALL_LOG.exists())
        self.assertLess(providers.CALL_LOG.stat().st_size, 1000)


class Candidates(unittest.TestCase):
    def test_env_override_goes_first(self):
        os.environ["GRIM_MODEL"] = "my-pinned-model"
        try:
            self.assertEqual(providers.model_candidates("gemini")[0], "my-pinned-model")
        finally:
            os.environ.pop("GRIM_MODEL", None)

    def test_default_ladder_is_used_without_env(self):
        os.environ.pop("GRIM_MODEL", None)
        self.assertEqual(providers.model_candidates("gemini")[0],
                         providers.DEFAULT_GEMINI)

    def test_missing_registry_does_not_crash(self):
        old = providers.MODEL_REGISTRY
        providers.MODEL_REGISTRY = Path("/nonexistent/model_registry.json")
        try:
            self.assertEqual(providers.registry_candidates("gemini"), [])
        finally:
            providers.MODEL_REGISTRY = old

    def test_registry_extras_are_appended_not_prepended(self):
        old = providers.MODEL_REGISTRY
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "reg.json"
            p.write_text(json.dumps({"providers": {"gemini": {
                "models": [{"id": "some-new-model", "status": "live"},
                           {"id": "dead-model", "status": "dead"}]}}}))
            providers.MODEL_REGISTRY = p
            try:
                cands = providers.model_candidates("gemini")
                self.assertEqual(cands[0], providers.DEFAULT_GEMINI)
                self.assertIn("some-new-model", cands)
                self.assertNotIn("dead-model", cands)
            finally:
                providers.MODEL_REGISTRY = old


if __name__ == "__main__":
    unittest.main()
