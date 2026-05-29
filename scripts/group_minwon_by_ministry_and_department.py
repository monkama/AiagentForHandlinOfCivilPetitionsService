from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = PROJECT_ROOT / "src" / "data_cache" / "minwon_info.json"
OUTPUT_PATH = PROJECT_ROOT / "src" / "data_cache" / "minwon_info_by_ministry_and_department.json"


def _normalized_name(raw: object) -> str:
    value = str(raw or "").strip()
    return value or "미분류"


def _classification_sort_key(record: dict[str, object]) -> tuple[int, int, str]:
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


def main() -> None:
    records = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise RuntimeError("minwon_info.json 형식이 올바르지 않습니다.")

    grouped: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        if not isinstance(record, dict):
            continue

        ministry = _normalized_name(record.get("소관부처"))
        department = _normalized_name(record.get("담당부서"))
        grouped[ministry][department].append(record)

    ordered = {
        ministry: {
            department: sorted(grouped[ministry][department], key=_classification_sort_key)
            for department in sorted(grouped[ministry])
        }
        for ministry in sorted(grouped)
    }

    OUTPUT_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")

    ministry_count = len(ordered)
    department_count = sum(len(departments) for departments in ordered.values())
    record_count = sum(
        len(items)
        for departments in ordered.values()
        for items in departments.values()
    )

    print(f"wrote: {OUTPUT_PATH}")
    print(f"ministries: {ministry_count}")
    print(f"departments: {department_count}")
    print(f"records: {record_count}")


if __name__ == "__main__":
    main()
