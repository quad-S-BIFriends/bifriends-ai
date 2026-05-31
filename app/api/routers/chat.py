"""
채팅 라우터.

흐름: BE → (이 라우터) → agent_runner(Leo) → ChatResponse 반환

- BE는 snake_case payload(ChatRequest)를 보낸다 (명세 9-1 내부 호출 포맷).
- 세션 첫 메시지면 제목 자동생성을 백그라운드로 발사(응답을 막지 않음).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_runner import agent_runner

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    # 첫 메시지 여부는 agent_runner.run 내부에서 세션 존재로 판단되지만,
    # 제목 생성 트리거를 위해 여기서도 확인한다.
    is_new_session = await agent_runner.is_new_session(req)

    response = await agent_runner.run(req)

    if is_new_session:
        # 제목 자동생성은 응답을 막지 않도록 백그라운드 실행
        asyncio.create_task(_safe_generate_title(req, response.message))

    return response


async def _safe_generate_title(req: ChatRequest, first_reply: str) -> None:
    """제목 생성 실패가 채팅 흐름에 영향 주지 않도록 예외를 삼킨다."""
    try:
        await agent_runner.generate_and_save_title(req, first_reply)
    except Exception:
        logger.exception("세션 제목 자동생성 실패: session_id=%s", req.session_id)