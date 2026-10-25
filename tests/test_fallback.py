"""Model ladder + key rotation + call log. Offline: fn and the key pool are injected."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import providers  # noqa: E402


class Base(unittest.TestCase):
    KEYS = ["key-one", "key-two"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_log, self._old_pool = providers.CALL_LOG, providers.key_pool
        providers.CALL_LOG = Path(self._tmp.name) / "calls.jsonl"
        providers.key_pool = lambda provider: list(self.KEYS)
        os.environ.pop("GRIM_NO_LOG", None)
        os.environ.pop("GRIM_MODEL", None)

    def tearDown(self):
        providers.CALL_LOG, providers.key_pool = self._old_log, self._old_pool
        os.environ.pop("GRIM_NO_LOG", None)
        os.environ.pop("GRIM_MODEL", None)
        self._tmp.cleanup()


class ModelLadder(Base):
    def test_falls_through_on_503(self):
        seen = []

        def fn(prompt, model, key):
            seen.append(model)
            if model == providers.MODEL_LADDERS["gemini"][0]:
                raise RuntimeError(f"HTTP 503 from gemini ({model})")
            return "ok"

        self.assertEqual(providers.ask_with_fallback("p", "gemini", fn), "ok")
        self.assertEqual(seen, list(providers.MODEL_LADDERS["gemini"][:2]))

    def test_all_models_unavailable_reports_the_ladder(self):
        def fn(prompt, model, key):
            raise RuntimeError("HTTP 503 from provider")

        with self.assertRaises(RuntimeError) as ctx:
            providers.ask_with_fallback("p", "gemini", fn)
        self.assertIn("every model and key candidate failed", str(ctx.exception))

    def test_last_model_used_reports_the_fallback(self):
        first = providers.MODEL_LADDERS["gemini"][0]

        def fn(prompt, model, key):
            if model == first:
                raise RuntimeError("HTTP 503 from gemini")
            return "ok"

        providers.ask_with_fallback("p", "gemini", fn)
        self.assertNotEqual(providers.last_model_used(), first)


class KeyRotation(Base):
    def test_throttled_key_rotates_without_waiting(self):
        """A pool exists so one busy key does not stall the run."""
        used, pauses = [], []

        def fn(prompt, model, key):
            used.append(key)
            if key == "key-one":
                raise RuntimeError("HTTP 429 from groq")
            return "ok"

        out = providers.ask_with_fallback("p", "groq", fn, sleep=pauses.append)
        self.assertEqual(out, "ok")
        self.assertEqual(used, ["key-one", "key-two"])
        self.assertEqual(pauses, [], "must rotate before sleeping")

    def test_rejected_key_is_dropped_for_the_process(self):
        used = []

        def fn(prompt, model, key):
            used.append(key)
            if key == "key-one":
                raise RuntimeError("HTTP 401 from groq")
            return "ok"

        self.assertEqual(providers.ask_with_fallback("p", "groq", fn), "ok")
        self.assertEqual(used, ["key-one", "key-two"])

    def test_every_key_throttled_falls_back_to_backoff(self):
        calls, pauses = [], []

        def fn(prompt, model, key):
            calls.append(key)
            if len(calls) <= 2:  # both keys throttled once
                raise RuntimeError("HTTP 429 from groq")
            return "ok"

        out = providers.ask_with_fallback("p", "groq", fn, sleep=pauses.append)
        self.assertEqual(out, "ok")
        self.assertEqual(len(calls), 3)
        self.assertTrue(pauses, "after the pool is exhausted, wait before retrying")

    def test_quota_error_counts_as_a_throttle(self):
        used = []

        def fn(prompt, model, key):
            used.append(key)
            if key == "key-one":
                raise RuntimeError("insufficient_quota")
            return "ok"

        self.assertEqual(providers.ask_with_fallback("p", "groq", fn), "ok")
        self.assertEqual(used, ["key-one", "key-two"])

    def test_missing_key_pool_fails_before_any_call(self):
        providers.key_pool = lambda provider: []

        def fn(prompt, model, key):
            raise AssertionError("must not call without a key")

        with self.assertRaises(RuntimeError) as ctx:
            providers.ask_with_fallback("p", "groq", fn)
        self.assertIn("no groq key", str(ctx.exception))

    def test_malformed_request_stops_immediately(self):
        calls = []

        def fn(prompt, model, key):
            calls.append(key)
            raise RuntimeError("HTTP 400 from groq")

        with self.assertRaises(RuntimeError):
            providers.ask_with_fallback("p", "groq", fn)
        self.assertEqual(len(calls), 1)


class CallLog(Base):
    def test_logs_without_storing_the_prompt(self):
        providers.log_call({"provider": "groq", "model_used": "m", "ok": True})
        line = providers.CALL_LOG.read_text(encoding="utf-8")
        self.assertNotIn("pitch", json.loads(line))

    def test_failed_call_is_logged_with_its_error(self):
        def fn(prompt, model, key):
            raise RuntimeError("HTTP 400 from groq (m)")

        with self.assertRaises(RuntimeError):
            providers.ask_with_fallback("p", "groq", fn)
        rec = json.loads(providers.CALL_LOG.read_text().splitlines()[0])
        self.assertFalse(rec["ok"])
        self.assertIn("HTTP 400", rec["error"])

    def test_prompt_text_never_appears_in_the_log(self):
        secret = "my private launch pitch that must not be stored"

        def fn(prompt, model, key):
            return "ok"

        providers.ask_with_fallback(secret, "groq", fn)
        self.assertNotIn(secret, providers.CALL_LOG.read_text())

    def test_no_log_env_disables_writing(self):
        os.environ["GRIM_NO_LOG"] = "1"
        providers.log_call({"provider": "x"})
        self.assertFalse(providers.CALL_LOG.exists())

    def test_log_rotates_instead_of_growing_unbounded(self):
        providers.CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        providers.CALL_LOG.write_text("x" * (providers.LOG_MAX_BYTES + 1))
        providers.log_call({"provider": "y"})
        self.assertLess(providers.CALL_LOG.stat().st_size, 1000)


class Candidates(Base):
    def test_env_override_goes_first(self):
        os.environ["GRIM_MODEL"] = "my-pinned-model"
        self.assertEqual(providers.model_candidates("gemini")[0], "my-pinned-model")

    def test_default_ladder_is_used_without_env(self):
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


class KeyPoolParsing(unittest.TestCase):
    def test_comma_separated_env_pool_is_split(self):
        os.environ["GROQ_API_KEY"] = "a, b ,c"
        try:
            self.assertEqual(providers.key_pool("groq"), ["a", "b", "c"])
        finally:
            os.environ.pop("GROQ_API_KEY", None)

    def test_status_counts_keys_without_revealing_them(self):
        old = providers.key_pool
        providers.key_pool = lambda p: ["k1", "k2"]
        try:
            st = providers.provider_status("groq")
            self.assertEqual(st["keys_in_pool"], 2)
            self.assertNotIn("k1", json.dumps(st))
        finally:
            providers.key_pool = old


if __name__ == "__main__":
    unittest.main()
