from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from tools.minwon_pageindex_tree import (
    get_department_catalog,
    get_ministry_catalog,
    get_records_in_scopes,
    write_search_log,
)
from tools.schemas import ToolResult, failure, merge_token_usage, normalize_token_usage, success


ORG_CODE_API_URL = "http://apis.data.go.kr/1741000/StanOrgCd2/getStanOrgCdList2"
ORG_CODE_SERVICE_KEY_ENV_NAMES = (
    "ORG_CODE_API_KEY",
    "PUBLIC_DATA_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "GOV_DATA_SERVICE_KEY",
)
MAX_RECORDS_PER_SCOPE = 25


class _MinistrySelection(BaseModel):
    selected_ministry_names: List[str]
    reason: str


class _DepartmentSelection(BaseModel):
    selected_scope_keys: List[str]
    reason: str


class _RoutingDecision(BaseModel):
    selected_record_ids: List[str]
    confidence: float
    routing_reason: str


def _build_router_llm() -> ChatOpenAI | None:
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    return ChatOpenAI(
        model=os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
        temperature=0,
    )


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


def _truncate(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _serialize_records_for_llm(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "record_id": record["record_id"],
            "scope_key": record.get("scope_key"),
            "분류번호": record.get("분류번호"),
            "사무명": record.get("사무명"),
            "사무개요": _truncate(record.get("사무개요", ""), 320),
            "소관부처": record.get("소관부처"),
            "담당부서": record.get("담당부서"),
        }
        for record in records
    ]


def _serialize_department_catalog(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "scope_key": item["scope_key"],
        }
        for item in catalog
    ]


def _serialize_ministry_catalog(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ministry_name": item["ministry_name"],
        }
        for item in catalog
    ]


def _split_channels(text: str) -> list[str]:
    normalized = str(text or "").replace("\r", "\n")
    parts = re.split(r"[,/\n]+", normalized)
    channels: list[str] = []
    for part in parts:
        value = " ".join(part.strip().split())
        if value and value not in channels:
            channels.append(value)
    return channels


def _extract_receiving_unit(record: dict[str, Any]) -> str | None:
    process = str(record.get("접수/처리") or "")
    for line in process.splitlines():
        if "*접수:" not in line:
            continue
        unit = line.split("*접수:", 1)[1]
        unit = re.sub(r"\([^)]*\)", "", unit).strip()
        if unit:
            return unit
    department = str(record.get("담당부서") or "").strip()
    return department or None


def _extract_channels(record: dict[str, Any]) -> list[str]:
    channels: list[str] = []
    for value in _split_channels(str(record.get("접수방법") or "")):
        if value not in channels:
            channels.append(value)

    receiving_unit = _extract_receiving_unit(record)
    if receiving_unit:
        receiving_channel = f"{receiving_unit} 접수"
        if receiving_channel not in channels:
            channels.append(receiving_channel)

    if not channels:
        channels.append("상세 접수방법 확인 필요")
    return channels


def _aggregate_related_laws(records: list[dict[str, Any]]) -> list[str]:
    laws: list[str] = []
    for record in records:
        text = str(record.get("근거법령") or "")
        for line in text.splitlines():
            value = " ".join(line.strip().split())
            if value and value not in laws:
                laws.append(value)
    return laws[:8]


def _aggregate_required_documents(records: list[dict[str, Any]]) -> list[str]:
    documents: list[str] = []
    ignored_prefixes = (
        "1. 기본서류",
        "1. 유형없음",
        "< 민원인 제출서류 >",
        "< 공무원확인사항 >",
    )
    ignored_contains = (
        "구비서류 없음",
    )

    for record in records:
        text = str(record.get("구비서류") or "")
        for raw_line in text.splitlines():
            value = " ".join(raw_line.strip().split())
            if not value:
                continue
            if any(value.startswith(prefix) for prefix in ignored_prefixes):
                continue
            if any(token in value for token in ignored_contains):
                continue
            value = re.sub(r"^\(\d+\)\s*", "", value)
            value = re.sub(r"^\d+\.\s*", "", value)
            value = value.strip()
            if not value:
                continue
            if value not in documents:
                documents.append(value)

    return documents[:8]


