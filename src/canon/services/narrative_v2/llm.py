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
) -> dict[str, Any]:
    """Call DeepSeek and return parsed JSON. Returns {} on failure."""

    if not settings.deepseek_api_key:
        raise RuntimeError(
            "WORLD_DEEPSEEK_API_KEY is not set. Narrative synthesis requires DeepSeek."
        )

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
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

    raw = data["choices"][0]["message"]["content"]
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        logger.warning("No JSON block in DeepSeek output (%d chars)", len(raw))
        return {}

    js = json_match.group()
    try:
        return json.loads(js)
    except json.JSONDecodeError:
        pass

    # Fix unescaped newlines inside string values
    fixed = re.sub(
        r'(?<=": ")(.*?)(?="[,\}])',
        lambda m: m.group().replace("\n", "\\n"),
        js,
        flags=re.DOTALL,
    )
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        logger.warning("Failed to parse DeepSeek JSON after fixup")
        return {}


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
