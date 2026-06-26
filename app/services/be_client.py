"""
BE(Spring) API 호출 클라이언트.

- 모든 호출에 X-Internal-Service 헤더 포함 (BE ↔ AI 내부 통신)
- httpx.AsyncClient 재사용 (앱 생명주기 동안 단일 인스턴스)
- memberId 전달 방식은 _member_params() 한 곳에 격리.
  → BE 팀 확인 후 query param / header 중 무엇이든 이 메서드만 수정하면 됨.

NOTE: 내부 API(math/concepts, lesson-status, korean/current)가
memberId를 어떻게 받는지 미확정. 현재는 query param ?memberId={id} 로 확정
"""
from __future__ import annotations
import httpx
from app.core.config import settings


class BEClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    # ---------- 생명주기 ----------
    async def initialize(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.be_base_url,
                headers=settings.internal_headers,  # X-Internal-Service
                timeout=httpx.Timeout(10.0, connect=5.0),
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("BEClient가 초기화되지 않았습니다. initialize()를 먼저 호출하세요.")
        return self._client

    @staticmethod
    def _member_params(member_id: int, **extra) -> dict:
        """
        내부 API에 회원을 식별시키는 방법.
        현재: query param ?memberId={id}
        """
        return {"memberId": member_id, **extra}

    @staticmethod
    def _chat_messages_range_params(member_id: int, week_start: str, week_end: str) -> dict:
        """
        BE GET /api/v1/chat/messages — memberId + from/to (ISO DATE_TIME).
        배치 요청의 week_start/end(yyyy-MM-dd)를 BE 형식으로 변환한다.
        """
        return {
            "memberId": member_id,
            "from": f"{week_start}T00:00:00",
            "to": f"{week_end}T23:59:59",
        }

    # ================================================================
    # 학습 — 수학
    # ================================================================
    async def get_math_concepts(self, member_id: int) -> dict:
        """수학 concept 목록 (10-2). create_todo 안내/학습 주제 안내용."""
        resp = await self.client.get(
            "/api/v1/learning/math/concepts",
            params=self._member_params(member_id),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_math_lesson_status(self, member_id: int, concept: str) -> dict:
        """
        수학 concept별 lesson 상태 (10-3). math_study 3분기 판단용.
        반환 lessonStatus: AVAILABLE | IN_PROGRESS | COMPLETED | LOCKED | NOT_FOUND
        """
        resp = await self.client.get(
            "/api/v1/learning/math/concepts/lesson-status",
            params=self._member_params(member_id, concept=concept),
        )
        resp.raise_for_status()
        return resp.json()

    # ================================================================
    # 학습 — 국어
    # ================================================================
    async def get_korean_current_lesson(self, member_id: int) -> dict:
        """현재 국어 lesson (10-4). korean_study 진입 step 조회용."""
        resp = await self.client.get(
            "/api/v1/learning/korean/lessons/current",
            params=self._member_params(member_id),
        )
        resp.raise_for_status()
        return resp.json()

    # ================================================================
    # 할 일 (create_todo 인텐트)
    # ================================================================
    async def create_todo(self, member_id: int, title: str) -> dict:
        """
        Agent 할 일 추가 (8-2). X-Internal-Service 인증.
        MVP: estimatedTimeSec 미사용 (명세상 선택 필드라 생략).
        반환: TodoResponse (assignedDate 포함)
        """
        resp = await self.client.post(
            "/api/v1/todos",
            json={"memberId": member_id, "title": title},
        )
        resp.raise_for_status()
        return resp.json()

    # ================================================================
    # 채팅 세션 제목 (title 인텐트)
    # ================================================================
    async def patch_session_title(self, session_id: str, title: str) -> None:
        """세션 제목 자동생성 결과 저장. 세션 첫 메시지 시 1회."""
        resp = await self.client.patch(
            f"/api/v1/chat/sessions/{session_id}",
            json={"title": title},
        )
        resp.raise_for_status()

    # ================================================================
    # 배치 — 주간 안전 신호 (다음 단계, 자리만 확보)
    # ================================================================
    async def get_weekly_messages(
        self, member_id: int, week_start: str, week_end: str
    ) -> dict:
        """주간 채팅 메시지 조회 (배치용)."""
        resp = await self.client.get(
            "/api/v1/chat/messages",
            params=self._chat_messages_range_params(member_id, week_start, week_end),
        )
        resp.raise_for_status()
        return resp.json()

    async def post_weekly_safety_report(self, payload: dict) -> dict:
        """주간 안전 리포트 저장."""
        resp = await self.client.post(
            "/api/v1/weekly-safety-report",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    # ================================================================
    # 부모 성장 리포트 — 주간 학습 집계 조회 / 콜백
    # ================================================================
    async def get_learning_summary(
        self, member_id: int, week_start: str, week_end: str
    ) -> dict:
        """
        리포트용 주간 학습 집계 (BE가 신설할 API).
        응답 예:
          {
            "math":   [{ "concept", "solved", "avg_attempts", "avg_hints" }, ...],
            "korean": [{ ... }],
            "todos":  { "assigned": 15, "completed": 12 }
          }
        """
        resp = await self.client.get(
            "/api/v1/report/learning-summary",
            params={"memberId": member_id, "from": week_start, "to": week_end},
        )
        resp.raise_for_status()
        return resp.json()

    async def post_weekly_report(
        self, member_id: int, week_start: str, week_end: str, sections_json: str
    ) -> dict:
        """주간 성장 리포트 콜백 — AI가 생성한 sections JSON 문자열을 BE에 저장."""
        resp = await self.client.post(
            "/api/v1/weekly-report",
            json={
                "member_id": member_id,
                "week_start": week_start,
                "week_end": week_end,
                "sections": sections_json,
            },
        )
        resp.raise_for_status()
        return resp.json()


# 앱 전역에서 공유하는 단일 인스턴스
be_client = BEClient()