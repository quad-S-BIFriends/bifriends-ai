# 비프렌드 AI 레포 (bifriends-ai)

경계선 지능 아동(8~12세)을 위한 학습 도우미 AI 서비스.

**스택**: Python · FastAPI · Google ADK · Gemini 2.0 Flash

---

## 아키텍처

```
Flutter FE
    ↓ JWT 인증
Spring BE (Kotlin) :18080
    ↓ X-Internal-Service 헤더
FastAPI AI (Python) :18001
    ↓
Gemini 2.0 Flash
```

- FE ↔ BE: JWT 인증
- BE ↔ AI: 도커 내부 네트워크 통신 (`X-Internal-Service` 헤더)
- AI → BE: BE API 호출 (DB 직접 접근 없음)

---

## 기능

### 1. 레오랑 톡톡 (채팅 에이전트)

`POST /api/v1/ai/chat`

아이의 메시지를 받아 인텐트를 분류하고 응답을 반환한다.

| 인텐트 | 설명 |
|--------|------|
| `math_study` | 수학 공부 도움. concept 기반 3분기 분기 처리 |
| `korean_study` | 국어 공부 도움. 팁 → 연습문제 → CTA 플로우 |
| `chat` | 말동무 대화. 공감 중심 응답 |
| `daily_question` | 생활 질문. 아이 눈높이 답변 |
| `create_todo` | 할 일 등록. BE API 호출 후 카드 형태로 응답 |
| `title` | 첫 메시지 도착 시 세션 제목 자동 생성 |

**수학 3분기 분기 로직**

```
아이가 수학 질문
    ↓
BE에서 concept별 lesson 상태 조회
    ↓
AVAILABLE / IN_PROGRESS / COMPLETED  →  해당 step으로 이동 CTA
LOCKED                                →  현재 가능한 step으로 안내
NOT_FOUND                             →  채팅 안에서 간단 연습문제 제공
```

**응답 JSON 구조**

```json
{
  "message": "오늘 어떤 수학 문제가 어려웠어?",
  "cta": {
    "type": "navigate_to_step",
    "label": "지금 바로 연습해볼까?",
    "step_id": 2,
    "cycle_number": 1,
    "subject": "math"
  },
  "todos_created": null
}
```

CTA 타입 목록:

| type | 설명 | 포함 필드 |
|------|------|-----------|
| `navigate_to_step` | 수학 특정 step으로 이동 | `step_id`, `cycle_number`, `subject` |
| `navigate_to_subject` | 국어 학습 화면으로 이동 | `subject` |
| `suggestions` | 웰컴 화면 추천 버튼 | `items[]` |

`todos_created`: 할 일 등록 인텐트일 때만 배열로 반환, 나머지는 `null`

```json
"todos_created": [
  { "title": "수학 문제 3개 풀기", "assigned_date": "2026-05-28" }
]
```

---

### 2. 주간 안전 신호 배치

`POST /api/v1/ai/batch/weekly-safety`

매주 금요일 저녁 BE 스케줄러가 호출. AI는 엔드포인트만 열어두고 처리.

**흐름**

```
BE 스케줄러 호출
    ↓
이번 주 chat_messages에서 user 메시지 전체 조회 (BE API)
    ↓
키워드 카운팅 (Gemini 호출 없이 Python 코드로만 처리)
    ↓
점수 계산 → GREEN / YELLOW / RED 판정
    ↓
YELLOW / RED일 때만 Gemini 1회 호출 → reason_summary 생성
    ↓
BE API로 weekly_safety_report 저장
```

**점수 계산**

| 조건 | 점수 |
|------|------|
| 동일 메시지 4회 이상 반복 | +2 |
| 부정 감정 3회 이상 (싫어, 짜증 등) | +2 |
| 감정 고립 표현 (외로워, 친구 없어 등) | +3 |
| 욕설 / 폭력 키워드 | +5 |

| 점수 | 판정 |
|------|------|
| 0 ~ 3 | GREEN |
| 4 ~ 7 | YELLOW |
| 8+ | RED |

---

### 3. 부모 성장 리포트 (개발 예정)

`POST /api/v1/ai/report/weekly`

주간 학습 데이터를 기반으로 부모용 리포트 생성. 4개 섹션을 한 번에 JSON으로 BE에 전달.

```json
{
  "member_id": 1,
  "week_start": "2026-05-25",
  "week_end": "2026-05-31",
  "sections": {
    "summary": "이번 주 혜나는 수학 덧셈을 열심히 공부했어요.",
    "well_done": "매일 꾸준히 접속하고 할 일을 완료했어요.",
    "learning_status": {
      "math": "뺄셈 2단계 진행 중이에요.",
      "korean": "낱말 익히기를 완료했어요."
    },
    "action_items": "이번 주는 곱셈 개념을 함께 살펴보세요."
  }
}
```

---

