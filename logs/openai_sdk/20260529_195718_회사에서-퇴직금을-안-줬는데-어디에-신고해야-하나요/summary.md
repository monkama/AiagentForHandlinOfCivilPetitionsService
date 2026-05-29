# OpenAI SDK 실행 로그

## user input

회사에서 퇴직금을 안 줬는데 어디에 신고해야 하나요?

## selected tool sequence

1. `RequestClassifierTool`
2. `AgencyRoutingTool`

## final answer

퇴직금을 지급받지 못한 경우, 고용노동부에 '근로기준법 위반사실에 대한 신고'를 하시면 됩니다.

- 소관 기관: 고용노동부 근로기준정책과 (관할 지방고용노동관서)
- 접수 채널: 방문, 우편, 인터넷(민원24 등), 지방고용노동관서 접수
- 준비 정보: 별도의 제출 서류 없이 신고가 가능합니다. (필요 시, 근로계약서, 임금명세서 등 참고자료를 준비하시면 처리에 도움이 될 수 있습니다.)
- 주의사항: 퇴직금 미지급 사실에 대해 되도록 근거자료(계약서, 임금명세서, 통장 거래내역 등)를 함께 제시하시면 신속한 처리가 가능합니다.

가까운 고용노동부 관서에 직접 방문하거나, 인터넷(민원24, 국민신문고)으로도 간편하게 신고할 수 있습니다.

## stop reason

final_answer

## total latency

15355 ms

## token statistics

- 총 tool 호출 수: 2
- 총 input tokens: 12302
- 총 output tokens: 328
- 총 total tokens: 12630

## tool statistics

- `AgencyRoutingTool`: calls=1, latency=7313 ms, input=11087, output=276, total=11363
- `RequestClassifierTool`: calls=1, latency=2448 ms, input=1215, output=52, total=1267