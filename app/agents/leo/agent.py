"""
Leo 에이전트 정의 (LlmAgent).

토큰/캐싱 구조:
  - static_instruction ← prompts/leo/ 디렉토리의 모듈 파일들을 이름순으로 합친 것
    (고정: 정체성·도메인별 규칙·안전·few-shot)
    · 프롬프트 맨 앞에 그대로 들어가고 {} 치환을 하지 않음 → few-shot에 안전.
    · 거의 안 바뀌므로 context caching 대상으로 적합.
  - instruction ← leo_dynamic.txt (동적: 닉네임·학년·concept 목록)
    · static 뒤에 붙고 {key}가 세션 state 값으로 자동 치환됨.

  프롬프트 모듈화:
    런타임은 단일 에이전트 그대로. 도메인별로 수정하기 쉽도록 프롬프트 "파일"만
    prompts/leo/ 아래로 쪼갰다. 파일명 숫자 prefix가 합쳐지는 순서를 정한다.
    (00_identity → 10_math → 20_korean → 30_vocabulary → 40_todo
     → 50_casual → 60_safety → 70_examples)
    새 도메인은 파일 하나 추가하면 자동으로 포함된다 (별도 코드 수정 불필요).

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
_STATIC_DIR = _PROMPTS_DIR / "leo"
_DYNAMIC_PATH = _PROMPTS_DIR / "leo_dynamic.txt"


def _load_static_prompt() -> str:
    """prompts/leo/*.txt 를 파일명 순으로 읽어 하나의 static instruction으로 합친다."""
    parts = [
        p.read_text(encoding="utf-8").strip()
        for p in sorted(_STATIC_DIR.glob("*.txt"))
    ]
    if not parts:
        raise RuntimeError(f"프롬프트 모듈을 찾을 수 없습니다: {_STATIC_DIR}")
    return "\n\n".join(parts)


# 프롬프트 캐싱 구조에 맞춰 static/dynamic 분리
_static_text = _load_static_prompt()
_dynamic_text = _DYNAMIC_PATH.read_text(encoding="utf-8")

leo_agent = LlmAgent(
    name="leo",
    model=settings.model_chat,
    static_instruction=_static_text,
    instruction=_dynamic_text,
    tools=[math_help, korean_help, create_todo],
)