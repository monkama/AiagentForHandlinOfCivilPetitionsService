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
| `AgencyRoutingTool` | `ChatOpenAI(gpt-4o-mini, temperature=0)` + 민원 트리 인덱스 + 공공 OpenAPI | LLM이 먼저 소관부처와 담당부서를 고르고, 그 범위의 민원 레코드를 읽어 최종 라우팅 수행 |
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

`AgencyRoutingTool`은 민원안내정보 원천 데이터를 `소관부처 -> 담당부서 -> 민원사무` 트리로 정리한 뒤, LLM이 그 구조를 단계적으로 좁혀가며 라우팅합니다.

현재 동작 방식:
- `minwon_info_by_ministry_and_department.json`을 기준으로 실제 검색 단위를 `소관부처 -> 담당부서 -> 민원사무` 계층으로 나눔
- 1차로 `ChatOpenAI(gpt-4o-mini, temperature=0)`가 소관부처를 선택
- 2차로 선택된 부처 안에서 다시 담당부서를 선택
- 3차로 선택된 담당부서 범위의 민원 레코드만 읽어 현재 질문과 가장 관련성이 높은 민원 사무를 선택
- 선택된 `소관부처`는 `행정표준코드_기관코드` API로 다시 조회해 기관명과 기관코드를 검증
- 최종적으로 `agency_candidates`, `channels`, `confidence`, `routing_reason`을 반환

즉 현재 라우팅은 벡터 유사도 검색이 아니라, `민원 트리 인덱스`를 바탕으로 LLM이 관련 범위를 좁히고 그 안에서 근거 레코드를 선택하는 reasoning 기반 흐름으로 동작합니다.

왜 이렇게 바꿨는가:
- 초기에 `사무명/사무개요`를 임베딩해 벡터 유사도 검색을 실험했지만, `퇴직금 미지급` 같은 broad한 질문에서 `퇴직연금사업자 등록`처럼 표면적으로만 비슷한 민원사무가 상위에 오르는 문제가 있었습니다.
- 이 데이터는 FAQ 답변 모음이 아니라 `행정 민원 사무 카탈로그`라서, 단순 유사도보다 `현재 질문이 어느 부처-부서-민원사무 트리에 가까운가`를 따지는 방식이 더 잘 맞았습니다.
- 그래서 현재는 `PageIndex`와 비슷한 철학으로, 문서 덩어리 top-k를 바로 신뢰하지 않고 `소관부처 -> 담당부서 -> 민원사무` 구조를 단계적으로 좁힌 뒤 최종 레코드를 고르게 했습니다.

왜 3단계로 나눴는가:
- `소관부처 선택`: 먼저 큰 행정 영역을 좁혀서 전혀 무관한 기관이 후보로 섞이는 문제를 줄입니다.
- `담당부서 선택`: 같은 부처 안에서도 역할이 다른 부서가 많기 때문에, 세부 업무 범위를 한 번 더 줄입니다.
- `민원사무 선택`: 마지막에야 실제 `사무명`과 `사무개요`를 읽고 현재 질문과 가장 직접적으로 맞는 민원사무를 고릅니다.
- 이 단계를 한 번에 합치면 한 호출에 너무 많은 범위를 보여줘야 해서 오히려 토큰이 커지고 판단도 흔들렸습니다. 실제 실험에서도 `부처+부서`를 한 번에 고르게 했을 때 토큰이 크게 증가해 다시 3단계로 되돌렸습니다.

### 4. PageIndex용 민원 트리

민원 원천 JSON은 PageIndex 계열 reasoning retrieval 실험을 위해 Markdown 트리로도 내보낼 수 있습니다.

생성 대상:
- `src/data_cache/minwon_pageindex_tree.md`

구조:
- `소관부처`
- `담당부서`
- `민원사무`
- 각 민원사무의 `사무개요`, `접수방법`, `근거법령`, `구비서류`

이 파일은 `scripts/export_minwon_pageindex_markdown.py`로 다시 생성할 수 있습니다.

### 5. 공공서비스 검색

`PublicServiceSearchTool`은 실제 정부24 공공서비스 API를 사용합니다.

현재 검색 예:
- 출산지원
- 아동수당
- 부모급여
- 복지 혜택

검색 결과에서는 서비스명, 제공기관, 신청 채널, 상세 URL, 추가로 필요한 조건을 함께 정리합니다.

### 6. 준비 정보 생성

`RequirementAndDraftTool`은 기관 정보와 사용자 요청을 받아 아래를 생성합니다.

