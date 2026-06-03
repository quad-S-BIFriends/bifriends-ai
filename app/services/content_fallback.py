"""
폴백 데이터.

1) STEP12_FALLBACK_URL: 감정별 step1·2 고정 이미지 URL (정상 생성 시에도 step1·2는 이걸 재사용).
2) STEP3_FALLBACK_URL: 감정별 step3 3컷 고정 이미지 URL (실시간 생성 안 함).
3) FALLBACK_TEXT: AI 생성 실패 시 통째로 내보낼 감정별 완성 시나리오 텍스트.

실제 URL은 _fallback_urls.FALLBACK_URLS 에 분리 (BE가 Firebase Storage 업로드 후 발급).
URL마다 token 쿼리 파라미터가 달라 규칙 조립 불가 -> 한글 감정명 키 딕셔너리를 통째로 보관.
"""

from app.schemas.content import Emotion
from app.services._fallback_urls import FALLBACK_URLS

# 감정명 별칭: enum.value 가 한글이든 영문 슬러그든 한글 키(FALLBACK_URLS)로 정규화.
_SLUG_TO_KO = {
    "joy": "기쁨", "sad": "속상함", "shy": "부끄러움",
    "angry": "화남", "disappointed": "실망", "grateful": "고마움",
}


def _ko_key(emotion: Emotion) -> str:
    v = emotion.value
    return v if v in FALLBACK_URLS else _SLUG_TO_KO[v]


STEP12_FALLBACK_URL: dict[Emotion, dict[str, str]] = {
    e: {"step1": FALLBACK_URLS[_ko_key(e)]["step1"],
        "step2": FALLBACK_URLS[_ko_key(e)]["step2"]}
    for e in Emotion
}

STEP3_FALLBACK_URL: dict[Emotion, list[str]] = {
    e: [FALLBACK_URLS[_ko_key(e)]["step3-1"],
        FALLBACK_URLS[_ko_key(e)]["step3-2"],
        FALLBACK_URLS[_ko_key(e)]["step3-3"]]
    for e in Emotion
}


def get_step12_urls(emotion: Emotion) -> dict[str, str]:
    return STEP12_FALLBACK_URL[emotion]


def get_step3_fallback_urls(emotion: Emotion) -> list[str]:
    return STEP3_FALLBACK_URL[emotion]


def get_fallback_urls_map() -> dict[str, dict[str, str]]:
    """BE가 요청 body로 넘기는 fallback_urls 와 동일 구조(한글 키)를 그대로 반환."""
    return FALLBACK_URLS


# ---------------------------------------------------------------------------
# 전체 폴백 시나리오 (AI 생성 실패 시 통째로 반환).
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_FALLBACK_JSON = _Path(__file__).parent.parent / "data" / "fallback_scenarios.json"
_FALLBACK_RAW: dict = _json.loads(_FALLBACK_JSON.read_text(encoding="utf-8"))
FALLBACK_TEXT: dict[str, dict] = {
    k: v for k, v in _FALLBACK_RAW.items() if not k.startswith("_")
}


def get_fallback_text(emotion: Emotion) -> dict:
    """폴백 텍스트 반환. 해당 감정이 아직 JSON에 없으면 화남(완성본)으로 안전 대체."""
    return FALLBACK_TEXT.get(emotion.value, FALLBACK_TEXT["화남"])