"""
친구랑 콘텐츠 라우터.
최종 경로: POST /api/v1/ai/content/scenario  (main이 /api/v1/ai prefix 부착)

text_generator / image_generator 는 의존성으로 주입.
- text_generator: agent_runner의 시나리오 텍스트 에이전트 (content_scenario.txt 사용)
- image_generator: Gemini 이미지 모델 클라이언트 (step3 멀티턴 생성)
실제 구현은 services 측에서 연결하며, 여기서는 호출 흐름만 고정.
"""

import logging
from fastapi import APIRouter, Depends

from app.schemas.content import ScenarioRequest, ScenarioResponse
from app.services.content_builder import build_scenario

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content"])


# --- 의존성 자리 (실제 구현 주입) ------------------------------------------
# 운영에서 agent_runner / image client 를 연결. 미구현 시 명확히 실패하도록 stub.

async def _text_generator(*, emotion, nickname, interests, learned_expressions) -> str:
    raise NotImplementedError("agent_runner의 SEL 텍스트 에이전트를 연결하세요.")

async def _image_generator(*, anchor_instruction, prompts, gender) -> list:
    raise NotImplementedError("Gemini 이미지 모델 클라이언트(step3 멀티턴)를 연결하세요.")

def _pick_emotion(learned_expressions: list[str]):
    # 간단 선택: 학습한 표현 수 기반 회전. 운영에서 정교화 가능.
    from app.schemas.content import Emotion
    pool = list(Emotion)
    return pool[len(learned_expressions) % len(pool)]


@router.post("/scenario", response_model=ScenarioResponse)
async def create_scenario(req: ScenarioRequest) -> ScenarioResponse:
    """친구랑 4단계 학습 세트 생성. step1·2는 고정 폴백 URL, step3 3컷은 실시간 생성."""
    return await build_scenario(
        req,
        text_generator=_text_generator,
        image_generator=_image_generator,
        pick_emotion=_pick_emotion,
    )