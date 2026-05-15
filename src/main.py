from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from tools import (
    AgencyRoutingTool as RawAgencyRoutingTool,
    PublicServiceSearchTool as RawPublicServiceSearchTool,
    RegionNormalizeTool as RawRegionNormalizeTool,
    RequestClassifierTool as RawRequestClassifierTool,
    RequirementAndDraftTool as RawRequirementAndDraftTool,
)


MAX_TURNS = 6
FOLLOW_UP_CONFIDENCE_THRESHOLD = 0.75
MAX_FOLLOW_UP_ROUNDS = 4


class ExecutionTimeoutError(RuntimeError):
    pass


def load_dotenv_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat()


def _slugify(text: str, limit: int = 40) -> str:
    normalized = re.sub(r"\s+", "-", text.strip())
    normalized = re.sub(r"[^0-9A-Za-z가-힣_-]", "", normalized)
    normalized = normalized.strip("-_")
    if not normalized:
        normalized = "run"
    return normalized[:limit]


def _read_prompt(filename: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8").strip()


def _max_execution_seconds() -> int:
    return int(os.environ.get("OPENAI_AGENT_TIMEOUT_SECONDS", "60"))


class ExecutionTimeout:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self._enabled = False
        self._previous_handler: Any = None

    def _handle_timeout(self, signum: int, frame: Any) -> None:
        raise ExecutionTimeoutError(f"실행 시간이 {self.seconds}초를 초과해 종료했습니다.")

    def __enter__(self) -> None:
        if self.seconds <= 0:
            return
        if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
            return

        self._enabled = True
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self._enabled:
            return

        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._previous_handler)


