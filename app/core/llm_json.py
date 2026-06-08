"""
LLM JSON 출력 가드레일 — 코드펜스 제거 + 파싱 (프로젝트 공통).

LLM은 JSON을 요청해도 ```json ... ``` / ``` ... ``` 마크다운 펜스로 감싸
보내는 경우가 잦다(특히 response_mime_type을 강제하지 않을 때). 파싱 전에
이 껍데기를 벗겨내야 한다. content_builder·report_builder가 공통으로 쓴다.
"""
from __future__ import annotations

import json


def strip_code_fence(text: str) -> str:
    """LLM 출력에서 ```json ... ``` / ``` ... ``` 펜스를 벗겨 알맹이만 반환.

    뒤에 개행·공백이 붙어도 견디도록 위치 기반(split/strip)으로 제거한다.
    """
    s = text.strip()
    if s.startswith("```"):
        # ```json ... ``` 또는 ``` ... ```
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    return s.strip().strip("`").strip()


def parse_llm_json(raw: str) -> dict:
    """펜스 제거 후 JSON 파싱. 실패 시 json.JSONDecodeError를 던진다(호출부가 폴백)."""
    return json.loads(strip_code_fence(raw))
