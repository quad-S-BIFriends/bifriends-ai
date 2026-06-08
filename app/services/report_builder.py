"""
부모 성장 리포트 생성.

흐름:
  1. BE에서 주간 학습 집계 조회 (get_learning_summary)
  2. 집계 데이터를 프롬프트에 넣어 Gemini 1회 호출 → 4섹션 JSON
  3. JSON 파싱 → ReportSections
  (안전신호·학습패턴은 분업으로 제외. BE가 부모 열람 시 합침)

가드레일:
  - 집계 조회 실패 시 빈 데이터로 진행 (리포트는 "이번 주 활동 없음" 류로 생성)
  - LLM JSON 파싱 실패 시 폴백 섹션
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.llm_json import parse_llm_json
from app.schemas.report import (
    ParentMission,
    ReportSections,
    SubjectSection,
    WeeklyReportRequest,
    WeeklyReportResponse,
)
from app.services.agent_runner import agent_runner
from app.services.be_client import be_client

logger = logging.getLogger(__name__)

_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "report_summary.txt"
).read_text(encoding="utf-8")

_FALLBACK = ReportSections(
    growth_summary="이번 주 리포트를 정리하는 데 어려움이 있었어요. 다음 주에 다시 확인해 주세요.",
    math=SubjectSection(well_done="-", struggled="-"),
    korean=SubjectSection(well_done="-", struggled="-"),
    parent_mission=ParentMission(
        praise="이번 주도 함께해줘서 고마워!",
        activity="아이와 가볍게 오늘 하루 어땠는지 이야기 나눠보세요.",
    ),
)


async def build_weekly_report(req: WeeklyReportRequest) -> WeeklyReportResponse:
    # 1. 주간 학습 집계 조회 (실패해도 빈 데이터로 진행)
    try:
        summary = await be_client.get_learning_summary(
            req.member_id, req.week_start, req.week_end
        )
    except Exception:
        logger.exception("학습 집계 조회 실패 (member_id=%s)", req.member_id)
        summary = {"math": [], "korean": [], "todos": {}}

    # 2. 프롬프트 구성 + LLM 호출
    prompt = (
        _PROMPT
        + "\n\n학습 집계 데이터:\n"
        + json.dumps(summary, ensure_ascii=False)
    )
    try:
        raw = await agent_runner.generate_text(prompt)
        parsed = parse_llm_json(raw)
        sections = ReportSections(
            growth_summary=parsed["growth_summary"],
            math=SubjectSection(**parsed["math"]),
            korean=SubjectSection(**parsed["korean"]),
            parent_mission=ParentMission(**parsed["parent_mission"]),
        )
    except Exception:
        logger.exception("리포트 생성/파싱 실패 (member_id=%s)", req.member_id)
        sections = _FALLBACK

    return WeeklyReportResponse(
        member_id=req.member_id,
        week_start=req.week_start,
        week_end=req.week_end,
        sections=sections,
    )