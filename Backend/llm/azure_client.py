"""Azure OpenAI client helpers (chat + embeddings)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from openai import AzureOpenAI

from core.config import get_settings


def _normalize_azure_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").strip().rstrip("/")
    # Project-style URLs sometimes include /api/projects/... — keep host root.
    marker = "/api/projects/"
    idx = endpoint.find(marker)
    if idx != -1:
        endpoint = endpoint[:idx]
    marker2 = "/openai/"
    idx2 = endpoint.find(marker2)
    if idx2 != -1:
        endpoint = endpoint[:idx2]
    return endpoint.rstrip("/")


@lru_cache
def get_openai_client() -> AzureOpenAI:
    settings = get_settings()
    if not settings.azure_api_key:
        raise ValueError("Set AZURE_OPENAI_API_KEY in .env")
    if not settings.azure_endpoint:
        raise ValueError("Set AZURE_OPENAI_ENDPOINT in .env")
    return AzureOpenAI(
        api_key=settings.azure_api_key,
        api_version=settings.azure_api_version,
        azure_endpoint=_normalize_azure_endpoint(settings.azure_endpoint),
    )


def is_azure_configured() -> bool:
    settings = get_settings()
    return bool(settings.azure_api_key and settings.azure_endpoint and settings.azure_deployment)


def chat_completion(
    messages: list[dict[str, str]],
    *,
    deployment: str | None = None,
    temperature: float = 0.0,
    response_format: dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, int]]:
    """Return (content, token_usage)."""
    settings = get_settings()
    client = get_openai_client()
    model = deployment or settings.extraction_model
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    usage = {
        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(resp.usage, "total_tokens", 0) or 0,
    }
    return content, usage


def embed_texts(texts: list[str], *, deployment: str | None = None) -> list[list[float]]:
    settings = get_settings()
    dep = deployment or settings.azure_embedding_deployment
    if not dep:
        raise ValueError(
            "Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT for Azure embeddings, "
            "or set EMBEDDING_PROVIDER=hashing"
        )
    client = get_openai_client()
    # Azure OpenAI embedding API
    resp = client.embeddings.create(model=dep, input=texts)
    # Ensure order by index
    ordered = sorted(resp.data, key=lambda d: d.index)
    return [list(d.embedding) for d in ordered]


def parse_json_content(content: str) -> Any:
    """Best-effort JSON extraction from LLM output."""
    content = (content or "").strip()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None
