"""
주간 안전 신호 배치 라우터.

엔드포인트: POST /api/v1/ai/batch/weekly-safety
호출 주체: BE 스케줄러 (매주 금요일 저녁)

회원 처리 방식 (길 A로 확정):
  BE 스케줄러가 '이번 주 활동한 아이'를 알고 있고, 회원 한 명씩 이 엔드포인트를
  호출한다. AI는 한 명 분석만 책임진다. (활동 회원 목록 판단은 BE 영역)

흐름:
  1. BE에서 해당 아이의 이번 주 user 메시지 조회
  2. 키워드 카운팅 → 점수 → GREEN/YELLOW/RED 판정 (Gemini 없음)
  3. GREEN: 고정 문구 / YELLOW·RED: Gemini가 '정말 주의가 필요한지' 평가 후 요약
  4. BE에 weekly_safety_report 저장

가드레일:
  - 메시지 0개(활동 없는 주): Gemini 안 부르고 GREEN 고정
  - Gemini에 넘기는 메시지 수 제한(최근 우선)으로 토큰 폭주 방지
  - Gemini 실패 시 신호별 폴백 문구
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.batch import WeeklySafetyResult
from app.services import safety_analyzer
from app.services.agent_runner import agent_runner
from app.services.be_client import be_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batch", tags=["batch"])

_REASON_MODEL = "gemini-2.0-flash"

# '걱정거리를 찾아내라'가 아니라 '걱정할 게 있는지 확인하라'는 관점
_REASON_PROMPT = """너는 경계선 지능 아동의 보호자에게 주간 정서·관계 신호를 전하는 조력자야.
아래는 한 아이가 이번 주 AI 친구에게 보낸 메시지야.

먼저 이 대화에 정말로 주의가 필요한지 차분히 판단해.
- 가벼운 투정, 일시적인 짜증, 단순한 장난이라면 과장하지 말고 "크게 걱정할 수준은 아니"라고 솔직히 전해.
- 반복되는 외로움·소외·자기비하·위험 신호처럼 실제로 살펴볼 필요가 있으면, 무엇이 관찰됐는지 1~2문장으로 부드럽게 짚어줘.

규칙:
- 진단하거나 단정하지 마. ("우울증이에요" 같은 표현 금지)
- 관찰된 경향만 차분하게. 보호자를 불안하게 몰지 마.
- 따뜻하고 존중하는 보호자용 존댓말. 2~3문장 이내.
"""

_RED_TAIL = " 마음이 많이 힘들어 보이는 신호가 있어, 아이와 편안하게 이야기를 나눠보시거나 필요하면 전문가의 도움을 함께 고려해보시길 권해요."

# 자해/자살 등 고위험 신호 감지 시 보호자에게 전하는 강한 안내 (코드에서 강제)
_CRITICAL_NOTICE = (
    "이번 주 대화에서 아이가 스스로를 해치거나 매우 힘들어하는 표현이 보였어요. "
    "가능한 빨리 아이와 따뜻하게 이야기를 나눠보시고, 전문가(상담사·소아청소년과 등)의 "
    "도움을 함께 받아보시길 권해요. 위급하다고 느껴지면 자살예방상담전화 109로 연락하실 수 있어요."
)

# 신호별 Gemini 실패 폴백
_FALLBACK = {
    "YELLOW": "이번 주 대화에서 살펴보면 좋을 만한 정서 신호가 조금 있었어요. 아이와 가볍게 이야기 나눠보세요.",
    "RED": "이번 주 대화에서 주의가 필요한 신호가 있었어요. 아이와 차분히 이야기 나눠보시고, 필요하면 전문가의 도움을 고려해보세요.",
}


class WeeklySafetyBatchRequest(BaseModel):
    member_id: int
    week_start: str
    week_end: str


async def _build_reason_summary(
    signal: str, messages: list[str], is_critical: bool = False
) -> str:
    """
    GREEN은 고정 문구, YELLOW/RED만 Gemini로 맥락 평가.
    단 고위험(is_critical)이면 LLM 판단에 맡기지 않고 고정 안내 문구를 강제한다.
    """
    # 고위험: 코드에서 안내 문구 강제 (LLM이 누그러뜨릴 여지를 주지 않음)
    if is_critical:
        return _CRITICAL_NOTICE

    if signal == "GREEN":
        return safety_analyzer.green_summary()

    # 토큰 폭주 방지: 최근 메시지 위주로 제한
    sample = messages[-safety_analyzer.MAX_MESSAGES_FOR_LLM:]
    prompt = _REASON_PROMPT + "\n메시지:\n" + "\n".join(f"- {m}" for m in sample)

    try:
        resp = await agent_runner._genai.aio.models.generate_content(
            model=_REASON_MODEL,
            contents=prompt,
        )
        summary = (resp.text or "").strip()
        if not summary:
            summary = _FALLBACK[signal]
    except Exception:
        logger.exception("주간 안전 사유 요약 생성 실패 (signal=%s)", signal)
        summary = _FALLBACK[signal]

    # RED는 책임 있는 안내 문구를 덧붙임 (중복 방지)
    if signal == "RED" and "전문가" not in summary:
        summary = summary.rstrip() + _RED_TAIL

    return summary


@router.post("/weekly-safety", response_model=WeeklySafetyResult)
async def weekly_safety(req: WeeklySafetyBatchRequest) -> WeeklySafetyResult:
    # 1. 주간 메시지 조회 (실패해도 배치가 죽지 않게 방어)
    try:
        data = await be_client.get_weekly_messages(
            req.member_id, req.week_start, req.week_end
        )
    except Exception:
        logger.exception("주간 메시지 조회 실패 (member_id=%s)", req.member_id)
        data = {}

    messages = [
        m.get("content", "")
        for m in data.get("messages", [])
        if m.get("role") == "user" and m.get("content")
    ]

    # 2. 점수 → 판정 (메시지 0개면 score=0 → GREEN)
    #    고위험(자해/자살 등) 표현이 있으면 점수 무관 무조건 RED
    score = safety_analyzer.compute_score(messages)
    signal = safety_analyzer.classify(score, messages)
    is_critical = safety_analyzer.has_critical_signal(messages)

    # 3. 사유 요약
    reason = await _build_reason_summary(signal, messages, is_critical)

    result = WeeklySafetyResult(
        member_id=req.member_id,
        week_start=req.week_start,
        week_end=req.week_end,
        safety_signal=signal,
        score=score,
        reason_summary=reason,
    )

    # 4. BE 저장 (저장 실패는 로깅하되 결과는 반환)
    try:
        await be_client.post_weekly_safety_report(result.model_dump())
    except Exception:
        logger.exception("주간 안전 리포트 저장 실패 (member_id=%s)", req.member_id)

    return result