class OpenAIExecutionLogger:
    def __init__(self, user_input: str, base_dir: str = "logs/openai_sdk") -> None:
        self.user_input = user_input
        self.started_dt = datetime.now().astimezone()
        self.started_at = self.started_dt.isoformat()
        self.tool_index = 0
        self.tool_records: list[dict[str, Any]] = []
        self.tool_signatures: set[str] = set()
        self.conversation_turns: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": user_input,
                "logged_at": self.started_at,
            }
        ]

        run_name = f"{_timestamp()}_{_slugify(user_input)}"
        self.run_dir = Path(base_dir) / run_name
        self.tool_calls_dir = self.run_dir / "tool_calls"
        self.tool_calls_dir.mkdir(parents=True, exist_ok=True)

    def is_repeated_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        signature = json.dumps(
            {
                "tool_name": tool_name,
                "arguments": arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature in self.tool_signatures:
            return True

        self.tool_signatures.add(signature)
        return False

    def log_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        latency_ms: Optional[int] = None,
        step_type: str = "tool_call",
    ) -> None:
        self.tool_index += 1
        record = {
            "index": self.tool_index,
            "type": step_type,
            "selected_tool": tool_name,
            "tool_arguments": arguments,
            "tool_result": result,
            "logged_at": _iso_now(),
        }
        if latency_ms is not None:
            record["latency_ms"] = latency_ms
        self.tool_records.append(record)
        path = self.tool_calls_dir / f"{self.tool_index:02d}_{tool_name}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def log_conversation_turn(self, role: str, content: str) -> None:
        self.conversation_turns.append(
            {
                "role": role,
                "content": content,
                "logged_at": _iso_now(),
            }
        )

    def finalize(self, final_answer: str, raw_result: dict[str, Any], stop_reason: str) -> None:
        completed_dt = datetime.now().astimezone()
        total_latency_ms = int((completed_dt - self.started_dt).total_seconds() * 1000)
        payload = {
            "user_input": self.user_input,
            "conversation_turns": self.conversation_turns,
            "tool_call_sequence": [record["selected_tool"] for record in self.tool_records],
            "tool_calls": self.tool_records,
            "final_answer": final_answer,
            "stop_reason": stop_reason,
            "started_at": self.started_at,
            "completed_at": completed_dt.isoformat(),
            "total_latency_ms": total_latency_ms,
            "raw_result": raw_result,
        }
        (self.run_dir / "run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_summary(payload)

    def _write_summary(self, payload: dict[str, Any]) -> None:
        lines = [
            "# OpenAI SDK 실행 로그",
            "",
            "## user input",
            "",
            payload["user_input"],
            "",
            "## selected tool sequence",
            "",
        ]

        if payload["tool_call_sequence"]:
            for index, tool_name in enumerate(payload["tool_call_sequence"], start=1):
                lines.append(f"{index}. `{tool_name}`")
        else:
            lines.append("호출된 tool이 없습니다.")

        lines.extend(
            [
                "",
                "## final answer",
                "",
                payload["final_answer"],
                "",
                "## stop reason",
                "",
                payload["stop_reason"],
                "",
                "## total latency",
                "",
                f"{payload['total_latency_ms']} ms",
            ]
        )

        (self.run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _sdk_instructions() -> str:
    return _read_prompt("openai_sdk_agent_instructions.txt")


def build_openai_agent(model: Optional[str] = None, logger: Optional[OpenAIExecutionLogger] = None) -> Any:
    try:
        from agents import Agent, function_tool
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK가 설치되어 있지 않습니다. `pip install -r requirements.txt` 로 설치해 주세요."
        ) from exc

    def _blocked_repeated_call(tool_name: str, arguments: dict[str, Any]) -> str | None:
        if logger is None:
            return None

        if not logger.is_repeated_tool_call(tool_name, arguments):
            return None

        result = {
            "ok": False,
            "data": None,
            "error": {
                "code": "REPEATED_TOOL_CALL",
                "message": "같은 Tool을 같은 입력으로 반복 호출할 수 없습니다. 현재까지 확보한 정보만으로 답변을 마무리하세요.",
            },
        }
        logger.log_tool_call(tool_name, arguments, result, latency_ms=0)
        return json.dumps(result, ensure_ascii=False)

    def _finalize_tool_result(tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> str:
        if logger is not None:
            logger.log_tool_call(tool_name, arguments, result, latency_ms=0)
        return json.dumps(result, ensure_ascii=False)

    @function_tool(name_override="RequestClassifierTool")
    def request_classifier_tool(message: str) -> str:
        arguments = {"message": message}
        blocked = _blocked_repeated_call("RequestClassifierTool", arguments)
        if blocked is not None:
            return blocked

        started = time.perf_counter()
        result = RawRequestClassifierTool(message)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _finalize_tool_result("RequestClassifierTool", arguments, result, latency_ms=latency_ms)

    @function_tool(name_override="RegionNormalizeTool")
    def region_normalize_tool(region_text: str) -> str:
        arguments = {"region_text": region_text}
        blocked = _blocked_repeated_call("RegionNormalizeTool", arguments)
        if blocked is not None:
            return blocked

        started = time.perf_counter()
        result = RawRegionNormalizeTool(region_text)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _finalize_tool_result("RegionNormalizeTool", arguments, result, latency_ms=latency_ms)

    @function_tool(name_override="AgencyRoutingTool")
    def agency_routing_tool(
        response_type: str,
        category: str,
        urgency: str,
        keywords: List[str],
        region_text: Optional[str] = None,
    ) -> str:
        arguments = {
            "response_type": response_type,
            "category": category,
            "urgency": urgency,
            "keywords": keywords,
            "region_text": region_text,
        }
        blocked = _blocked_repeated_call("AgencyRoutingTool", arguments)
        if blocked is not None:
            return blocked

        normalized_region = None
        if region_text:
            region_result = RawRegionNormalizeTool(region_text)
            if region_result["ok"]:
                normalized_region = region_result["data"]

        started = time.perf_counter()
        result = RawAgencyRoutingTool(
            response_type=response_type,
            category=category,
            urgency=urgency,
            keywords=keywords,
            normalized_region=normalized_region,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _finalize_tool_result("AgencyRoutingTool", arguments, result, latency_ms=latency_ms)

    @function_tool(name_override="PublicServiceSearchTool")
    def public_service_search_tool(
        category: str,
        keywords: List[str],
        region_text: Optional[str] = None,
        profile_text: Optional[str] = None,
    ) -> str:
        arguments = {
            "category": category,
            "keywords": keywords,
            "region_text": region_text,
            "profile_text": profile_text,
        }
        blocked = _blocked_repeated_call("PublicServiceSearchTool", arguments)
        if blocked is not None:
            return blocked

        started = time.perf_counter()
        result = RawPublicServiceSearchTool(
            category=category,
            keywords=keywords,
            region_text=region_text,
            profile_text=profile_text,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _finalize_tool_result("PublicServiceSearchTool", arguments, result, latency_ms=latency_ms)

    @function_tool(name_override="RequirementAndDraftTool")
    def requirement_and_draft_tool(
        category: str,
        agency_name: str,
        agency_unit: str,
        user_input: str,
        want_draft: bool = True,
    ) -> str:
        arguments = {
            "category": category,
            "agency_name": agency_name,
            "agency_unit": agency_unit,
            "user_input": user_input,
            "want_draft": want_draft,
        }
        blocked = _blocked_repeated_call("RequirementAndDraftTool", arguments)
        if blocked is not None:
            return blocked

        agency = {
            "name": agency_name,
            "unit": agency_unit,
        }
        started = time.perf_counter()
        result = RawRequirementAndDraftTool(
            category=category,
            agency=agency,
            user_input=user_input,
            want_draft=want_draft,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _finalize_tool_result("RequirementAndDraftTool", arguments, result, latency_ms=latency_ms)

    agent_kwargs = {
        "name": "Civil Petitions Navigator",
        "instructions": _sdk_instructions(),
        "tools": [
            request_classifier_tool,
            region_normalize_tool,
            agency_routing_tool,
            public_service_search_tool,
            requirement_and_draft_tool,
        ],
    }
    if model is not None:
        agent_kwargs["model"] = model

    return Agent(**agent_kwargs)


def run_openai_agent(
    user_input: str,
    model: Optional[str] = None,
    logger: Optional[OpenAIExecutionLogger] = None,
    session: Optional[Any] = None,
) -> dict[str, Any]:
    try:
        from agents import Runner
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK가 설치되어 있지 않습니다. `pip install -r requirements.txt` 로 설치해 주세요."
        ) from exc

    agent = build_openai_agent(model=model, logger=logger)
    start_index = len(logger.tool_records) if logger is not None else 0
    with ExecutionTimeout(_max_execution_seconds()):
        result = Runner.run_sync(agent, user_input, max_turns=MAX_TURNS, session=session)

    turn_tool_calls = logger.tool_records[start_index:] if logger is not None else []
    return {
        "mode": "openai_agents_sdk",
        "input": user_input,
        "last_agent": result.last_agent.name,
        "final_output": result.final_output,
        "turn_tool_calls": turn_tool_calls,
    }


def _load_input(args: list[str]) -> str:
    if not args:
        raise ValueError("입력 파일 경로 또는 사용자 요청 문장을 인자로 전달해야 합니다.")

    candidate = Path(args[0])
    if candidate.exists() and candidate.is_file():
        return candidate.read_text(encoding="utf-8").strip()

    return args[0]


def _turn_requires_follow_up(result: dict[str, Any]) -> bool:
    tool_calls = result.get("turn_tool_calls", [])
    if not tool_calls:
        return False

    public_service_record = next(
        (record for record in reversed(tool_calls) if record["selected_tool"] == "PublicServiceSearchTool"),
        None,
    )
    if public_service_record is not None:
        service_result = public_service_record.get("tool_result", {})
        if service_result.get("ok"):
            need_more_info = (service_result.get("data") or {}).get("need_more_info") or []
            if need_more_info:
                return True

    if any(
        record["selected_tool"] in {"AgencyRoutingTool", "RegionNormalizeTool", "RequirementAndDraftTool"}
        for record in tool_calls
    ):
        return False

    classifier_record = next(
        (record for record in tool_calls if record["selected_tool"] == "RequestClassifierTool"),
        None,
    )
    if classifier_record is None:
        return False

    tool_result = classifier_record.get("tool_result", {})
    if not tool_result.get("ok"):
        return False

    data = tool_result.get("data") or {}
    confidence = float(data.get("confidence", 1.0))
    needs_region = bool(data.get("needs_region"))
    region_text = data.get("region_text")
    category = data.get("category")

    return (
        category == "unknown"
        or confidence < FOLLOW_UP_CONFIDENCE_THRESHOLD
        or (needs_region and not region_text)
    )


def _infer_stop_reason(result: dict[str, Any], follow_up_required: bool = False) -> str:
    if result.get("error") and "final_output" not in result:
        return "runtime_error"
    if follow_up_required:
        return "follow_up_required"

    tool_calls = result.get("turn_tool_calls", []) or []
    for record in reversed(tool_calls):
        tool_result = record.get("tool_result", {})
        if not tool_result.get("ok", True):
            return f"tool_error:{tool_result.get('error', {}).get('code', 'UNKNOWN')}"

    return "final_answer"


def _print_output(text: str) -> None:
    print(text)


def _run_interactive_session(initial_input: str, model: Optional[str] = None) -> dict[str, Any]:
    try:
        from agents import SQLiteSession
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK가 설치되어 있지 않습니다. `pip install -r requirements.txt` 로 설치해 주세요."
        ) from exc

    logger = OpenAIExecutionLogger(initial_input)
    session = SQLiteSession(session_id=f"civil-petitions-{_timestamp()}")
    current_input = initial_input
    last_result: dict[str, Any] | None = None

    try:
        for _ in range(MAX_FOLLOW_UP_ROUNDS + 1):
            result = run_openai_agent(current_input, model=model, logger=logger, session=session)
            last_result = result
            final_output = result.get("final_output", "")
            logger.log_conversation_turn("assistant", final_output)
            _print_output(final_output)

            follow_up_required = _turn_requires_follow_up(result)
            if not follow_up_required:
                result["stop_reason"] = _infer_stop_reason(result, follow_up_required=False)
                return result

            try:
                follow_up = input("> ").strip()
            except EOFError:
                result["stop_reason"] = "follow_up_abandoned"
                return result

            if not follow_up:
                result["stop_reason"] = "follow_up_abandoned"
                return result

            logger.log_conversation_turn("user", follow_up)
            current_input = follow_up

        last_result = {
            "mode": "openai_agents_sdk",
            "input": current_input,
            "error": f"RuntimeError: 추가 질문 한도({MAX_FOLLOW_UP_ROUNDS})에 도달해 실행을 종료했습니다.",
            "stop_reason": "follow_up_limit",
        }
        return last_result
    except Exception as exc:
        last_result = {
            "mode": "openai_agents_sdk",
            "input": current_input,
            "error": f"{type(exc).__name__}: {exc}",
            "stop_reason": "runtime_error",
        }
        return last_result
    finally:
        if last_result is not None:
            logger.finalize(
                last_result.get("final_output", last_result.get("error", "")),
                last_result,
                last_result.get("stop_reason", _infer_stop_reason(last_result)),
            )
        if hasattr(session, "close"):
            session.close()


def main() -> None:
    load_dotenv_file()
    user_input: Optional[str] = None

    try:
        user_input = _load_input(sys.argv[1:])
        result = _run_interactive_session(user_input)
        if "error" in result and "final_output" not in result:
            output = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            output = None
    except Exception as exc:
        result = {
            "mode": "openai_agents_sdk",
            "input": user_input,
            "error": f"{type(exc).__name__}: {exc}",
        }
        output = json.dumps(result, ensure_ascii=False, indent=2)

    if output is not None:
        print(output)


if __name__ == "__main__":
    main()
