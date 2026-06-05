"""
할 일 등록 도구 (create_todo).

- 아이가 여러 할 일을 한꺼번에 말하면 각각 따로 등록 (titles 리스트).
- Agent 생성 한도: 하루 2개 (시스템 3 + Agent 2 = 5). 한도 초과분은 등록 시도하지 않음.
- MVP: estimatedTimeSec 미사용 (BE 명세상 선택 필드라 생략).

선택한 방식:
  도구가 BE 호출 → 등록 결과(todos_created)를 state에 저장.
  LLM에는 등록 요약 힌트만 반환.

state 키:
  state["member_id"]     : int
  state["todos_created"] : list[{title, assigned_date}]  (이 도구가 저장)
"""
from __future__ import annotations

from google.adk.tools import ToolContext

from app.services.be_client import be_client

STATE_MEMBER_ID = "member_id"
STATE_TODOS_CREATED = "todos_created"

# Agent가 한 번에 만들 수 있는 최대 개수
_MAX_AGENT_TODOS = 2


async def create_todo(titles: list[str], tool_context: ToolContext) -> dict:
    """
    아이가 할 일 등록을 명시적으로 요청할 때 호출한다.

    언제 호출하는가:
      - "~추가해줘", "~할 일 만들어줘", "~등록해줘"처럼 등록 의도가 명확할 때.
      - 여러 개를 한꺼번에 말하면 titles 리스트에 각각 분리해서 담는다.
        예: "수학 문제 3개 풀기랑 책 읽기 추가해줘" → ["수학 문제 3개 풀기", "책 읽기"]

    호출하지 않는 경우:
      - "수학 숙제 있어", "오늘 책 읽어야 해"처럼 단순히 언급만 했을 때.
        "추가해줘", "만들어줘" 같은 명시적 등록 요청이 없으면 호출하지 않는다.
      - 수학·국어 학습 안내 요청 → math_help / korean_help 사용.

    Args:
        titles: 등록할 할 일 제목 목록. 아이의 말을 명사구로 정리해서 담는다.
                예: ["수학 문제 3개 풀기", "책 읽기 30분"]
                한 번에 최대 2개까지만 등록된다 (초과분은 skipped로 반환).

    Returns:
        - created_count: 실제로 등록된 개수
        - skipped: 한도 초과로 등록하지 못한 개수 (0이면 전부 등록됨)
    """
    member_id = tool_context.state.get(STATE_MEMBER_ID)

    to_create = titles[:_MAX_AGENT_TODOS]
    skipped = len(titles) - len(to_create)

    created: list[dict] = []
    for title in to_create:
        resp = await be_client.create_todo(member_id, title)
        created.append({
            "title": resp.get("title", title),
            "assigned_date": resp.get("assignedDate"),
        })

    tool_context.state[STATE_TODOS_CREATED] = created

    return {
        "created_count": len(created),
        "skipped": skipped,
    }