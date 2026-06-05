"""
국어 학습 도움 도구 (korean_help).

수학과 달리 분기/concept 매칭이 없다.
BE의 '현재 국어 lesson' 하나(IN_PROGRESS → AVAILABLE → 첫 스텝 우선순위)를 받아
무조건 그 lesson(과목 페이지)으로 이동하는 CTA(navigate_to_subject)를 만든다.

선택한 방식:
  도구가 BE 호출 → CTA 완성 → tool_context.state에 저장.
  LLM에는 말풍선 텍스트용 힌트만 반환.

state 저장 키:
  state["korean_cta"]: SubjectCTA(dict)  ← agent_runner가 최종 응답에 사용
"""
from __future__ import annotations

from google.adk.tools import ToolContext

from app.schemas.chat import SubjectCTA
from app.services.be_client import be_client

STATE_KOREAN_CTA = "korean_cta"


async def korean_help(tool_context: ToolContext) -> dict:
    """
    아이가 국어 학습을 요청할 때 호출한다.

    언제 호출하는가:
      - "국어 도와줘", "국어 공부하고 싶어", "받아쓰기/독서/어휘 등 국어 관련 학습 요청".
      - 어떤 국어 개념이든 항상 현재 진행 중인 lesson 하나로 안내하므로 개념 인자가 없다.

    호출하지 않는 경우:
      - "국어 숙제 추가해줘" → create_todo 사용.
      - "국어 시험 어려웠어" 같은 단순 일상 언급 → 도구 없이 공감 대화.

    Returns (말풍선 텍스트를 만들 때 참고할 힌트):
        - step_title: 지금 진행할 국어 lesson 제목 (예: "낱말 익히기")
        - concept: 학습 개념 (예: "어휘")
    """
    member_id = tool_context.state.get("member_id")
    data = await be_client.get_korean_current_lesson(member_id)

    # 국어는 항상 navigate_to_subject CTA (과목 페이지 진입)
    cta = SubjectCTA(label="국어 공부하러 가볼까?")
    tool_context.state[STATE_KOREAN_CTA] = cta.model_dump()

    return {
        "step_title": data.get("stepTitle"),
        "concept": data.get("concept"),
    }