"""
CSP DocMaker — the AI model behind the ask-anything chat (tracker No. 114)

One job: send the conversation and the tool list to the model and return
its answer — either text for the person or the tools it wants run. It never
touches the database and never sends anything; assistant_tools does the
looking up, and only a person's Send press puts a message on the wire.

Both providers speak the OpenAI chat-completions format, so one client
serves them:

  * cloudflare — Workers AI (the account the photo studio already uses;
    free daily allowance). Chosen 16 Oct 2026.
  * gemini — Google's OpenAI-compatible endpoint, if a key is set.

What the model sees: the question, and the CSP details the tools return
(names, contacts). That is the trade the user accepted on 16 Oct 2026.
Nothing of it is logged here — only sizes, timings and failures.
"""

import logging
from typing import List, Optional

from app import telemetry
from app.config import get_settings

logger = logging.getLogger(__name__)

CLOUDFLARE = "cloudflare"
GEMINI = "gemini"
PROVIDERS = (CLOUDFLARE, GEMINI)


class AssistantUnavailable(RuntimeError):
    """The chat cannot answer: switched off, not configured, or the model failed."""


def provider() -> str:
    return (get_settings().assistant_provider or "").strip().lower()


def _endpoint() -> tuple:
    """(url, api key) for the configured provider, or AssistantUnavailable."""
    s = get_settings()
    name = provider()
    if name == CLOUDFLARE:
        account = (s.cloudflare_account_id or "").strip()
        token = (s.cloudflare_api_token or "").strip()
        if not (account and token):
            raise AssistantUnavailable(
                "The chat uses Cloudflare AI, but CLOUDFLARE_ACCOUNT_ID or "
                "CLOUDFLARE_API_TOKEN is not set on the server.")
        return (f"https://api.cloudflare.com/client/v4/accounts/{account}"
                f"/ai/v1/chat/completions", token)
    if name == GEMINI:
        key = (s.gemini_api_key or "").strip()
        if not key:
            raise AssistantUnavailable(
                "The chat uses Gemini, but GEMINI_API_KEY is not set on the "
                "server.")
        return ("https://generativelanguage.googleapis.com/v1beta/openai/"
                "chat/completions", key)
    if name in ("", "off", "none"):
        raise AssistantUnavailable("The chat is switched off "
                                   "(ASSISTANT_PROVIDER=off).")
    raise AssistantUnavailable(
        f"ASSISTANT_PROVIDER={name!r} is not one of {', '.join(PROVIDERS)} "
        f"or off.")


def is_configured() -> bool:
    try:
        _endpoint()
        return True
    except AssistantUnavailable:
        return False


def complete(messages: List[dict], tools: Optional[List[dict]] = None) -> dict:
    """One model turn. Returns the assistant message dict
    ({"content": str|None, "tool_calls": [...]|None}).

    Raises AssistantUnavailable with a plain reason on every failure; the
    original exception is chained and logged with its traceback by
    telemetry.external_call.
    """
    import httpx

    url, key = _endpoint()
    s = get_settings()
    body = {"model": s.assistant_model, "messages": messages,
            "temperature": 0.1, "max_tokens": 900}
    if tools:
        body["tools"] = tools

    try:
        with telemetry.external_call(
                provider(), "chat.completions", model=s.assistant_model,
                messages=len(messages)) as span:
            response = httpx.post(
                url, json=body, timeout=s.assistant_timeout_seconds,
                headers={"Authorization": f"Bearer {key}"})
            telemetry.note_http(span, provider(), "chat.completions",
                                response.status_code)
            if response.status_code != 200:
                raise telemetry.ExternalResponseError(
                    telemetry.http_failure_kind(response.status_code) or "http",
                    f"HTTP {response.status_code}: {response.text[:300]}")
            try:
                message = response.json()["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise telemetry.ExternalResponseError(
                    "malformed", f"unreadable answer ({type(e).__name__}): "
                    f"{response.text[:300]}") from e
    except AssistantUnavailable:
        raise
    except Exception as e:
        raise AssistantUnavailable(
            f"The AI model did not answer ({provider()}, "
            f"{type(e).__name__}: {str(e)[:200]})") from e

    if not isinstance(message, dict):
        raise AssistantUnavailable("The AI model's answer had no message.")
    return message
