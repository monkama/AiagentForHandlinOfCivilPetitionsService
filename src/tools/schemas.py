from __future__ import annotations

from typing import Any, TypedDict


class ToolError(TypedDict):
    code: str
    message: str


class TokenUsage(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int
    cached_input_tokens: int


class ToolMeta(TypedDict, total=False):
    token_usage: TokenUsage
    usage_breakdown: dict[str, TokenUsage]
    model: str


class ToolResult(TypedDict):
    ok: bool
    data: dict[str, Any] | None
    error: ToolError | None
    meta: ToolMeta | None


def empty_token_usage() -> TokenUsage:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def normalize_token_usage(token_usage: dict[str, Any] | None) -> TokenUsage:
    if not isinstance(token_usage, dict):
        return empty_token_usage()

    input_tokens = int(token_usage.get("input_tokens", 0) or 0)
    output_tokens = int(token_usage.get("output_tokens", 0) or 0)
    total_tokens = int(token_usage.get("total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
    reasoning_tokens = int(token_usage.get("reasoning_tokens", 0) or 0)
    cached_input_tokens = int(token_usage.get("cached_input_tokens", 0) or 0)

    normalized: TokenUsage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    if reasoning_tokens:
        normalized["reasoning_tokens"] = reasoning_tokens
    if cached_input_tokens:
        normalized["cached_input_tokens"] = cached_input_tokens
    return normalized


def merge_token_usage(*token_usages: dict[str, Any] | None) -> TokenUsage:
    merged = empty_token_usage()
    reasoning_total = 0
    cached_total = 0

    for token_usage in token_usages:
        normalized = normalize_token_usage(token_usage)
        merged["input_tokens"] += normalized["input_tokens"]
        merged["output_tokens"] += normalized["output_tokens"]
        merged["total_tokens"] += normalized["total_tokens"]
        reasoning_total += int(normalized.get("reasoning_tokens", 0) or 0)
        cached_total += int(normalized.get("cached_input_tokens", 0) or 0)

    if reasoning_total:
        merged["reasoning_tokens"] = reasoning_total
    if cached_total:
        merged["cached_input_tokens"] = cached_total
    return merged


def extract_token_usage(result: dict[str, Any] | None) -> TokenUsage:
    if not isinstance(result, dict):
        return empty_token_usage()

    meta = result.get("meta")
    if not isinstance(meta, dict):
        return empty_token_usage()

    return normalize_token_usage(meta.get("token_usage"))


def _normalize_meta(meta: dict[str, Any] | None) -> ToolMeta | None:
    if not isinstance(meta, dict):
        return None

    normalized_meta: ToolMeta = {}
    token_usage = meta.get("token_usage")
    if token_usage is not None:
        normalized_meta["token_usage"] = normalize_token_usage(token_usage)

    usage_breakdown = meta.get("usage_breakdown")
    if isinstance(usage_breakdown, dict):
        normalized_meta["usage_breakdown"] = {
            str(key): normalize_token_usage(value if isinstance(value, dict) else None)
            for key, value in usage_breakdown.items()
        }

    model = meta.get("model")
    if model:
        normalized_meta["model"] = str(model)

    return normalized_meta or None


def success(data: dict[str, Any], meta: dict[str, Any] | None = None) -> ToolResult:
    return {
        "ok": True,
        "data": data,
        "error": None,
        "meta": _normalize_meta(meta),
    }


def failure(code: str, message: str, meta: dict[str, Any] | None = None) -> ToolResult:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
        "meta": _normalize_meta(meta),
    }
