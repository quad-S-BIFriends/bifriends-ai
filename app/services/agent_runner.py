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

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
import base64

logger = logging.getLogger(__name__)

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

# Gemini 2.5 thinking 모델이 function_call 이벤트에 system instruction을 텍스트로 포함하는 버그 대응.
# leo_dynamic.txt 첫 줄과 일치하는 마커로 에코 감지.
_SYS_ECHO_MARKER = "# 지금 대화 중인 아이 정보"


def _clean_model_text(text: str) -> str:
    """system instruction 에코가 포함된 텍스트에서 실제 답변만 추출."""
    if not text or _SYS_ECHO_MARKER not in text:
        return text
    contaminated = text[text.find(_SYS_ECHO_MARKER):]
    for p in reversed(contaminated.split("\n\n")):
        p = p.strip()
        if not p:
            continue
        if p[0] in "#①②③④▶-" or p.startswith("수학을") or p.startswith("예:"):
            continue
        if len(p) > 3:
            return p
    return ""


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
        try:
            concepts_raw = await be_client.get_math_concepts(req.member_id)
            concepts = concepts_raw.get("concepts", [])
        except Exception:
            logger.exception("_ensure_session: get_math_concepts 실패 (member_id=%s)", req.member_id)
            concepts = []

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
        _fallback_text = ""  # is_final_response 텍스트가 비면 여기서 가져옴

        try:
            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=req.session_id,
                new_message=message,
                state_delta=reset_delta,
            ):
                if not (event.content and event.content.parts):
                    continue

                # function_call 이벤트는 fallback에서 제외 (system instruction 에코가 텍스트로 섞이는 버그 방어)
                has_fc = any(getattr(p, "function_call", None) for p in event.content.parts)

                # model 이벤트의 텍스트를 fallback으로 수집 (function_call 이벤트 제외)
                if not has_fc and getattr(event.content, "role", None) == "model":
                    candidate = _clean_model_text("".join(
                        p.text for p in event.content.parts if getattr(p, "text", None)
                    ))
                    if candidate:
                        _fallback_text = candidate

                # is_final_response를 선호하되, 텍스트가 없으면 폴백에서 채운다
                if event.is_final_response():
                    candidate = _clean_model_text("".join(
                        p.text for p in event.content.parts if getattr(p, "text", None)
                    ))
                    if candidate:
                        final_text = candidate
        except Exception:
            logger.exception("run_async 실패: member_id=%s session_id=%s", req.member_id, req.session_id)

        if not final_text:
            final_text = _fallback_text
        if not final_text:
            final_text = "레오가 잠깐 생각 중이야! 😊 다시 한번 말해줄래?"

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
        _fallback_text = ""

        try:
            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=req.session_id,
                new_message=message,
                state_delta=reset_delta,
            ):
                if not (event.content and event.content.parts):
                    continue

                has_fc = False
                for part in event.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and getattr(fc, "name", None):
                        has_fc = True
                        trajectory.tool_calls.append(
                            ToolCallRecord(name=fc.name, args=dict(fc.args or {}))
                        )

                if not has_fc and getattr(event.content, "role", None) == "model":
                    candidate = _clean_model_text("".join(
                        p.text for p in event.content.parts if getattr(p, "text", None)
                    ))
                    if candidate:
                        _fallback_text = candidate

                if event.is_final_response():
                    candidate = _clean_model_text("".join(
                        p.text for p in event.content.parts if getattr(p, "text", None)
                    ))
                    if candidate:
                        final_text = candidate
        except Exception:
            logger.exception("run_async 실패 (trajectory): member_id=%s session_id=%s", req.member_id, req.session_id)

        if not final_text:
            final_text = _fallback_text
        if not final_text:
            final_text = "레오가 잠깐 생각 중이야! 😊 다시 한번 말해줄래?"

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
 
    async def _generate_one_image(self, parts: list, cfg) -> str | None:
        """이미지 모델 1회 호출 → base64. 실패(빈 응답/차단/예외) 시 None."""
        from app.core.config import settings
        try:
            resp = await self._genai.aio.models.generate_content(
                model=settings.model_image,
                contents=[types.Content(role="user", parts=parts)],
                config=cfg,
            )
            return self._extract_image_b64(resp)
        except Exception:
            logger.exception("EMO 이미지 1컷 생성 실패")
            return None

    async def generate_emo_images(
        self,
        *,
        anchor_instruction: str,
        prompts: list[str],
        gender: str,
        strategy: str = "parallel",
    ) -> list[str | None]:
        """
        step3 컷 이미지를 생성 → base64 리스트 반환.

        모든 컷은 앵커 이미지(boy/girl)를 동봉해 캐릭터 외형을 고정한다. 1:1 강제.
        실패(빈 응답/차단) 시 해당 컷은 None → 호출부(content_builder)가 폴백 처리.

        strategy (속도 vs 컷 간 일관성 트레이드오프):
          - "parallel"  : 모든 컷을 앵커만 참조해 동시 생성 (가장 빠름·캐릭터 정체성 일관성 최고). 기본값.
          - "hybrid"    : 1컷 먼저 생성 → 나머지 컷은 1컷을 공통 참조로 병렬 (절충).
          - "sequential": 컷을 순차 생성, 각 컷이 직전 컷을 참조 (인접 컷 연속성↑·드리프트 누적·가장 느림).

        프로덕션 동작을 바꾸려면 호출부에서 strategy를 넘기거나 이 기본값을 변경한다.
        (scripts/emo_image_bench.py 로 세 전략의 레이턴시·이미지를 직접 비교할 수 있다.)
        """
        anchor_path = _ANCHOR_PATH[gender]
        anchor_part = types.Part.from_bytes(
            data=anchor_path.read_bytes(), mime_type="image/png"
        )
        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="1:1"),
        )

        if not prompts:
            return []

        def _img_part(b64: str):
            return types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/png")

        # ── parallel: 모든 컷이 앵커만 참조, 한 번에 동시 생성 ──
        if strategy == "parallel":
            async def gen(prompt: str):
                parts = [types.Part(text=anchor_instruction), anchor_part, types.Part(text=prompt)]
                return await self._generate_one_image(parts, cfg)
            return list(await asyncio.gather(*(gen(p) for p in prompts)))

        # ── hybrid: 1컷 먼저 → 나머지는 1컷을 공통 참조로 병렬 ──
        if strategy == "hybrid":
            first_parts = [types.Part(text=anchor_instruction), anchor_part, types.Part(text=prompts[0])]
            first_b64 = await self._generate_one_image(first_parts, cfg)
            if len(prompts) == 1:
                return [first_b64]
            prefix: list = []
            if first_b64 is not None:
                prefix.append(_img_part(first_b64))  # 1컷을 공통 참조로
            prefix.append(anchor_part)

            async def gen_rest(prompt: str):
                return await self._generate_one_image(prefix + [types.Part(text=prompt)], cfg)
            rest = await asyncio.gather(*(gen_rest(p) for p in prompts[1:]))
            return [first_b64, *rest]

        # ── sequential (기본): 각 컷이 직전 컷을 참조해 순차 생성 ──
        results: list[str | None] = []
        prev_image_part = None
        for i, prompt in enumerate(prompts):
            parts: list = []
            if i == 0:
                parts.append(types.Part(text=anchor_instruction))
                parts.append(anchor_part)
            else:
                if prev_image_part is not None:
                    parts.append(prev_image_part)  # 직전 컷 참조 (드리프트 방지)
                parts.append(anchor_part)  # 앵커도 계속 동봉(외형 고정 강화)
            parts.append(types.Part(text=prompt))

            b64 = await self._generate_one_image(parts, cfg)
            results.append(b64)
            prev_image_part = _img_part(b64) if b64 is not None else None

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