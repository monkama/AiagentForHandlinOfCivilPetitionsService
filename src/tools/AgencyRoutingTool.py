from __future__ import annotations

from typing import Any

from tools.schemas import ToolResult, failure, success


def AgencyRoutingTool(
    *,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None = None,
) -> ToolResult:
    if response_type == "issue_resolution" and category == "labor":
        return success(
            {
                "agency_candidates": [
                    {
                        "name": "고용노동부",
                        "unit": "관할 지방고용노동관서",
                        "reason": "퇴직금 미지급은 노동관계법 위반 가능성이 있어 고용노동부 진정 대상에 해당할 수 있습니다.",
                        "confidence": 0.97,
                    }
                ],
                "channels": [
                    "고용노동부 고객상담센터 1350",
                    "고용노동부 민원/진정 접수",
                    "관할 지방고용노동관서 방문 접수",
                ],
                "confidence": 0.97,
                "keywords": keywords,
            }
        )

    if response_type == "administrative_procedure" and category == "residence":
        location_hint = "정부24 또는 전입지 주민센터"
        if normalized_region and normalized_region.get("sigungu"):
            location_hint = f"{normalized_region['sigungu']} 주민센터 또는 정부24"

        return success(
            {
                "agency_candidates": [
                    {
                        "name": "행정복지센터",
                        "unit": location_hint,
                        "reason": "전입신고는 전입지 기준 주민센터 또는 정부24에서 처리하는 대표적인 행정 절차입니다.",
                        "confidence": 0.95,
                    }
                ],
                "channels": [
                    "정부24 온라인 신청",
                    "전입지 관할 주민센터 방문",
                ],
                "confidence": 0.95,
                "keywords": keywords,
            }
        )

    if response_type == "issue_resolution" and category == "road_safety":
        channels = [
            "긴급 상황이면 112 또는 119",
            "안전신문고 신고",
            "지자체 도로관리부서 또는 당직실",
        ]
        if urgency == "emergency":
            channels = [
                "즉시 112 또는 119 신고",
                "지자체 당직실 또는 도로관리부서 긴급 연락",
                "안전신문고 후속 신고",
            ]

        return success(
            {
                "agency_candidates": [
                    {
                        "name": "지방자치단체",
                        "unit": "도로관리부서",
                        "reason": "도로 파손, 싱크홀, 붕괴 위험은 위치 기반 현장 조치가 필요한 지자체 소관 안전 민원입니다.",
                        "confidence": 0.92,
                    },
                    {
                        "name": "경찰/소방",
                        "unit": "112 또는 119",
                        "reason": "즉시 사고 위험이 있으면 일반 민원보다 긴급 대응 채널이 우선입니다.",
                        "confidence": 0.95,
                    },
                ],
                "channels": channels,
                "confidence": 0.94,
                "keywords": keywords,
            }
        )

    return failure(
        "NO_ROUTE_FOUND",
        f"response_type={response_type}, category={category} 조합에 맞는 기관 후보를 찾지 못했습니다.",
    )


run_agency_router = AgencyRoutingTool
