"""주간 안전 신호 배치 스키마."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class WeeklySafetyRequest(BaseModel):
    """BE 스케줄러 → AI (매주 금요일 저녁)."""
    week_start: str  # yyyy-MM-dd
    week_end: str    # yyyy-MM-dd


class WeeklySafetyResult(BaseModel):
    """회원 1명에 대한 판정 결과 (BE 저장 payload와 동일 구조)."""
    member_id: int
    week_start: str
    week_end: str
    safety_signal: Literal["GREEN", "YELLOW", "RED"]
    score: int
    reason_summary: str


class WeeklySafetyResponse(BaseModel):
    """배치 실행 요약 (처리한 회원 수 등)."""
    processed: int
    results: list[WeeklySafetyResult]