- `required_info`
- `missing_info`
- `draft`
- `cautions`

즉, 단순히 “어디로 가세요”에서 끝나지 않고 접수 전에 무엇을 준비해야 하는지도 같이 안내합니다.

### 7. 최종 답변 후처리

최종 자연어 답변은 오케스트레이터가 만들지만, 일부 정보는 코드 후처리로 보강합니다.

현재는 `AgencyRoutingTool`이 최종적으로 선택한 민원 레코드에서 아래 항목을 다시 모아서 답변 뒤에 붙입니다.

- `관련 법령`
- `구비 서류`

즉, 라우팅 판단 단계에서는 토큰 절감을 위해 이 필드들을 LLM 입력에서 제거할 수 있지만, 최종 사용자 답변에서는 필요한 참고 정보가 빠지지 않도록 유지하고 있습니다.

## 현재 지원 시나리오

- 퇴직금 미지급 문의
- 전입신고 절차 문의
- 도로 위험 신고
- 출산지원 / 복지 혜택 조회

## 실행 로그

실행 로그는 `logs/openai_sdk/` 아래에 저장됩니다.
민원 라우팅 후보 로그는 `logs/minwon_pageindex_search/` 아래에 저장됩니다.

대표 기록 항목:
- `user_input`
- `conversation_turns`
- `tool_call_sequence`
- `tool_calls[].selected_tool`
- `tool_calls[].tool_arguments`
- `tool_calls[].tool_result`
- `tool_calls[].token_usage`
- `tool_calls[].tool_model`
- `tool_calls[].latency_ms`
- `final_answer`
- `stop_reason`
- `started_at`
- `completed_at`
- `total_latency_ms`
- `total_token_usage`
- `tool_statistics`

민원 라우팅 로그에는 추가로 아래 항목이 남습니다.
- `query_text`
- `selected_ministry_names`
- `selected_scope_keys`
- `candidate_records`

추가로 각 실행 폴더에는 `summary.md`가 함께 생성되며, 여기에는 아래 통계가 요약됩니다.

- 전체 input / output / total token
- tool별 호출 횟수
- tool별 latency
- tool별 token 사용량

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
- `AgencyRoutingTool`은 부처 선택, 부서 선택, 최종 민원 선택에 OpenAI API를 사용하고, 기관코드 검증에 `ORG_CODE_API_KEY`를 사용합니다.
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

### 4. PageIndex용 Markdown 트리 생성

```bash
PYTHONPATH=src ./.venv/bin/python scripts/export_minwon_pageindex_markdown.py
```

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
    minwon_pageindex_search/
  scripts/
    export_minwon_pageindex_markdown.py
  src/
    main.py
    prompts/
    tools/
    data_cache/
      minwon_info_by_ministry_and_department.json
      minwon_pageindex_tree.md
```

## 현재 상태와 한계

현재는 MVP 단계입니다.

현재 상태:
- `RequestClassifierTool`은 실제 OpenAI API 사용
- `RegionNormalizeTool`은 실제 법정동 코드 API 사용
- `PublicServiceSearchTool`은 실제 정부24 공공서비스 API 사용
- `RequirementAndDraftTool`은 실제 OpenAI API 사용
- `AgencyRoutingTool`은 LLM 기반 `소관부처 -> 담당부서 -> 민원사무` reasoning 구조 사용
- 민원안내정보는 PageIndex용 Markdown 트리로도 변환 가능
- 실행 로그에는 tool별 token 사용량과 latency가 함께 기록됨

현재 한계:
- 민원안내정보 자체가 런타임 query API가 아니라 파일 데이터 기반이라, 주기적 인덱스 갱신 전략이 필요함
- broad한 사용자 질문과 세부 행정 절차 사이의 간극을 LLM이 해석해야 하므로, 후보 선택 품질에 영향을 받음
- 도로 위험, 생활불편 같은 민원은 지역 세부 부서까지 정확히 좁히는 데 한계가 있음
- 공공서비스 검색은 실제 API 기반이지만, 사용자 조건이 부족하면 추가 질문이 필요함
- 현재는 PageIndex용 Markdown 트리를 생성하지만, self-hosted PageIndex 런타임과 직접 연결한 상태는 아님
- `AgencyRoutingTool`이 여전히 가장 큰 token 병목이라, candidate 범위 축소와 단계별 payload pruning을 계속 다듬을 필요가 있음

## 설계 참고

- 6주차 설계 문서: https://github.com/monkama/aiagent-repo/blob/main/week-6/design.md
