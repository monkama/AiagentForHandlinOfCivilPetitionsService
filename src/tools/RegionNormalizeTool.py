from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from tools.schemas import ToolResult, failure, success


API_URL = "http://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList"
SERVICE_KEY_ENV_NAMES = (
    "PUBLIC_DATA_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "GOV_DATA_SERVICE_KEY",
)
SIDO_ALIASES = {
    "서울": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "광주": "광주광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전북특별자치도",
    "전남": "전라남도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
}
SIGUNGU_SUFFIXES = ("시", "군", "구")
DONG_SUFFIXES = ("읍", "면", "동", "가", "리")


def _service_key() -> str | None:
    for env_name in SERVICE_KEY_ENV_NAMES:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


def _normalize_text(region_text: str) -> str:
    return " ".join(region_text.strip().split())


def _query_candidates(region_text: str) -> list[str]:
    normalized = _normalize_text(region_text)
    if not normalized:
        return []

    candidates = [normalized]
    parts = normalized.split()
    first = parts[0]
    if first in SIDO_ALIASES:
        expanded = " ".join([SIDO_ALIASES[first], *parts[1:]]).strip()
        if expanded not in candidates:
            candidates.append(expanded)

    return candidates


def _request_rows(query: str, service_key: str) -> list[dict[str, Any]]:
    params = {
        "serviceKey": service_key,
        "pageNo": "1",
        "numOfRows": "100",
        "type": "json",
        "locatadd_nm": query,
    }
    url = f"{API_URL}?{urlencode(params)}"

    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "locatadd_nm" in node and any(key in node for key in ("region_cd", "locatadd_nm", "locallow_nm")):
                rows.append(node)
            for value in node.values():
                walk(value)
            return

        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return rows


def _score_row(row: dict[str, Any], query: str) -> tuple[int, int]:
    address = _normalize_text(str(row.get("locatadd_nm", "")))
    lowered_query = query.lower()
    lowered_address = address.lower()

    if address == query:
        return (400, len(address))
    if lowered_address.endswith(lowered_query):
        return (300, len(address))
    if lowered_query in lowered_address:
        return (200, len(address))

    query_tokens = set(query.split())
    address_tokens = set(address.split())
    overlap = len(query_tokens & address_tokens)
    if overlap:
        return (100 + overlap, len(address))

    return (0, len(address))


def _select_best_row(rows: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    if not rows:
        return None

    scored_rows = [(row, _score_row(row, query)) for row in rows]
    scored_rows = [item for item in scored_rows if item[1][0] > 0]
    if not scored_rows:
        return None

    scored_rows.sort(key=lambda item: item[1], reverse=True)
    best_score = scored_rows[0][1]
    best_rows = [row for row, score in scored_rows if score == best_score]

    unique_addresses = {_normalize_text(str(row.get("locatadd_nm", ""))) for row in best_rows}
    if len(unique_addresses) > 1:
        return None

    return best_rows[0]


def _split_region_name(address: str) -> tuple[str | None, str | None, str | None]:
    parts = _normalize_text(address).split()
    if not parts:
        return None, None, None

    sido = parts[0]
    index = 1
    sigungu_parts: list[str] = []

    if index < len(parts) and parts[index].endswith(SIGUNGU_SUFFIXES):
        sigungu_parts.append(parts[index])
        index += 1
        if (
            sigungu_parts[0].endswith("시")
            and index < len(parts)
            and parts[index].endswith(("구", "군"))
        ):
            sigungu_parts.append(parts[index])
            index += 1

    dong_parts = parts[index:]
    sigungu = " ".join(sigungu_parts) or None
    dong = " ".join(dong_parts) or None

    if dong and not dong.endswith(DONG_SUFFIXES):
        dong = None

    return sido, sigungu, dong


def _build_success(region_text: str, row: dict[str, Any], query: str) -> ToolResult:
    address = _normalize_text(str(row.get("locatadd_nm", "")))
    sido, sigungu, dong = _split_region_name(address)

    if address == query:
        confidence = 0.99
    elif address.endswith(query):
        confidence = 0.95
    else:
        confidence = 0.9

    legal_dong_code = (
        row.get("region_cd")
        or row.get("locatjijuk_cd")
        or row.get("locatjumin_cd")
    )

    return success(
        {
            "region_text": region_text,
            "sido": sido,
            "sigungu": sigungu,
            "dong": dong,
            "legal_dong_code": str(legal_dong_code) if legal_dong_code is not None else None,
            "confidence": confidence,
        }
    )


def RegionNormalizeTool(region_text: str) -> ToolResult:
    normalized = _normalize_text(region_text)
    if not normalized:
        return failure("REGION_NOT_FOUND", "지역 정보가 비어 있어 표준화할 수 없습니다.")

    service_key = _service_key()
    if service_key is None:
        return failure(
            "REGION_API_FAILED",
            "공공데이터포털 서비스키가 없어 RegionNormalizeTool API를 호출할 수 없습니다.",
        )

    try:
        for query in _query_candidates(normalized):
            rows = _request_rows(query, service_key)
            best_row = _select_best_row(rows, query)
            if best_row is not None:
                return _build_success(normalized, best_row, query)
    except HTTPError as exc:
        return failure("REGION_API_FAILED", f"지역 표준화 API 호출 중 HTTP 오류가 발생했습니다: {exc.code}")
    except URLError as exc:
        return failure("REGION_API_FAILED", f"지역 표준화 API 호출 중 네트워크 오류가 발생했습니다: {exc.reason}")
    except json.JSONDecodeError:
        return failure("REGION_API_FAILED", "지역 표준화 API 응답을 JSON으로 해석하지 못했습니다.")
    except Exception as exc:
        return failure("REGION_API_FAILED", f"지역 표준화 API 호출 중 오류가 발생했습니다: {exc}")

    return failure("REGION_NOT_FOUND", f"입력한 지역명 '{normalized}' 을(를) 표준 행정구역으로 찾지 못했습니다.")


run_region_normalizer = RegionNormalizeTool
