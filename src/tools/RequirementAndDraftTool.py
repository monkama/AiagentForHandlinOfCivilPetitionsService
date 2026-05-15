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

    parsed = response.output_parsed
    if parsed is None:
        return failure("DRAFT_FAILED", "LLM 문안 생성 결과를 파싱하지 못했습니다.")

    data = parsed.model_dump()
    if not want_draft:
        data["draft"] = None

    data["facts"] = {
        "user_input": user_input,
        "want_draft": want_draft,
        "agency_name": agency.get("name"),
        "agency_unit": agency.get("unit"),
    }

    return success(data)


run_requirement_and_draft = RequirementAndDraftTool
