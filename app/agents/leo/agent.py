"""
Leo 에이전트 정의 (LlmAgent).

- 시스템 프롬프트: app/prompts/leo_agent.txt
- 도구: math_help, korean_help, create_todo
  (chat / daily_question은 도구 없이 LLM이 직접 응답)
- 모델: Gemini 2.0 Flash

instruction에는 정적 프롬프트 + 동적 컨텍스트(닉네임/학년/concept 목록)를
세션 state 기반으로 주입한다. ADK는 instruction에 {state_key} 치환을 지원한다.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from app.agents.leo.tools.math_tool import math_help
from app.agents.leo.tools.korean_tool import korean_help
from app.agents.leo.tools.todo_tool import create_todo

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "leo_agent.txt"


def _load_instruction() -> str:
    base = _PROMPT_PATH.read_text(encoding="utf-8")
    # 세션 state에서 주입되는 동적 컨텍스트.
    # {key} 형식은 ADK가 InstructionProvider 없이도 state 값으로 치환해줌.
    dynamic = (
        "\n\n# 지금 대화 중인 아이 정보\n"
        "- 닉네임: {nickname}\n"
        "- 학년: {grade}학년\n"
        "- 이 아이가 배우는 수학 개념 목록(concept): {math_concepts_text}\n"
        "  → 수학 도움을 줄 땐 반드시 이 목록 안의 concept 문자열을 그대로 골라 math_help에 넘길 것.\n"
    )
    return base + dynamic


leo_agent = LlmAgent(
    name="leo",
    model="gemini-2.0-flash",
    instruction=_load_instruction(),
    tools=[math_help, korean_help, create_todo],
)