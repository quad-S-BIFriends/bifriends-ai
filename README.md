# bifriends-ai

경계선 지능 아동(8~12세)이 공부와 감정 표현을 각자의 속도로 매일 연습하고, 그 성장을 부모와 함께 보는 앱

**Python · FastAPI · Google ADK · Gemini 2.5**



## 아키텍처

```
Flutter FE
    ↓ JWT
Spring BE (Kotlin) :18080
    ↓ X-Internal-Service 헤더 (도커 내부망)
FastAPI AI (Python) :8001
    ↓
Gemini 2.5 Flash / Flash-Image
```



## API 엔드포인트

| 엔드포인트 | 호출 주체 | 설명 |
|---|---|---|
| `POST /api/v1/ai/chat` | BE | 레오 채팅 에이전트 — 학습 안내·할 일·말동무 |
| `POST /api/v1/ai/batch/weekly-safety` | BE 스케줄러 | 주간 안전 신호 분석 → GREEN/YELLOW/RED 판정 |
| `POST /api/v1/ai/report/weekly` | BE 스케줄러 | 부모 성장 리포트 4개 섹션 생성 |
| `POST /api/v1/ai/content/scenario` | BE | EMO 감정 학습 시나리오 + 이미지 3컷 생성 |
| `GET  /health` | 인프라 | 헬스체크 |

**🤎 레오 채팅** — Google ADK 기반 대화 에이전트. 아이 메시지에서 인텐트(수학·국어 공부, 할 일 등록, 말동무)를 판단하고, 학습 CTA는 BE 데이터 기반으로 코드에서 결정론적으로 조립한다.

**🤎 주간 안전 신호** — 주간 채팅 메시지를 키워드 점수로 분석해 GREEN/YELLOW/RED 판정. 자해·자살 표현은 LLM 없이 코드에서 즉시 RED 강제, YELLOW/RED일 때만 Gemini 1회 호출해 요약문을 생성한다.

**🤎 부모 성장 리포트** — 주간 학습 집계를 받아 성장 요약·수학·국어·보호자 미션 4개 섹션을 Gemini로 생성해 반환한다.

**🤎 친구랑 EMO 콘텐츠** — 감정별 4단계 학습 세트를 생성한다. 텍스트 생성(Gemini) → step3 이미지 3컷(모든 컷이 동일 앵커 이미지를 참조해 **병렬** 생성, 캐릭터 정체성 일관성 유지) 순으로 실행하며, 생성 실패 시 폴백 시나리오로 자동 대체한다.



### 채팅 응답 구조

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

`cta` 타입: `navigate_to_step` (수학) · `navigate_to_subject` (국어) · `null`  
`todos_created`: 할 일 등록 시에만 배열, 나머지는 `null`

### 레오 프롬프트 모듈

레오는 **단일 에이전트**다. 시스템 프롬프트(static instruction)는 도메인별 수정이 쉽도록
`app/prompts/leo/` 아래로 파일만 쪼개 두었고, [`agent.py`](app/agents/leo/agent.py)의
`_load_static_prompt()`가 **파일명 순**으로 읽어 `\n\n`으로 이어 붙인다. 런타임에 멀티 에이전트로 분기하지 않는다.

| 파일 | 내용 |
|---|---|
| `00_identity.txt` | 정체성·말투·판단 원칙 |
| `10_math.txt` / `20_korean.txt` | 수학·국어 도움 라우팅·톤 |
| `30_vocabulary.txt` / `40_todo.txt` / `50_casual.txt` | 어휘력·할 일·일상 대화 |
| `60_safety.txt` | 안전 규칙 (모든 응답에 적용, **절대 비우지 말 것**) |
| `70_examples.txt` | few-shot 예시 (항상 맨 뒤) |

- 새 도메인은 `NN_xxx.txt` 파일만 추가하면 자동 포함된다 (코드 수정 불필요).
- 세션별 동적 값(닉네임·학년·concept 목록)은 `app/prompts/leo_dynamic.txt`에 있고 static 뒤에 붙어 `{key}`가 치환된다.

### 안전 신호 점수 기준

