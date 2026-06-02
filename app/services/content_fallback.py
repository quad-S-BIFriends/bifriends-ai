"""
폴백 데이터.

1) STEP12_FALLBACK_URL: 감정별 step1·2 고정 이미지 URL (정상 생성 시에도 step1·2는 이걸 재사용).
   - URL은 BE가 폴백 12장을 GCS 업로드 후 발급. 아래는 자리표시자.
   - 운영 전 BE가 준 실제 URL로 교체 (또는 .env/config 주입으로 분리 가능).

2) FALLBACK_SCENARIOS: AI 생성 실패 시 통째로 내보낼 감정별 완성 시나리오(텍스트+이미지 URL 전부 포함).
   - 생성 규격 문서의 6개 샘플(기쁨~고마움)을 채워넣는다. 여기서는 구조만 잡고 실제 텍스트는 추후 채움.
   - step3 이미지도 폴백은 고정 URL (실시간 생성 안 함).
"""

from app.schemas.content import Emotion

# 자리표시자 — BE가 GCS 업로드 후 발급한 URL로 교체
_BASE = "https://storage.googleapis.com/bifriends-sel-fallback"

STEP12_FALLBACK_URL: dict[Emotion, dict[str, str]] = {
    Emotion.JOY: {
        "step1": f"{_BASE}/joy/step1.png",
        "step2": f"{_BASE}/joy/step2.png",
    },
    Emotion.SAD: {
        "step1": f"{_BASE}/sad/step1.png",
        "step2": f"{_BASE}/sad/step2.png",
    },
    Emotion.SHY: {
        "step1": f"{_BASE}/shy/step1.png",
        "step2": f"{_BASE}/shy/step2.png",
    },
    Emotion.ANGRY: {
        "step1": f"{_BASE}/angry/step1.png",
        "step2": f"{_BASE}/angry/step2.png",
    },
    Emotion.DISAPPOINTED: {
        "step1": f"{_BASE}/disappointed/step1.png",
        "step2": f"{_BASE}/disappointed/step2.png",
    },
    Emotion.GRATEFUL: {
        "step1": f"{_BASE}/grateful/step1.png",
        "step2": f"{_BASE}/grateful/step2.png",
    },
}

# step3 폴백 컷 이미지 URL (전체 폴백 시나리오에서 사용)
STEP3_FALLBACK_URL: dict[Emotion, list[str]] = {
    e: [f"{_BASE}/{slug}/step3_1.png",
        f"{_BASE}/{slug}/step3_2.png",
        f"{_BASE}/{slug}/step3_3.png"]
    for e, slug in [
        (Emotion.JOY, "joy"), (Emotion.SAD, "sad"), (Emotion.SHY, "shy"),
        (Emotion.ANGRY, "angry"), (Emotion.DISAPPOINTED, "disappointed"),
        (Emotion.GRATEFUL, "grateful"),
    ]
}


def get_step12_urls(emotion: Emotion) -> dict[str, str]:
    return STEP12_FALLBACK_URL[emotion]


def get_step3_fallback_urls(emotion: Emotion) -> list[str]:
    return STEP3_FALLBACK_URL[emotion]


# ---------------------------------------------------------------------------
# 전체 폴백 시나리오 (AI 생성 실패 시 통째로 반환).
# 콘텐츠는 app/data/fallback_scenarios.json 에 분리 (기획이 코드 안 건드리고 수정).
# JSON 키는 LLM 텍스트 출력(content_scenario.txt 출력 양식)과 동일 구조.
# step3 이미지는 실시간 생성 안 하고 STEP3_FALLBACK_URL을 쓴다.
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_FALLBACK_JSON = _Path(__file__).parent.parent / "data" / "fallback_scenarios.json"
_FALLBACK_RAW: dict = _json.loads(_FALLBACK_JSON.read_text(encoding="utf-8"))
# "_TODO" 같은 메타 키 제외, 감정 키만 보관
FALLBACK_TEXT: dict[str, dict] = {
    k: v for k, v in _FALLBACK_RAW.items() if not k.startswith("_")
}


def get_fallback_text(emotion: Emotion) -> dict:
    """폴백 텍스트 반환. 해당 감정이 아직 JSON에 없으면 화남(완성본)으로 안전 대체."""
    return FALLBACK_TEXT.get(emotion.value, FALLBACK_TEXT["화남"])