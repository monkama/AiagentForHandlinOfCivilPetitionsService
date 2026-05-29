# OpenAI SDK 실행 로그

이 폴더는 `OpenAI Agents SDK` 실행 로그만 저장합니다.

로그에는 최소한 아래 항목이 남습니다.

- user input
- selected tool
- tool arguments
- tool result
- final answer

구조 예시:

```text
logs/
  openai_sdk/
    20260513_213000_회사에서-퇴직금을-안-줬는데/
      run.json
      summary.md
      tool_calls/
        01_RequestClassifierTool.json
        02_AgencyRoutingTool.json
```
