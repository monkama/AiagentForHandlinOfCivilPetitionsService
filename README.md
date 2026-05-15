# 행정 민원 내비게이터 Agent

사용자의 자연어 질문을 바탕으로 민원 성격을 분류하고, 필요한 경우 추가 질문을 이어가며 소관 기관, 접수 채널, 준비 정보까지 안내하는 AI Agent 프로젝트입니다.

이 프로젝트는 단순 FAQ가 아니라 `분류 -> 관찰 -> 추가 질문 또는 Tool 호출 -> 최종 답변` 흐름으로 동작하는 민원 안내형 에이전트를 목표로 합니다.

## 무엇을 해주나요

- 사용자 요청을 행정 민원 유형으로 분류합니다.
- 질문 성격에 따라 필요한 Tool만 골라서 호출합니다.
- 지역 정보가 부족하면 같은 세션에서 추가 질문을 이어갑니다.
- 소관 기관 후보와 접수 채널을 안내합니다.
- 민원 접수 전에 필요한 준비 정보와 주의사항을 정리합니다.
- 출산지원, 복지 혜택 같은 공공서비스를 실제 API로 검색합니다.
- 실행 로그를 남겨 Tool 호출 순서와 실패 지점을 추적할 수 있습니다.

## 현재 구현 구조

이 프로젝트는 `OpenAI Agents SDK` 기반 단일 오케스트레이터 구조로 동작합니다.

기본 흐름:

```text
user input
-> RequestClassifierTool
-> observe
-> 필요 시 추가 질문
-> 필요 시 RegionNormalizeTool
-> public_service_inquiry면 PublicServiceSearchTool
-> issue_resolution / administrative_procedure면 AgencyRoutingTool
-> 필요 시 RequirementAndDraftTool
-> final answer
```

즉, 모든 Tool을 고정 순서로 호출하는 것이 아니라 현재 입력에 필요한 Tool만 선택해서 사용합니다.

## Tool 구성

| Tool 이름 | 현재 방식 | 역할 |
|-----------|-----------|------|
| `RequestClassifierTool` | OpenAI API | 사용자 요청을 `response_type`, `category`, `urgency`, `keywords` 등으로 분류 |
| `RegionNormalizeTool` | 공공 OpenAPI | 입력된 지역명을 법정동 코드 기준으로 정규화 |
| `AgencyRoutingTool` | OpenAI + 공공 OpenAPI | category별 후보 카탈로그를 바탕으로 라우팅 LLM이 기관 후보를 고르고, 기관코드 API로 기관명을 검증 |
| `PublicServiceSearchTool` | 공공 OpenAPI | 정부24 공공서비스 API에서 지원금·혜택 정보를 검색 |
| `RequirementAndDraftTool` | OpenAI API | 기관 정보와 사용자 요청을 바탕으로 준비 정보, 누락 정보, 초안을 생성 |

## 핵심 기능

### 1. 요청 분류

`RequestClassifierTool`은 사용자 입력을 구조화된 값으로 바꿉니다.

주요 출력 필드:
- `response_type`
- `category`
- `urgency`
- `keywords`
- `needs_region`
- `confidence`
- `region_text`

예시:
- 퇴직금 미지급 문의 -> `issue_resolution / labor`
- 전입신고 문의 -> `administrative_procedure / residence`
- 출산지원 문의 -> `public_service_inquiry / birth_support`

### 2. 추가 질문과 세션 유지

분류 결과상 정보가 부족하면 오케스트레이터가 같은 세션에서 follow-up 질문을 생성합니다.

예:
- 전입신고 문의에서 지역이 없으면 이사한 지역을 다시 질문
- 공공서비스 문의에서 출생일, 연령, 소득 조건이 부족하면 추가 정보 요청

사용자가 답을 입력하면 새 요청으로 끊지 않고 같은 흐름으로 다음 Tool 호출을 이어갑니다.

### 3. 기관 라우팅

`AgencyRoutingTool`은 현재 완전 자유 탐색형이 아니라, `category`별 후보 카탈로그를 먼저 두고 그 안에서 내부 라우팅 LLM이 우선 후보를 선택하는 구조입니다.

현재 동작 방식:
- 분류 결과의 `category`, `urgency`, `keywords`, `region`을 입력으로 받음
- category별 후보 기관/채널 카탈로그를 구성
- 내부 라우팅 LLM이 그 후보들 중 우선 기관을 선택
- 선택된 기관명은 `행정표준코드_기관코드` API로 다시 조회해 기관명과 기관코드를 검증
- 최종적으로 `agency_candidates`, `channels`, `confidence`, `routing_reason`을 반환

이 구조는 실제 기관코드 API를 쓰지만, `정답 소관기관을 완전히 외부 공식 API가 판정하는 구조`는 아닙니다. 현재는 LLM 기반 후보 선택 + 공공 API 검증에 가깝습니다.

### 4. 공공서비스 검색

`PublicServiceSearchTool`은 실제 정부24 공공서비스 API를 사용합니다.

