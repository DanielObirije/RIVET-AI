import os
from dataclasses import dataclass

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
UPSTREAM_TIMEOUT_SECONDS = 40.0
DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000"


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str | None
    deepseek_model: str
    allowed_origins: tuple[str, ...]


def load_settings() -> Settings:
    api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    origins = os.getenv("CORS_ALLOWED_ORIGINS") or DEFAULT_ALLOWED_ORIGINS
    return Settings(
        deepseek_api_key=api_key or None,
        deepseek_model=(os.getenv("DEEPSEEK_MODEL") or "").strip() or "deepseek-chat",
        allowed_origins=tuple(
            origin.strip() for origin in origins.split(",") if origin.strip()
        ),
    )
