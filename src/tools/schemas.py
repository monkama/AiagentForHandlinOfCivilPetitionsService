from __future__ import annotations

from typing import Any, TypedDict


class ToolError(TypedDict):
    code: str
    message: str


class ToolResult(TypedDict):
    ok: bool
    data: dict[str, Any] | None
    error: ToolError | None


def success(data: dict[str, Any]) -> ToolResult:
    return {
        "ok": True,
        "data": data,
        "error": None,
    }


def failure(code: str, message: str) -> ToolResult:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
    }
