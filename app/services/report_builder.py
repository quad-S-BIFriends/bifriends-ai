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

_GUIDE_DIR = Path(__file__).parent.parent / "assets" / "parent_guide"

_FALLBACK = ReportSections(
    growth_summary="이번 주 리포트를 준비하는 데 잠깐 어려움이 있었어요. 걱정 마세요, 다음 주에 더 멋진 리포트로 찾아올게요 :)",
    math=SubjectSection(well_done="-", struggled="-"),
    korean=SubjectSection(well_done="-", struggled="-"),
    parent_mission=ParentMission(
        praise="이번 주도 레오 열어봤네, 그 작은 한 걸음이 정말 대단해!",
        activity="오늘 아이에게 '오늘 제일 기억에 남는 게 뭐야?' 하고 가볍게 물어봐 주세요. 짧은 대화도 아이에게 큰 힘이 됩니다.",
    ),
)


def _load_parent_guide(grade: int) -> str:
    if grade <= 4:
        path = _GUIDE_DIR / "grade_3_4.txt"
    else:
        path = _GUIDE_DIR / "grade_5_6.txt"
    return path.read_text(encoding="utf-8")


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
    guide = _load_parent_guide(req.grade)

    # 이번 주 학습 활동이 전혀 없으면 LLM에 컨텍스트를 명시해 따뜻한 톤 유도
    no_activity = (
        not summary.get("math")
        and not summary.get("korean")
        and not (summary.get("todos") or {}).get("completed")
    )
    no_activity_hint = (
        "\n\n## 참고 (이번 주 활동 없음)\n"
        "이번 주에는 아이가 레오와 학습을 하지 않았습니다. "
        "growth_summary는 부담 없이 따뜻하게, 레오와의 첫 만남을 응원하는 2문장으로 작성해 주세요. "
        "예: '이번 주는 레오와 아직 만나지 못했네요! 언제든 레오가 기다리고 있을 거예요 :)'"
        if no_activity else ""
    )

    prompt = (
        _PROMPT
        + "\n\n## 이번 아이의 학년대별 부모 역할 가이드\n"
        + guide
        + no_activity_hint
        + "\n\n## 학습 집계 데이터\n"
        + json.dumps(summary, ensure_ascii=False)
    )
    try:
        raw = await agent_runner.generate_text(prompt)
        parsed = parse_llm_json(raw)
        mission = parsed.get("parent_mission", {})
        if not (mission.get("praise") or "").strip():
            logger.warning("praise 비어있음 → 하드코딩 폴백 (member_id=%s)", req.member_id)
            mission["praise"] = "천천히 해나가는 것만으로도 충분히 멋져! 다음 주도 차근차근 해보자 :)"
        if not (mission.get("activity") or "").strip():
            logger.warning("activity 비어있음 → 하드코딩 폴백 (member_id=%s)", req.member_id)
            mission["activity"] = "오늘 아이에게 '오늘 제일 기억에 남는 게 뭐야?' 하고 가볍게 물어봐 주세요. 짧은 대화도 아이에게 큰 힘이 됩니다."
        sections = ReportSections(
            growth_summary=parsed["growth_summary"],
            math=SubjectSection(**parsed["math"]),
            korean=SubjectSection(**parsed["korean"]),
            parent_mission=ParentMission(**mission),
        )
    except Exception:
        logger.exception("리포트 생성/파싱 실패 (member_id=%s)", req.member_id)
        sections = _FALLBACK

    # 3. BE 콜백 — sections JSON 저장
    try:
        await be_client.post_weekly_report(
            req.member_id,
            req.week_start,
            req.week_end,
            sections.model_dump_json(),
        )
    except Exception:
        logger.exception("BE 콜백 실패 (member_id=%s) — 리포트는 정상 반환", req.member_id)

    return WeeklyReportResponse(
        member_id=req.member_id,
        week_start=req.week_start,
        week_end=req.week_end,
        sections=sections,
    )