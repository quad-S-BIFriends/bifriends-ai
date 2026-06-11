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

import logging

from google.adk.tools import ToolContext

from app.schemas.chat import StepCTA
from app.services.be_client import be_client

logger = logging.getLogger(__name__)

_NAVIGABLE = ("AVAILABLE", "IN_PROGRESS", "COMPLETED")

STATE_MEMBER_ID = "member_id"
STATE_MATH_CONCEPTS = "math_concepts"
STATE_MATH_CTA = "math_cta"


_OUT_OF_CURRICULUM_SENTINEL = "모름"


def _build_math_cta(data: dict) -> StepCTA | None:
    """BE 원본(data)으로 CTA를 결정론적으로 조립. NOT_FOUND 또는 stepId 없으면 None."""
    status = data.get("lessonStatus")

    if status in _NAVIGABLE:
        step_id = data.get("stepId")
        if step_id is None:
            return None
        return StepCTA(
            label="지금 바로 수학 연습해볼까?",
            step_id=step_id,
            cycle_number=1,
        )

    if status == "LOCKED":
        step_id = data.get("currentAvailableStepId")
        if step_id is None:
            return None
        return StepCTA(
            label="지금 하던 공부 계속하기",
            step_id=step_id,
            cycle_number=1,
        )

    # NOT_FOUND
    return None


async def math_help(concept: str, tool_context: ToolContext) -> dict:
    """
    아이가 특정 수학 개념을 언급하며 어렵다고 하거나 학습 도움을 요청할 때 호출한다.

    언제 호출하는가:
      - 개념 이름이 명확할 때: "곱셈이 어려워", "분수 모르겠어", "나눗셈 알려줘"
      - 배우고 있다는 맥락 + 어려움: "곱셈 나가고 있는데 어려워", "지금 분수 배우는데 모르겠어"
      - 직접 도움 요청: "수학 문제 풀고 싶어", "수학 공부 도와줘"

    호출하지 않는 경우:
      - 개념 언급 없이 막연히 어렵다고만 할 때: "수학이 어려워", "수학 싫어"
        → 먼저 "어떤 부분이 어려워? 요즘 뭐 배우고 있어?"처럼 뭐가 어려운지 물어본 뒤 개념을 확인하고 호출.
      - "수학 문제집 풀기 할 일 추가해줘" → create_todo 사용.
      - "수학 시험 봤어", "오늘 수학 숙제 있어" 같은 단순 일상 언급 → 도구 없이 공감 대화.

    Args:
        concept: 아이가 묻는 수학 개념. 반드시 세션 state의 math_concepts_text에
                 나열된 concept 문자열 중 하나를 정확히 그대로 넣어야 한다.
                 (예: "받아올림/내림 없는 세 자리 수 덧셈과 뺄셈")
                 목록에 딱 맞는 항목이 없으면 가장 가까운 것을 고른다.
                 커리큘럼 밖이거나 전혀 모르겠으면 "모름"을 넣는다.

    Returns (말풍선 텍스트를 만들 때 참고할 힌트):
        - lesson_status: AVAILABLE | IN_PROGRESS | COMPLETED → 해당 step으로 이동 가능
                         LOCKED    → 아직 잠긴 단계, 현재 가능한 step으로 안내
                         NOT_FOUND → 커리큘럼 밖, in_chat_practice=True로 직접 연습문제 출제
        - in_chat_practice: True면 채팅 안에서 쉬운 연습문제 1개를 직접 내야 함
        - step_title: 안내에 쓸 step 이름 (없으면 None)
        - locked_concept: LOCKED일 때 아이가 물어본 개념명 — "곧 배우게 될 거야"라고 말해줄 때 사용
    """
    member_id = tool_context.state.get(STATE_MEMBER_ID)

    # "모름" sentinel → 커리큘럼 밖, 채팅 내 연습문제
    if concept == _OUT_OF_CURRICULUM_SENTINEL:
        tool_context.state[STATE_MATH_CTA] = None
        return {
            "matched_concept": None,
            "lesson_status": "NOT_FOUND",
            "step_title": None,
            "locked_concept": None,
            "in_chat_practice": True,
        }

    # BE 호출 — BE가 exact match 우선, 이후 contains 검색으로 처리
    try:
        data = await be_client.get_math_lesson_status(member_id, concept)
    except Exception:
        logger.exception("math_help: BE 호출 실패 (member_id=%s, concept=%s)", member_id, concept)
        tool_context.state[STATE_MATH_CTA] = None
        return {
            "matched_concept": concept,
            "lesson_status": "NOT_FOUND",
            "step_title": None,
            "locked_concept": None,
            "in_chat_practice": True,
        }
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