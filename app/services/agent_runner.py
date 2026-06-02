"""
Leo 에이전트 실행 래퍼 (지휘자).

역할:
  1. 앱 시작 시 ADK Runner 초기화 (initialize)
  2. 세션 첫 턴: 그 학년 수학 concept 목록을 BE에서 받아 state에 캐싱
                + member_id / nickname / grade 주입
  3. 매 턴: 이전 턴 CTA state 초기화 → Leo 실행 → state에서 CTA/todos 수거
  4. 최종 ChatResponse 조립 (CTA는 코드가 보장, LLM 텍스트만 message로)

ADK 1.18.0 기준:
  - SessionService.create_session(state=...) 로 초기 state 주입
  - Runner.run_async(state_delta=...) 로 매 턴 state 갱신
  - instruction의 {key}는 세션 state 값으로 자동 치환됨
"""
from __future__ import annotations

import json
from pathlib import Path

from google import genai
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from app.agents.leo.agent import leo_agent
from app.agents.leo.tools.math_tool import STATE_MATH_CTA
from app.agents.leo.tools.korean_tool import STATE_KOREAN_CTA
from app.agents.leo.tools.todo_tool import STATE_TODOS_CREATED
from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.be_client import be_client

_APP_NAME = "bifriends"

# 매 턴 시작 시 비워야 할 CTA/결과 state 키
_PER_TURN_KEYS = (STATE_MATH_CTA, STATE_KOREAN_CTA, STATE_TODOS_CREATED)

# 제목 생성 프롬프트
_TITLE_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "title_gen.txt"
).read_text(encoding="utf-8")
_TITLE_MODEL = settings.model_title 


class AgentRunner:
    def __init__(self) -> None:
        self._runner: Runner | None = None
        self._session_service: DatabaseSessionService | None = None
        self._genai: genai.Client | None = None

    async def initialize(self) -> None:
        self._session_service = DatabaseSessionService(db_url=settings.session_db_url)
        self._runner = Runner(
            agent=leo_agent,
            app_name=_APP_NAME,
            session_service=self._session_service,
        )
        # 제목 생성용 경량 genai 클라이언트 (ADK와 별개 1회성 호출)
        self._genai = genai.Client(api_key=settings.google_api_key)

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            raise RuntimeError("AgentRunner가 초기화되지 않았습니다.")
        return self._runner

    async def _ensure_session(self, req: ChatRequest):
        """세션이 없으면 첫 턴 → concept 목록 캐싱 + 프로필 주입해 생성."""
        user_id = str(req.member_id)
        existing = await self._session_service.get_session(
            app_name=_APP_NAME, user_id=user_id, session_id=req.session_id
        )
        if existing is not None:
            return existing

        # --- 세션 첫 턴: 수학 concept 목록 받아오기 ---
        concepts_raw = await be_client.get_math_concepts(req.member_id)
        concepts = concepts_raw.get("concepts", [])

        # LLM에게 보여줄 텍스트(concept + stepTitle 함께)
        concepts_text = json.dumps(
            [{"concept": c.get("concept"), "stepTitle": c.get("stepTitle")} for c in concepts],
            ensure_ascii=False,
        )

        initial_state = {
            "member_id": req.member_id,
            "nickname": req.nickname,
            "grade": req.grade,
            "math_concepts": concepts,          # 도구가 검증에 사용
            "math_concepts_text": concepts_text,  # 프롬프트 {math_concepts_text} 치환용
        }
        return await self._session_service.create_session(
            app_name=_APP_NAME,
            user_id=user_id,
            session_id=req.session_id,
            state=initial_state,
        )

    async def run(self, req: ChatRequest) -> ChatResponse:
        await self._ensure_session(req)
        user_id = str(req.member_id)

        # 매 턴 CTA/결과 state 초기화 (이전 턴 잔재 방지)
        reset_delta = {k: None for k in _PER_TURN_KEYS}

        message = types.Content(role="user", parts=[types.Part(text=req.message)])

        final_text = ""
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=req.session_id,
            new_message=message,
            state_delta=reset_delta,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(p.text or "" for p in event.content.parts)

        # 실행 후 state에서 CTA/todos 수거
        session = await self._session_service.get_session(
            app_name=_APP_NAME, user_id=user_id, session_id=req.session_id
        )
        state = session.state if session else {}

        cta = state.get(STATE_MATH_CTA) or state.get(STATE_KOREAN_CTA)
        todos = state.get(STATE_TODOS_CREATED)

        return ChatResponse(
            message=final_text,
            cta=cta,                       # dict 그대로 (이미 검증된 CTA)
            todos_created=todos or None,
        )

    async def generate_text(self, prompt: str, model: str = "gemini-2.0-flash") -> str:
        """
        ADK 세션과 무관한 1회성 텍스트 생성 (배치·리포트 등에서 공용).
        실패 시 예외를 그대로 올리므로 호출부에서 처리한다.
        """
        resp = await self._genai.aio.models.generate_content(
            model=model or settings.model_summary,
            contents=prompt,
        )
        return (resp.text or "").strip()

    async def is_new_session(self, req: ChatRequest) -> bool:
        """run() 호출 전에 세션이 아직 없는지(=첫 메시지인지) 확인."""
        existing = await self._session_service.get_session(
            app_name=_APP_NAME,
            user_id=str(req.member_id),
            session_id=req.session_id,
        )
        return existing is None

    async def generate_and_save_title(self, req: ChatRequest, first_reply: str) -> None:
        """
        세션 첫 메시지 기반으로 10~15자 제목을 생성하고 BE에 저장.
        백그라운드로 호출되며, 실패해도 채팅 흐름에 영향 없음(호출부에서 예외 처리).
        """
        prompt = (
            f"{_TITLE_PROMPT}\n\n"
            f"아이: {req.message}\n"
            f"레오: {first_reply}"
        )
        resp = await self._genai.aio.models.generate_content(
            model=_TITLE_MODEL,
            contents=prompt,
        )
        title = (resp.text or "").strip()
        if title:
            await be_client.patch_session_title(req.session_id, title)


agent_runner = AgentRunner()