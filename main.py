from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import chat, batch, report, content
from app.core.config import settings
from app.services.agent_runner import agent_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent_runner.initialize()
    print("✅ ADK Runner 초기화 완료")
    yield
    print("👋 서버 종료")


app = FastAPI(
    title="비프렌드 AI API",
    description="아이의 속도로 배우고 소통하는 느린 학습자 아이의 성장 앱",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.be_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/v1/ai")
app.include_router(batch.router, prefix="/api/v1/ai")
app.include_router(report.router, prefix="/api/v1/ai")
app.include_router(content.router, prefix="/api/v1/ai")


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "bifriends-ai"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=settings.is_dev,
    )