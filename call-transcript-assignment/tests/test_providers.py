from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from labeler.providers import ProviderError, model_settings, post_json, send_model
from labeler.schemas import FIRST_PASS

URL = "https://example.test"
CONTENT = json.dumps({"ok": True})
GROQ, GEMINI = "groq/openai/gpt-oss-120b", "gemini/gemini-3.5-flash-lite"


def http_error(code, message=""):
    return HTTPError(URL, code, "error", {}, BytesIO(json.dumps({"error": {"message": message}}).encode()))


class Reply(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RequestTests(TestCase):
    def test_groq_and_gemini_request_shapes_and_usage(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "g", "GEMINI_API_KEY": "m"}):
            with patch("labeler.providers.post_json", return_value={
                    "choices": [{"message": {"content": CONTENT}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10}}) as send:
                answer, usage = send_model(GROQ, "rules", "call", FIRST_PASS, model_settings(GROQ))
                _, headers, body, _ = send.call_args.args
                self.assertEqual((headers["Authorization"], body["model"], body["reasoning_effort"], body["temperature"]),
                                 ("Bearer g", "openai/gpt-oss-120b", "low", 0))
                self.assertTrue(body["response_format"]["json_schema"]["strict"])
                self.assertEqual((answer, usage), ({"ok": True}, {"prompt_tokens": 20, "completion_tokens": 10}))
            with patch("labeler.providers.post_json", return_value={
                    "candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": CONTENT}]}}],
                    "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 10, "thoughtsTokenCount": 4}}) as send:
                answer, usage = send_model(GEMINI, "rules", "call", FIRST_PASS, model_settings(GEMINI))
                url, headers, body, _ = send.call_args.args
                self.assertTrue(url.endswith("/gemini-3.5-flash-lite:generateContent"))
                self.assertEqual((headers["x-goog-api-key"], body["generationConfig"]["temperature"]), ("m", 0))
                self.assertIn("outcome", body["generationConfig"]["responseJsonSchema"]["required"])
                self.assertEqual((answer, usage["completion_tokens"]), ({"ok": True}, 14))

    def test_request_too_large_retries_once_with_a_smaller_output_cap(self):
        too_large = ProviderError("HTTP 413")
        too_large.token_excess = 1075
        caps = []

        def send(url, headers, body, settings):
            caps.append(body["max_completion_tokens"])
            if len(caps) == 1:
                raise too_large
            return {"choices": [{"message": {"content": CONTENT}}]}

        with patch.dict("os.environ", {"GROQ_API_KEY": "g"}), patch("labeler.providers.post_json", side_effect=send):
            send_model(GROQ, "rules", "call", FIRST_PASS, model_settings(GROQ))
        self.assertEqual(caps, [4096, 2971])


class RetryTests(TestCase):
    settings = {"timeout": 1, "retries": 2}

    def test_rate_limit_waits_as_long_as_the_provider_asks(self):
        limited = http_error(429, "(TPM): Limit 8000. Please try again in 1m2.5s.")
        with patch("labeler.providers.urlopen", side_effect=[limited, Reply(b"{}")]), \
                patch("labeler.providers.sleep") as wait:
            self.assertEqual(post_json(URL, {}, {}, self.settings), {})
            wait.assert_called_once_with(63.5)

    def test_server_error_backs_off_then_gives_up(self):
        with patch("labeler.providers.urlopen", side_effect=[http_error(503, "high demand") for _ in range(3)]), \
                patch("labeler.providers.sleep") as wait:
            with self.assertRaisesRegex(ProviderError, r"HTTP 503 \(high demand\)"):
                post_json(URL, {}, {}, self.settings)
            self.assertEqual([c.args[0] for c in wait.call_args_list], [11, 21])

    def test_daily_limit_and_client_errors_fail_fast(self):
        gemini_daily = HTTPError(URL, 429, "error", {}, BytesIO(json.dumps({"error": {
            "message": "Quota exceeded", "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}}).encode()))
        for error, pattern in ((http_error(429, "tokens per day (TPD): try again in 3m"), "rate limit TPD"),
                               (gemini_daily, "rate limit RPD"), (http_error(400, "bad request"), "HTTP 400")):
            with self.subTest(pattern=pattern), patch("labeler.providers.urlopen", side_effect=[error]), \
                    patch("labeler.providers.sleep") as wait:
                with self.assertRaisesRegex(ProviderError, pattern):
                    post_json(URL, {}, {}, self.settings)
                wait.assert_not_called()
