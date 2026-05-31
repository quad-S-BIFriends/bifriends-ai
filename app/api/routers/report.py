"""
부모 성장 리포트 라우터 (기능 2 — 추후 구현).
엔드포인트 예정: POST /api/v1/ai/report/weekly
"""
from fastapi import APIRouter

router = APIRouter(prefix="/report", tags=["report"])

# TODO: 주간 리포트 생성 엔드포인트 (Gemini 1회로 4개 섹션 JSON 생성 → BE 전달)