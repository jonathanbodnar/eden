"""LLM + embedding clients for the V2 narrative pipeline."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from src.canon.config import settings

logger = logging.getLogger(__name__)


async def call_deepseek(
    user_prompt: str,
    system_prompt: str,
    *,
    temperature: float = 0.4,
    max_tokens: int = 8192,
    timeout: float = 300.0,
    json_mode: bool = True,
) -> dict[str, Any]:
    """Call DeepSeek and return parsed JSON. Returns {} on failure."""

    if not settings.deepseek_api_key:
        raise RuntimeError(
            "WORLD_DEEPSEEK_API_KEY is not set. Narrative synthesis requires DeepSeek."
        )

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode and "reasoner" not in settings.deepseek_model.lower():
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error("DeepSeek HTTP %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("DeepSeek call failed")
        return {}

    raw = data["choices"][0]["message"]["content"] or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)

    parsed = _try_parse_json(raw)
    if parsed is not None:
        return parsed

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        logger.warning(
            "No JSON block in DeepSeek output (%d chars). Sample: %s",
            len(raw),
            raw[:200],
        )
        return {}

    js = json_match.group()

    # Fix unescaped newlines inside string values
    fixed = re.sub(
        r'(?<=": ")(.*?)(?="[,\}])',
        lambda m: m.group().replace("\n", "\\n"),
        js,
        flags=re.DOTALL,
    )
    parsed = _try_parse_json(fixed)
    if parsed is not None:
        return parsed

    # Last resort: balance trailing braces if response was truncated
    repaired = _repair_truncated_json(js)
    if repaired:
        parsed = _try_parse_json(repaired)
        if parsed is not None:
            logger.warning("Recovered truncated DeepSeek JSON via brace balancing")
            return parsed

    logger.warning(
        "Failed to parse DeepSeek JSON after fixup. Sample: %s ... %s",
        js[:200],
        js[-200:] if len(js) > 200 else "",
    )
    return {}


def _try_parse_json(s: str) -> dict[str, Any] | None:
    try:
        out = json.loads(s)
        return out if isinstance(out, dict) else {"_root": out}
    except json.JSONDecodeError:
        return None


def _repair_truncated_json(s: str) -> str | None:
    """Best-effort repair: cut at last comma/value boundary and balance braces."""
    if not s:
        return None
    # Strip dangling characters at the tail until we land on a sane boundary
    tail = s.rstrip()
    # Find the last position that ends a value or key safely
    for cut in range(len(tail), 0, -1):
        ch = tail[cut - 1]
        if ch in '"]}0123456789tfnel':
            tail = tail[:cut]
            break
    # Balance brackets / braces
    open_curly = tail.count("{") - tail.count("}")
    open_square = tail.count("[") - tail.count("]")
    if open_curly < 0 or open_square < 0:
        return None
    # Remove any trailing comma
    tail = re.sub(r",\s*$", "", tail)
    return tail + ("]" * open_square) + ("}" * open_curly)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return an embedding vector for each input text via OpenAI.

    Returns a list of all-zero vectors on failure so callers don't crash.
    """

    if not settings.openai_api_key:
        logger.warning("WORLD_OPENAI_API_KEY not set — returning zero embeddings")
        return [[0.0] * settings.embedding_dimensions for _ in texts]

    if not texts:
        return []

    # OpenAI embeddings API accepts batches; stay well under token limits
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": settings.embedding_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        return [item["embedding"] for item in data["data"]]
    except Exception:
        logger.exception("Embedding call failed")
        return [[0.0] * settings.embedding_dimensions for _ in texts]
