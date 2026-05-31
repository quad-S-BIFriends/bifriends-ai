"""
부모 성장 리포트 라우터.

엔드포인트: POST /api/v1/ai/report/weekly
호출 주체: BE 스케줄러 (주 1회)

AI는 4섹션(성장요약·수학·국어·보호자미션)만 생성해 반환한다.
BE는 이 결과를 weekly_report.sections(JSONB)에 저장하고,
부모 열람 시 안전신호(weekly_safety_report) + 학습패턴과 합쳐 FE로 전달한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas.report import WeeklyReportRequest, WeeklyReportResponse
from app.services.report_builder import build_weekly_report

router = APIRouter(prefix="/report", tags=["report"])


@router.post("/weekly", response_model=WeeklyReportResponse)
async def weekly_report(req: WeeklyReportRequest) -> WeeklyReportResponse:
    return await build_weekly_report(req)