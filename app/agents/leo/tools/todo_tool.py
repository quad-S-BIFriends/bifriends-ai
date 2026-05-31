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
    아이가 만들고 싶어 하는 할 일을 등록하는 도구.

    Args:
        titles: 등록할 할 일 제목 목록. 아이가 여러 개를 말하면 각각 분리해서 넣을 것.
                예: ["수학 문제 3개 풀기", "책 읽기"]

    Returns:
        - created_count: 실제로 등록된 개수
        - skipped: 한도 초과로 등록하지 못한 개수
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