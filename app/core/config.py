from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    google_api_key: str = ""
    google_genai_use_vertexai: bool = False
    be_base_url: str = "http://bifriends-be:8080"
    internal_service_token: str = ""
    session_db_url: str = "sqlite+aiosqlite:///./sessions.db"
    app_env: str = "development"
    app_port: int = 8001

    # ── Gemini 모델 (용도별) ───────────────────────────────
    # gemini-2.0-flash는 2026 상반기 종료 → 2.5-flash 계열로 교체.
    # 실제 사용 가능한 정확한 모델 문자열은 배포 전 공식 문서에서 재확인할 것:
    #   https://ai.google.dev/gemini-api/docs/models
    # 각 값은 .env에서 환경변수로 덮어쓸 수 있음 (예: MODEL_CHAT=gemini-2.5-pro).
    model_chat: str = "gemini-2.5-flash"       # 레오 채팅 (ADK 에이전트)
    model_title: str = "gemini-2.5-flash-lite" # 세션 제목 (짧고 가벼움 → 저비용)
    model_summary: str = "gemini-2.5-flash"    # 배치/리포트 요약
    model_scenario: str = "gemini-2.5-flash"   # EMO 시나리오 (구조화 JSON)
    model_image: str = "gemini-2.5-flash-image"  # EMO 이미지 (Nano Banana )
    #model_image: str = "gemini-3.1-flash-image"  # EMO 이미지 (Nano Banana 2)

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def internal_headers(self) -> dict:
        return {"X-Internal-Service": self.internal_service_token}


settings = Settings()