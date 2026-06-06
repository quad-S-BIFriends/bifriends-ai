#!/usr/bin/env python3
"""
레오 에이전트 로컬 터미널 테스트.

사용법:
  python scripts/chat_cli.py                          # 기본 (4학년, mock BE)
  python scripts/chat_cli.py --grade 5 --nickname 민준  # 학년/닉네임 지정
  python scripts/chat_cli.py --trajectory             # 도구 호출 경로 표시
  python scripts/chat_cli.py --real-be                # 실제 BE 서버 사용 (BE 실행 중일 때)

종료: 'q', 'quit', Ctrl+C
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

# 프로젝트 루트를 path에 추가 (scripts/ 에서 실행해도 동작)
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google import genai

from app.core.config import settings
from app.agents.leo.agent import leo_agent
from app.services.agent_runner import AgentRunner, RunTrajectory
from app.services import be_client as be_client_module
from app.schemas.chat import ChatRequest

# ── mock BE 데이터 (--real-be 없으면 이걸로 BE 응답을 대체) ──────────────────
_MATH_CONCEPTS_BY_GRADE: dict[int, list[dict]] = {
    3: [
        {"concept": "받아올림 없는 세 자리 수 덧셈과 뺄셈", "stepTitle": "1단계"},
        {"concept": "받아올림/내림 있는 세 자리 수 덧셈과 뺄셈", "stepTitle": "2단계"},
        {"concept": "나눗셈의 기초", "stepTitle": "3단계"},
    ],
    4: [
        {"concept": "받아올림/내림 2번 있는 세 자리 수 덧셈과 뺄셈", "stepTitle": "1단계"},
        {"concept": "분수의 덧셈과 뺄셈", "stepTitle": "2단계"},
        {"concept": "소수의 곱셈", "stepTitle": "3단계"},
    ],
    5: [
        {"concept": "분수의 곱셈과 나눗셈", "stepTitle": "1단계"},
        {"concept": "소수의 나눗셈", "stepTitle": "2단계"},
        {"concept": "약수와 배수", "stepTitle": "3단계"},
    ],
    6: [
        {"concept": "분수와 소수의 혼합 계산", "stepTitle": "1단계"},
        {"concept": "비와 비율", "stepTitle": "2단계"},
        {"concept": "원의 넓이", "stepTitle": "3단계"},
    ],
}

_LESSON_AVAILABLE = {"lessonStatus": "AVAILABLE", "stepId": 2, "stepTitle": "2단계"}
_KOREAN_LESSON = {"stepTitle": "낱말 익히기", "concept": "어휘"}
_TODO_RESP = {"title": "테스트 할 일", "assignedDate": "2026-06-06"}


def _setup_runner(grade: int) -> AgentRunner:
    os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)
    r = AgentRunner()
    r._session_service = InMemorySessionService()
    r._runner = Runner(agent=leo_agent, app_name="bifriends", session_service=r._session_service)
    r._genai = genai.Client(api_key=settings.google_api_key)
    return r


def _mock_context(grade: int):
    """BE 클라이언트 메서드를 학년별 mock 데이터로 교체하는 context manager."""
    client = be_client_module.be_client
    concepts = _MATH_CONCEPTS_BY_GRADE.get(grade, _MATH_CONCEPTS_BY_GRADE[4])
    return patch.multiple(
        client,
        get_math_concepts=AsyncMock(return_value={"concepts": concepts}),
        get_math_lesson_status=AsyncMock(return_value=_LESSON_AVAILABLE),
        get_korean_current_lesson=AsyncMock(return_value=_KOREAN_LESSON),
        create_todo=AsyncMock(return_value=_TODO_RESP),
        patch_session_title=AsyncMock(return_value=None),
    )


def _print_response(
    reply: str,
    cta,
    todos: list | None,
    trajectory: RunTrajectory | None,
    show_trajectory: bool,
    elapsed: float,
) -> None:
    if show_trajectory and trajectory and trajectory.tool_calls:
        calls = " → ".join(
            f"{tc.name}({', '.join(f'{k}={v!r}' for k, v in tc.args.items())})"
            for tc in trajectory.tool_calls
        )
        print(f"  \033[90m[도구] {calls}\033[0m")

    print(f"\033[96m레오\033[0m: {reply}  \033[90m({elapsed:.1f}s)\033[0m")

    if cta:
        # Pydantic 모델로 역직렬화됐을 수도 있으므로 dict로 통일
        cta_dict = cta if isinstance(cta, dict) else cta.model_dump()
        label = cta_dict.get("label", "")
        cta_type = cta_dict.get("type", "")
        print(f"  \033[93m[버튼] {label}  ({cta_type})\033[0m")

    if todos:
        titles = ", ".join(t["title"] if isinstance(t, dict) else t.title for t in todos)
        print(f"  \033[92m[할 일 등록] {titles}\033[0m")

    print()


async def run_loop(args: argparse.Namespace) -> None:
    if not settings.google_api_key:
        print("오류: .env에 GOOGLE_API_KEY가 없습니다.")
        sys.exit(1)

    runner = _setup_runner(args.grade)
    session_id = f"cli-{uuid.uuid4().hex[:8]}"

    print(f"\n\033[1m레오 에이전트 터미널 테스트\033[0m")
    print(f"  학년: {args.grade}학년  닉네임: {args.nickname}  세션: {session_id}")
    print(f"  BE: {'실제 서버' if args.real_be else 'mock'}  trajectory: {'켜짐' if args.trajectory else '꺼짐'}")
    print("  종료: q / quit / Ctrl+C\n")

    while True:
        try:
            user_input = input("\033[97m아이\033[0m: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if user_input.lower() in ("q", "quit", "exit"):
            break
        if not user_input:
            continue

        req = ChatRequest(
            member_id=args.member_id,
            nickname=args.nickname,
            grade=args.grade,
            session_id=session_id,
            message=user_input,
        )

        try:
            t0 = time.monotonic()
            if args.real_be:
                await be_client_module.be_client.initialize()
                resp, traj = await runner.run_with_trajectory(req)
            else:
                with _mock_context(args.grade):
                    resp, traj = await runner.run_with_trajectory(req)
            elapsed = time.monotonic() - t0
        except Exception as e:
            print(f"  \033[91m[오류] {e}\033[0m\n")
            continue

        _print_response(
            reply=resp.reply,
            cta=resp.cta,
            todos=resp.todos_created,
            trajectory=traj,
            show_trajectory=args.trajectory,
            elapsed=elapsed,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="레오 에이전트 로컬 터미널 테스트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--member-id", type=int, default=9999, metavar="ID")
    parser.add_argument("--nickname", default="테스트", metavar="NAME")
    parser.add_argument("--grade", type=int, default=4, choices=[3, 4, 5, 6], metavar="N")
    parser.add_argument("--trajectory", action="store_true", help="도구 호출 경로를 응답 위에 표시")
    parser.add_argument("--real-be", action="store_true", help="BE mock 대신 실제 서버 사용")
    args = parser.parse_args()

    asyncio.run(run_loop(args))


if __name__ == "__main__":
    main()
