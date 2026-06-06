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
from dataclasses import dataclass, field
from pathlib import Path
import base64

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


@dataclass
class ToolCallRecord:
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class RunTrajectory:
    """한 턴에서 LLM이 호출한 도구들의 순서·인자를 기록한다."""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [tc.name for tc in self.tool_calls]

    def called(self, tool_name: str) -> bool:
        return tool_name in self.tool_names

    def args_for(self, tool_name: str) -> dict | None:
        for tc in self.tool_calls:
            if tc.name == tool_name:
                return tc.args
        return None

# 매 턴 시작 시 비워야 할 CTA/결과 state 키
_PER_TURN_KEYS = (STATE_MATH_CTA, STATE_KOREAN_CTA, STATE_TODOS_CREATED)

# 제목 생성 프롬프트
_TITLE_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "title_gen.txt"
).read_text(encoding="utf-8")
_TITLE_MODEL = settings.model_title 

_ANCHOR_DIR = Path(__file__).parent.parent / "assets" / "anchors"
_ANCHOR_PATH = {
    "boy": _ANCHOR_DIR / "boy.png",
    "girl": _ANCHOR_DIR / "girl.png",
}

_EMO_SCENARIO_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "content_scenario.txt"
).read_text(encoding="utf-8")


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
                # text 없는 파트(function_response 등)가 섞여도 실제 텍스트만 수집.
                # 빈 문자열로 이전 텍스트를 덮어쓰는 것을 방지한다.
                candidate = "".join(p.text for p in event.content.parts if p.text)
                if candidate:
                    final_text = candidate

        # 실행 후 state에서 CTA/todos 수거
        session = await self._session_service.get_session(
            app_name=_APP_NAME, user_id=user_id, session_id=req.session_id
        )
        state = session.state if session else {}

        cta = state.get(STATE_MATH_CTA) or state.get(STATE_KOREAN_CTA)
        todos = state.get(STATE_TODOS_CREATED)

        return ChatResponse(
            reply=final_text,
            cta=cta,
            todos_created=todos or None,
        )

    async def run_with_trajectory(
        self, req: ChatRequest
    ) -> tuple[ChatResponse, RunTrajectory]:
        """run()과 동일하지만 도구 호출 경로(RunTrajectory)를 함께 반환한다.
        디버깅·테스트 전용 — 프로덕션 라우터에서는 run()을 사용한다."""
        await self._ensure_session(req)
        user_id = str(req.member_id)
        reset_delta = {k: None for k in _PER_TURN_KEYS}
        message = types.Content(role="user", parts=[types.Part(text=req.message)])

        trajectory = RunTrajectory()
        final_text = ""

        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=req.session_id,
            new_message=message,
            state_delta=reset_delta,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and getattr(fc, "name", None):
                        trajectory.tool_calls.append(
                            ToolCallRecord(name=fc.name, args=dict(fc.args or {}))
                        )

            if event.is_final_response() and event.content and event.content.parts:
                candidate = "".join(p.text for p in event.content.parts if p.text)
                if candidate:
                    final_text = candidate

        session = await self._session_service.get_session(
            app_name=_APP_NAME, user_id=user_id, session_id=req.session_id
        )
        state = session.state if session else {}
        cta = state.get(STATE_MATH_CTA) or state.get(STATE_KOREAN_CTA)
        todos = state.get(STATE_TODOS_CREATED)

        response = ChatResponse(reply=final_text, cta=cta, todos_created=todos or None)
        return response, trajectory

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

    async def generate_emo_scenario_text(
        self,
        *,
        emotion: str,
        nickname: str,
        interests: list[str],
        learned_expressions: list[str],
    ) -> str:
        """
        친구랑 시나리오 '텍스트'를 1회성으로 생성 (JSON 문자열 반환).
        ADK 대화 세션과 무관 — generate_text 와 동일 계열.
        content_scenario.txt 를 시스템 지시로, 입력을 사용자 메시지로 전달.
        모델: settings.model_scenario (구조화 JSON용).
        """
        from app.core.config import settings  # 지연 import (예시 파일 기준)
 
        user_input = (
            f"emotion(감정): {emotion}\n"
            f"nickname(아이 이름): {nickname}\n"
            f"interests(관심사): {', '.join(interests) if interests else '없음'}\n"
            f"learned_expressions(이미 배운 표현): "
            f"{', '.join(learned_expressions) if learned_expressions else '없음'}\n"
            f"위 조건으로 4단계 감정 학습 세트를 생성해줘. 순수 JSON만 출력."
        )
        resp = await self._genai.aio.models.generate_content(
            model=settings.model_scenario,
            contents=[
                types.Content(role="user", parts=[
                    types.Part(text=_EMO_SCENARIO_PROMPT),
                    types.Part(text=user_input),
                ]),
            ],
        )
        return (resp.text or "").strip()
 
    async def generate_emo_images(
        self,
        *,
        anchor_instruction: str,
        prompts: list[str],
        gender: str,
    ) -> list[str | None]:
        """
        step3 3컷 이미지를 멀티턴으로 순차 생성 → base64 리스트 반환.
        - 첫 컷: 앵커 이미지(boy/girl) + anchor_instruction + prompts[0]
        - 이후 컷: 직전 생성 이미지를 contents에 포함해 캐릭터/배경 일관성 유지
        - 1:1 은 image_config 로 강제.
        실패(빈 응답/차단) 시 해당 컷은 None → 호출부(content_builder)가 폴백 처리.
        """
        from app.core.config import settings
 
        # 앵커 이미지 바이트 로드
        anchor_path = _ANCHOR_PATH[gender]
        anchor_bytes = anchor_path.read_bytes()
        anchor_part = types.Part.from_bytes(data=anchor_bytes, mime_type="image/png")
 
        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="1:1"),
        )
 
        results: list[str | None] = []
        prev_image_part = None  # 직전 컷 이미지(일관성용)
 
        for i, prompt in enumerate(prompts):
            # contents 조립: 첫 컷은 앵커, 이후 컷은 직전 이미지 + 앵커지시 동봉
            parts: list = []
            if i == 0:
                parts.append(types.Part(text=anchor_instruction))
                parts.append(anchor_part)
            else:
                # 직전 컷 이미지를 참조로 (드리프트 방지)
                if prev_image_part is not None:
                    parts.append(prev_image_part)
                parts.append(anchor_part)  # 앵커도 계속 동봉(외형 고정 강화)
            parts.append(types.Part(text=prompt))
 
            try:
                resp = await self._genai.aio.models.generate_content(
                    model=settings.model_image,
                    contents=[types.Content(role="user", parts=parts)],
                    config=cfg,
                )
                b64 = self._extract_image_b64(resp)
            except Exception:
                b64 = None
 
            results.append(b64)
            if b64 is not None:
                prev_image_part = types.Part.from_bytes(
                    data=base64.b64decode(b64), mime_type="image/png"
                )
            else:
                prev_image_part = None  # 실패 컷은 참조 끊김
 
        return results
 
    @staticmethod
    def _extract_image_b64(resp) -> str | None:
        """genai 응답에서 첫 이미지 inline_data(base64) 추출. 없으면 None."""
        try:
            for part in resp.candidates[0].content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
                    # SDK가 bytes로 줄 수도, str(base64)로 줄 수도 있음 → 표준화
                    if isinstance(data, bytes):
                        return base64.b64encode(data).decode("ascii")
                    return data  # 이미 base64 문자열
        except (AttributeError, IndexError):
            pass
        return None
 
agent_runner = AgentRunner()