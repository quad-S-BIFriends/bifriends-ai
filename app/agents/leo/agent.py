"""
Leo 에이전트 정의 (LlmAgent).

토큰/캐싱 구조:
  - static_instruction ← leo_agent.txt (고정: 정체성·규칙·few-shot)
    · 프롬프트 맨 앞에 그대로 들어가고 {} 치환을 하지 않음 → few-shot에 안전.
    · 거의 안 바뀌므로 context caching 대상으로 적합.
  - instruction ← leo_dynamic.txt (동적: 닉네임·학년·concept 목록)
    · static 뒤에 붙고 {key}가 세션 state 값으로 자동 치환됨.

  실제 캐싱 활성화는 App 레벨 context_cache_config로 별도 설정.
  (이 구조는 캐싱을 켰을 때 고정/동적 경계가 맞아떨어지도록 미리 잡아둔 것)

도구: math_help, korean_help, create_todo
모델: Gemini 2.5 계열
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from app.agents.leo.tools.math_tool import math_help
from app.agents.leo.tools.korean_tool import korean_help
from app.agents.leo.tools.todo_tool import create_todo
from app.core.config import settings

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_STATIC_PATH = _PROMPTS_DIR / "leo_agent.txt"
_DYNAMIC_PATH = _PROMPTS_DIR / "leo_dynamic.txt"

# 프롬프트 캐싱 구조에 맞춰 static/dynamic 분리
_static_text = _STATIC_PATH.read_text(encoding="utf-8")  
_dynamic_text = _DYNAMIC_PATH.read_text(encoding="utf-8")

leo_agent = LlmAgent(
    name="leo",
    model=settings.model_chat,
    static_instruction=_static_text,
    instruction=_dynamic_text,
    tools=[math_help, korean_help, create_todo],
)