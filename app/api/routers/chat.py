"""
채팅 라우터.

흐름: BE → (이 라우터) → agent_runner(Leo) → ChatResponse 반환

- BE는 snake_case payload(ChatRequest)를 보낸다 (명세 9-1 내부 호출 포맷).
- 세션 첫 메시지면 제목 자동생성을 백그라운드로 발사(응답을 막지 않음).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_runner import agent_runner

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        is_new_session = await agent_runner.is_new_session(req)
        response = await agent_runner.run(req)
    except Exception:
        logger.exception("chat 엔드포인트 오류: member_id=%s session_id=%s", req.member_id, req.session_id)
        raise HTTPException(status_code=500, detail="레오가 잠깐 자리를 비웠어요. 다시 시도해 주세요.")

    if is_new_session:
        asyncio.create_task(_safe_generate_title(req, response.reply))

    return response


async def _safe_generate_title(req: ChatRequest, first_reply: str) -> None:
    """제목 생성 실패가 채팅 흐름에 영향 주지 않도록 예외를 삼킨다."""
    try:
        await agent_runner.generate_and_save_title(req, first_reply)
    except Exception:
        logger.exception("세션 제목 자동생성 실패: session_id=%s", req.session_id)