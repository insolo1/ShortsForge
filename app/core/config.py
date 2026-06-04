import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://videobot:videobot@localhost:5432/videobot")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

    VIDEO_CROP_MODE: str = os.getenv("VIDEO_CROP_MODE", "9:16")
    VIDEO_ZOOM_ENABLE: bool = os.getenv("VIDEO_ZOOM_ENABLE", "0") == "1"

    SUBTITLE_FONT: str = os.getenv("SUBTITLE_FONT", "Verdana")
    SUBTITLE_STYLE: str = os.getenv("SUBTITLE_STYLE", "normal")
    SUBTITLE_FONTSIZE: int = int(os.getenv("SUBTITLE_FONTSIZE", "75"))
    SUBTITLE_FONTCOLOR: str = os.getenv("SUBTITLE_FONTCOLOR", "white")
    SUBTITLE_POSITION_Y: int = int(os.getenv("SUBTITLE_POSITION_Y", "600"))
    SUBTITLE_CAPITALIZE: bool = os.getenv("SUBTITLE_CAPITALIZE", "1") == "1"
    SUBTITLE_BORDERW: int = int(os.getenv("SUBTITLE_BORDERW", "0"))
    SUBTITLE_BORDERCOLOR: str = os.getenv("SUBTITLE_BORDERCOLOR", "black")
    SUBTITLE_BOX_BORDER: int = int(os.getenv("SUBTITLE_BOX_BORDER", "0"))
    SUBTITLE_BOX_COLOR: str = os.getenv("SUBTITLE_BOX_COLOR", "black@0.8")
    SUBTITLE_SHADOW_X: int = int(os.getenv("SUBTITLE_SHADOW_X", "0"))
    SUBTITLE_SHADOW_Y: int = int(os.getenv("SUBTITLE_SHADOW_Y", "0"))
    SUBTITLE_SHADOW_COLOR: str = os.getenv("SUBTITLE_SHADOW_COLOR", "black")
    SUBTITLE_WORDS_COUNT: int = int(os.getenv("SUBTITLE_WORDS_COUNT", "5"))
    SUBTITLE_WORD_FADE: bool = os.getenv("SUBTITLE_WORD_FADE", "1") == "1"

    BANNER_X: str = os.getenv("BANNER_X", "0")
    BANNER_Y: str = os.getenv("BANNER_Y", "0")
    BANNER_W: str = os.getenv("BANNER_W", "1080")
    BANNER_H: str = os.getenv("BANNER_H", "200")
    BANNER_OPACITY: int = int(os.getenv("BANNER_OPACITY", "100"))

    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "auto")

    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    YTDLP_PATH: str = os.getenv("YTDLP_PATH", "yt-dlp")

    BASE_DIR: Path = Path(__file__).parent.parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "output"
    FONTS_DIR: Path = BASE_DIR / "fonts"
    TOKENS_DIR: Path = BASE_DIR / "tokens"
    GOOGLE_CREDENTIALS_DIR: Path = BASE_DIR / "google_credentials"

    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    class Config:
        env_file = ".env"


settings = Settings()
