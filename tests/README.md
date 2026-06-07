# 테스트 실행 가이드

## 설치

```bash
pip install -r requirements-dev.txt
```

---

## 1. 로컬 터미널 대화 테스트 (CLI)

레오와 직접 대화하며 응답을 눈으로 확인하는 방법. API 키만 있으면 됨. BE 서버 불필요.

```bash
# 기본 (4학년, mock BE 데이터)
python scripts/chat_cli.py

# 학년·닉네임 지정
python scripts/chat_cli.py --grade 5 --nickname 민준

# 도구 호출 경로 함께 표시 (어떤 툴이 불렸는지 확인)
python scripts/chat_cli.py --trajectory
```

`--trajectory` 출력 예시:
```
아이: 소수 곱셈이 어려워
  [도구] math_help(concept='소수의 곱셈')
레오: 소수 곱셈 하고 있구나! ...
  [버튼] 지금 바로 연습해볼까?  (navigate_to_step)
```

옵션 전체:

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--grade N` | 아이 학년 (3~6) | 4 |
| `--nickname NAME` | 아이 닉네임 | 테스트 |
| `--trajectory` | 도구 호출 이름·인자 표시 | off |
| `--real-be` | mock 대신 실제 BE 서버 사용 (⚠️ Docker 내부에서만 동작) | off |

> **⚠️ `--real-be` 주의**: BE URL이 Docker 내부 주소(`http://be:8080`)로 설정되어 있어 **로컬 터미널에서 실행하면 DNS 오류(`[Errno 8] nodename nor servname provided`)가 발생**한다.
> `--real-be`는 Docker 컨테이너 내부에서 실행할 때만 사용한다. 로컬 테스트는 기본 mock 모드를 사용할 것.

종료: `q` 입력 또는 `Ctrl+C`

---

## 2. 유닛 테스트 (API 키 불필요)

```bash
pytest tests/ -v
```

Gemini API를 호출하지 않는 순수 Python 함수 테스트. CI에서 항상 실행한다.

| 파일 | 커버 범위 |
|---|---|
| `test_safety_analyzer.py` | 안전 신호 점수 계산·판정·경계값·오탐 케이스 |
| `test_math_tool_utils.py` | concept 목록 검증, lessonStatus → CTA 조립 분기 |
| `test_content_builder.py` | LLM JSON 파싱 엣지케이스, step4 choice 타입 보정 |

---

## 3. 통합 테스트 (Gemini API 키 필요)

`.env`에 `GOOGLE_API_KEY`가 있으면 그대로 읽힘. BE 서버 불필요.

### 라우팅 테스트 — 올바른 도구를 선택하는지 (결과 기반)

```bash
pytest tests/test_agent_routing.py -v --integration
```

| 테스트 클래스 | 검증 내용 |
|---|---|
| `TestMathRouting` | 수학 질문 → CTA 있음, 일상 언급 → CTA 없음 |
| `TestKoreanRouting` | 국어 공부방 이동 의향 → 즉시 CTA, 일상 언급 → CTA 없음 |
| `TestTodoRouting` | "추가해줘" → todos_created, 내용 없으면 → 도구 없음 |
| `TestChatRouting` | 말동무·생활 질문 → 도구 없음 |
| `TestVocabularyRouting` | "어휘력 키우고 싶어" → 도구 없이 단어 3개 답변 |
| `TestAmbiguousRouting` | "수학 숙제 추가해줘" → create_todo (math_help 아님) |

### Trajectory 테스트 — 도구 호출 자체와 인자를 검증

```bash
pytest tests/test_agent_trajectory.py -v --integration
```

라우팅 테스트가 "도구의 결과"를 보는 것과 달리, trajectory 테스트는 **어떤 도구가 불렸는지, 인자가 올바른지** 직접 검증한다.

| 테스트 클래스 | 검증 내용 |
|---|---|
| `TestMathTrajectory` | `math_help` 호출 여부·concept 인자가 커리큘럼 목록 내 값인지 |
| `TestKoreanTrajectory` | 이동 의향 시 즉시 `korean_help` 호출, 첫 턴엔 도구 없음 |
| `TestTodoTrajectory` | `create_todo` 호출 여부, 수학 숙제 등록 시 `math_help` 혼용 없음 |
| `TestChatTrajectory` | 감정대화·생활궁금증·어휘력 요청 시 도구 호출 없음 |

---

## 빠른 명령 모음

| 명령 | 설명 |
|---|---|
| `pytest tests/` | 유닛 테스트만 (통합 자동 skip) |
| `pytest tests/ --integration` | 유닛 + 통합 전체 실행 |
| `pytest tests/test_agent_routing.py -v --integration` | 라우팅만 |
| `pytest tests/test_agent_trajectory.py -v --integration` | trajectory만 |
| `pytest tests/ -k "수학"` | 이름에 "수학" 포함된 것만 |
| `pytest tests/ -x` | 첫 실패 시 즉시 중단 |
