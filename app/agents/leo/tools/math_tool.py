"""
수학 학습 도움 도구 (math_help):
  - 학년별 concept 목록은 세션 첫 턴에 agent_runner가 받아 state["math_concepts"]에 캐싱.
  - LLM은 그 목록(concept + step_title) 중 아이 질문에 맞는 concept 문자열 하나를 골라 넘긴다.
    (자유 생성 금지 — DB의 정확한 concept 문자열과 일치해야 BE 조회가 됨)
  - 도구는 넘어온 concept이 실제 목록에 있는지 방어 검증 후 BE lesson-status 조회.
  - CTA는 도구가 완성해 state에 저장. LLM은 말풍선 텍스트만 생성.

분기 (lessonStatus):
  AVAILABLE / IN_PROGRESS / COMPLETED → 해당 stepId 이동 CTA
  LOCKED                              → currentAvailableStepId 이동 CTA
                                        (+ 잠긴 개념 이름과 이론도 힌트로 줘서 "곧 배워" 톤)
  NOT_FOUND / 목록에 없음              → CTA 없음, 채팅 안에서 LLM이 연습문제 1개

state 키:
  state["member_id"]     : int          (agent_runner가 세션 시작 시 주입)
  state["math_concepts"] : list[dict]   (세션 첫 턴 캐싱; 각 항목 concept/stepId/stepTitle)
  state["math_cta"]      : dict | None   (도구가 저장 → agent_runner가 응답에 사용)
"""
from __future__ import annotations

from google.adk.tools import ToolContext

from app.schemas.chat import StepCTA
from app.services.be_client import be_client

_NAVIGABLE = ("AVAILABLE", "IN_PROGRESS", "COMPLETED")

STATE_MEMBER_ID = "member_id"
STATE_MATH_CONCEPTS = "math_concepts"
STATE_MATH_CTA = "math_cta"


def _build_math_cta(data: dict) -> StepCTA | None:
    """BE 원본(data)으로 CTA를 결정론적으로 조립. NOT_FOUND면 None."""
    status = data.get("lessonStatus")
    if status in _NAVIGABLE:
        return StepCTA(
            label="지금 바로 연습해볼까?",
            step_id=data["stepId"],
            cycle_number=1,
        )
    if status == "LOCKED":
        return StepCTA(
            label="진행하던 수업 계속해볼게!",
            step_id=data["currentAvailableStepId"],
            cycle_number=1,
        )
    return None  # NOT_FOUND


def _concept_in_curriculum(concept: str, concepts: list[dict]) -> bool:
    """LLM이 고른 concept이 실제 학년 커리큘럼 목록에 있는지 검증."""
    return any(c.get("concept") == concept for c in (concepts or []))


async def math_help(concept: str, tool_context: ToolContext) -> dict:
    """
    아이가 수학을 도와달라고 할 때 사용하는 도구.

    concept은 반드시 시스템이 알려준 '이번 학년 수학 개념 목록'에 있는 문자열
    그대로여야 한다. 목록에 맞는 게 없으면, 가장 가까운 것을 임의로 만들지 말고
    아이가 말한 표현을 그대로 넣어라(도구가 '커리큘럼 밖'으로 처리한다).

    Args:
        concept: 학년 개념 목록에서 고른 정확한 개념 문자열.

    Returns:
        말풍선 텍스트 생성에 쓸 힌트.
        - lesson_status: AVAILABLE | IN_PROGRESS | COMPLETED | LOCKED | NOT_FOUND
        - asked_concept: 아이가 물어본 개념(LOCKED일 때 "곧 배워" 안내에 사용)
        - available_step_title: 지금 할 수 있는 스텝 이름(LOCKED일 때)
        - step_title: 이동할 스텝 이름(정상일 때)
        - in_chat_practice: True면 채팅 안에서 쉬운 연습문제 1개를 직접 내야 함
    """
    member_id = tool_context.state.get(STATE_MEMBER_ID)
    concepts = tool_context.state.get(STATE_MATH_CONCEPTS) or []

    # 1) LLM이 목록 밖 개념을 골랐으면 BE 호출 없이 커리큘럼 밖 처리
    if not _concept_in_curriculum(concept, concepts):
        tool_context.state[STATE_MATH_CTA] = None
        return {
            "asked_concept": concept,
            "lesson_status": "NOT_FOUND",
            "in_chat_practice": True,
        }

    # 2) 정확한 concept으로 BE lesson-status 조회
    data = await be_client.get_math_lesson_status(member_id, concept)
    status = data.get("lessonStatus")

    # 3) CTA 완성해 state에 저장 (LLM을 거치지 않음)
    cta = _build_math_cta(data)
    tool_context.state[STATE_MATH_CTA] = cta.model_dump() if cta else None

    if status == "NOT_FOUND":
        return {
            "asked_concept": concept,
            "lesson_status": status,
            "in_chat_practice": True,
        }

    if status == "LOCKED":
        # 잠김: "곧 배워" 톤 + 지금 할 수 있는 곳으로 유도
        return {
            "asked_concept": concept,
            "lesson_status": status,
            "available_step_title": data.get("currentAvailableStepTitle"),
            "in_chat_practice": False,
        }

    # AVAILABLE / IN_PROGRESS / COMPLETED
    return {
        "asked_concept": concept,
        "lesson_status": status,
        "step_title": data.get("stepTitle"),
        "in_chat_practice": False,
    }