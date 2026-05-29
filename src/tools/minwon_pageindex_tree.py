from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


GROUPED_PATH = (
    Path(__file__).resolve().parents[1]
    / "data_cache"
    / "minwon_info_by_ministry_and_department.json"
)
PAGEINDEX_MD_PATH = Path(__file__).resolve().parents[1] / "data_cache" / "minwon_pageindex_tree.md"
SEARCH_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "minwon_pageindex_search"

_GROUPED_CACHE: dict[str, dict[str, list[dict[str, Any]]]] | None = None


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def _slugify(text: str, limit: int = 60) -> str:
    import re

    normalized = re.sub(r"\s+", "-", text.strip())
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]", "", normalized)
    normalized = normalized.strip("-_")
    return (normalized or "query")[:limit]


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat()


def load_grouped_records() -> dict[str, dict[str, list[dict[str, Any]]]]:
    global _GROUPED_CACHE

    if _GROUPED_CACHE is not None:
        return _GROUPED_CACHE

    if not GROUPED_PATH.exists():
        raise RuntimeError(f"부처/부서 분류 데이터 파일이 없습니다: {GROUPED_PATH}")

    data = json.loads(GROUPED_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("minwon_info_by_ministry_and_department.json 형식이 올바르지 않습니다.")

    _GROUPED_CACHE = data
    return data


def _scope_key(ministry_name: str, department_name: str) -> str:
    return f"{ministry_name}::{department_name}"


def _record_id(scope_key: str, index: int) -> str:
    return f"{scope_key}::{index}"


def _classification_sort_key(record: dict[str, Any]) -> tuple[int, int, str]:
    raw = str(record.get("분류번호") or "").strip()
    if "-" in raw:
        left, right = raw.split("-", 1)
        try:
            return (int(left), int(right), raw)
        except ValueError:
            return (10**9, 10**9, raw)
    try:
        return (int(raw), 0, raw)
    except ValueError:
        return (10**9, 10**9, raw)


def get_ministry_catalog() -> list[dict[str, Any]]:
    grouped = load_grouped_records()
    return [
        {
            "ministry_name": ministry_name,
        }
        for ministry_name in sorted(grouped.keys())
    ]


def get_department_catalog(ministry_names: list[str] | None = None) -> list[dict[str, Any]]:
    grouped = load_grouped_records()
    catalog: list[dict[str, Any]] = []
    target_ministry_names = ministry_names or sorted(grouped.keys())
    for ministry_name in target_ministry_names:
        for department_name, records in grouped.get(ministry_name, {}).items():
            catalog.append(
                {
                    "scope_key": _scope_key(ministry_name, department_name),
                }
            )
    return sorted(catalog, key=lambda item: item["scope_key"])


def get_records_in_scopes(selected_scope_keys: list[str], limit_per_scope: int = 25) -> list[dict[str, Any]]:
    grouped = load_grouped_records()
    collected: list[dict[str, Any]] = []

    for scope_key in selected_scope_keys:
        if "::" not in scope_key:
            continue
        ministry_name, department_name = scope_key.split("::", 1)
        records = sorted(
            grouped.get(ministry_name, {}).get(department_name, []),
            key=_classification_sort_key,
        )
        for index, raw in enumerate(records[: max(1, limit_per_scope)], start=1):
            if not isinstance(raw, dict):
                continue
            collected.append(
                {
                    "record_id": _record_id(scope_key, index),
                    "scope_key": scope_key,
                    "분류번호": str(raw.get("분류번호") or "").strip(),
                    "사무명": str(raw.get("사무명") or "").strip(),
                    "사무개요": str(raw.get("사무개요") or "").strip(),
                    "신청유형": str(raw.get("신청유형") or "").strip(),
                    "신청자 자격": str(raw.get("신청자 자격") or "").strip(),
                    "수수료": str(raw.get("수수료") or "").strip(),
                    "수수료내역": str(raw.get("수수료내역") or "").strip(),
                    "소관부처": ministry_name,
                    "담당부서": department_name,
                    "접수방법": str(raw.get("접수방법") or "").strip(),
                    "접수/처리": str(raw.get("접수/처리") or "").strip(),
                    "근거법령": str(raw.get("근거법령") or "").strip(),
                    "신청서": str(raw.get("신청서") or "").strip(),
                    "발급물 내용": str(raw.get("발급물 내용") or "").strip(),
                    "구비서류": str(raw.get("구비서류") or "").strip(),
                }
            )

    return collected


def write_search_log(
    query_text: str,
    selected_ministry_names: list[str],
    selected_scope_keys: list[str],
    candidate_records: list[dict[str, Any]],
) -> str:
    SEARCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = SEARCH_LOG_DIR / f"{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')}_{_slugify(query_text)}.json"
    payload = {
        "query_text": query_text,
        "logged_at": _iso_now(),
        "selected_ministry_names": selected_ministry_names,
        "selected_scope_keys": selected_scope_keys,
        "candidate_records": candidate_records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def export_pageindex_markdown(output_path: Path | None = None) -> Path:
    grouped = load_grouped_records()
    destination = output_path or PAGEINDEX_MD_PATH

    lines = [
        "# 대한민국 행정 민원 안내 데이터",
        "",
        "이 문서는 행정안전부 민원안내정보를 `소관부처 -> 담당부서 -> 민원사무` 계층으로 정리한 PageIndex용 Markdown 트리입니다.",
        "",
    ]

    for ministry_name in sorted(grouped):
        lines.append(f"## 소관부처: {ministry_name}")
        lines.append("")

        departments = grouped[ministry_name]
        for department_name in sorted(departments):
            records = sorted(departments[department_name], key=_classification_sort_key)
            lines.append(f"### 담당부서: {department_name}")
            lines.append("")
            lines.append(f"- 소속 소관부처: {ministry_name}")
            lines.append(f"- 민원 사무 수: {len(records)}")
            lines.append("")

            for index, record in enumerate(records, start=1):
                if not isinstance(record, dict):
                    continue

                title = _normalize_text(str(record.get("사무명") or f"민원사무 {index}"))
                summary = _normalize_text(str(record.get("사무개요") or ""))
                lines.append(f"#### 민원사무: {title}")
                lines.append("")
                lines.append(f"- 분류번호: {str(record.get('분류번호') or '').strip()}")
                if summary:
                    lines.append(f"- 사무개요: {summary}")
                if str(record.get("신청유형") or "").strip():
                    lines.append(f"- 신청유형: {str(record.get('신청유형') or '').strip()}")
                if str(record.get("신청자 자격") or "").strip():
                    lines.append(f"- 신청자 자격: {str(record.get('신청자 자격') or '').strip()}")
                if str(record.get("접수방법") or "").strip():
                    lines.append(f"- 접수방법: {str(record.get('접수방법') or '').strip()}")
                if str(record.get("접수/처리") or "").strip():
                    lines.append(f"- 접수/처리: {_normalize_text(str(record.get('접수/처리') or ''))}")
                if str(record.get("근거법령") or "").strip():
                    lines.append(f"- 근거법령: {_normalize_text(str(record.get('근거법령') or ''))}")
                if str(record.get("구비서류") or "").strip():
                    lines.append(f"- 구비서류: {_normalize_text(str(record.get('구비서류') or ''))}")
                lines.append("")

    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination
