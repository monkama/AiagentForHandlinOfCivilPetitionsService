from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from tools.schemas import ToolResult, failure, success


SERVICE_LIST_API_URL = "https://api.odcloud.kr/api/gov24/v3/serviceList"
SERVICE_DETAIL_API_URL = "https://api.odcloud.kr/api/gov24/v3/serviceDetail"
SUPPORT_CONDITIONS_API_URL = "https://api.odcloud.kr/api/gov24/v3/supportConditions"
SERVICE_KEY_ENV_NAMES = (
    "PUBLIC_SERVICE_API_KEY",
    "PUBLIC_DATA_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "GOV_DATA_SERVICE_KEY",
)


def _service_key() -> str | None:
    for env_name in SERVICE_KEY_ENV_NAMES:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


def _request_json(url: str, params: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    encoded = urlencode({key: value for key, value in params.items() if value is not None})
    request_url = f"{url}?{encoded}"
    with urlopen(request_url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _query_terms(keywords: list[str]) -> list[str]:
    cleaned: list[str] = []
    for keyword in keywords:
        normalized = " ".join(keyword.strip().split())
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)

    terms: list[str] = []
    if cleaned:
        terms.append(" ".join(cleaned[:3]))
    terms.extend(cleaned[:4])

    unique_terms: list[str] = []
    for term in terms:
        if term and term not in unique_terms:
            unique_terms.append(term)
    return unique_terms


def _service_list_query(query: str, service_key: str) -> list[dict[str, Any]]:
    payload = _request_json(
        SERVICE_LIST_API_URL,
        {
            "serviceKey": service_key,
            "page": 1,
            "perPage": 10,
            "returnType": "json",
            "cond[서비스명::LIKE]": query,
        },
    )
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _service_detail(service_id: str, service_key: str) -> dict[str, Any] | None:
    payload = _request_json(
        SERVICE_DETAIL_API_URL,
        {
            "serviceKey": service_key,
            "page": 1,
            "perPage": 1,
            "returnType": "json",
            "cond[서비스ID::EQ]": service_id,
        },
    )
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _support_conditions(service_id: str, service_key: str) -> dict[str, Any] | None:
    payload = _request_json(
        SUPPORT_CONDITIONS_API_URL,
        {
            "serviceKey": service_key,
            "page": 1,
            "perPage": 1,
            "returnType": "json",
            "cond[서비스ID::EQ]": service_id,
        },
    )
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _region_tokens(region_text: str | None) -> list[str]:
    if not region_text:
        return []
    return [token for token in region_text.split() if token]


def _score_service(item: dict[str, Any], query_terms: list[str], region_text: str | None) -> int:
    haystack = " ".join(
        str(item.get(field, ""))
        for field in ("서비스명", "서비스목적요약", "지원내용", "소관기관명")
    ).lower()
    score = 0
    for term in query_terms:
        if term.lower() in haystack:
            score += 5
    for token in _region_tokens(region_text):
        if token.lower() in haystack:
            score += 3
    return score


def _build_application_channel(detail: dict[str, Any] | None, item: dict[str, Any]) -> str:
    channels: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in channels:
            channels.append(text)

    if detail is not None:
        add(detail.get("온라인신청사이트URL"))
        add(detail.get("신청방법"))
        add(detail.get("접수기관명"))
        add(detail.get("문의처"))

    add(item.get("신청방법"))
    add(item.get("접수기관"))
    add(item.get("전화문의"))

    if not channels:
        return "정부24 또는 소관기관 문의"
    return " / ".join(channels[:3])


def _join_non_empty(*values: Any) -> str:
    parts = [str(value).strip() for value in values if str(value or "").strip()]
    return " / ".join(parts)


def _truncate(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _matched_conditions(category: str, region_text: str | None, profile_text: str | None) -> list[str]:
    matched: list[str] = []
    if region_text:
        matched.append(f"거주/이용 지역: {region_text}")
    if profile_text:
        matched.append(f"사용자 조건: {profile_text}")
    if category == "birth_support":
        matched.append("출산·양육 관련 키워드 일치")
    elif category == "welfare":
        matched.append("복지 혜택 관련 키워드 일치")
    return matched


def _need_more_info(category: str, region_text: str | None, profile_text: str | None) -> list[str]:
    needed: list[str] = []

    def add(field_name: str) -> None:
        if field_name not in needed:
            needed.append(field_name)

    if category in {"birth_support", "welfare", "housing", "residence"} and not region_text:
        add("거주 지역")

    if not profile_text:
        if category == "birth_support":
            add("자녀 출생일 또는 자녀 연령")
        elif category == "welfare":
            add("가구 구성 또는 소득 기준")
        elif category == "housing":
            add("거주 형태 또는 소득 기준")

    return needed


def PublicServiceSearchTool(
    *,
    category: str,
    keywords: list[str],
    region_text: str | None = None,
    profile_text: str | None = None,
) -> ToolResult:
    service_key = _service_key()
    if service_key is None:
        return failure(
            "SERVICE_API_FAILED",
            "공공데이터포털 서비스키가 없어 PublicServiceSearchTool API를 호출할 수 없습니다.",
        )

    query_terms = _query_terms(keywords)
    if not query_terms:
        return failure("SERVICE_API_FAILED", "공공서비스 검색에 사용할 키워드가 부족합니다.")

    try:
        aggregated: dict[str, dict[str, Any]] = {}
        for query in query_terms:
            for item in _service_list_query(query, service_key):
                service_id = str(item.get("서비스ID", "")).strip()
                if not service_id:
                    continue
                score = _score_service(item, [query], region_text)
                current = aggregated.get(service_id)
                if current is None or score > current["_score"]:
                    item = dict(item)
                    item["_score"] = score
                    item["_matched_query"] = query
                    aggregated[service_id] = item

        ranked_items = sorted(
            aggregated.values(),
            key=lambda item: (-int(item.get("_score", 0)), str(item.get("서비스명", ""))),
        )
        if not ranked_items:
            return failure("NO_SERVICE_FOUND", "공공서비스 API에서 요청에 맞는 서비스를 찾지 못했습니다.")

        services: list[dict[str, Any]] = []
        for item in ranked_items[:5]:
            service_id = str(item.get("서비스ID", "")).strip()
            detail = _service_detail(service_id, service_key)
            conditions = _support_conditions(service_id, service_key)
            summary = _truncate(
                _join_non_empty(
                    (detail or {}).get("지원내용"),
                    item.get("서비스목적요약"),
                )
            )
            eligibility = _truncate(
                _join_non_empty(
                    (detail or {}).get("지원대상"),
                    (detail or {}).get("선정기준"),
                    item.get("지원대상"),
                    item.get("선정기준"),
                )
            )
            services.append(
                {
                    "name": (detail or {}).get("서비스명") or item.get("서비스명"),
                    "provider": (detail or {}).get("소관기관명") or item.get("소관기관명"),
                    "summary": summary or _truncate(str(item.get("서비스목적요약", "")).strip()),
                    "eligibility": eligibility,
                    "application_channel": _build_application_channel(detail, item),
                    "service_id": service_id,
                    "detail_url": item.get("상세조회URL"),
                    "matched_query": item.get("_matched_query"),
                    "support_condition_snapshot": {
                        key: value
                        for key, value in (conditions or {}).items()
                        if key.startswith("JA") and str(value or "").strip()
                    },
                }
            )

        return success(
            {
                "services": services,
                "matched_conditions": _matched_conditions(category, region_text, profile_text),
                "need_more_info": _need_more_info(category, region_text, profile_text),
                "query_terms": query_terms,
            }
        )
    except HTTPError as exc:
        return failure("SERVICE_API_FAILED", f"공공서비스 API 호출 중 HTTP 오류가 발생했습니다: {exc.code}")
    except URLError as exc:
        return failure("SERVICE_API_FAILED", f"공공서비스 API 호출 중 네트워크 오류가 발생했습니다: {exc.reason}")
    except json.JSONDecodeError:
        return failure("SERVICE_API_FAILED", "공공서비스 API 응답을 JSON으로 해석하지 못했습니다.")
    except Exception as exc:
        return failure("SERVICE_API_FAILED", f"공공서비스 API 호출 중 오류가 발생했습니다: {exc}")


run_public_service_search = PublicServiceSearchTool
