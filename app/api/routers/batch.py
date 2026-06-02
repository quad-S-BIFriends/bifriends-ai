"""
주간 안전 신호 배치 라우터.

엔드포인트: POST /api/v1/ai/batch/weekly-safety
호출 주체: BE 스케줄러 (매주 금요일 저녁)

회원 처리 방식 (길 A):
  BE 스케줄러가 회원 한 명씩 member_id를 담아 호출한다. AI는 한 명만 분석.
  여러 명이면 BE가 이 엔드포인트를 회원 수만큼 반복 호출한다.

흐름:
  1. BE에서 해당 아이의 이번 주 user 메시지 조회
  2. 키워드 카운팅 → 점수 → GREEN/YELLOW/RED 판정 (Gemini 없음)
     + 자해/자살 등 고위험 표현은 점수 무관 무조건 RED (코드 강제)
  3. reason_summary:
     - GREEN(메시지 0개 포함): 고정 문구
     - critical(고위험): 고정 안내 문구 (전문가/상담 안내, Gemini 안 거침)
     - YELLOW/RED: Gemini 1회로 맥락 요약 (원문 인용 금지 — 프롬프트에 명시)
  4. BE에 weekly_safety_report 저장

가드레일:
  - 메시지 0개: GREEN 고정 (MVP — 활동 없음도 일단 GREEN)
  - Gemini에 넘기는 메시지 수 제한(최근 우선)으로 토큰 폭주 방지
  - Gemini 실패 시 신호별 폴백 문구
  - 조회/저장 실패해도 배치가 죽지 않게 방어
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.batch import WeeklySafetyResult
from app.core.config import settings
from app.services import safety_analyzer
from app.services.agent_runner import agent_runner
from app.services.be_client import be_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batch", tags=["batch"])

_REASON_MODEL = settings.model_summary
_REASON_PROMPT = (
    Path(__file__).parent.parent.parent / "prompts" / "safety_analyzer.txt"
).read_text(encoding="utf-8")

# 자해/자살 등 고위험 신호 감지 시 보호자에게 전하는 고정 안내 (코드 강제)
_CRITICAL_NOTICE = (
    "이번 주 대화에서 아이가 스스로를 힘들어하거나 자신을 해치고 싶어 하는 듯한 표현이 보였어요. "
    "가능한 한 빨리 아이와 따뜻하게 마음을 나눠보시고, 필요하다면 전문가(상담사·소아청소년과 등)의 "
    "도움을 함께 받아보시길 권해요. 급하다고 느껴지시면 자살예방 상담전화 109로 연락하실 수 있어요."
)

# Gemini 실패 시 신호별 폴백
_FALLBACK = {
    "YELLOW": "이번 주 대화에서 마음을 한 번 살펴보면 좋을 작은 신호가 있었어요. 아이와 가볍게 안부를 나눠보세요.",
    "RED": "이번 주 대화에서 조금 더 살펴보면 좋을 신호가 있었어요. 아이와 차분히 마음을 나눠보시고, 필요하면 전문가의 도움도 고려해보세요.",
}


class WeeklySafetyBatchRequest(BaseModel):
    member_id: int
    week_start: str
    week_end: str


async def _build_reason_summary(
    signal: str, messages: list[str], is_critical: bool
) -> str:
    # 고위험: LLM에 맡기지 않고 고정 안내 강제
    if is_critical:
        return _CRITICAL_NOTICE

    # GREEN(메시지 0개 포함): 고정 문구
    if signal == "GREEN":
        return safety_analyzer.green_summary()

    # YELLOW/RED: Gemini로 맥락 요약 (원문 인용 금지)
    sample = messages[-safety_analyzer.MAX_MESSAGES_FOR_LLM:]
    prompt = _REASON_PROMPT + "\n메시지:\n" + "\n".join(f"- {m}" for m in sample)
    try:
        resp = await agent_runner._genai.aio.models.generate_content(
            model=_REASON_MODEL,
            contents=prompt,
        )
        summary = (resp.text or "").strip()
        return summary or _FALLBACK[signal]
    except Exception:
        logger.exception("주간 안전 사유 요약 생성 실패 (signal=%s)", signal)
        return _FALLBACK[signal]


@router.post("/weekly-safety", response_model=WeeklySafetyResult)
async def weekly_safety(req: WeeklySafetyBatchRequest) -> WeeklySafetyResult:
    # 1. 주간 메시지 조회 (실패해도 배치가 죽지 않게)
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

    # 2. 점수 → 판정 (고위험이면 무조건 RED)
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

    # 4. BE 저장
    try:
        await be_client.post_weekly_safety_report(result.model_dump())
    except Exception:
        logger.exception("주간 안전 리포트 저장 실패 (member_id=%s)", req.member_id)

    return result