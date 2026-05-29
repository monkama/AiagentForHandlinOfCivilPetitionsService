from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel

from tools.schemas import ToolResult, failure, success


class _DraftOutput(BaseModel):
    required_info: List[str]
    missing_info: List[str]
    draft: Optional[str] = None
    cautions: List[str]


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


def RequirementAndDraftTool(
    *,
    category: str,
    agency: dict[str, Any] | None,
    user_input: str,
    want_draft: bool = True,
) -> ToolResult:
    if agency is None:
        return failure("DRAFT_FAILED", "기관 정보가 없어 필요 정보와 문안 초안을 생성할 수 없습니다.")

    client = _build_openai_client()
    if client is None:
        return failure("DRAFT_FAILED", "OpenAI client 또는 API 키를 사용할 수 없습니다.")

    model = os.environ.get("OPENAI_DRAFT_MODEL", "gpt-4o-mini")
    instructions = _read_prompt("requirement_and_draft_instructions.txt")

    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "category": category,
                        "agency": agency,
                        "user_input": user_input,
                        "want_draft": want_draft,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
        text_format=_DraftOutput,
        temperature=0,
        max_output_tokens=600,
    )

    token_usage = _response_token_usage(response)
    parsed = response.output_parsed
    if parsed is None:
        return failure(
            "DRAFT_FAILED",
            "LLM 문안 생성 결과를 파싱하지 못했습니다.",
            meta={
                "model": model,
                "token_usage": token_usage,
            },
        )

    data = parsed.model_dump()
    if not want_draft:
        data["draft"] = None

    data["facts"] = {
        "user_input": user_input,
        "want_draft": want_draft,
        "agency_name": agency.get("name"),
        "agency_unit": agency.get("unit"),
    }

    return success(
        data,
        meta={
            "model": model,
            "token_usage": token_usage,
        },
    )


run_requirement_and_draft = RequirementAndDraftTool
