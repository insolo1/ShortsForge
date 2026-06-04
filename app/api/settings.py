from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/")
async def get_settings():
    env_path = settings.BASE_DIR / ".env"
    existing = {}
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k] = v.strip().strip('"')
    return {
        "status": "success",
        "settings": {
            "crop_mode": existing.get("VIDEO_CROP_MODE", "9:16"),
            "zoom_enabled": existing.get("VIDEO_ZOOM_ENABLE", "0") == "1",
            "font": existing.get("SUBTITLE_FONT", "Verdana"),
            "fontsize": int(existing.get("SUBTITLE_FONTSIZE", "75")),
            "fontcolor": existing.get("SUBTITLE_FONTCOLOR", "white"),
            "position": int(existing.get("SUBTITLE_POSITION_Y", "600")),
            "words_count": int(existing.get("SUBTITLE_WORDS_COUNT", "5")),
            "api_provider": "groq" if settings.GROQ_API_KEY else "openai" if settings.OPENAI_API_KEY else "groq",
            "api_key_masked": "***" if (settings.GROQ_API_KEY or settings.OPENAI_API_KEY) else "",
        }
    }


from fastapi import Form


@router.post("/")
async def update_settings(
    font: str = Form("Verdana"), fontsize: int = Form(75),
    fontcolor: str = Form("white"), position: int = Form(600),
    crop_mode: str = Form("9:16"), zoom_enabled: bool = Form(False),
    borderw: int = Form(0), bordercolor: str = Form("black"),
    boxborder: int = Form(0), boxcolor: str = Form("black@0.8"),
    shadowx: int = Form(0), shadowy: int = Form(0),
    shadowcolor: str = Form("black"),
    words_count: int = Form(5), word_fade: bool = Form(True),
    api_provider: str = Form(None), api_key: str = Form(None),
    banner_x: str = Form("0"), banner_y: str = Form("0"),
    banner_w: str = Form("1080"), banner_h: str = Form("200"),
    banner_opacity: str = Form("100")
):
    env_path = settings.BASE_DIR / ".env"
    existing = {}
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k] = v.strip().strip('"')

    existing["GROQ_API_KEY"] = settings.GROQ_API_KEY
    existing["VIDEO_CROP_MODE"] = crop_mode
    existing["VIDEO_ZOOM_ENABLE"] = "1" if zoom_enabled else "0"
    existing["SUBTITLE_FONT"] = font
    existing["SUBTITLE_FONTSIZE"] = str(fontsize)
    existing["SUBTITLE_FONTCOLOR"] = fontcolor
    existing["SUBTITLE_POSITION_Y"] = str(position)
    existing["SUBTITLE_BORDERW"] = str(borderw)
    existing["SUBTITLE_BORDERCOLOR"] = bordercolor
    existing["SUBTITLE_BOX_BORDER"] = str(boxborder)
    existing["SUBTITLE_BOX_COLOR"] = boxcolor
    existing["SUBTITLE_SHADOW_X"] = str(shadowx)
    existing["SUBTITLE_SHADOW_Y"] = str(shadowy)
    existing["SUBTITLE_SHADOW_COLOR"] = shadowcolor
    existing["SUBTITLE_WORDS_COUNT"] = str(words_count)
    existing["SUBTITLE_WORD_FADE"] = "1" if word_fade else "0"
    existing["BANNER_X"] = banner_x
    existing["BANNER_Y"] = banner_y
    existing["BANNER_W"] = banner_w
    existing["BANNER_H"] = banner_h
    existing["BANNER_OPACITY"] = banner_opacity

    if api_provider and api_key:
        key_name = "GROQ_API_KEY" if api_provider == "groq" else "OPENAI_API_KEY"
        existing[key_name] = api_key

    env_content = "\n".join(f'{k}="{v}"' if not v.isdigit() else f"{k}={v}" for k, v in existing.items())
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_content)

    from dotenv import load_dotenv
    load_dotenv(override=True)

    return {"status": "success", "message": "Settings saved"}
