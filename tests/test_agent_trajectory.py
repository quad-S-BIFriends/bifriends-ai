"""
에이전트 trajectory 통합 테스트.

목적: 어떤 도구를 몇 번, 어떤 인자로 호출했는지 직접 검증한다.
  - test_agent_routing.py 는 "결과(CTA/todos)" 기반 검증
  - 이 파일은 "도구 호출 경로" 기반 검증 — 도구가 실제로 불렸는지, 인자가 맞는지

실행:
    pytest tests/test_agent_trajectory.py -v --integration
"""
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.agent_runner import AgentRunner
from app.services import be_client as be_client_module

pytestmark = pytest.mark.integration

_MATH_CONCEPTS = [
    {"concept": "받아올림/내림 2번 있는 세 자리 수 덧셈과 뺄셈", "stepTitle": "1단계"},
    {"concept": "분수의 덧셈과 뺄셈", "stepTitle": "2단계"},
    {"concept": "소수의 곱셈", "stepTitle": "3단계"},
]
_LESSON_AVAILABLE = {"lessonStatus": "AVAILABLE", "stepId": 3, "stepTitle": "3단계"}
_KOREAN_LESSON = {"stepTitle": "낱말 익히기", "concept": "어휘"}
_TODO_RESP = {"title": "테스트 할 일", "assignedDate": "2026-06-06"}


@pytest_asyncio.fixture
async def runner():
    if not settings.google_api_key:
        pytest.skip("GOOGLE_API_KEY 없음 — .env 파일에 설정하세요")

    import os
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google import genai
    from app.agents.leo.agent import leo_agent

    os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)

    r = AgentRunner()
    r._session_service = InMemorySessionService()
    r._runner = Runner(agent=leo_agent, app_name="bifriends", session_service=r._session_service)
    r._genai = genai.Client(api_key=settings.google_api_key)
    yield r


def _req(message: str) -> ChatRequest:
    return ChatRequest(
        member_id=9999,
        nickname="테스트",
        grade=4,
        session_id=f"traj-{uuid.uuid4().hex[:8]}",
        message=message,
    )


async def _run(runner: AgentRunner, message: str):
    client = be_client_module.be_client
    with (
        patch.object(client, "get_math_concepts", new_callable=AsyncMock,
                     return_value={"concepts": _MATH_CONCEPTS}),
        patch.object(client, "get_math_lesson_status", new_callable=AsyncMock,
                     return_value=_LESSON_AVAILABLE),
        patch.object(client, "get_korean_current_lesson", new_callable=AsyncMock,
                     return_value=_KOREAN_LESSON),
        patch.object(client, "create_todo", new_callable=AsyncMock,
                     return_value=_TODO_RESP),
    ):
        return await runner.run_with_trajectory(_req(message))


# ────────────────────────────────────────────────────────────────────────────
# 수학
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMathTrajectory:
    async def test_개념_특정_시_math_help_호출(self, runner):
        _, traj = await _run(runner, "분수 덧셈 어려워")
        assert traj.called("math_help"), f"math_help가 호출되지 않음 — {traj.tool_names}"

    async def test_math_help_concept_인자_목록_내_값(self, runner):
        # LLM이 concept 인자에 목록 밖의 값을 넣으면 NOT_FOUND → CTA 없음 → 버그
        _, traj = await _run(runner, "소수 곱셈이 어려워")
        args = traj.args_for("math_help")
        assert args is not None, "math_help 가 호출되지 않음"
        concept = args.get("concept", "")
        valid = [c["concept"] for c in _MATH_CONCEPTS] + ["모름"]
        assert concept in valid, (
            f"concept={concept!r} 이 커리큘럼 목록 밖의 값 — LLM이 임의로 생성했음\n"
            f"허용값: {valid}"
        )

    async def test_막연한_수학_어려움_도구_호출_없음(self, runner):
        _, traj = await _run(runner, "수학이 너무 어려워")
        assert not traj.called("math_help"), (
            f"개념 없이 막연히 어렵다고 했는데 math_help가 호출됨 — {traj.tool_names}"
        )

    async def test_수학_일상언급_도구_없음(self, runner):
        _, traj = await _run(runner, "오늘 수학 시험 봤어")
        assert traj.tool_names == [], f"일상 언급에 도구 호출 발생: {traj.tool_names}"

    async def test_수학_단독_도구_호출_korean_혼용_없음(self, runner):
        _, traj = await _run(runner, "분수 모르겠어")
        assert not traj.called("korean_help"), "수학 질문에 korean_help가 호출됨"
        assert not traj.called("create_todo"), "수학 질문에 create_todo가 호출됨"


# ────────────────────────────────────────────────────────────────────────────
# 국어
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestKoreanTrajectory:
    async def test_공부방_이동의향_즉시_korean_help_호출(self, runner):
        _, traj = await _run(runner, "국어 공부하고 싶어!")
        assert traj.called("korean_help"), (
            f"직접 이동 의향 시 korean_help가 호출되어야 함 — {traj.tool_names}"
        )

    async def test_국어_어려움_첫턴_도구_없음(self, runner):
        # 4단계 흐름 — 첫 턴은 어디가 어려운지 물어보는 단계, 도구 없음
        _, traj = await _run(runner, "국어 도와줘")
        assert not traj.called("korean_help"), (
            f"국어 어려움 첫 턴에는 korean_help 없어야 함 — {traj.tool_names}"
        )

    async def test_국어_단어뜻_직접질문_도구_없음(self, runner):
        _, traj = await _run(runner, "뿌듯하다가 무슨 뜻이야?")
        assert traj.tool_names == [], f"단어 뜻 직접 질문에 도구 호출 발생: {traj.tool_names}"


# ────────────────────────────────────────────────────────────────────────────
# 할 일
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTodoTrajectory:
    async def test_명시적_할일_create_todo_호출(self, runner):
        _, traj = await _run(runner, "수학 문제 3개 풀기 할 일 추가해줘")
        assert traj.called("create_todo"), f"create_todo가 호출되지 않음 — {traj.tool_names}"

    async def test_할일_내용_없으면_create_todo_안호출(self, runner):
        _, traj = await _run(runner, "오늘 할 일을 적을게")
        assert not traj.called("create_todo"), (
            f"내용 없이 create_todo가 호출됨 — {traj.tool_names}"
        )

    async def test_수학_숙제_create_todo_not_math_help(self, runner):
        # "수학 숙제 추가해줘" → create_todo 이어야 하고 math_help가 아님
        _, traj = await _run(runner, "수학 문제집 풀기 할 일 추가해줘")
        assert traj.called("create_todo"), "수학 숙제 등록인데 create_todo가 호출되지 않음"
        assert not traj.called("math_help"), "숙제 등록인데 math_help가 함께 호출됨"


# ────────────────────────────────────────────────────────────────────────────
# 일반 대화
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestChatTrajectory:
    async def test_감정대화_도구_없음(self, runner):
        _, traj = await _run(runner, "오늘 기분이 안 좋아")
        assert traj.tool_names == [], f"감정 대화에 도구 호출 발생: {traj.tool_names}"

    async def test_생활궁금증_도구_없음(self, runner):
        _, traj = await _run(runner, "왜 하늘은 파란색이야?")
        assert traj.tool_names == [], f"생활 궁금증에 도구 호출 발생: {traj.tool_names}"

    async def test_어휘력_요청_도구_없음(self, runner):
        _, traj = await _run(runner, "어휘력 키우고 싶어")
        assert traj.tool_names == [], f"오늘의 단어 요청에 도구가 호출됨: {traj.tool_names}"
