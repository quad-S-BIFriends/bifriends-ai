"""
주간 안전 신호 배치 라우터.

엔드포인트: POST /api/v1/ai/batch/weekly-safety
호출 주체: BE 스케줄러 (매주 금요일 저녁)

흐름:
  1. BE에서 이번 주 user 메시지 조회
  2. 키워드 카운팅 → 점수 → GREEN/YELLOW/RED 판정 (safety_analyzer, Gemini 없음)
  3. GREEN: 고정 문구 / YELLOW·RED: Gemini 1회로 reason_summary
  4. BE에 weekly_safety_report 저장

NOTE(BE 확인): 컨텍스트 문서 요청 body는 week_start/week_end만 있어
  '어느 회원을 처리할지'가 빠져 있음. 전체 회원 목록 조회 API도 명세에 없음.
  → 현재는 요청에 member_id를 함께 받는다고 가정(회원 단위 호출).
    BE가 전체 순회를 원하면 회원 목록 조회 방식 확정 후 수정 필요.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.batch import WeeklySafetyResult
from app.services import safety_analyzer
from app.services.agent_runner import agent_runner
from app.services.be_client import be_client

router = APIRouter(prefix="/batch", tags=["batch"])

_REASON_MODEL = "gemini-2.0-flash"
_REASON_PROMPT = (
    "다음은 한 아이가 이번 주 AI 친구에게 보낸 메시지들이야. "
    "보호자가 읽을 수 있도록, 걱정되는 정서·관계 신호를 1~2문장으로 부드럽게 요약해줘. "
    "단정하거나 진단하지 말고, 관찰된 경향만 차분히 전달해.\n\n메시지:\n"
)


class WeeklySafetyBatchRequest(BaseModel):
    # NOTE: member_id는 BE 확인 후 확정 (현재 회원 단위 호출 가정)
    member_id: int
    week_start: str
    week_end: str


async def _build_reason_summary(signal: str, messages: list[str]) -> str:
    """GREEN은 고정 문구, YELLOW/RED만 Gemini 1회 호출."""
    if signal == "GREEN":
        return safety_analyzer.green_summary()

    prompt = _REASON_PROMPT + "\n".join(f"- {m}" for m in messages)
    resp = await agent_runner._genai.aio.models.generate_content(
        model=_REASON_MODEL,
        contents=prompt,
    )
    return (resp.text or "").strip() or "이번 주 대화에서 주의가 필요한 신호가 있었어요."


@router.post("/weekly-safety", response_model=WeeklySafetyResult)
async def weekly_safety(req: WeeklySafetyBatchRequest) -> WeeklySafetyResult:
    # 1. 주간 메시지 조회
    data = await be_client.get_weekly_messages(
        req.member_id, req.week_start, req.week_end
    )
    # user 메시지 텍스트만 추출 (응답 구조는 BE 확인 필요)
    messages = [
        m.get("content", "")
        for m in data.get("messages", [])
        if m.get("role") == "user"
    ]

    # 2~3. 점수 → 판정 → 사유 요약
    score = safety_analyzer.compute_score(messages)
    signal = safety_analyzer.classify(score)
    reason = await _build_reason_summary(signal, messages)

    result = WeeklySafetyResult(
        member_id=req.member_id,
        week_start=req.week_start,
        week_end=req.week_end,
        safety_signal=signal,
        score=score,
        reason_summary=reason,
    )

    # 4. BE 저장
    await be_client.post_weekly_safety_report(result.model_dump())

    return result