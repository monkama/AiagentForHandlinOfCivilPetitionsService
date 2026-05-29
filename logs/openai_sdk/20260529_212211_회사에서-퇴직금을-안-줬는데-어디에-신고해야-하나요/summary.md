# OpenAI SDK 실행 로그

## user input

회사에서 퇴직금을 안 줬는데 어디에 신고해야 하나요?

## selected tool sequence

1. `RequestClassifierTool`
2. `AgencyRoutingTool`

## final answer

퇴직금을 받지 못했다면 고용노동부에 “근로기준법 위반사실에 대한 신고”를 하시면 됩니다.

- 소관 기관: 고용노동부(근로기준정책과)
- 신청 채널: 가까운 고용노동관서 방문, 인터넷(고용노동부 홈페이지), 우편, 지방노동위원회 방문 등
- 필요 서류: 근로계약서 사본, 근로조건 위반을 입증할 수 있는 자료 등(퇴직 관련 서류, 급여 내역 등)
- 참고사항: 외국인 근로자는 외국인등록사실증명이 필요할 수 있습니다.

신고 절차를 시작하시려면 고용노동부 통합 고객센터(1350, 유료)로 문의하거나 인터넷으로 민원 신청을 하실 수 있습니다.

관련 법령:
- 1. 근로기준법(제104조 제1항)
- 1. 근로기준법(제19조 제2항)
- 2. 근로기준법 시행규칙(제2조 [별지1호])
구비 서류:
- 외국인등록사실증명
- 근로계약서 사본 1부
- 사용자의 근로조건 위반사실을 입증하는 자료 1부

## stop reason

final_answer

## total latency

19323 ms

## token statistics

- 총 tool 호출 수: 2
- 총 input tokens: 7597
- 총 output tokens: 373
- 총 total tokens: 7970

## tool statistics

- `AgencyRoutingTool`: calls=1, latency=10837 ms, input=6382, output=321, total=6703
- `RequestClassifierTool`: calls=1, latency=1710 ms, input=1215, output=52, total=1267