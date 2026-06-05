# 테스트 실행 가이드

## 설치

```bash
pip install -r requirements-dev.txt
```

## 유닛 테스트 (API 키 불필요)

```bash
pytest tests/ -v
```

Gemini API를 호출하지 않는 순수 Python 함수 테스트. CI에서 항상 실행한다.

| 파일 | 커버 범위 |
|---|---|
| `test_safety_analyzer.py` | 안전 신호 점수 계산·판정·경계값·오탐 케이스 |
| `test_math_tool_utils.py` | concept 목록 검증, lessonStatus → CTA 조립 분기 |
| `test_content_builder.py` | LLM JSON 파싱 엣지케이스, step4 choice 타입 보정 |

## 통합 테스트 (Gemini API 키 필요)

```bash
GOOGLE_API_KEY=AIza... pytest tests/test_agent_routing.py -v --integration
```

실제 Gemini 모델을 호출해 **LLM이 올바른 도구를 선택하는지** 검증한다.
BE API 호출은 mock으로 대체하므로 BE 서버 불필요.

| 테스트 클래스 | 검증 내용 |
|---|---|
| `TestMathRouting` | 수학 질문 → `math_help` 호출, 일상 언급 → 도구 없음 |
| `TestKoreanRouting` | 국어 요청 → `korean_help` 호출 |
| `TestTodoRouting` | "추가해줘" → `create_todo`, 단순 언급 → 도구 없음 |
| `TestChatRouting` | 말동무·생활 질문 → 도구 없음 |
| `TestAmbiguousRouting` | "수학 숙제 추가해줘" → `create_todo` (math_help 아님) |

## 플래그

| 명령 | 설명 |
|---|---|
| `pytest tests/` | 유닛 테스트만 실행 (통합 테스트 자동 skip) |
| `pytest tests/ --integration` | 유닛 + 통합 테스트 모두 실행 |
| `pytest tests/ -k "안전"` | 테스트 이름 필터 |
| `pytest tests/ -x` | 첫 실패 시 즉시 중단 |
