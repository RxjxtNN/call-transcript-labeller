"""Direct HTTPS calls to Groq (the submission provider) and Gemini (testing)."""

from collections import Counter
import json
import os
import re
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

DEFAULT_MODEL = "groq/openai/gpt-oss-120b"
API_KEYS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"


class ProviderError(ValueError):
    """A sanitized provider failure: never includes transcript text or credentials."""

    token_excess = None  # HTTP 413: how far prompt + output cap exceeds the per-minute token limit.


def model_settings(model):
    """Generation settings, recorded in the run manifest."""
    if model.startswith("groq/"):
        # GPT-OSS reasoning counts against max_tokens. Medium effort used 5k+ tokens on one call, which
        # overflows the free tier's 8k tokens-per-minute limit, so use low effort.
        return dict(temperature=0, max_tokens=4096, timeout=45, retries=5, reasoning_effort="low")
    # Gemini (testing): temperature 0 so reruns are comparable.
    return dict(temperature=0, max_tokens=2048, timeout=30, retries=1)


def classify(error):
    """(sanitized reason, seconds to wait or None, token excess or None) from an HTTP error body."""
    try:
        body = json.load(error).get("error", {})
        message, details = str(body.get("message", "")), json.dumps(body.get("details", ""))
    except (ValueError, AttributeError, OSError):
        message = details = ""
    finally:
        error.close()
    reason, wait, excess = "", None, None
    if limit := re.search(r"\((TPM|TPD|RPM|RPD)\)", message):  # Groq
        reason = f" (rate limit {limit[1]})"
    elif "PerDay" in details:  # Gemini: e.g. GenerateRequestsPerDayPerProjectPerModel
        reason = " (rate limit RPD)"
    elif "high demand" in message.lower():
        reason = " (high demand)"
    if match := re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", message):  # e.g. "1m2.5s"
        hours, minutes, seconds = (float(part or 0) for part in match.groups())
        wait = hours * 3600 + minutes * 60 + seconds or None
    if error.code == 413 and (match := re.search(r"Limit (\d+), Requested (\d+)", message)):
        excess = int(match[2]) - int(match[1])
    return reason, wait, excess


def post_json(url, headers, payload, settings):
    """POST, retrying 429 and 5xx after the provider's stated wait or a backoff. Daily limits fail fast."""
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                      headers={**headers, "Content-Type": "application/json", "User-Agent": "CallLabeler/1.0"})
    for attempt in range(settings["retries"] + 1):
        try:
            with urlopen(request, timeout=settings["timeout"]) as response:
                return json.load(response)
        except HTTPError as error:
            reason, wait, excess = classify(error)
            retryable = error.code == 429 and "TPD" not in reason and "RPD" not in reason or error.code >= 500
            if not retryable or attempt == settings["retries"]:
                failure = ProviderError(f"HTTP {error.code}{reason}")
                failure.token_excess = excess
                raise failure from None
            sleep(min(wait or 10 * 2 ** attempt, 120) + 1)
        except (TimeoutError, URLError) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
            raise ProviderError("request timed out" if timed_out else "network connection failed") from None


def send_groq(model_id, key, system, user, response_format, settings):
    body = {"model": model_id, "response_format": response_format, "temperature": settings["temperature"],
            "max_completion_tokens": settings["max_tokens"], "reasoning_effort": settings["reasoning_effort"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = post_json(GROQ_URL, headers, body, settings)
    except ProviderError as error:
        # A long transcript plus the output cap can exceed the per-minute limit (HTTP 413): shrink the cap once.
        if not error.token_excess or body["max_completion_tokens"] - error.token_excess < 1024:
            raise
        body["max_completion_tokens"] -= error.token_excess + 50
        response = post_json(GROQ_URL, headers, body, settings)
    choice = (response.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise ProviderError("output reached the token limit")
    usage = response.get("usage") or {}
    return choice.get("message", {}).get("content"), usage.get("prompt_tokens"), usage.get("completion_tokens")


def send_gemini(model_id, key, system, user, response_format, settings):
    response = post_json(GEMINI_URL.format(quote(model_id, safe="")), {"x-goog-api-key": key}, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": settings["temperature"],
                             "maxOutputTokens": settings["max_tokens"],
                             "responseJsonSchema": response_format["json_schema"]["schema"]}}, settings)
    candidate = (response.get("candidates") or [{}])[0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        raise ProviderError("output reached the token limit")
    content = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", [])
                      if not part.get("thought"))
    usage = response.get("usageMetadata") or {}
    completion = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
    return content, usage.get("promptTokenCount"), completion


def api_key(model):
    """The API key for 'groq/<id>' or 'gemini/<id>'; raises ValueError for an unknown provider or a missing key."""
    provider, _, model_id = model.partition("/")
    if provider not in API_KEYS or not model_id:
        raise ValueError("model must look like groq/<model> or gemini/<model>")
    if not (key := os.environ.get(API_KEYS[provider])):
        raise ValueError(f"set {API_KEYS[provider]} in .env or your environment")
    return key


def send_model(model, system, user, response_format, settings):
    """One schema-constrained request -> (parsed JSON object, Counter of prompt and completion tokens)."""
    provider, _, model_id = model.partition("/")
    send = send_groq if provider == "groq" else send_gemini
    content, prompt_tokens, completion_tokens = send(model_id, api_key(model), system, user, response_format, settings)
    if not content:
        raise ProviderError("provider returned no answer")
    return json.loads(content), Counter(prompt_tokens=prompt_tokens or 0, completion_tokens=completion_tokens or 0)
