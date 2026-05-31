"""부모 성장 리포트 스키마."""
from __future__ import annotations

from pydantic import BaseModel


class WeeklyReportRequest(BaseModel):
    """BE → AI (매주 리포트 생성 트리거)."""
    member_id: int
    week_start: str  # yyyy-MM-dd
    week_end: str    # yyyy-MM-dd


class SubjectSection(BaseModel):
    """과목별 학습 현황."""
    well_done: str   # 잘한 점
    struggled: str   # 어려웠던 점


class ParentMission(BaseModel):
    """보호자 미션."""
    praise: str      # 아이에게 건넬 칭찬 멘트
    activity: str    # 함께하면 좋은 활동


class ReportSections(BaseModel):
    """AI가 생성하는 4개 섹션 (안전신호·학습패턴은 분업으로 제외)."""
    growth_summary: str
    math: SubjectSection
    korean: SubjectSection
    parent_mission: ParentMission


class WeeklyReportResponse(BaseModel):
    """AI → BE (BE가 weekly_report.sections(JSONB)에 저장)."""
    member_id: int
    week_start: str
    week_end: str
    sections: ReportSections