### 4. 친구랑 콘텐츠 생성 (개발 예정)

`POST /api/v1/ai/content/scenario`

SEL(사회정서학습) 시나리오 생성. 아이의 관심사를 반영한 소재로 생성.

예시: 공룡을 좋아하는 아이 → "공룡 장난감을 친구가 뺏었을 때 어떻게 할까?"

---

## 디렉토리 구조

```
bifriends-ai/
├── main.py                          # FastAPI 앱 진입점
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example                     # 환경변수 템플릿
├── requirements.txt
└── app/
    ├── core/
    │   └── config.py                # 환경변수 설정
    ├── prompts/                     # 프롬프트 파일 관리
    │   ├── leo_agent.txt            # 레오 메인 프롬프트
    │   ├── math_study.txt           # 수학 공부 도움
    │   ├── korean_study.txt         # 국어 공부 도움
    │   ├── safety_analyzer.txt      # 안전신호 분석 (YELLOW/RED용)
    │   ├── report_summary.txt       # 부모 리포트 생성
    │   └── content_scenario.txt     # 친구랑 시나리오 생성
    ├── agents/
    │   └── leo/
    │       ├── agent.py             # ADK 레오 에이전트
    │       └── tools/
    │           ├── todo_tool.py     # 할일 등록/수정/삭제
    │           ├── math_tool.py     # 수학 3분기 로직
    │           └── korean_tool.py   # 국어 현재 lesson 조회
    ├── api/
    │   └── routers/
    │       ├── chat.py              # POST /api/v1/ai/chat
    │       ├── batch.py             # POST /api/v1/ai/batch/weekly-safety
    │       ├── report.py            # 부모 성장 리포트 (예정)
    │       └── content.py           # 친구랑 콘텐츠 생성 (예정)
    ├── schemas/
    │   ├── chat.py                  # 채팅 request/response 모델
    │   ├── batch.py                 # 배치 request/response 모델
    │   ├── report.py                # 리포트 모델 (예정)
    │   └── content.py               # 콘텐츠 모델 (예정)
    └── services/
        ├── agent_runner.py          # ADK Runner 래퍼 (싱글턴)
        ├── be_client.py             # BE API HTTP 클라이언트
        ├── safety_analyzer.py       # 안전신호 키워드 분석
        └── report_builder.py        # 부모 리포트 생성 로직
```

---

## 시작하기

```bash
# 1. 환경변수 설정 
cp .env.example .env
# .env 파일에서 GOOGLE_API_KEY, INTERNAL_SERVICE_TOKEN 입력

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 로컬 서버 실행
python main.py
# → http://localhost:8001/docs 에서 Swagger 확인

# 4. 도커 실행 (BE 먼저 띄운 후)
docker compose up -d
```

---

## 도커 네트워크

BE와 AI는 같은 도커 네트워크(`bifriends-be-default`)에서 통신한다.

```bash
# BE 먼저 실행 (bifriends-be 레포에서)
docker compose up -d

# AI 실행 (bifriends-ai 레포에서)
docker compose up -d

# 확인
curl http://localhost:18001/health
```

BE 레포 `docker-compose.yml` 맨 아래에 아래 블록이 있어야 네트워크 이름이 고정된다:

```yaml
networks:
  default:
    name: bifriends-be-default
```

---

## 환경변수

| 변수 | 설명 | 예시 |
|------|------|------|
| `GOOGLE_API_KEY` | Gemini API 키 | `AIza...` |
| `BE_BASE_URL` | BE 서버 주소 | `http://bifriends-be:8080` |
| `INTERNAL_SERVICE_TOKEN` | 내부 서비스 인증 토큰 | `bifriends-ai-secret-token` |
| `SESSION_DB_URL` | ADK 세션 DB | `sqlite+aiosqlite:///./sessions.db` |
| `APP_ENV` | 실행 환경 | `development` / `production` |
| `APP_PORT` | 서버 포트 | `8001` |

---

## BE API 연동 목록

AI 레포에서 호출하는 BE API 목록 (모두 `X-Internal-Service` 헤더 필요):

```
GET  /api/v1/members/{memberId}/profile          # 멤버 정보 (nickname, grade, interests)
GET  /api/v1/learning/math/concepts              # 수학 concept 목록
GET  /api/v1/learning/math/concepts/lesson-status?concept=   # 수학 lesson 상태
GET  /api/v1/learning/korean/lessons/current     # 국어 현재 lesson
GET  /api/v1/chat/messages?member_id=&from=&to=  # 주간 채팅 메시지 조회
POST /api/v1/todos                               # 할 일 등록
PATCH /api/v1/todos/{todoId}                     # 할 일 수정
DELETE /api/v1/todos/{todoId}?memberId=          # 할 일 삭제
POST /api/v1/weekly-safety-report                # 안전 신호 저장
PATCH /api/v1/chat/sessions/{session_id}         # 세션 제목 업데이트
```
