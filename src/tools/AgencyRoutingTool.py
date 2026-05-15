from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel

from tools.schemas import ToolResult, failure, success


ORG_CODE_API_URL = "http://apis.data.go.kr/1741000/StanOrgCd2/getStanOrgCdList2"
ORG_CODE_SERVICE_KEY_ENV_NAMES = (
    "ORG_CODE_API_KEY",
    "PUBLIC_DATA_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "GOV_DATA_SERVICE_KEY",
)


class _RoutingDecision(BaseModel):
    selected_candidate_ids: List[str]
    confidence: float
    routing_reason: str


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


def _service_key() -> str | None:
    for env_name in ORG_CODE_SERVICE_KEY_ENV_NAMES:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


def _request_json(url: str, params: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    encoded = urlencode({key: value for key, value in params.items() if value is not None})
    request_url = f"{url}?{encoded}"
    with urlopen(request_url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _walk_org_rows(node: Any, rows: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "full_nm" in node or "org_cd" in node:
            rows.append(node)
        for value in node.values():
            _walk_org_rows(value, rows)
        return
    if isinstance(node, list):
        for item in node:
            _walk_org_rows(item, rows)


def _normalize_agency_name(label: str, service_key: str | None) -> dict[str, Any] | None:
    if service_key is None:
        return None

    payload = _request_json(
        ORG_CODE_API_URL,
        {
            "serviceKey": service_key,
            "pageNo": "1",
            "numOfRows": "20",
            "type": "json",
            "full_nm": label,
            "stop_selt": "0",
        },
    )
    rows: list[dict[str, Any]] = []
    _walk_org_rows(payload, rows)
    if not rows:
        return None

    lowered_label = label.lower()
    exact = None
    contains = None
    for row in rows:
        full_name = str(row.get("full_nm", "")).strip()
        if not full_name:
            continue
        lowered_name = full_name.lower()
        if lowered_name == lowered_label:
            exact = row
            break
        if lowered_label in lowered_name and contains is None:
            contains = row

    selected = exact or contains or rows[0]
    full_name = str(selected.get("full_nm", "")).strip() or label
    org_code = str(selected.get("org_cd", "")).strip() or None
    return {
        "name": full_name,
        "org_code": org_code,
    }


def _region_label(normalized_region: dict[str, Any] | None) -> str | None:
    if not normalized_region:
        return None
    for key in ("sigungu", "sido"):
        value = normalized_region.get(key)
        if value:
            return str(value)
    return None


def _build_candidate_catalog(
    response_type: str,
    category: str,
    urgency: str,
    normalized_region: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    region_label = _region_label(normalized_region)
    residence_unit = f"{region_label} 관할 행정복지센터" if region_label else "전입지 관할 행정복지센터"
    road_unit = f"{region_label} 도로관리부서" if region_label else "관할 도로관리부서"
    env_unit = f"{region_label} 환경부서" if region_label else "관할 환경부서"
    food_unit = f"{region_label} 위생부서" if region_label else "관할 위생부서"

    catalog_by_category: dict[str, list[dict[str, Any]]] = {
        "labor": [
            {
                "id": "labor_moel",
                "agency_name": "고용노동부",
                "verification_name": "고용노동부",
                "local_unit": "관할 지방고용노동관서",
                "channels": [
                    "고용노동부 고객상담센터 1350",
                    "고용노동부 홈페이지 민원/진정 접수",
                    "관할 지방고용노동관서 방문",
                ]
            },
            {
                "id": "labor_portal",
                "agency_name": "국민권익위원회",
                "verification_name": "국민권익위원회",
                "local_unit": "국민신문고",
                "channels": ["국민신문고 온라인 민원 접수"]
            },
        ],
        "residence": [
            {
                "id": "residence_main",
                "agency_name": "행정안전부",
                "verification_name": "행정안전부",
                "local_unit": residence_unit,
                "channels": [
                    "정부24 온라인 신청",
                    f"{residence_unit} 방문",
                ]
            },
        ],
        "road_safety": [
            {
                "id": "road_emergency",
                "agency_name": "긴급신고",
                "verification_name": None,
                "local_unit": "112 또는 119",
                "channels": ["즉시 112 신고", "즉시 119 신고"]
            },
            {
                "id": "road_local",
                "agency_name": "지방자치단체",
                "verification_name": None,
                "local_unit": road_unit,
                "channels": [
                    "안전신문고 신고",
                    f"{road_unit} 문의",
                    "관할 지자체 민원실 문의",
                ]
            },
        ],
        "food_safety": [
            {
                "id": "food_local",
                "agency_name": "식품의약품안전처",
                "verification_name": "식품의약품안전처",
                "local_unit": food_unit,
                "channels": [
                    "식품안전나라 또는 관할 위생부서 신고",
                    f"{food_unit} 문의",
                ]
            },
        ],
        "environment": [
            {
                "id": "environment_local",
                "agency_name": "환경부",
                "verification_name": "환경부",
                "local_unit": env_unit,
                "channels": [
                    f"{env_unit} 민원 접수",
                    "국민신문고 온라인 민원 접수",
                ]
            },
        ],
        "tax": [
            {
                "id": "tax_nts",
                "agency_name": "국세청",
                "verification_name": "국세청",
                "local_unit": "관할 세무서",
                "channels": [
                    "홈택스 온라인 신청/문의",
                    "관할 세무서 방문 또는 전화 문의",
                ]
            },
        ],
        "housing": [
            {
                "id": "housing_molit",
                "agency_name": "국토교통부",
                "verification_name": "국토교통부",
                "local_unit": "지자체 주택부서 또는 주거복지센터",
                "channels": [
                    "국토교통부/지자체 주거민원 채널",
                    "주거복지센터 또는 관할 지자체 문의",
                ]
            },
        ],
    }

    if category in catalog_by_category:
        candidates = catalog_by_category[category]
    elif response_type == "administrative_procedure":
        candidates = [
            {
                "id": "procedure_generic",
                "agency_name": "행정안전부",
                "verification_name": "행정안전부",
                "local_unit": region_label + " 관할 행정기관" if region_label else "관할 행정기관",
                "channels": ["정부24", "관할 행정기관 민원 창구"]
            },
        ]
    else:
        candidates = [
            {
                "id": "generic_portal",
                "agency_name": "국민권익위원회",
                "verification_name": "국민권익위원회",
                "local_unit": "국민신문고",
                "channels": ["국민신문고 온라인 민원 접수"]
            },
        ]

    if category == "road_safety" and urgency != "emergency":
        candidates = [candidate for candidate in candidates if candidate["id"] != "road_emergency"]

    return candidates


def _llm_route(
    *,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None,
    catalog: list[dict[str, Any]],
) -> _RoutingDecision | None:
    client = _build_openai_client()
    if client is None:
        return None

    instructions = _read_prompt("agency_routing_instructions.txt")
    model = os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini")

    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "response_type": response_type,
                        "category": category,
                        "urgency": urgency,
                        "keywords": keywords,
                        "normalized_region": normalized_region,
                        "candidate_catalog": catalog,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
        text_format=_RoutingDecision,
        temperature=0,
        max_output_tokens=400,
    )

    return response.output_parsed


def AgencyRoutingTool(
    *,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None = None,
) -> ToolResult:
    catalog = _build_candidate_catalog(response_type, category, urgency, normalized_region)
    if not catalog:
        return failure("NO_ROUTE_FOUND", "현재 조건에 맞는 기관 후보 카탈로그를 구성하지 못했습니다.")

    decision = _llm_route(
        response_type=response_type,
        category=category,
        urgency=urgency,
        keywords=keywords,
        normalized_region=normalized_region,
        catalog=catalog,
    )
    if decision is None:
        return failure("ROUTING_FAILED", "OpenAI client 또는 API 키를 사용할 수 없어 기관 라우팅을 수행할 수 없습니다.")

    selected_ids: list[str] = []
    for candidate_id in decision.selected_candidate_ids:
        if candidate_id not in selected_ids:
            selected_ids.append(candidate_id)
    selected_ids = [candidate_id for candidate_id in selected_ids if any(item["id"] == candidate_id for item in catalog)]

    if not selected_ids:
        return failure("NO_ROUTE_FOUND", "기관 후보 선택 결과가 비어 있어 라우팅을 완료할 수 없습니다.")

    org_service_key = _service_key()
    agency_candidates: list[dict[str, Any]] = []
    channels: list[str] = []

    for index, candidate_id in enumerate(selected_ids[:3]):
        candidate = next(item for item in catalog if item["id"] == candidate_id)
        verified_name = candidate["agency_name"]
        institution_code = None
        verification_name = candidate.get("verification_name")
        if verification_name:
            try:
                normalized = _normalize_agency_name(str(verification_name), org_service_key)
            except (HTTPError, URLError, json.JSONDecodeError, Exception):
                normalized = None
            if normalized is not None:
                verified_name = normalized["name"]
                institution_code = normalized["org_code"]

        for channel in candidate["channels"]:
            if channel not in channels:
                channels.append(channel)

        confidence = max(0.4, round(float(decision.confidence) - (index * 0.08), 2))
        agency_candidates.append(
            {
                "name": verified_name,
                "local_unit": candidate["local_unit"],
                "reason": f"라우팅 AI가 현재 요청과 가장 직접적으로 연결되는 후보로 선택했습니다.",
                "confidence": confidence,
                "institution_code": institution_code,
            }
        )

    return success(
        {
            "agency_candidates": agency_candidates,
            "channels": channels,
            "confidence": round(float(decision.confidence), 2),
            "keywords": keywords,
            "routing_reason": decision.routing_reason,
            "candidate_catalog_size": len(catalog),
            "selected_candidate_ids": selected_ids[:3],
        }
    )


run_agency_router = AgencyRoutingTool
