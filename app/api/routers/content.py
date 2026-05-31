"""
친구랑 콘텐츠 생성 라우터 (기능 3 — 추후 구현).
엔드포인트 예정: POST /api/v1/ai/content/scenario
"""
from fastapi import APIRouter

router = APIRouter(prefix="/content", tags=["content"])

# TODO: 관심사 기반 SEL 시나리오 생성 엔드포인트