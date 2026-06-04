"""
수학 학습 도움 도구 (math_help).

핵심: LLM이 concept을 자유 생성하면 DB의 실제 concept 문자열과 안 맞는다.
  (예: 아이 "세 자리 더하기" / DB "받아올림/내림 없는 세 자리 수 덧셈과 뺄셈")
  → 세션 첫 턴에 그 학년 concept 목록을 state["math_concepts"]에 캐싱해두고,
    LLM은 그 목록 중 하나의 정확한 concept 문자열을 골라 이 도구에 넘긴다.
  → 도구는 받은 concept이 목록에 실제로 있는지 한 번 더 검증한다.
선택한 방식: 
  도구가 BE 호출 → CTA를 완성 → tool_context.state에 저장.
  LLM에는 말풍선 텍스트용 힌트만 반환 (CTA는 LLM을 거치지 않음).

분기 (lessonStatus):
  AVAILABLE / IN_PROGRESS / COMPLETED → 해당 stepId 이동 CTA
  LOCKED      → currentAvailableStepId 이동 CTA + '곧 배워' 톤 힌트
  NOT_FOUND   → CTA 없음, 채팅 안에서 LLM이 연습문제 1개

concept이 캐싱된 목록에 아예 없으면(LLM이 잘못 골랐거나 학년 밖):
  → out_of_curriculum=True 로 NOT_FOUND와 동일하게 처리 (채팅 내 연습문제)

state 키:
  state["member_id"]      : int          (agent_runner가 세션 시작 시 주입)
  state["math_concepts"]  : list[dict]    (agent_runner가 세션 첫 턴에 캐싱)
  state["math_cta"]       : StepCTA(dict) | None  (이 도구가 저장)
"""
from __future__ import annotations

from google.adk.tools import ToolContext

from app.schemas.chat import StepCTA
from app.services.be_client import be_client

_NAVIGABLE = ("AVAILABLE", "IN_PROGRESS", "COMPLETED")

STATE_MEMBER_ID = "member_id"
STATE_MATH_CONCEPTS = "math_concepts"
STATE_MATH_CTA = "math_cta"


_OUT_OF_CURRICULUM_SENTINEL = "모름"


def _is_known_concept(concept: str, concepts: list[dict]) -> bool:
    """LLM이 고른 concept이 실제 캐싱된 목록에 있는지 검증. sentinel "모름"은 항상 False."""
    if concept == _OUT_OF_CURRICULUM_SENTINEL:
        return False
    return any(c.get("concept") == concept for c in concepts)


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
            label="지금 하던 공부 계속하기",
            step_id=data["currentAvailableStepId"],
            cycle_number=1,
        )

    # NOT_FOUND
    return None


async def math_help(concept: str, tool_context: ToolContext) -> dict:
    """
    아이가 수학을 도와달라고 할 때 사용하는 도구.

    Args:
        concept: 반드시 'math_concepts 목록에 있는 concept 문자열 그대로'를 넘길 것.
                 목록에 마땅한 게 없으면 가장 가까운 것을 넘기되,
                 도구가 목록에 없다고 판단하면 채팅 안 연습문제로 안내한다.

    Returns:
        말풍선 텍스트용 힌트.
        - matched_concept: 실제로 매칭된 concept (없으면 None)
        - lesson_status  : AVAILABLE | IN_PROGRESS | COMPLETED | LOCKED | NOT_FOUND
        - step_title     : 안내에 쓸 스텝 이름 (없으면 None)
        - locked_concept : LOCKED일 때 아이가 원래 물어본(잠긴) 개념 이름
        - in_chat_practice: True면 채팅 안에서 직접 쉬운 연습문제 1개를 내야 함
    """
    member_id = tool_context.state.get(STATE_MEMBER_ID)
    concepts = tool_context.state.get(STATE_MATH_CONCEPTS) or []

    # 1) LLM이 고른 concept이 실제 목록에 없으면 → 커리큘럼 밖, 채팅 내 연습문제
    if not _is_known_concept(concept, concepts):
        tool_context.state[STATE_MATH_CTA] = None
        return {
            "matched_concept": None,
            "lesson_status": "NOT_FOUND",
            "step_title": None,
            "locked_concept": None,
            "in_chat_practice": True,
        }

    # 2) 정확한 concept으로 BE 상태 조회
    data = await be_client.get_math_lesson_status(member_id, concept)
    status = data.get("lessonStatus")

    cta = _build_math_cta(data)
    tool_context.state[STATE_MATH_CTA] = cta.model_dump() if cta else None

    if status == "NOT_FOUND":
        return {
            "matched_concept": concept,
            "lesson_status": status,
            "step_title": None,
            "locked_concept": None,
            "in_chat_practice": True,
        }

    if status == "LOCKED":
        return {
            "matched_concept": concept,
            "lesson_status": status,
            "step_title": data.get("currentAvailableStepTitle"),
            "locked_concept": concept,  # 곧 배운다고 인정해줄 개념
            "in_chat_practice": False,
        }

    # AVAILABLE / IN_PROGRESS / COMPLETED
    return {
        "matched_concept": concept,
        "lesson_status": status,
        "step_title": data.get("stepTitle"),
        "locked_concept": None,
        "in_chat_practice": False,
    }