| 조건 | 점수 |
|---|---|
| 동일 메시지 4회 이상 반복 | +2 |
| 부정 감정 3회 이상 | +2 |
| 감정 고립 표현 | +3 |
| 욕설·폭력 키워드 | +5 |

0–3 → GREEN (Gemini 호출 없음) · 4–7 → YELLOW · 8+ → RED  
자해·자살 표현은 점수와 무관하게 **코드에서 즉시 RED 강제**

### 이미지 생성 전략 실험

친구랑 step3 이미지의 컷 간 일관성·레이턴시를 전략별로 비교하는 벤치 스크립트가 있다.
프로덕션 코드 경로(`generate_emo_images`)를 그대로 호출하므로 실제 이미지 모델과 비용이 든다.

```bash
# 세 전략(sequential·hybrid·parallel)을 같은 시나리오로 비교
python scripts/emo_image_bench.py

# 감정·관심사 지정
python scripts/emo_image_bench.py --emotion 속상함 --interests 공룡,그림그리기

# 특정 전략만, 편차 확인용 반복
python scripts/emo_image_bench.py --strategies hybrid,parallel --repeat 2
```

결과는 `experiments/emo_bench/<타임스탬프>/` 아래 전략별 폴더로 저장되고, `summary.md`에
레이턴시 표와 컷 프롬프트가 함께 기록된다. 각 폴더의 `cut0/1/2.png`를 나란히 열어 비교한다.

| 전략 | 참조 방식 | 특징 |
|---|---|---|
| `parallel` (기본) | 모든 컷이 동일 앵커만 참조, 동시 생성 | 가장 빠름·캐릭터 정체성 일관성 최고 |
| `hybrid` | 1컷 먼저 → 나머지는 1컷 참조해 병렬 | 절충 |
| `sequential` | 각 컷이 직전 컷을 순차 참조 | 인접 컷 연속성↑·드리프트 누적·가장 느림 |

> 프로덕션 기본 전략은 [`generate_emo_images`](app/services/agent_runner.py)의 `strategy` 기본값으로 결정된다.


## 시작하기

```bash
# 1. 환경변수 설정
cp .env.example .env
# GOOGLE_API_KEY, INTERNAL_SERVICE_TOKEN 입력

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 로컬 실행
python main.py
# → http://localhost:8001/docs
```

### 도커 (BE와 함께 실행)

```bash
# BE 레포에서 먼저 실행
docker compose up -d

# AI 레포에서 실행
docker compose up -d

curl http://localhost:18001/health
```

BE `docker-compose.yml`에 네트워크 이름 고정이 필요합니다:
```yaml
networks:
  default:
    name: bifriends-be-default
```

---

## 환경변수

| 변수 | 설명 | 기본값 |
|---|---|---|
| `GOOGLE_API_KEY` | Gemini API 키 | — |
| `BE_BASE_URL` | BE 서버 주소 | `http://bifriends-be:8080` |
| `INTERNAL_SERVICE_TOKEN` | 내부 서비스 인증 토큰 | — |
| `SESSION_DB_URL` | ADK 세션 DB | `sqlite+aiosqlite:///./sessions.db` |
| `APP_ENV` | 실행 환경 (`development` / `production`) | `development` |
| `APP_PORT` | 서버 포트 | `8001` |
| `MODEL_CHAT` | 레오 채팅 모델 | `gemini-2.5-flash` |
| `MODEL_IMAGE` | 이미지 생성 모델 | `gemini-2.5-flash-image` |

> `production` 환경에서는 `/docs`, `/redoc`이 비활성화됩니다.

---

## BE API 연동 목록

AI → BE 호출 (모두 `X-Internal-Service` 헤더 필요):

```
GET  /api/v1/learning/math/concepts                     # 수학 concept 목록
GET  /api/v1/learning/math/concepts/lesson-status       # concept별 lesson 상태
GET  /api/v1/learning/korean/lessons/current            # 국어 현재 lesson
POST /api/v1/todos                                      # 할 일 등록
PATCH /api/v1/chat/sessions/{session_id}                # 세션 제목 저장
GET  /api/v1/chat/messages                              # 주간 채팅 메시지 조회
POST /api/v1/weekly-safety-report                       # 안전 신호 저장
GET  /api/v1/report/learning-summary                    # 주간 학습 집계 조회
```
