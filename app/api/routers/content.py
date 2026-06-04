"""
친구랑 콘텐츠 라우터.
최종 경로: POST /api/v1/ai/content/scenario  (main이 /api/v1/ai prefix 부착)

text_generator / image_generator 는 의존성으로 주입.
- text_generator: agent_runner의 시나리오 텍스트 에이전트 (content_scenario.txt 사용)
- image_generator: Gemini 이미지 모델 클라이언트 (step3 멀티턴 생성)
실제 구현은 services 측에서 연결하며, 여기서는 호출 흐름만 고정.
"""

import logging
from fastapi import APIRouter

from app.schemas.content import ScenarioRequest, ScenarioResponse
from app.services.content_builder import build_scenario
from app.services.agent_runner import agent_runner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content"])


@router.post("/scenario", response_model=ScenarioResponse)
async def create_scenario(req: ScenarioRequest) -> ScenarioResponse:
    """친구랑 4단계 학습 세트 생성. step1·2는 고정 폴백 URL, step3 3컷은 실시간 생성."""
    return await build_scenario(
        req,
        text_generator=agent_runner.generate_emo_scenario_text,
        image_generator=agent_runner.generate_emo_images,
    )