현재 검색 예:
- 출산지원
- 아동수당
- 부모급여
- 복지 혜택

검색 결과에서는 서비스명, 제공기관, 신청 채널, 상세 URL, 추가로 필요한 조건을 함께 정리합니다.

### 5. 준비 정보 생성

`RequirementAndDraftTool`은 기관 정보와 사용자 요청을 받아 아래를 생성합니다.

- `required_info`
- `missing_info`
- `draft`
- `cautions`

즉, 단순히 “어디로 가세요”에서 끝나지 않고 접수 전에 무엇을 준비해야 하는지도 같이 안내합니다.

## 현재 지원 시나리오

- 퇴직금 미지급 문의
- 전입신고 절차 문의
- 도로 위험 신고
- 출산지원 / 복지 혜택 조회

## 실행 로그

실행 로그는 `logs/openai_sdk/` 아래에 저장됩니다.

대표 기록 항목:
- `user_input`
- `conversation_turns`
- `tool_call_sequence`
- `tool_calls[].selected_tool`
- `tool_calls[].tool_arguments`
- `tool_calls[].tool_result`
- `final_answer`
- `stop_reason`
- `started_at`
- `completed_at`
- `total_latency_ms`

이 로그를 통해 정상 케이스와 실패 케이스 모두에서 Tool 호출 순서와 실패 지점을 추적할 수 있습니다.

## 빠른 실행

### 1. 설치

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### 2. 환경 변수

`.env` 예시:

```env
OPENAI_API_KEY=sk-proj-...
PUBLIC_SERVICE_API_KEY=...
ORG_CODE_API_KEY=...
REGION_CODE_API_KEY=...
PUBLIC_DATA_SERVICE_KEY=...
```

참고:
- `PublicServiceSearchTool`은 `PUBLIC_SERVICE_API_KEY`를 우선 사용합니다.
- `AgencyRoutingTool`은 기관코드 검증에 `ORG_CODE_API_KEY`를 사용합니다.
- `RegionNormalizeTool`은 `REGION_CODE_API_KEY`를 우선 사용합니다.
- 일부 Tool은 `PUBLIC_DATA_SERVICE_KEY`를 fallback으로 사용할 수 있습니다.

### 3. 실행

```bash
./.venv/bin/python -B src/main.py examples/input_1.txt
```

문장을 직접 넣어 실행할 수도 있습니다.

```bash
./.venv/bin/python -B src/main.py "회사에서 퇴직금을 안 줬는데 어디에 신고해야 하나요?"
```

추가 질문이 필요한 경우에는 같은 콘솔에서 `>` 프롬프트가 나타나고, 거기에 답하면 같은 대화 흐름으로 이어집니다.

## 예시 대화

```text
전입신고는 통상적으로 새로운 거주지 관할 행정복지센터(주민센터)나 전자정부 민원포털(정부24)에서 할 수 있습니다.
더 정확한 안내를 위해, 새로 이사하신 지역을 알려주시면 해당 관할 기관과 접수 방법을 안내드릴 수 있습니다.

> 서울시 강남구

서울시 강남구로 이사하신 경우, 전입신고는 아래 두 가지 방법 중 선택해서 하실 수 있습니다.
- 정부24 온라인 신청
- 전입지 주민센터 방문
```

## 종료 및 안정성 규칙

현재 구현에는 아래 규칙이 들어 있습니다.

- `max_turns = 6`
- 실행 시간 제한 `60초`
- 같은 Tool / 같은 입력 반복 호출 방지
- Tool 실패 시 구조화된 에러 반환 및 fallback 안내

## 프로젝트 구조

```text
project-root/
  README.md
  requirements.txt
  examples/
    input_1.txt
    input_2.txt
    input_3.txt
  logs/
    openai_sdk/
  src/
    main.py
    prompts/
    tools/
```

## 현재 상태와 한계

현재는 MVP 단계입니다.

현재 상태:
- `RequestClassifierTool`은 실제 OpenAI API 사용
- `RegionNormalizeTool`은 실제 법정동 코드 API 사용
- `PublicServiceSearchTool`은 실제 정부24 공공서비스 API 사용
- `RequirementAndDraftTool`은 실제 OpenAI API 사용
- `AgencyRoutingTool`은 내부 라우팅 LLM + 후보 카탈로그 + 기관코드 API 검증 구조 사용

현재 한계:
- `AgencyRoutingTool`은 여전히 후보 카탈로그 의존이 있어 완전한 동적 라우팅은 아님
- 카테고리별 후보군 자체가 모델에 일종의 prior 역할을 함
- 도로 위험, 생활불편 같은 민원은 지역 세부 부서까지 정확히 좁히는 데 한계가 있음
- 공공서비스 검색은 실제 API 기반이지만, 사용자 조건이 부족하면 추가 질문이 필요함

## 설계 참고

- 6주차 설계 문서: https://github.com/monkama/aiagent-repo/blob/main/week-6/design.md
