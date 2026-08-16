import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    CORS_ORIGINS: list = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    MEDIA_VIDEOS_DIR: str = os.getenv(
        "MEDIA_VIDEOS_DIR",
        str(Path(__file__).resolve().parents[2] / "media" / "videos"),
    )
    STREAM_STALE_SECONDS: int = int(os.getenv("STREAM_STALE_SECONDS", "5"))
    # MediaMTX serves HLS on port 8888 by default; override via env if changed
    MEDIAMTX_HLS_PORT: int = int(os.getenv("MEDIAMTX_HLS_PORT", "8888"))
    ALLOW_DEBUG_PLAYBACK: bool = os.getenv("ALLOW_DEBUG_PLAYBACK", "false").lower() == "true"
    HISTORY_SAMPLE_SECONDS: int = int(os.getenv("HISTORY_SAMPLE_SECONDS", "5"))
    HISTORY_DEFAULT_WINDOW_HOURS: int = int(os.getenv("HISTORY_DEFAULT_WINDOW_HOURS", "2"))
    HISTORY_MAX_WINDOW_HOURS: int = int(os.getenv("HISTORY_MAX_WINDOW_HOURS", "6"))

    # Telegram Integration
    API_KEY_SECRET: str = os.getenv("API_KEY_SECRET", "sk_skywatch_local_secret_123")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_IDS: str = os.getenv("TELEGRAM_CHAT_IDS", "")

    # Auth / JWT
    JWT_SECRET: str = os.getenv("JWT_SECRET", "skywatch_jwt_super_secret_change_me")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

settings = Settings()
