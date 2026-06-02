"""
주간 안전 신호 분석.

설계 원칙:
  - 점수/판정은 순수 파이썬 (Gemini 호출 없음). 키워드는 '확인이 필요한 후보'를
    걸러내는 1차 필터이며, 그 자체로 단정하지 않는다.
  - 단, 자해·자살 등 고위험 표현은 점수와 무관하게 코드에서 즉시 RED로 강제한다
    (deterministic safety floor — LLM 판단에 맡기지 않는 안전망).
  - GREEN: Gemini 호출 없이 고정 문구.
  - YELLOW/RED: Gemini가 맥락을 평가해 정말 주의가 필요한지 판단 후 요약.

점수 규칙 (컨텍스트 문서 기반):
  동일 메시지 4회 이상 반복      → +2
  부정 감정 3회 이상            → +2
  감정 고립 표현 (1회+)         → +3
  욕설/폭력 키워드 (1회+)       → +5
판정:
  0~3 GREEN / 4~7 YELLOW / 8+ RED
  + 고위험(자해/자살/심각한 위해) 표현이 1회라도 있으면 → 무조건 RED
"""
from __future__ import annotations

from collections import Counter

# ──────────────────────────────────────────────────────────────
# 고위험 표현: 점수와 무관하게 무조건 RED로 강제 (안전 최우선)
# 자해/자살 암시, 심각한 위해 신호. 오탐(과검출)을 감수하더라도 놓치지 않는다.
# ──────────────────────────────────────────────────────────────
_CRITICAL = (
    "죽고 싶", "죽고싶", "죽을래", "죽어버", "죽어 버",
    "자살", "목숨", "목매", "목 매",
    "사라지고 싶", "사라지고싶", "없어지고 싶", "없어지고싶",
    "살기 싫", "살기싫", "살고 싶지 않", "태어나지 말",
    "내 손목", "손목 긋", "손목긋", "칼로", "약 먹고", "뛰어내리",
    "다 끝내고 싶", "죽는 게 나",
)

# ──────────────────────────────────────────────────────────────
# 점수용 키워드 사전 (운영하며 지속 보강)
# ──────────────────────────────────────────────────────────────
_NEGATIVE_EMOTION = (
    "싫어", "하기 싫어", "짜증", "미워", "화나", "화가", "귀찮", "지겨",
    "재미없", "최악", "힘들어", "지쳐", "포기",
)

_ISOLATION = (
    "외로워", "외롭", "슬퍼", "슬프", "혼자", "아무도", "친구 없", "친구가 없",
    "끼워주지", "안 놀아", "따돌", "왕따", "소외", "버림", "쓸모없",
)

# 욕설/폭력 (피해 호소 포함). 자해/자살은 _CRITICAL에서 별도 처리.
_PROFANITY_VIOLENCE = (
    "때리", "때려", "맞았", "맞아", "괴롭", "협박", "폭력",
    "씨발", "시발", "ㅅㅂ", "꺼져", "닥쳐", "병신", "ㅂㅅ", "지랄", "개새",
)

_GREEN_FIXED = "이번 주는 레오와 편안하게 잘 지냈어요. 특별히 걱정할 만한 신호는 보이지 않았답니다. 😊"

# 토큰 폭주 방지: Gemini에 넘길 최대 메시지 수 (최근 우선)
MAX_MESSAGES_FOR_LLM = 60


def _count_keyword_hits(messages: list[str], keywords: tuple[str, ...]) -> int:
    total = 0
    for msg in messages:
        for kw in keywords:
            if kw in msg:
                total += 1
    return total


def has_critical_signal(messages: list[str]) -> bool:
    """자해/자살 등 고위험 표현이 1회라도 있는지."""
    return _count_keyword_hits(messages, _CRITICAL) >= 1


def compute_score(messages: list[str]) -> int:
    """user 메시지 리스트 → 안전 점수. 메시지 없으면 0."""
    if not messages:
        return 0

    score = 0

    counts = Counter(m.strip() for m in messages if m.strip())
    if any(c >= 4 for c in counts.values()):
        score += 2

    if _count_keyword_hits(messages, _NEGATIVE_EMOTION) >= 3:
        score += 2

    if _count_keyword_hits(messages, _ISOLATION) >= 1:
        score += 3

    if _count_keyword_hits(messages, _PROFANITY_VIOLENCE) >= 1:
        score += 5

    return score


def classify(score: int, messages: list[str] | None = None) -> str:
    """
    점수 → GREEN/YELLOW/RED.
    고위험 표현이 있으면 점수와 무관하게 무조건 RED (안전 강제).
    """
    if messages is not None and has_critical_signal(messages):
        return "RED"
    if score <= 3:
        return "GREEN"
    if score <= 7:
        return "YELLOW"
    return "RED"


def green_summary() -> str:
    return _GREEN_FIXED