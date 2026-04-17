"""MiniMax m2.5 LLM client.

Used for reasoning-heavy archetype merge analysis in the deity-dossier
pipeline. MiniMax exposes an OpenAI-compatible chat/completions API, so the
surface mirrors `call_deepseek` in `llm.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any

import httpx

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 529}
_MAX_RETRIES = 5


async def _post_with_retry(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> httpx.Response | None:
    """POST with exponential backoff for transient MiniMax errors.

    MiniMax-M2.5 routinely returns HTTP 529 "overloaded_error" when the
    cluster is saturated; the request is idempotent-ish for our workload
    (we re-generate proposals with wipe), so retrying with backoff is
    the right call. Returns the final successful (or last-seen) response,
    or None if every attempt raised.
    """
    last_exc: Exception | None = None
    last_resp: httpx.Response | None = None
    delay = 2.0
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
            last_resp = resp
            if resp.status_code == 200:
                return resp
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                wait = delay + random.uniform(0, 1)
                logging.getLogger(__name__).warning(
                    "MiniMax %d on attempt %d/%d; retrying in %.1fs",
                    resp.status_code,
                    attempt,
                    _MAX_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)
                delay = min(delay * 2, 30.0)
                continue
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                wait = delay + random.uniform(0, 1)
                logging.getLogger(__name__).warning(
                    "MiniMax transport error on attempt %d/%d: %s; retrying in %.1fs",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
                delay = min(delay * 2, 30.0)
                continue
            break
    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    return None

from src.canon.config import settings
from src.canon.services.narrative_v2.llm import (
    _repair_truncated_json,
    _try_parse_json,
)

logger = logging.getLogger(__name__)


def _bracket_aware_repair(s: str) -> str:
    """Fix mismatched `]` vs `}` closings.

    MiniMax-M2.5 has a recurring failure mode where an inner array is closed
    with `}` instead of `]`, e.g. `"evidence":["a","b","c"}]}]}`. We walk the
    string character-by-character, tracking whether each closing bracket is
    inside a string or a real structural token, and swap mismatched
    closers to match the innermost opener on the stack. Any still-open
    brackets at EOS are closed cleanly.
    """

    stack: list[str] = []
    out: list[str] = []
    in_string = False
    escape = False

    for ch in s:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string:
            out.append(ch)
            continue

        if ch in "[{":
            stack.append(ch)
            out.append(ch)
        elif ch in "]}":
            if not stack:
                continue
            expected = "]" if stack[-1] == "[" else "}"
            out.append(expected)
            stack.pop()
        else:
            if not stack:
                continue
            out.append(ch)

    while stack:
        out.append("]" if stack.pop() == "[" else "}")

    return "".join(out)


async def call_minimax(
    user_prompt: str,
    system_prompt: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 16384,
    timeout: float = 600.0,
    json_mode: bool = True,
) -> dict[str, Any]:
    """Call MiniMax m2.5 and return parsed JSON. Returns {} on failure.

    MiniMax's chat/completions endpoint is OpenAI-compatible. Model names
    like "MiniMax-M2" (or whatever is configured) are accepted via the
    `model` field.
    """

    if not settings.minimax_api_key:
        raise RuntimeError(
            "WORLD_MINIMAX_API_KEY is not set. The deity-dossier pipeline "
            "requires MiniMax m2.5 for archetype merge reasoning."
        )

    url = f"{settings.minimax_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.minimax_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = await _post_with_retry(url, payload, headers, timeout)
        if resp is None:
            return {}
        if resp.status_code != 200:
            logger.error(
                "MiniMax HTTP %d (final): %s",
                resp.status_code,
                resp.text[:500],
            )
            return {}
        data = resp.json()
    except Exception:
        logger.exception("MiniMax call failed")
        return {}

    try:
        raw = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected MiniMax response shape: %s", str(data)[:500])
        return {}

    # Strip <think> blocks (some MiniMax variants emit reasoning tags)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)

    parsed = _try_parse_json(raw)
    if parsed is not None:
        return parsed

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        logger.warning(
            "No JSON block in MiniMax output (%d chars). Sample: %s",
            len(raw),
            raw[:200],
        )
        return {}

    js = json_match.group()
    fixed = re.sub(
        r'(?<=": ")(.*?)(?="[,\}])',
        lambda m: m.group().replace("\n", "\\n"),
        js,
        flags=re.DOTALL,
    )
    parsed = _try_parse_json(fixed)
    if parsed is not None:
        return parsed

    repaired = _repair_truncated_json(js)
    if repaired:
        parsed = _try_parse_json(repaired)
        if parsed is not None:
            logger.warning("Recovered truncated MiniMax JSON via brace balancing")
            return parsed

    bracket_fixed = _bracket_aware_repair(js)
    if bracket_fixed != js:
        parsed = _try_parse_json(bracket_fixed)
        if parsed is not None:
            logger.warning("Recovered MiniMax JSON via bracket-aware repair")
            return parsed

    logger.warning(
        "Failed to parse MiniMax JSON after fixup. Sample: %s ... %s",
        js[:200],
        js[-200:] if len(js) > 200 else "",
    )
    logger.warning(
        "MiniMax raw content (len=%d) FULL: %s",
        len(raw),
        raw,
    )
    return {}


async def call_minimax_text(
    user_prompt: str,
    system_prompt: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: float = 300.0,
) -> str:
    """Call MiniMax and return the raw text content. Returns '' on failure."""

    if not settings.minimax_api_key:
        raise RuntimeError(
            "WORLD_MINIMAX_API_KEY is not set."
        )

    url = f"{settings.minimax_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.minimax_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = await _post_with_retry(url, payload, headers, timeout)
        if resp is None:
            return ""
        if resp.status_code != 200:
            logger.error(
                "MiniMax HTTP %d (final): %s",
                resp.status_code,
                resp.text[:500],
            )
            return ""
        data = resp.json()
    except Exception:
        logger.exception("MiniMax text call failed")
        return ""

    try:
        raw = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""

    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return raw
