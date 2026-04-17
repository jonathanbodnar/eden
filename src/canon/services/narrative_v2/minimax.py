"""MiniMax m2.5 LLM client.

Used for reasoning-heavy archetype merge analysis in the deity-dossier
pipeline. MiniMax exposes an OpenAI-compatible chat/completions API, so the
surface mirrors `call_deepseek` in `llm.py`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from src.canon.config import settings
from src.canon.services.narrative_v2.llm import (
    _repair_truncated_json,
    _try_parse_json,
)

logger = logging.getLogger(__name__)


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
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(
                    "MiniMax HTTP %d: %s", resp.status_code, resp.text[:500]
                )
            resp.raise_for_status()
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
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(
                    "MiniMax HTTP %d: %s", resp.status_code, resp.text[:500]
                )
            resp.raise_for_status()
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
