from __future__ import annotations

from typing import Any

from tools.schemas import ToolResult, failure, success


def _labor_draft(agency_name: str) -> dict[str, Any]:
    required_info = [
        "사업장명",
        "근무기간",
        "퇴사일",
        "미지급 퇴직금 금액",
        "근로계약서 또는 급여명세서",
    ]
    return {
        "required_info": required_info,
        "missing_info": required_info,
        "draft": (
            f"{agency_name}에 퇴직금 미지급 관련 진정을 접수하고 싶습니다. "
            "사업장명, 근무기간, 퇴사일, 미지급 금액을 바탕으로 사실관계 확인과 필요한 조치를 요청드립니다."
        ),
        "cautions": [
            "근무기간과 퇴사일을 가능한 정확히 정리하세요.",
            "급여명세서, 근로계약서, 통장내역 등 증빙자료를 준비하세요.",
            "정확한 사업장 명칭과 사업장 주소를 함께 확인하면 접수에 도움이 됩니다.",
        ],
    }


def _residence_draft(agency_name: str) -> dict[str, Any]:
    required_info = [
        "새 주소",
        "전입일",
        "세대주 여부",
        "신분증",
        "필요 시 임대차계약서",
    ]
    return {
        "required_info": required_info,
        "missing_info": ["새 주소", "전입일", "세대주 여부"],
        "draft": (
            f"{agency_name}에서 전입신고를 진행하려고 합니다. "
            "필요 서류와 접수 절차를 확인하고 싶습니다."
        ),
        "cautions": [
            "온라인 신청 가능 여부는 정부24에서 먼저 확인하세요.",
            "세대주 변경이나 세대 합가가 있으면 추가 확인이 필요할 수 있습니다.",
            "주소와 전입일 정보가 정확해야 처리 지연을 줄일 수 있습니다.",
        ],
    }


def RequirementAndDraftTool(
    *,
    category: str,
    agency: dict[str, Any] | None,
    user_input: str,
    want_draft: bool = True,
) -> ToolResult:
    if agency is None:
        return failure("DRAFT_FAILED", "기관 정보가 없어 필요 정보와 문안 초안을 생성할 수 없습니다.")

    agency_name = agency.get("name", "담당 기관")

    if category == "labor":
        data = _labor_draft(agency_name)
    elif category == "residence":
        data = _residence_draft(agency_name)
    else:
        return failure("DRAFT_FAILED", f"category={category} 에 대한 초안 템플릿이 아직 없습니다.")

    data["facts"] = {
        "user_input": user_input,
        "want_draft": want_draft,
    }
    if not want_draft:
        data["draft"] = None

    return success(data)


run_requirement_and_draft = RequirementAndDraftTool
