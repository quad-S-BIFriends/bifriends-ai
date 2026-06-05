"""
에이전트 라우팅 통합 테스트.

실제 Gemini API를 호출하므로 GOOGLE_API_KEY 환경변수가 필요하다.
BE API 호출은 unittest.mock으로 대체한다.

실행:
    pytest tests/test_agent_routing.py -v --integration

판정 기준:
    - cta.type == "navigate_to_step"  → math_help 호출됨
    - cta.type == "navigate_to_subject" → korean_help 호출됨
    - todos_created is not None       → create_todo 호출됨
    - cta is None and todos_created is None → 도구 없음 (일반 대화)
"""
import os
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from app.schemas.chat import ChatRequest
from app.services.agent_runner import AgentRunner
from app.services import be_client as be_client_module

pytestmark = pytest.mark.integration

_MATH_CONCEPTS = [
    {"concept": "받아올림 없는 세 자리 수 덧셈과 뺄셈", "stepTitle": "1단계"},
    {"concept": "분수의 덧셈과 뺄셈", "stepTitle": "2단계"},
    {"concept": "소수의 곱셈", "stepTitle": "3단계"},
]
_LESSON_AVAILABLE = {"lessonStatus": "AVAILABLE", "stepId": 3, "stepTitle": "3단계"}
_KOREAN_LESSON = {"stepTitle": "낱말 익히기", "concept": "어휘"}
_TODO_RESP = {"title": "테스트 할 일", "assignedDate": "2026-06-05"}


@pytest.fixture(scope="module")
def api_key():
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        pytest.skip("GOOGLE_API_KEY 없음 — 통합 테스트 건너뜀")
    return key


@pytest_asyncio.fixture(scope="module")
async def runner(api_key):
    r = AgentRunner()
    await r.initialize()
    yield r


def _req(message: str) -> ChatRequest:
    return ChatRequest(
        member_id=9999,
        nickname="테스트",
        grade=4,
        session_id=f"test-{uuid.uuid4().hex[:8]}",
        message=message,
    )


async def _run(runner: AgentRunner, message: str):
    """BE 호출을 mock 처리하고 agent 실행."""
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
        return await runner.run(_req(message))


@pytest.mark.asyncio
class TestMathRouting:
    async def test_수학_개념_질문(self, runner):
        resp = await _run(runner, "분수 덧셈 도와줘")
        assert resp.cta is not None
        assert resp.cta["type"] == "navigate_to_step"

    async def test_수학_모르겠다(self, runner):
        resp = await _run(runner, "소수 곱셈이 너무 어려워")
        assert resp.cta is not None
        assert resp.cta["type"] == "navigate_to_step"

    async def test_수학_일상_언급_도구_없음(self, runner):
        # "수학 시험 봤어" — 학습 요청 아님, 도구 호출 없어야 함
        resp = await _run(runner, "오늘 수학 시험 봤어")
        assert resp.cta is None


@pytest.mark.asyncio
class TestKoreanRouting:
    async def test_국어_공부_요청(self, runner):
        resp = await _run(runner, "국어 공부 도와줘")
        assert resp.cta is not None
        assert resp.cta["type"] == "navigate_to_subject"

    async def test_국어_일상_언급_도구_없음(self, runner):
        resp = await _run(runner, "국어 시험 어려웠어")
        assert resp.cta is None


@pytest.mark.asyncio
class TestTodoRouting:
    async def test_명시적_할일_등록(self, runner):
        resp = await _run(runner, "수학 문제 3개 풀기 할 일 추가해줘")
        assert resp.todos_created is not None
        assert len(resp.todos_created) >= 1

    async def test_여러_할일_한번에(self, runner):
        resp = await _run(runner, "수학 문제 풀기랑 책 읽기 두 개 추가해줘")
        assert resp.todos_created is not None

    async def test_숙제_언급만으로는_등록_안함(self, runner):
        # "숙제 있어" — 등록 요청 없으므로 create_todo 호출 없어야 함
        resp = await _run(runner, "오늘 수학 숙제 있어")
        assert resp.todos_created is None


@pytest.mark.asyncio
class TestChatRouting:
    async def test_말동무_도구_없음(self, runner):
        resp = await _run(runner, "오늘 기분이 좀 안 좋아")
        assert resp.cta is None
        assert resp.todos_created is None

    async def test_생활_질문_도구_없음(self, runner):
        resp = await _run(runner, "왜 하늘은 파란색이야?")
        assert resp.cta is None
        assert resp.todos_created is None


@pytest.mark.asyncio
class TestAmbiguousRouting:
    async def test_수학숙제_추가는_todo(self, runner):
        # "수학 숙제 추가해줘" → create_todo (math_help 아님)
        resp = await _run(runner, "수학 문제집 풀기 할 일 추가해줘")
        assert resp.todos_created is not None
        assert resp.cta is None or resp.cta["type"] != "navigate_to_step"

    async def test_응답은_항상_있음(self, runner):
        resp = await _run(runner, "안녕")
        assert resp.reply
