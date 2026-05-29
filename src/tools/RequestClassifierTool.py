from __future__ import annotations

import os
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

from tools.schemas import ToolResult, failure, success


class _ClassificationOutput(BaseModel):
    """사용자 행정 민원 요청 분류 결과 스키마."""

    response_type: Literal[
        "public_service_inquiry",
        "issue_resolution",
        "administrative_procedure",
    ]
    category: Literal[
        "labor",
        "housing",
        "road_safety",
        "food_safety",
        "birth_support",
        "welfare",
        "tax",
        "environment",
        "residence",
        "unknown",
    ]
    urgency: Literal["normal", "high", "emergency"]
    keywords: List[str]
    needs_region: bool
    confidence: float
    region_text: Optional[str] = None


def _build_openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        return None

    if not os.environ.get("OPENAI_API_KEY"):
        return None

    return OpenAI()


def _read_prompt(filename: str) -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8").strip()


def _response_token_usage(response: object) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()

    if not isinstance(usage, dict):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))

    token_usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }

    reasoning_tokens = int(output_details.get("reasoning", 0) or 0)
    cached_input_tokens = int(
        input_details.get("cached_tokens", input_details.get("cache_read", 0)) or 0
    )
    if reasoning_tokens:
        token_usage["reasoning_tokens"] = reasoning_tokens
    if cached_input_tokens:
        token_usage["cached_input_tokens"] = cached_input_tokens
    return token_usage


def _llm_classifier(message: str) -> ToolResult:
    client = _build_openai_client()
    if client is None:
        return failure("CLASSIFICATION_FAILED", "OpenAI client 또는 API 키를 사용할 수 없습니다.")

    model = os.environ.get("OPENAI_CLASSIFIER_MODEL", "gpt-4o-mini")
    instructions = _read_prompt("request_classifier_instructions.txt")

    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": message},
        ],
        text_format=_ClassificationOutput,
        temperature=0,
        max_output_tokens=300,
    )

    token_usage = _response_token_usage(response)
    parsed = response.output_parsed
    if parsed is None:
        return failure(
            "CLASSIFICATION_FAILED",
            "LLM 분류 결과를 파싱하지 못했습니다.",
            meta={
                "model": model,
                "token_usage": token_usage,
            },
        )

    return success(
        parsed.model_dump(),
        meta={
            "model": model,
            "token_usage": token_usage,
        },
    )


def RequestClassifierTool(message: str) -> ToolResult:
    normalized = message.strip()
    if not normalized:
        return failure("CLASSIFICATION_FAILED", "요청 내용이 비어 있어 분류할 수 없습니다.")

    return _llm_classifier(normalized)


run_request_classifier = RequestClassifierTool
