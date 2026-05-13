# 행정 민원 내비게이터 Agent

사용자의 자연어 질문을 바탕으로 어떤 행정 민원인지 분류하고, 소관 기관과 접수 채널, 준비 정보까지 안내해주는 AI Agent 프로젝트입니다.

이 프로젝트는 단순 FAQ가 아니라, 질문의 성격을 먼저 이해한 뒤 필요한 Tool을 선택하고, 정보가 부족하면 추가 질문을 이어가며 최종 답변을 만드는 흐름을 목표로 합니다.

## 무엇을 해주나요

- 사용자의 요청을 행정 민원 유형으로 분류합니다.
- 상황에 맞는 소관 기관 후보와 접수 채널을 안내합니다.
- 지역 정보가 필요하면 추가 질문을 통해 대화를 이어갑니다.
- 민원 접수 전에 준비하면 좋은 정보와 주의사항을 정리합니다.
- 긴급 상황에서는 일반 민원 안내보다 즉시 대응 채널을 우선합니다.

## 주요 기능

### 1. 요청 분류

`RequestClassifierTool`이 사용자 입력을 읽고 아래 정보를 구조화합니다.

- `response_type`
- `category`
- `urgency`
- `keywords`
- `needs_region`
- `confidence`
- `region_text`

예를 들어:
- 퇴직금 미지급 문의 → `issue_resolution / labor`
- 전입신고 문의 → `administrative_procedure / residence`
- 도로 붕괴 위험 신고 → `issue_resolution / road_safety / emergency`

### 2. 지역 정보 보강

분류 결과상 지역 정보가 필요한데 사용자 입력에 지역이 없으면, 오케스트레이터가 같은 세션 안에서 추가 질문을 생성합니다.  
사용자가 답하면 그 맥락을 유지한 채 다음 단계로 이어집니다.

### 3. 기관 라우팅

`AgencyRoutingTool`이 분류 결과를 바탕으로 소관 가능성이 높은 기관과 접수 채널을 반환합니다.

현재 예시:
- 퇴직금 미지급 → 고용노동부
- 전입신고 → 정부24 / 전입지 주민센터
- 도로 위험 신고 → 지자체 도로관리부서 / 112 / 119

### 4. 준비 정보 안내

`RequirementAndDraftTool`이 민원 접수 전에 확인해야 할 준비 정보, 누락 가능 정보, 주의사항을 정리합니다.

## 현재 지원 시나리오

- 퇴직금 미지급 문의
- 전입신고 절차 문의
- 도로 붕괴·도로 위험 신고

## 동작 방식

이 프로젝트는 `OpenAI Agents SDK` 기반 단일 오케스트레이터 구조로 동작합니다.

기본 흐름:

```text
user input
-> RequestClassifierTool
-> observe
-> 필요 시 추가 질문 또는 RegionNormalizeTool
-> AgencyRoutingTool
-> 필요 시 RequirementAndDraftTool
-> final answer
```

즉, 고정된 순서로 모든 Tool을 다 부르는 것이 아니라, 현재 질문에 필요한 Tool만 선택해서 호출합니다.

## Tool 구성

| Tool 이름 | 종류 | 역할 |
|-----------|------|------|
| `RequestClassifierTool` | OpenAI API | 사용자 요청 분류 |
| `RegionNormalizeTool` | 공공 OpenAPI | 지역명 표준화 및 법정동 코드 확인 |
| `AgencyRoutingTool` | mock | 소관 기관 후보 및 채널 안내 |
| `RequirementAndDraftTool` | mock | 준비 정보, 누락 정보, 주의사항 정리 |

## 빠른 실행

### 1. 설치

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### 2. 환경 변수

`.env` 파일 예시:

```env
OPENAI_API_KEY=sk-proj-...
PUBLIC_DATA_SERVICE_KEY=...
```

### 3. 실행

```bash
./.venv/bin/python -B src/main.py examples/input_1.txt
```

문장을 직접 넣어 실행할 수도 있습니다.

```bash
./.venv/bin/python -B src/main.py "회사에서 퇴직금을 안 줬는데 어디에 신고해야 하나요?"
```

추가 질문이 필요한 경우에는 실행이 끝나지 않고 같은 콘솔에서 `>` 프롬프트가 나타납니다.  
그 아래에 답을 입력하면 같은 대화 맥락으로 다음 단계가 이어집니다.

## 예시 대화

```text
전입신고는 이사하신 지역의 행정복지센터(동주민센터) 또는 온라인(정부24)에서 할 수 있습니다.

정확한 안내를 위해 이사하신 지역(시/군/구와 동/읍/면 이름)을 알려주시면, 해당 지역 소관 기관과 접수 방법을 안내해드릴 수 있습니다. 이사한 지역을 입력해 주세요!
> 서울시 강남구
서울시 강남구로 이사하셨다면 전입신고는 다음 두 가지 방법으로 하실 수 있습니다.

1. 정부24(www.gov.kr) 온라인 신청
2. 강남구 내 전입하신 주소지 관할 주민센터(행정복지센터) 직접 방문
```

## 종료 및 안정성 규칙

현재 구현에는 다음 제어 규칙이 들어 있습니다.

- `max_turns = 6`
- 실행 시간 60초 제한
- 같은 Tool/argument 반복 호출 방지
- Tool 실패 시 구조화된 에러 반환

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
  src/
    main.py
    prompts/
    tools/
```

## 현재 상태

현재는 MVP 단계입니다.

- `RequestClassifierTool`은 실제 OpenAI API를 사용합니다.
- `RegionNormalizeTool`은 실제 공공 OpenAPI를 사용합니다.
- `AgencyRoutingTool`, `RequirementAndDraftTool`는 아직 mock 데이터 기반입니다.
- 실행 로그는 `logs/` 폴더에 저장됩니다.

## 한계와 다음 단계

- 공공서비스 탐색용 `PublicServiceSearchTool`은 아직 구현하지 않았습니다.
- 기관 라우팅과 준비 정보는 일부 시나리오에서만 정교하게 구성되어 있습니다.
- 추후에는 실제 공공 API 연동 범위를 넓히고, 더 많은 민원 유형과 서류 안내를 지원할 수 있습니다.

## 설계 참고

- 설계 문서: https://github.com/monkama/aiagent-repo/blob/main/week-6/design.md