def _build_search_query(user_input: str, keywords: list[str]) -> str:
    normalized_user_input = " ".join(user_input.strip().split())
    if normalized_user_input:
        return normalized_user_input
    return " ".join(keyword.strip() for keyword in keywords if keyword.strip())


def _raw_message_token_usage(raw_message: Any) -> dict[str, int]:
    usage = getattr(raw_message, "usage_metadata", None)
    if usage is None and hasattr(raw_message, "response_metadata"):
        response_metadata = getattr(raw_message, "response_metadata", {}) or {}
        usage = response_metadata.get("token_usage")

    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()

    if not isinstance(usage, dict):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    return normalize_token_usage(
        {
            "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
            "output_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)),
            "total_tokens": usage.get("total_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens", (usage.get("output_token_details") or {}).get("reasoning")),
            "cached_input_tokens": usage.get(
                "cached_input_tokens",
                (usage.get("input_token_details") or {}).get("cache_read", 0),
            ),
        }
    )


def _invoke_structured_llm(
    structured_llm: Any,
    instructions: str,
    payload: dict[str, Any],
) -> tuple[Any | None, dict[str, int]]:
    response = structured_llm.invoke(
        [
            SystemMessage(content=instructions),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]
    )

    if not isinstance(response, dict):
        return response, {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    raw = response.get("raw")
    parsed = response.get("parsed")
    parsing_error = response.get("parsing_error")
    token_usage = _raw_message_token_usage(raw)

    if parsing_error is not None or parsed is None:
        return None, token_usage

    return parsed, token_usage


def _llm_select_ministries(
    *,
    user_input: str,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None,
    ministry_catalog: list[dict[str, Any]],
) -> tuple[_MinistrySelection | None, dict[str, int]]:
    llm = _build_router_llm()
    if llm is None:
        return None, {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    instructions = _read_prompt("agency_routing_ministry_selection_instructions.txt")
    structured_llm = llm.with_structured_output(_MinistrySelection, include_raw=True)
    return _invoke_structured_llm(
        structured_llm,
        instructions,
        {
            "user_input": user_input,
            "response_type": response_type,
            "category": category,
            "urgency": urgency,
            "keywords": keywords,
            "normalized_region": normalized_region,
            "available_ministries": _serialize_ministry_catalog(ministry_catalog),
        },
    )


def _llm_select_departments(
    *,
    user_input: str,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None,
    selected_ministry_names: list[str],
    department_catalog: list[dict[str, Any]],
) -> tuple[_DepartmentSelection | None, dict[str, int]]:
    llm = _build_router_llm()
    if llm is None:
        return None, {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    instructions = _read_prompt("agency_routing_department_selection_instructions.txt")
    structured_llm = llm.with_structured_output(_DepartmentSelection, include_raw=True)
    return _invoke_structured_llm(
        structured_llm,
        instructions,
        {
            "user_input": user_input,
            "response_type": response_type,
            "category": category,
            "urgency": urgency,
            "keywords": keywords,
            "normalized_region": normalized_region,
            "selected_ministry_names": selected_ministry_names,
            "available_department_scopes": _serialize_department_catalog(department_catalog),
        },
    )


def _llm_route(
    *,
    user_input: str,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None,
    retrieved_records: list[dict[str, Any]],
) -> tuple[_RoutingDecision | None, dict[str, int]]:
    llm = _build_router_llm()
    if llm is None:
        return None, {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    instructions = _read_prompt("agency_routing_instructions.txt")
    structured_llm = llm.with_structured_output(_RoutingDecision, include_raw=True)
    return _invoke_structured_llm(
        structured_llm,
        instructions,
        {
            "user_input": user_input,
            "response_type": response_type,
            "category": category,
            "urgency": urgency,
            "keywords": keywords,
            "normalized_region": normalized_region,
            "candidate_records": _serialize_records_for_llm(retrieved_records),
        },
    )


def AgencyRoutingTool(
    *,
    user_input: str,
    response_type: str,
    category: str,
    urgency: str,
    keywords: list[str],
    normalized_region: dict[str, Any] | None = None,
) -> ToolResult:
    search_query = _build_search_query(user_input, keywords)
    if not search_query:
        return failure("NO_ROUTE_FOUND", "민원 검색에 사용할 사용자 질의가 비어 있습니다.")

    ministry_catalog = get_ministry_catalog()
    ministry_selection, ministry_token_usage = _llm_select_ministries(
        user_input=user_input,
        response_type=response_type,
        category=category,
        urgency=urgency,
        keywords=keywords,
        normalized_region=normalized_region,
        ministry_catalog=ministry_catalog,
    )
    if ministry_selection is None:
        return failure(
            "ROUTING_FAILED",
            "소관부처 선택을 위한 ChatOpenAI 또는 API 키를 사용할 수 없습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": ministry_token_usage,
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                },
            },
        )

    valid_ministry_names = {item["ministry_name"] for item in ministry_catalog}
    selected_ministry_names: list[str] = []
    for ministry_name in ministry_selection.selected_ministry_names:
        if ministry_name in valid_ministry_names and ministry_name not in selected_ministry_names:
            selected_ministry_names.append(ministry_name)

    if not selected_ministry_names:
        return failure(
            "NO_ROUTE_FOUND",
            "소관부처 선택 결과가 비어 있어 라우팅을 진행할 수 없습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": ministry_token_usage,
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                },
            },
        )

    department_catalog = get_department_catalog(selected_ministry_names)
    department_selection, department_token_usage = _llm_select_departments(
        user_input=user_input,
        response_type=response_type,
        category=category,
        urgency=urgency,
        keywords=keywords,
        normalized_region=normalized_region,
        selected_ministry_names=selected_ministry_names,
        department_catalog=department_catalog,
    )
    if department_selection is None:
        return failure(
            "ROUTING_FAILED",
            "담당부서 선택을 위한 ChatOpenAI 또는 API 키를 사용할 수 없습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": merge_token_usage(ministry_token_usage, department_token_usage),
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                    "department_selection": department_token_usage,
                },
            },
        )

    valid_scope_keys = {item["scope_key"] for item in department_catalog}
    selected_scope_keys: list[str] = []
    for scope_key in department_selection.selected_scope_keys:
        if scope_key in valid_scope_keys and scope_key not in selected_scope_keys:
            selected_scope_keys.append(scope_key)

    if not selected_scope_keys:
        return failure(
            "NO_ROUTE_FOUND",
            "담당부서 선택 결과가 비어 있어 라우팅을 진행할 수 없습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": merge_token_usage(ministry_token_usage, department_token_usage),
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                    "department_selection": department_token_usage,
                },
            },
        )

    candidate_records = get_records_in_scopes(selected_scope_keys, limit_per_scope=MAX_RECORDS_PER_SCOPE)
    if not candidate_records:
        return failure(
            "NO_ROUTE_FOUND",
            "선택된 담당부서 범위에서 민원 후보를 찾지 못했습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": merge_token_usage(ministry_token_usage, department_token_usage),
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                    "department_selection": department_token_usage,
                },
            },
        )

    write_search_log(
        search_query,
        selected_ministry_names=selected_ministry_names,
        selected_scope_keys=selected_scope_keys,
        candidate_records=candidate_records,
    )

    decision, routing_token_usage = _llm_route(
        user_input=user_input,
        response_type=response_type,
        category=category,
        urgency=urgency,
        keywords=keywords,
        normalized_region=normalized_region,
        retrieved_records=candidate_records,
    )
    if decision is None:
        return failure(
            "ROUTING_FAILED",
            "최종 민원 선택을 위한 ChatOpenAI 또는 API 키를 사용할 수 없습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": merge_token_usage(
                    ministry_token_usage,
                    department_token_usage,
                    routing_token_usage,
                ),
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                    "department_selection": department_token_usage,
                    "record_selection": routing_token_usage,
                },
            },
        )

    selected_record_ids: list[str] = []
    available_ids = {record["record_id"] for record in candidate_records}
    for record_id in decision.selected_record_ids:
        if record_id in available_ids and record_id not in selected_record_ids:
            selected_record_ids.append(record_id)

    if not selected_record_ids:
        return failure(
            "NO_ROUTE_FOUND",
            "민원 후보 선택 결과가 비어 있어 라우팅을 완료할 수 없습니다.",
            meta={
                "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
                "token_usage": merge_token_usage(
                    ministry_token_usage,
                    department_token_usage,
                    routing_token_usage,
                ),
                "usage_breakdown": {
                    "ministry_selection": ministry_token_usage,
                    "department_selection": department_token_usage,
                    "record_selection": routing_token_usage,
                },
            },
        )

    org_service_key = _service_key()
    agency_candidates: list[dict[str, Any]] = []
    channels: list[str] = []
    selected_records: list[dict[str, Any]] = []

    for index, record_id in enumerate(selected_record_ids[:2]):
        record = next(item for item in candidate_records if item["record_id"] == record_id)
        selected_records.append(record)
        candidate_rank = next(
            (
                record_index
                for record_index, item in enumerate(candidate_records, start=1)
                if item["record_id"] == record_id
            ),
            index + 1,
        )

        agency_name = str(record.get("소관부처") or "").strip() or "소관기관 확인 필요"
        verified_name = agency_name
        institution_code = None
        if agency_name and agency_name != "소관기관 확인 필요":
            try:
                normalized = _normalize_agency_name(agency_name, org_service_key)
            except (HTTPError, URLError, json.JSONDecodeError, Exception):
                normalized = None
            if normalized is not None:
                verified_name = normalized["name"]
                institution_code = normalized["org_code"]

        local_unit = _extract_receiving_unit(record) or _region_label(normalized_region) or "접수 기관 확인 필요"
        for channel in _extract_channels(record):
            if channel not in channels:
                channels.append(channel)

        confidence = max(0.35, round(float(decision.confidence) - (index * 0.08), 2))
        agency_candidates.append(
            {
                "name": verified_name,
                "local_unit": local_unit,
                "reason": f"`{record.get('사무명', '민원 사무')}` 항목이 선택된 담당부서 범위 안에서 현재 문의와 가장 직접적으로 연결되는 민원으로 선택되었습니다.",
                "confidence": confidence,
                "institution_code": institution_code,
                "minwon_record_id": record_id,
                "minwon_name": str(record.get("사무명") or "").strip(),
                "scope_key": record.get("scope_key"),
                "candidate_rank": candidate_rank,
            }
        )

    total_token_usage = merge_token_usage(
        ministry_token_usage,
        department_token_usage,
        routing_token_usage,
    )

    return success(
        {
            "agency_candidates": agency_candidates,
            "channels": channels,
            "confidence": round(float(decision.confidence), 2),
            "keywords": keywords,
            "selected_ministry_names": selected_ministry_names,
            "selected_scope_keys": selected_scope_keys,
            "ministry_selection_reason": ministry_selection.reason,
            "department_selection_reason": department_selection.reason,
            "routing_reason": decision.routing_reason,
            "search_query": search_query,
            "candidate_records": _serialize_records_for_llm(candidate_records),
            "selected_record_ids": selected_record_ids[:2],
            "related_laws": _aggregate_related_laws(selected_records),
            "required_documents": _aggregate_required_documents(selected_records),
        },
        meta={
            "model": os.environ.get("OPENAI_ROUTER_MODEL", "gpt-4o-mini"),
            "token_usage": total_token_usage,
            "usage_breakdown": {
                "ministry_selection": ministry_token_usage,
                "department_selection": department_token_usage,
                "record_selection": routing_token_usage,
            },
        },
    )


run_agency_router = AgencyRoutingTool
