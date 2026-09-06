import os
import sys
import json
import time
import uuid
import hashlib
import threading
import asyncio
import re
import logging
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

# Force line-buffered output for real-time logs
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Suppress uvicorn access log spam
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

_default_cpu_threads = str(max(1, min(4, os.cpu_count() or 1)))
os.environ.setdefault("OMP_NUM_THREADS", _default_cpu_threads)
os.environ.setdefault("MKL_NUM_THREADS", _default_cpu_threads)
os.environ.setdefault("OPENBLAS_NUM_THREADS", _default_cpu_threads)

# FFmpeg path from env (default: ffmpeg in PATH)
# On Windows, set FFMPEG_PATH in .env if not in system PATH
# On Linux/Docker, ffmpeg is typically at /usr/bin/ffmpeg
# No hardcoded paths - use FFMPEG_PATH env var or system PATH

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

from processor import VideoProcessor, _read_env
from ai_service import AIService
from youtube_api import YouTubeAPI
from api_keys import get_keys, add_key, remove_key, masked_keys, set_keys, mask_key

BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
USERS_FILE = BASE_DIR / "users.json"
SESSIONS_FILE = BASE_DIR / "sessions.json"
JOBS_FILE = BASE_DIR / "jobs.json"
JOB_LOGS_FILE = BASE_DIR / "job_logs.json"
PRESETS_FILE = BASE_DIR / "presets.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
FONTS_DIR = BASE_DIR / "fonts"
BANNER_DIR = UPLOAD_DIR / "banners"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)
BANNER_DIR.mkdir(parents=True, exist_ok=True)

processor = VideoProcessor(str(UPLOAD_DIR), str(OUTPUT_DIR))
ai_service = AIService()
youtube_api = YouTubeAPI(
    client_secret_file=str(BASE_DIR / "client_secret.json"),
    tokens_dir=str(BASE_DIR / "tokens")
)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

ROLES = {
    "admin": ["create_shorts", "delete_shorts", "manage_accounts", "settings", "cleanup", "view_all", "delete_all"],
    "user": ["create_shorts", "view_all"]
}

VERSION = "3.3.0"


def _ok(data):
    return JSONResponse({"status": "success", **data})


def _err(msg, code=400):
    return JSONResponse({"status": "error", "message": msg}, status_code=code)


def _load_settings_json() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[SETTINGS] JSON read error: {e}")
    return {}


def _save_settings_json(updates: dict):
    data = _load_settings_json()
    data.update(updates)
    try:
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[SETTINGS] JSON save error: {e}")


def _load_json(path):
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def _save_json(path, data):
    tmp = path.with_suffix('.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, path)
        except OSError:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[JSON] Write error: {e}")


jobs = _load_json(JOBS_FILE)
sessions = _load_json(SESSIONS_FILE)
job_logs = _load_json(JOB_LOGS_FILE)
_jobs_lock = threading.Lock()
_job_logs_lock = threading.Lock()
_last_log_save = 0.0

# Clean old completed/failed/cancelled jobs on startup
for jid in list(jobs.keys()):
    if jobs[jid].get("status") in ("completed", "failed", "cancelled"):
        del jobs[jid]
        job_logs.pop(jid, None)
_save_json(JOBS_FILE, jobs)
_save_json(JOB_LOGS_FILE, job_logs)

# Simple sequential job queue (1 at a time)
_processing_busy = False
_processing_queue = []  # list of (fn, args)
_processing_lock = threading.Lock()
_cancel_flag = False  # set True to stop current job


def _enqueue_job(fn, args):
    global _processing_busy
    with _processing_lock:
        if not _processing_busy:
            _processing_busy = True
            threading.Thread(target=_run_job_wrapper, args=(fn, args), daemon=True).start()
            return True
        else:
            _processing_queue.append((fn, args))
            return False


def _run_job_wrapper(fn, args):
    global _processing_busy, _cancel_flag
    try:
        fn(*args)
    except Exception as e:
        print(f"[QUEUE] Job error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _cancel_flag = False
        with _processing_lock:
            if _processing_queue:
                next_fn, next_args = _processing_queue.pop(0)
                threading.Thread(target=_run_job_wrapper, args=(next_fn, next_args), daemon=True).start()
            else:
                _processing_busy = False


def save_jobs():
    with _jobs_lock:
        _save_json(JOBS_FILE, jobs)


def save_job_logs():
    with _job_logs_lock:
        _save_json(JOB_LOGS_FILE, job_logs)


def add_job_log(job_id: str, message: str, log_type: str = "info"):
    global _last_log_save
    if job_id not in job_logs:
        job_logs[job_id] = []
    job_logs[job_id].append({
        "message": message, "type": log_type,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    })
    if len(job_logs[job_id]) > 2000:
        job_logs[job_id] = job_logs[job_id][-2000:]
    now = time.time()
    if now - _last_log_save > 5.0:
        _last_log_save = now
        save_job_logs()


def load_users():
    """РџРѕР»СЊР·РѕРІР°С‚РµР»Рё РІ РІРёРґРµ СЃР»РѕРІР°СЂСЏ: {Р»РѕРіРёРЅ: {"password": sha256, "admin": bool}}.
    РџРѕРґРґРµСЂР¶РёРІР°РµС‚ Рё СЃС‚Р°СЂС‹Р№ С„РѕСЂРјР°С‚-СЃРїРёСЃРѕРє (РјРёРіСЂР°С†РёСЏ РІ РїР°РјСЏС‚Рё)."""
    data = _load_json(USERS_FILE)
    if isinstance(data, list):
        users = {}
        for u in data:
            users[u.get("username", "")] = {
                "password": u.get("password", ""),
                "admin": u.get("role") == "admin" or bool(u.get("admin"))
            }
        return users
    return data if isinstance(data, dict) else {}


def save_users(users):
    _save_json(USERS_FILE, users)


def load_sessions():
    return _load_json(SESSIONS_FILE)


def load_presets():
    return _load_json(PRESETS_FILE)


def save_presets_to_file(data):
    _save_json(PRESETS_FILE, data)


def hsh(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def safe_email(email: str) -> str:
    return email.replace('@', '_at_').replace('.', '_')


def get_creds(email: str) -> str:
    f = BASE_DIR / "google_credentials" / f"{safe_email(email)}.json"
    return str(f) if f.exists() else str(BASE_DIR / "client_secret.json")


# в”Ђв”Ђ РџРѕРїСЂРѕР±СѓРµРј РїРѕРґРєР»СЋС‡РёС‚СЊ РЅРѕРІС‹Рµ РјРѕРґСѓР»Рё (РЅРµРѕР±СЏР·Р°С‚РµР»СЊРЅРѕ) в”Ђв”Ђ
_use_db = False
try:
    from app.core.database import init_db, close_db, get_session
    from app.core.redis import init_redis, close_redis
    _use_db = True
except Exception as e:
    print(f"[DB] Not available (non-fatal): {e}")

# в”Ђв”Ђ Lifespan в”Ђв”Ђ
@asynccontextmanager
async def lifespan(app: FastAPI):
    stale_states = {"processing", "queued", "starting", "downloading", "uploading"}
    stale_jobs = 0
    for job_id, job in jobs.items():
        if job.get("status") not in stale_states:
            continue
        job["status"] = "failed"
        job["error"] = "Обработка была прервана перезапуском сервера. Уже созданные файлы сохранены."
        job.pop("delete_after_finish", None)
        job_logs.setdefault(job_id, []).append({
            "message": job["error"],
            "type": "warning",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        stale_jobs += 1
    if stale_jobs:
        save_jobs()
        save_job_logs()
        print(f"[BOOT] Marked {stale_jobs} interrupted jobs as failed; output files preserved")

    if _use_db:
        try:
            await init_db()
            await init_redis()
            print("[BOOT] DB + Redis initialized")
        except Exception as e:
            print(f"[BOOT] DB init failed (continuing with JSON): {e}")
    yield
    if _use_db:
        try:
            await close_db()
            await close_redis()
        except:
            pass

app = FastAPI(title="Video to Shorts Bot", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")


# в”Ђв”Ђ РЎС‚Р°СЂС‹Рµ (JSON-based) СЂРѕСѓС‚С‹ в”Ђв”Ђ

def verify(request: Request):
    token = request.headers.get('Authorization') or request.cookies.get('token')
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return sessions[token]


def _is_admin(sess) -> bool:
    if not sess:
        return False
    if "admin" in sess:
        return bool(sess.get("admin"))
    return sess.get("role") == "admin"


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    async with aiofiles.open(BASE_DIR / "static" / "login.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=await f.read())


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    t = request.cookies.get('token')
    if not t or t not in sessions:
        return RedirectResponse(url='/login')
    async with aiofiles.open(BASE_DIR / "static" / "index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=await f.read())


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    t = request.cookies.get('token')
    if not t or t not in sessions:
        return RedirectResponse(url='/login')
    if not _is_admin(sessions[t]):
        return RedirectResponse(url='/')
    async with aiofiles.open(BASE_DIR / "static" / "admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=await f.read())


@app.get("/notes", response_class=HTMLResponse)
async def notes_page(request: Request):
    t = request.cookies.get('token')
    if not t or t not in sessions:
        return RedirectResponse(url='/login')
    async with aiofiles.open(BASE_DIR / "static" / "notes.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=await f.read())


@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...)):
    users = load_users()
    user = users.get(username)
    if not user or user.get("password") != hsh(password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    is_admin = bool(user.get("admin"))
    token = str(uuid.uuid4())
    sessions[token] = {"username": username, "admin": is_admin}
    _save_json(SESSIONS_FILE, sessions)
    resp = JSONResponse({"token": token, "username": username, "admin": is_admin})
    resp.set_cookie("token", token, httponly=False, max_age=86400*30, path="/", samesite="lax")
    return resp


@app.get("/api/me")
async def me(request: Request):
    s = verify(request)
    return {"username": s.get("username"), "admin": bool(s.get("admin"))}


@app.post("/api/logout")
async def logout(request: Request):
    t = request.cookies.get('token')
    sessions.pop(t, None)
    _save_json(SESSIONS_FILE, sessions)
    resp = JSONResponse({"status": "success"})
    resp.delete_cookie("token")
    return resp


@app.get("/api/users")
async def get_users(request: Request):
    s = verify(request)
    if not _is_admin(s):
        raise HTTPException(status_code=403, detail="Admin required")
    users = load_users()
    return {"status": "success", "users": [
        {"username": u, "admin": bool(v.get("admin"))} for u, v in users.items()
    ]}


@app.post("/api/users")
async def create_user(request: Request, username: str = Form(...), password: str = Form(...), admin: bool = Form(False)):
    """РЎРѕР·РґР°С‘С‚/РѕР±РЅРѕРІР»СЏРµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ. Р•СЃР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ СѓР¶Рµ РµСЃС‚СЊ вЂ” СЃР±СЂР°СЃС‹РІР°РµС‚ РїР°СЂРѕР»СЊ (РґРѕСЃС‚СѓРї)."""
    s = verify(request)
    if not _is_admin(s):
        raise HTTPException(status_code=403, detail="Admin required")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий (мин. 4 символа)")
    users = load_users()
    users[username] = {"password": hsh(password), "admin": bool(admin)}
    save_users(users)
    return {"status": "success"}


@app.delete("/api/users/{username}")
async def delete_user(username: str, request: Request):
    s = verify(request)
    if not _is_admin(s):
        raise HTTPException(status_code=403, detail="Admin required")
    if username == s.get("username"):
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")
    users = load_users()
    users.pop(username, None)
    save_users(users)
    return {"status": "success"}


@app.get("/api/roles")
async def get_roles():
    return {"roles": ROLES}


def _font_user_dir(request: Request) -> tuple[dict, Path, str]:
    session = verify(request)
    username = str(session.get("username") or "user")
    user_key = hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]
    user_dir = FONTS_DIR / "users" / user_key
    user_dir.mkdir(parents=True, exist_ok=True)
    return session, user_dir, user_key


@app.get("/api/fonts")
async def get_fonts(request: Request):
    _, user_dir, user_key = _font_user_dir(request)
    items = []
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        items.append({
            "value": path.stem, "label": path.stem,
            "url": f"/fonts/{path.name}", "custom": False, "deletable": False,
        })
    for path in sorted(user_dir.glob("*.ttf")):
        items.append({
            "value": f"users/{user_key}/{path.stem}",
            "label": f"{path.stem} (мой)",
            "url": f"/fonts/users/{user_key}/{path.name}",
            "custom": True, "deletable": True, "font_name": path.stem,
        })
    for font in ("Arial", "Verdana", "Impact"):
        items.append({"value": font, "label": font, "custom": False, "deletable": False})
    return {
        "fonts": [item["value"] for item in items],
        "font_items": items,
        "custom_fonts": [item for item in items if item.get("custom")],
    }


@app.post("/api/fonts/upload")
async def upload_font(request: Request, font_file: UploadFile = File(...)):
    _, user_dir, user_key = _font_user_dir(request)
    original_name = Path(font_file.filename or "").name
    if Path(original_name).suffix.lower() != ".ttf":
        raise HTTPException(status_code=400, detail="Можно загрузить только файл .ttf")
    safe_stem = re.sub(r"[^0-9A-Za-zА-Яа-яЁё _.-]+", "", Path(original_name).stem).strip(" .")
    if not safe_stem:
        raise HTTPException(status_code=400, detail="Некорректное имя шрифта")
    target = user_dir / f"{safe_stem}.ttf"
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Шрифт «{safe_stem}» уже загружен")
    content = await font_file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Размер шрифта не должен превышать 20 МБ")
    if len(content) < 12 or content[:4] not in (b"\x00\x01\x00\x00", b"true", b"typ1", b"ttcf"):
        raise HTTPException(status_code=400, detail="Файл не похож на корректный TTF-шрифт")
    target.write_bytes(content)
    font_value = f"users/{user_key}/{safe_stem}"
    return {
        "status": "success", "font_name": safe_stem, "font_value": font_value,
        "message": f"Шрифт «{safe_stem}» загружен и выбран",
    }


@app.delete("/api/fonts")
async def delete_font(request: Request, font_name: str):
    _, user_dir, _ = _font_user_dir(request)
    safe_name = Path(font_name).name
    if safe_name != font_name or not safe_name:
        raise HTTPException(status_code=400, detail="Некорректное имя шрифта")
    target = user_dir / f"{safe_name}.ttf"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Пользовательский шрифт не найден")
    target.unlink()
    return {"status": "success", "message": f"Шрифт «{safe_name}» удалён"}


@app.get("/api/presets/list")
async def list_presets():
    return {"status": "success", "presets": load_presets()}


@app.post("/api/presets/save")
async def save_preset(data: dict):
    presets = load_presets()
    name = data.get("name")
    if not name:
        return _err("Name required")
    for i, p in enumerate(presets):
        if p.get("name") == name:
            presets[i] = data
            break
    else:
        presets.append(data)
    save_presets_to_file(presets)
    return _ok({"message": "Preset saved"})


@app.get("/api/presets/load")
async def load_preset(name: str):
    p = next((p for p in load_presets() if p.get("name") == name), None)
    if not p:
        return _err("Not found", 404)
    return _ok({"preset": p})


@app.delete("/api/presets/delete")
async def delete_preset(name: str):
    presets = load_presets()
    new_presets = [p for p in presets if p.get("name") != name]
    if len(new_presets) == len(presets):
        return _err("Not found", 404)
    save_presets_to_file(new_presets)
    return _ok({"message": "Deleted"})


@app.get("/api/settings")
async def get_settings():
    return JSONResponse({
        "version": VERSION,
        "settings": {
            "crop_mode": _read_env("VIDEO_CROP_MODE", "9:16"),
            "font": _read_env("SUBTITLE_FONT", "Montserrat"),
            "style": _read_env("SUBTITLE_STYLE", "normal"),
            "fontsize": int(_read_env("SUBTITLE_FONTSIZE", "100")),
            "fontcolor": _read_env("SUBTITLE_FONTCOLOR", "white"),
            "position": int(_read_env("SUBTITLE_POSITION_Y", "1670")),
            "capitalize": _read_env("SUBTITLE_CAPITALIZE", "1") == "1",
            "borderw": int(_read_env("SUBTITLE_BORDERW", "0")),
            "bordercolor": _read_env("SUBTITLE_BORDERCOLOR", "black"),
            "boxborder": int(_read_env("SUBTITLE_BOX_BORDER", "0")),
            "boxcolor": _read_env("SUBTITLE_BOX_COLOR", "black@0.8"),
            "shadowx": int(_read_env("SUBTITLE_SHADOW_X", "2")),
            "shadowy": int(_read_env("SUBTITLE_SHADOW_Y", "2")),
            "shadowcolor": _read_env("SUBTITLE_SHADOW_COLOR", "black"),
            "words_count": int(_read_env("SUBTITLE_WORDS_COUNT", "1")),
            "word_fade": _read_env("SUBTITLE_WORD_FADE", "1") == "1",
            "whisper_model": _read_env("WHISPER_MODEL", "base"),
            "api_provider": "groq" if _read_env("GROQ_API_KEY") else ("openai" if _read_env("OPENAI_API_KEY") else "groq"),
            "api_key_masked": "***" if (_read_env("GROQ_API_KEY") or _read_env("OPENAI_API_KEY")) else "",
            "api_keys": {
                "groq": masked_keys("groq"),
                "openai": masked_keys("openai"),
            },
        }
    })


@app.post("/api/settings")
async def update_settings(
    font: str = Form("Montserrat"), style: str = Form("normal"),
    fontsize: int = Form(100), fontcolor: str = Form("white"),
    position: int = Form(1670), capitalize: bool = Form(True),
    crop_mode: str = Form("9:16"),
    borderw: int = Form(0), bordercolor: str = Form("black"),
    boxborder: int = Form(0), boxcolor: str = Form("black@0.8"),
    shadowx: int = Form(2), shadowy: int = Form(2), shadowcolor: str = Form("black"),
    words_count: int = Form(1), word_fade: bool = Form(True),
    whisper_model: str = Form("base"),
    api_provider: Optional[str] = Form(None), api_key: Optional[str] = Form(None),
    banner_x: str = Form("0"), banner_y: str = Form("0"),
    banner_w: str = Form("1080"), banner_h: str = Form("200"), banner_opacity: str = Form("100")
):
    from dotenv import set_key, unset_key, load_dotenv

    # РЎРѕС…СЂР°РЅСЏРµРј РЅРѕРІС‹Р№ API-РєР»СЋС‡ РІ РѕР±С‰РёР№ СЃРїРёСЃРѕРє РєР»СЋС‡РµР№ (failover)
    if api_key and api_provider in ("groq", "openai"):
        add_key(api_provider, api_key)

    _keys = {"groq": ",".join(get_keys("groq")), "openai": ",".join(get_keys("openai"))}

    keys_to_set = {
        "GROQ_API_KEY": _keys["groq"] or _read_env('GROQ_API_KEY', ''),
        "OPENAI_API_KEY": _keys["openai"] or _read_env('OPENAI_API_KEY', ''),
        "VIDEO_CROP_MODE": crop_mode,
        "SUBTITLE_FONT": font,
        "SUBTITLE_STYLE": style,
        "SUBTITLE_FONTSIZE": str(fontsize),
        "SUBTITLE_FONTCOLOR": fontcolor,
        "SUBTITLE_POSITION_Y": str(position),
        "SUBTITLE_CAPITALIZE": '1' if capitalize else '0',
        "SUBTITLE_BORDERW": str(borderw),
        "SUBTITLE_BORDERCOLOR": bordercolor,
        "SUBTITLE_BOX_BORDER": str(boxborder),
        "SUBTITLE_BOX_COLOR": boxcolor,
        "SUBTITLE_SHADOW_X": str(shadowx),
        "SUBTITLE_SHADOW_Y": str(shadowy),
        "SUBTITLE_SHADOW_COLOR": shadowcolor,
        "SUBTITLE_WORDS_COUNT": str(words_count),
        "SUBTITLE_WORD_FADE": '1' if word_fade else '0',
        "WHISPER_MODEL": whisper_model,
        "BANNER_X": banner_x,
        "BANNER_Y": banner_y,
        "BANNER_W": banner_w,
        "BANNER_H": banner_h,
        "BANNER_OPACITY": str(banner_opacity),
    }

    # Сохраняем в settings.json (всегда — UI является источником правды),
    # а .env пробуем дополнительно (на сервере он может быть смонтирован :ro)
    _save_settings_json(keys_to_set)
    try:
        env_path = BASE_DIR / ".env"
        for key, val in keys_to_set.items():
            set_key(str(env_path), key, val)
        # Reload env
        load_dotenv(str(env_path), override=True)
    except Exception as e:
        print(f"[SETTINGS] .env write failed (ro mount?), using settings.json: {e}")
    return {"status": "success"}


@app.post("/api/keys/add")
async def api_keys_add(data: dict):
    provider = (data.get("provider") or "groq").lower()
    key = (data.get("key") or "").strip()
    if provider not in ("groq", "openai"):
        return _err("Provider must be groq or openai")
    if not key:
        return _err("Key required")
    try:
        keys = add_key(provider, key)
    except ValueError as e:
        return _err(str(e))
    return _ok({"provider": provider, "keys": [mask_key(k) for k in keys]})


@app.delete("/api/keys")
async def api_keys_remove(data: dict):
    provider = (data.get("provider") or "groq").lower()
    index = data.get("index", -1)
    if provider not in ("groq", "openai"):
        return _err("Provider must be groq or openai")
    keys = remove_key(provider, index)
    return _ok({"provider": provider, "keys": [mask_key(k) for k in keys]})


@app.get("/api/video-info")
async def video_info(url: str):
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ РґР»РёС‚РµР»СЊРЅРѕСЃС‚СЊ РІРёРґРµРѕ РїРѕ URL (YouTube Рё РґСЂ.) С‡РµСЂРµР· yt-dlp, Р±РµР· СЃРєР°С‡РёРІР°РЅРёСЏ."""
    if not url or not url.strip():
        return _err("URL required")
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=False)
        return _ok({
            "duration": float(info.get("duration") or 0),
            "title": info.get("title") or "",
        })
    except Exception as e:
        print(f"[VIDEO-INFO] Error: {e}")
        return _err(f"РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РґР°РЅРЅС‹Рµ: {e}")


# в”Ђв”Ђ Jobs / Integration в”Ђв”Ђ


# в”Ђв”Ђ YouTube в”Ђв”Ђ
@app.post("/api/youtube/authorize")
async def yt_authorize(data: dict):
    email = data.get("email", "")
    if not email:
        return _err("Email required")
    youtube_api.client_secret_file = get_creds(email)
    if youtube_api.authenticate(email):
        return _ok({"message": f"Authorized: {email}"})
    return _err("Authorization failed")


@app.post("/api/youtube/upload-credentials")
async def yt_upload_creds(email: str = Form(...), credentials: UploadFile = File(...)):
    content = await credentials.read()
    try:
        json.loads(content)
    except:
        return _err("Invalid JSON")
    d = BASE_DIR / "google_credentials"
    d.mkdir(exist_ok=True)
    with open(d / f"{safe_email(email)}.json", 'wb') as f:
        f.write(content)
    return _ok({"message": f"Credentials saved for {email}"})


@app.get("/api/youtube/accounts")
async def yt_accounts():
    accounts = []
    d = BASE_DIR / "google_credentials"
    if d.exists():
        for f in d.glob("*.json"):
            email = f.stem.replace('_at_', '@').replace('_', '.')
            accounts.append({"email": email, "has_token": youtube_api.get_token_file(email).exists()})
    return _ok({"accounts": accounts})


@app.delete("/api/youtube/accounts")
async def yt_delete(data: dict):
    email = data.get("email", "").strip()
    if not email:
        return _err("Email required")
    s = safe_email(email)
    deleted = []
    for p in [BASE_DIR / "google_credentials" / f"{s}.json", youtube_api.get_token_file(email)]:
        if p.exists() and p.is_file():
            p.unlink()
            deleted.append(str(p))
    return _ok({"message": f"Deleted: {email}", "deleted": deleted})


@app.post("/api/cleanup")
async def cleanup():
    c = 0
    now = time.time()
    for jid, j in list(jobs.items()):
        if j.get("status") in ("completed", "failed") or (j.get("finished_at") and now - j["finished_at"] > 3600):
            for s in j.get("shorts", []):
                p = s.get("filepath")
                if p and Path(p).exists():
                    try:
                        Path(p).unlink()
                        c += 1
                    except:
                        pass
            inp = UPLOAD_DIR / f"{jid}_input.mp4"
            if inp.exists():
                try:
                    inp.unlink()
                    c += 1
                except:
                    pass
            del jobs[jid]
    save_jobs()
    return {"deleted": c}


@app.get("/api/logs/{job_id}")
async def get_logs(job_id: str, after: int = 0, limit: int = 300):
    logs = job_logs.get(job_id, [])
    start = max(0, min(int(after or 0), len(logs)))
    batch_limit = max(1, min(int(limit or 300), 500))
    batch = logs[start:start + batch_limit]
    return {
        "logs": batch,
        "next": start + len(batch),
        "total": len(logs),
        "status": jobs.get(job_id, {}).get("status", "unknown"),
        "progress": jobs.get(job_id, {}).get("progress", 0),
    }


@app.get("/api/jobs")
async def list_jobs_api():
    return {"jobs": [{"id": jid, "status": j.get("status"), "progress": j.get("progress", 0), "shorts_count": len(j.get("shorts", [])), "created_at": j.get("created_at")} for jid, j in jobs.items()]}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    j = jobs.get(job_id)
    if not j:
        return _err("Not found", 404)
    shorts = j.get("shorts", [])
    completed_count = len(shorts)
    target_count = max(0, int(j.get("shorts_count", 0) or 0))
    eta_seconds = None
    started_at = j.get("started_at")
    if j.get("status") == "processing" and started_at and completed_count > 0 and target_count > completed_count:
        elapsed = max(0.0, time.time() - float(started_at))
        eta_seconds = round((elapsed / completed_count) * (target_count - completed_count))
    return {
        "status": j.get("status", "unknown"),
        "progress": j.get("progress", 0),
        "error": j.get("error", ""),
        "target_count": target_count,
        "completed_count": completed_count,
        "eta_seconds": eta_seconds,
        "shorts": [{
            "id": s.get("index", i),
            "title": s.get("title", f"#shorts #{s.get('index', i)+1}"),
            "description": s.get("description", ""),
            "tags": s.get("tags", ["#shorts"]),
            "filename": s.get("filename", ""),
            "filepath": s.get("filepath", ""),
        } for i, s in enumerate(shorts)]
    }


@app.get("/api/jobs/{job_id}")
async def get_job_api(job_id: str):
    j = jobs.get(job_id)
    if not j:
        return _err("Not found", 404)
    shorts = j.get("shorts", [])
    return {
        "id": job_id, "status": j.get("status"), "progress": j.get("progress", 0),
        "shorts": [{
            "id": s.get("index", i),
            "title": s.get("title", f"#shorts #{s.get('index', i)+1}"),
            "description": s.get("description", ""),
            "tags": s.get("tags", ["#shorts"]),
            "filename": s.get("filename", ""),
            "filepath": s.get("filepath", ""),
            "youtube_url": s.get("youtube_url", ""),
        } for i, s in enumerate(shorts)]
    }


@app.delete("/api/jobs/{job_id}")
async def delete_job_api(job_id: str):
    if job_id not in jobs:
        return _err("Not found", 404)
    job = jobs[job_id]
    if job.get("status") in ("processing", "queued", "starting", "downloading", "uploading"):
        job["delete_after_finish"] = True
        save_jobs()
        return _ok({"message": "Project will be deleted after processing", "scheduled": True})
    deleted = _delete_job_artifacts(job_id)
    save_jobs()
    save_job_logs()
    return _ok({"message": "Project deleted", "deleted": deleted})


@app.get("/api/download/{short_idx}")
async def download_short(short_idx: int, job_id: str = None):
    # Try to find the short in any job
    for jid, j in jobs.items():
        for s in j.get("shorts", []):
            if s.get("index") == short_idx or s.get("filepath", "").endswith(f"short_{jid}_{short_idx}.mp4"):
                fp = Path(s["filepath"])
                if fp.exists():
                    return FileResponse(str(fp), media_type="video/mp4", filename=s.get("filename", fp.name))
    # Fallback: search by index pattern
    for jid, j in jobs.items():
        for s in j.get("shorts", []):
            if s.get("index") == short_idx:
                fp = Path(s["filepath"])
                if fp.exists():
                    return FileResponse(str(fp), media_type="video/mp4", filename=s.get("filename", fp.name))
    return _err("Not found", 404)


def _shorts_with_inferred_sources(job_id: str, shorts: list) -> list:
    """Recover source grouping for folder jobs created before source_name was persisted."""
    if not shorts or all(item.get("source_name") for item in shorts):
        return shorts

    source_by_index = {}
    current_source = ""
    video_pattern = re.compile(r"^\[Video \d+/\d+\]\s+(.+?)\s+(?:—|вЂ”)\s+\d+\s+shorts$")
    short_pattern = re.compile(r"^\[(\d+)/\d+\]\s+Processing\b")
    for entry in job_logs.get(job_id, []):
        message = str(entry.get("message", "")) if isinstance(entry, dict) else str(entry)
        video_match = video_pattern.match(message)
        if video_match:
            current_source = video_match.group(1).strip()
            continue
        short_match = short_pattern.match(message)
        if short_match and current_source:
            source_by_index[int(short_match.group(1)) - 1] = current_source

    enriched = []
    for fallback_index, item in enumerate(shorts):
        copy = dict(item)
        short_index = int(copy.get("index", fallback_index))
        if not copy.get("source_name") and short_index in source_by_index:
            copy["source_name"] = source_by_index[short_index]
        enriched.append(copy)
    return enriched

MAX_ZIP_SIZE = int(1.5 * 1024 * 1024 * 1024)  # 1.5 GiB
ZIP_SIZE_RESERVE = 2 * 1024 * 1024  # ZIP headers, filenames and descriptions.txt


def _safe_zip_folder(source_name: str) -> str:
    name = Path(source_name).stem if source_name else "video"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "video"


def _plan_zip_parts(shorts: list, max_size: int = MAX_ZIP_SIZE):
    """Group shorts into downloadable ZIP parts while preserving source folders."""
    if max_size <= 0:
        raise ValueError("max_size must be positive")

    # Leave room for ZIP metadata so the finished archive stays below max_size.
    reserve = min(ZIP_SIZE_RESERVE, max_size // 100)
    payload_limit = max(1, max_size - reserve)
    by_source = {}
    for item in shorts:
        file_path = Path(item.get("filepath", ""))
        if file_path.is_file():
            source = str(item.get("source_name") or "video")
            by_source.setdefault(source, []).append((item, file_path.stat().st_size))

    # Different source paths can have the same filename, so folder names must be unique.
    used_folders = set()
    source_chunks = []
    for source, entries in by_source.items():
        base_folder = _safe_zip_folder(source)
        candidate = base_folder
        suffix = 2
        while candidate.casefold() in used_folders:
            candidate = f"{base_folder} {suffix}"
            suffix += 1
        base_folder = candidate
        used_folders.add(base_folder.casefold())

        chunks = []
        chunk_items, chunk_size = [], 0
        for item, file_size in entries:
            if chunk_items and chunk_size + file_size > payload_limit:
                chunks.append((chunk_items, chunk_size))
                chunk_items, chunk_size = [], 0
            chunk_items.append(item)
            chunk_size += file_size
        if chunk_items:
            chunks.append((chunk_items, chunk_size))

        split_source = len(chunks) > 1
        for chunk_index, (chunk_items, chunk_size) in enumerate(chunks, 1):
            folder = f"{base_folder} {chunk_index}" if split_source else base_folder
            prepared_items = []
            for item in chunk_items:
                prepared = dict(item)
                prepared["_zip_folder"] = folder
                prepared_items.append(prepared)
            source_chunks.append({
                "items": prepared_items,
                "size": chunk_size,
                "folders": [folder],
                "oversized": chunk_size > payload_limit,
            })

    parts = []
    current = {"items": [], "size": 0, "folders": [], "oversized": False}
    for chunk in source_chunks:
        if current["items"] and (chunk["oversized"] or current["size"] + chunk["size"] > payload_limit):
            parts.append(current)
            current = {"items": [], "size": 0, "folders": [], "oversized": False}
        current["items"].extend(chunk["items"])
        current["size"] += chunk["size"]
        current["folders"].extend(chunk["folders"])
        current["oversized"] = current["oversized"] or chunk["oversized"]
        if chunk["oversized"]:
            parts.append(current)
            current = {"items": [], "size": 0, "folders": [], "oversized": False}
    if current["items"]:
        parts.append(current)

    for part_number, part in enumerate(parts, 1):
        part["part_num"] = part_number
    return parts


def _zip_parts_for_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return None, _err("Job not found", 404)
    shorts = _shorts_with_inferred_sources(job_id, job.get("shorts", []))
    default_source = job.get("filename") or "video"
    shorts = [
        item if item.get("source_name") else {**item, "source_name": default_source}
        for item in shorts
    ]
    parts = _plan_zip_parts(shorts)
    if not parts:
        return None, _err("No finished video files found", 404)
    return parts, None


def _zip_part_filename(job_id: str, part_number: int, total_parts: int) -> str:
    if total_parts == 1:
        return f"shorts_{job_id}.zip"
    return f"shorts_{job_id}_part_{part_number}_of_{total_parts}.zip"


@app.get("/api/download-zip/{job_id}/manifest")
async def download_job_zip_manifest(job_id: str):
    parts, error = _zip_parts_for_job(job_id)
    if error:
        return error
    total = len(parts)
    return _ok({
        "max_part_size": MAX_ZIP_SIZE,
        "parts": [{
            "number": part["part_num"],
            "filename": _zip_part_filename(job_id, part["part_num"], total),
            "media_size": part["size"],
            "folders": part["folders"],
            "oversized": part["oversized"],
            "url": f"/api/download-zip/{job_id}/part/{part['part_num']}",
        } for part in parts],
    })


@app.get("/api/download-zip/{job_id}/part/{part_number}")
async def download_job_zip_part(job_id: str, part_number: int):
    import functools
    import tempfile

    parts, error = _zip_parts_for_job(job_id)
    if error:
        return error
    if part_number < 1 or part_number > len(parts):
        return _err("ZIP part not found", 404)

    part = parts[part_number - 1]
    fd, tmp_path = tempfile.mkstemp(prefix=f"shorts_{job_id}_{part_number}_", suffix=".zip")
    os.close(fd)
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, functools.partial(_build_zip, tmp_path, part["items"]))
        zip_size = os.path.getsize(tmp_path)
        if zip_size > MAX_ZIP_SIZE and not part["oversized"]:
            Path(tmp_path).unlink(missing_ok=True)
            return _err("ZIP part exceeded the 1.5 GB limit", 500)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    async def stream_file():
        try:
            with open(tmp_path, "rb") as file_obj:
                while chunk := file_obj.read(1024 * 1024):
                    yield chunk
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    filename = _zip_part_filename(job_id, part_number, len(parts))
    return StreamingResponse(
        stream_file(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(zip_size),
        },
    )


@app.get("/api/download-zip/{job_id}")
async def download_job_zip(job_id: str):
    """Backward-compatible download for jobs that fit into one ZIP part."""
    parts, error = _zip_parts_for_job(job_id)
    if error:
        return error
    if len(parts) > 1:
        return _err("Archive is split into parts; request the ZIP manifest first", 409)
    return await download_job_zip_part(job_id, 1)


def _build_zip(path: str, shorts: list, folder_prefix: str = ""):
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        descriptions = []
        used_names = set()
        for index, item in enumerate(shorts):
            file_path = Path(item["filepath"])
            if not file_path.is_file():
                continue

            # Папка уже определена в плане
            folder = item.get("_zip_folder", "")
            name = item.get("filename") or file_path.name
            archive_name = f"{folder}/{name}" if folder else name
            if archive_name in used_names:
                name = f"{index + 1}_{name}"
                archive_name = f"{folder}/{name}" if folder else name
            used_names.add(archive_name)
            archive.write(str(file_path), arcname=archive_name)

            tags = item.get("tags", [])
            tags_text = tags if isinstance(tags, str) else ", ".join(str(tag) for tag in tags)
            source_name = item.get("source_name") or ""
            source_file_name = Path(source_name).name if source_name else ""
            descriptions.append(
                f"--- #{index + 1} ---\n"
                f"Имя исходного файла: {source_file_name}\n"
                f"Путь исходного видео: {source_name}\n"
                f"Файл: {archive_name}\n"
                f"Заголовок: {item.get('title', '')}\n"
                f"Описание: {item.get('description', '')}\n"
                f"Теги: {tags_text}\n"
            )

        if descriptions:
            archive.writestr("descriptions.txt", "\ufeff" + "\n".join(descriptions))

async def _save_banner_upload(banner_file, job_id: str) -> str:
    """РЎРѕС…СЂР°РЅСЏРµС‚ Р·Р°РіСЂСѓР¶РµРЅРЅС‹Р№ Р±Р°РЅРЅРµСЂ (РёР·РѕР±СЂР°Р¶РµРЅРёРµ РёР»Рё РІРёРґРµРѕ) РІ BANNER_DIR."""
    if not banner_file or not banner_file.filename:
        return None
    ext = Path(banner_file.filename).suffix or ".png"
    filename = f"banner_{job_id}{ext}"
    try:
        BANNER_DIR.mkdir(parents=True, exist_ok=True)
        path = BANNER_DIR / filename
        # Opening also verifies permissions on an existing bind-mounted folder.
        file_obj = open(path, "wb")
    except PermissionError:
        # uploads/banners can retain root ownership while /app/uploads is writable.
        path = UPLOAD_DIR / filename
        print(f"[UPLOAD] Banner directory is not writable; using {path}")
        file_obj = open(path, "wb")
    with file_obj as f:
        while True:
            chunk = await banner_file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return str(path)


async def _save_music_upload(audio_file, job_id: str) -> str:
    """РЎРѕС…СЂР°РЅСЏРµС‚ Р·Р°РіСЂСѓР¶РµРЅРЅС‹Р№ Р°СѓРґРёРѕ-С„Р°Р№Р» (РјСѓР·С‹РєР°) РІ UPLOAD_DIR."""
    if not audio_file or not audio_file.filename:
        return None
    ext = Path(audio_file.filename).suffix or ".mp3"
    path = UPLOAD_DIR / f"{job_id}_audio{ext}"
    with open(path, "wb") as f:
        while True:
            chunk = await audio_file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return str(path)


# в”Ђв”Ђ Admin в”Ђв”Ђ
@app.get("/api/admin/analytics")
async def analytics():
    from datetime import datetime, timedelta
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%d.%m") for i in range(6, -1, -1)]
    accounts = []
    tv = ts = tvc = 0
    for tf in Path(youtube_api.tokens_dir).glob("token_*.pickle"):
        email = tf.stem.replace('token_', '').replace('_', '@', 1).replace('_at_', '@')
        try:
            if youtube_api.authenticate(email):
                info = youtube_api.get_channel_info()
                if info:
                    s = info.get("statistics", {})
                    subs = int(s.get("subscriberCount", 0))
                    views = int(s.get("viewCount", 0))
                    vids = int(s.get("videoCount", 0))
                    tv += views; ts += subs; tvc += vids
                    accounts.append({"email": email, "videos_count": vids, "views": views, "subscribers": subs, "status": "active"})
                else:
                    accounts.append({"email": email, "status": "inactive"})
        except:
            accounts.append({"email": email, "status": "inactive"})
    if not accounts:
        for jid, j in jobs.items():
            if j.get("status") == "completed":
                tvc += len(j.get("shorts", []))
    return {"total_videos": tvc, "total_views": tv, "total_subscribers": ts, "accounts": accounts, "videos": []}


@app.post("/api/admin/analyze")
async def analyze(data: dict):
    import re
    url = data.get("url", "").strip()
    if not url:
        return _err("URL required")
    client = None
    if YOUTUBE_API_KEY:
        from googleapiclient.discovery import build
        client = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    if not client:
        return _err("No API key")
    m = re.search(r'(?:youtube\.com|youtu\.be)/channel/([a-zA-Z0-9_-]{10,})', url)
    channel_id = m.group(1) if m else None
    if not channel_id:
        m = re.search(r'(?:youtube\.com|youtu\.be)/@([a-zA-Z0-9_-]+)', url)
        if m:
            resp = client.search().list(part='snippet', q=m.group(1), type='channel', maxResults=1).execute()
            channel_id = resp['items'][0]['snippet']['channelId'] if resp.get('items') else None
    if not channel_id:
        return _err("Channel not found")
    try:
        chan = client.channels().list(part='snippet,statistics', id=channel_id).execute()['items'][0]
    except:
        return _err("Channel fetch failed")
    sn = chan.get('snippet', {})
    st = chan.get('statistics', {})
    videos = []
    try:
        sr = client.search().list(part='id', channelId=channel_id, type='video', maxResults=20, order='date').execute()
        vids = [i['id']['videoId'] for i in sr.get('items', [])]
        if vids:
            vr = client.videos().list(part='snippet,statistics', id=','.join(vids)).execute()
            for item in vr.get('items', []):
                vs = item.get('statistics', {})
                videos.append({"id": item['id'], "title": item.get('snippet', {}).get('title', ''), "views": int(vs.get('viewCount', 0)), "likes": int(vs.get('likeCount', 0)), "url": f"https://youtube.com/watch?v={item['id']}"})
    except:
        pass
    return {"channel": {"title": sn.get('title', ''), "subscribers": int(st.get('subscriberCount', 0)), "views": int(st.get('viewCount', 0))}, "videos": videos}


# в”Ђв”Ђ Missing frontend routes в”Ђв”Ђ

SAVED_DIR = BASE_DIR / "saved"


@app.get("/api/stats")
async def get_stats():
    total_jobs = len(jobs)
    completed = sum(1 for j in jobs.values() if j.get("status") == "completed")
    failed = sum(1 for j in jobs.values() if j.get("status") == "failed")
    running = sum(1 for j in jobs.values() if j.get("status") in ("processing", "uploading", "starting"))
    total_shorts = sum(len(j.get("shorts", [])) for j in jobs.values())
    return {
        "total_videos": len([f for f in UPLOAD_DIR.glob("*.mp4") if f.is_file()]),
        "total_shorts": total_shorts,
        "completed": completed, "failed": failed,
        "running": running, "total_jobs": total_jobs
    }


@app.delete("/api/cleanup/uploads")
async def cleanup_uploads():
    deleted = 0
    for f in UPLOAD_DIR.glob("*"):
        if f.is_file() and f.suffix in (".mp4", ".mkv", ".avi", ".mov", ".wav"):
            try:
                f.unlink(); deleted += 1
            except: pass
    return {"status": "success", "deleted": deleted}


@app.delete("/api/cleanup/output")
async def cleanup_output():
    deleted = 0
    for f in OUTPUT_DIR.rglob("*.mp4"):
        try:
            f.unlink(); deleted += 1
        except: pass
    return {"status": "success", "deleted": deleted}


@app.get("/api/saved-folders")
async def list_saved_folders():
    SAVED_DIR.mkdir(exist_ok=True)
    folders = [d.name for d in SAVED_DIR.iterdir() if d.is_dir()]
    return {"status": "success", "folders": folders}


@app.post("/api/saved-folders")
async def create_saved_folder(data: dict):
    name = data.get("folder", "").strip()
    if not name:
        return _err("Folder name required")
    (SAVED_DIR / name).mkdir(parents=True, exist_ok=True)
    return {"status": "success"}


@app.delete("/api/saved-folders")
async def delete_saved_folder(data: dict):
    name = data.get("folder", "").strip()
    if not name:
        return _err("Folder name required")
    folder = SAVED_DIR / name
    if folder.exists():
        import shutil
        shutil.rmtree(folder)
    return {"status": "success"}


@app.get("/api/projects")
async def list_projects():
    items = []
    for jid, j in jobs.items():
        items.append({
            "id": jid, "status": j.get("status"), "progress": j.get("progress", 0),
            "shorts_count": len(j.get("shorts", [])),
            "created_at": j.get("created_at", "")
        })
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"projects": items}


@app.delete("/api/jobs/old")
async def delete_old_jobs(days_old: int = 7):
    import time
    now = time.time()
    threshold = now - days_old * 86400
    deleted = 0
    import copy
    for jid in list(jobs.keys()):
        j = jobs[jid]
        created = j.get("created_at", 0)
        if isinstance(created, str):
            try:
                from datetime import datetime
                created = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").timestamp()
            except:
                created = 0
        if j.get("status") in ("completed", "failed") and created < threshold:
            del jobs[jid]
            job_logs.pop(jid, None)
            deleted += 1
    save_jobs()
    save_job_logs()
    return {"status": "success", "deleted": deleted}


@app.post("/api/jobs/cancel")
async def cancel_current_job():
    global _cancel_flag, _processing_queue, _processing_busy
    with _processing_lock:
        if not _processing_busy and not _processing_queue:
            _cancel_flag = False
            return {"status": "success", "cancelled_queued": 0, "message": "Nothing running"}
        _cancel_flag = True
        queued = list(_processing_queue)
        _processing_queue.clear()
    # Mark queued jobs as cancelled
    for fn, args in queued:
        jid = args[0] if args else None
        if jid and jid in jobs:
            jobs[jid]["status"] = "cancelled"
            jobs[jid]["error"] = "Cancelled by user"
            add_job_log(jid, "Cancelled (was in queue)", "warning")
    save_jobs()
    save_job_logs()
    return {"status": "success", "cancelled_queued": len(queued)}


def _delete_job_artifacts(jid: str) -> int:
    """Delete one project's generated files, uploads and database records."""
    job = jobs.get(jid)
    if not job:
        return 0
    deleted = 0
    for short in job.get("shorts", []):
        fp = Path(short.get("filepath", ""))
        if fp.is_file():
            try:
                fp.unlink(); deleted += 1
            except:
                pass
    patterns = (
        (UPLOAD_DIR, f"{jid}_input*"),
        (UPLOAD_DIR, f"{jid}_audio*"),
        (OUTPUT_DIR, f"subs_{jid}*"),
        (OUTPUT_DIR, f"short_{jid}_*"),
        (OUTPUT_DIR, f"freeze_{jid}*"),
        (OUTPUT_DIR, f"mus_{jid}*"),
        (BANNER_DIR, f"banner_{jid}*"),
    )
    for directory, pattern in patterns:
        for path in directory.glob(pattern):
            try:
                if path.is_file():
                    path.unlink(); deleted += 1
            except:
                pass
    jobs.pop(jid, None)
    job_logs.pop(jid, None)
    return deleted


@app.post("/api/cleanup-after-close")
async def cleanup_after_close(data: dict):
    """Delete completed session projects; page reloads must not affect active jobs."""
    ids = data.get("job_ids", [])
    if isinstance(ids, str):
        ids = [ids]
    deleted = 0
    preserved = 0
    for jid in ids:
        job = jobs.get(jid)
        if not job:
            continue
        if job.get("status") in ("processing", "queued", "starting", "downloading", "uploading"):
            job.pop("delete_after_finish", None)
            preserved += 1
            continue
        deleted += _delete_job_artifacts(jid)
    save_jobs()
    save_job_logs()
    return {"status": "success", "deleted": deleted, "preserved": preserved}


# в”Ђв”Ђ Processing endpoints (threaded) в”Ђв”Ђ

def _process_one_segment(job_id, video_path, seg_index, seg, total,
                         use_smart, full_subtitles, whisper_model,
                         crop_mode, blurred_bg, filename_keywords,
                         banner_enabled, banner_path, banner_x, banner_y, banner_w, banner_h, banner_opacity,
                         banner_style, banner_position, banner_duration, banner_full_duration,
                         save_video, save_folder,
                         music_path=None, music_volume=0.7, music_start=0.0, music_end=0.0,
                         replace_audio=False, subtitle_font_name=None):
    """РћР±СЂР°Р±Р°С‚С‹РІР°РµС‚ РѕРґРёРЅ СЃРµРіРјРµРЅС‚ РІ РѕС‚РґРµР»СЊРЅРѕРј РїРѕС‚РѕРєРµ. Р’РѕР·РІСЂР°С‰Р°РµС‚ (index, short_path) РёР»Рё None."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if _cancel_flag:
            add_job_log(job_id, f"[{seg_index+1}/{total}] Cancelled", "warning")
            return None
        add_job_log(job_id, f"[{seg_index+1}/{total}] Processing {seg['start']:.1f}s-{seg['end']:.1f}s", "progress")
        try:
            n_audio = processor.count_audio_streams(video_path)
            if n_audio > 1:
                add_job_log(job_id, f"[{seg_index+1}/{total}] Р’РЅРёРјР°РЅРёРµ: РІ РІРёРґРµРѕ {n_audio} Р°СѓРґРёРѕ-РґРѕСЂРѕР¶РєРё вЂ” Р±РµСЂС‘С‚СЃСЏ РїРµСЂРІР°СЏ", "warning")
        except Exception:
            pass

        if use_smart and full_subtitles and whisper_model == "base":
            # Р±Р°Р·РѕРІР°СЏ РјРѕРґРµР»СЊ СѓР¶Рµ РѕС‚СЃРєР°РЅРёСЂРѕРІР°Р»Р° РІРёРґРµРѕ вЂ” СЂРµР¶РµРј С‚СЂР°РЅСЃРєСЂРёРїС‚ РїРѕРґ СЃРµРіРјРµРЅС‚
            seg_subtitles = []
            for w in full_subtitles:
                if w.get("end", 0) >= seg["start"] and w.get("start", 0) <= seg["end"]:
                    seg_subtitles.append({
                        "start": max(0.0, w["start"] - seg["start"]),
                        "end": min(seg["end"] - seg["start"], w["end"] - seg["start"]),
                        "text": w.get("text", "")
                    })
            subtitle_segments = seg_subtitles
        else:
            # С‚СЂР°РЅСЃРєСЂРёР±РёСЂСѓРµРј СЃРµРіРјРµРЅС‚ РІС‹Р±СЂР°РЅРЅРѕР№ РјРѕРґРµР»СЊСЋ (РґР»СЏ РєР°С‡РµСЃС‚РІР° СЃСѓР±С‚РёС‚СЂРѕРІ)
            subtitle_data = loop.run_until_complete(
                processor.get_subtitles(video_path, seg["start"], seg["end"])
            )
            subtitle_segments = subtitle_data.get("segments", [])
        add_job_log(job_id, f"[{seg_index+1}/{total}] Subtitles: {len(subtitle_segments)} words", "info")

        short_path = loop.run_until_complete(
            processor.create_short(
                video_path, seg, seg_index, job_id,
                subtitle_segments,
                crop_mode, blurred_bg, filename_keywords,
                banner_enabled, banner_path, banner_x, banner_y,
                banner_w, banner_h, banner_opacity,
                banner_style, banner_position, banner_duration,
                banner_full_duration,
                music_path, music_volume, music_start, music_end, replace_audio,
                subtitle_font_name
            )
        )
        if not short_path or not Path(short_path).exists():
            add_job_log(job_id, f"[{seg_index+1}/{total}] Video not created", "warning")
            return None
        add_job_log(job_id, f"[{seg_index+1}/{total}] Video created", "success")
        transcript_text = " ".join(
            item.get("text", "").strip() for item in subtitle_segments
            if item.get("text", "").strip()
        )
        return (seg_index, short_path, transcript_text)
    except Exception as e:
        add_job_log(job_id, f"[{seg_index+1}/{total}] Segment error: {e}", "error")
        import traceback
        traceback.print_exc()
        return None
    finally:
        loop.close()


def _process_job_thread(job_id: str, video_path: str, short_length: int, shorts_count: int,
                        crop_mode: str, blurred_bg: bool, smart_selection: str,
                        save_video: bool, save_folder: str,
                        banner_enabled: bool, banner_x: int, banner_y: int,
                        banner_w: int, banner_h: int, banner_opacity: int,
                        filename_keywords: str = "",
                        banner_path: str = None, banner_style: str = "overlay",
                        banner_position: int = 50, banner_duration: int = 3,
                        banner_full_duration: bool = False,
                        min_short_length: int = 30, max_short_length: int = 60,
                        auto_duration: bool = False,
                        music_path: str = None, music_volume: float = 0.7,
                        music_start: float = 0.0, music_end: float = 0.0,
                        replace_audio: bool = False, scene_start: bool = False,
                        subtitle_font_name: str = None):
    """Run processing in a thread, updating jobs + job_logs"""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["started_at"] = time.time()
        add_job_log(job_id, f"Processing started", "progress")

        video_info = loop.run_until_complete(processor.get_video_info(video_path))
        dur = video_info.get("duration", 0)
        add_job_log(job_id, f"Duration: {dur:.1f}s", "info")
        add_job_log(job_id, f"Format: {crop_mode}", "info")

        # Р”Р»СЏ РІС‹Р±РѕСЂР° Р»СѓС‡С€РёС… РјРѕРјРµРЅС‚РѕРІ СЃРєР°РЅРёСЂРµРј РІРёРґРµРѕ С†РµР»РёРєРѕРј Р±С‹СЃС‚СЂРѕР№ base-РјРѕРґРµР»СЊСЋ
        if scene_start and (smart_selection or "off") == "off":
            smart_selection = "global"
        use_smart = (smart_selection or "off") != "off"
        if scene_start:
            add_job_log(job_id, "Scene start: candidates will begin at detected visual cuts", "info")
        whisper_model = _read_env("WHISPER_MODEL", "base")
        full_subtitles = None
        if use_smart:
            add_job_log(job_id, "Scanning full video (base model) for smart selection...", "info")
            def _trans_progress(pct):
                jobs[job_id]["progress"] = max(jobs[job_id].get("progress", 0), 5 + int(pct * 0.1))
                save_jobs()
                add_job_log(job_id, f"Scanning full video... {pct}%", "progress")
            full = loop.run_until_complete(
                processor.get_subtitles(video_path, 0, dur, model_size="base", progress_cb=_trans_progress)
            )
            full_subtitles = full.get("segments", [])
            add_job_log(job_id, f"Scan done: {len(full_subtitles)} words", "info")

        segments = loop.run_until_complete(
            processor.extract_segments(
                video_path, short_length, shorts_count,
                subtitle_segments=full_subtitles,
                smart_selection=smart_selection,
                auto_duration=auto_duration,
                min_length=min_short_length, max_length=max_short_length,
                scene_start=scene_start
            )
        )
        add_job_log(job_id, f"Found {len(segments)} segments", "success")

        _seg_args = (use_smart, full_subtitles, whisper_model,
                     crop_mode, blurred_bg, filename_keywords,
                     banner_enabled, banner_path, banner_x, banner_y, banner_w, banner_h, banner_opacity,
                     banner_style, banner_position, banner_duration, banner_full_duration,
                     save_video, save_folder,
                     music_path, music_volume, music_start, music_end, replace_audio,
                     subtitle_font_name)

        results = []
        workers = max(1, int(_read_env("SEGMENT_WORKERS", "2")))
        if workers > 1 and len(segments) > 1:
            from concurrent.futures import ThreadPoolExecutor
            add_job_log(job_id, f"Processing {len(segments)} segments in parallel ({workers} workers)...", "info")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [
                    ex.submit(_process_one_segment, job_id, video_path, i, seg, len(segments), *_seg_args)
                    for i, seg in enumerate(segments)
                ]
                for f in futures:
                    r = f.result()
                    if r:
                        results.append(r)
        else:
            for i, seg in enumerate(segments):
                r = _process_one_segment(job_id, video_path, i, seg, len(segments), *_seg_args)
                if r:
                    results.append(r)
                if _cancel_flag:
                    add_job_log(job_id, f"Cancelled after {len(results)} shorts", "warning")
                    break

        # СЃРѕР±РёСЂР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹ РІ РїРѕСЂСЏРґРєРµ РёРЅРґРµРєСЃРѕРІ
        shorts_list = []
        for i, short_path, transcript_text in sorted(results, key=lambda item: item[0]):
            add_job_log(job_id, f"[{i+1}/{len(results)}] Generating AI metadata...", "info")
            metadata = loop.run_until_complete(
                ai_service.generate_metadata(transcript_text, i + 1, video_info)
            )
            if metadata.get("_ai_error"):
                add_job_log(
                    job_id,
                    f"[{i+1}/{len(results)}] AI fallback: {metadata['_ai_error']}",
                    "warning"
                )
            for warning in metadata.get("_ai_warnings", []):
                add_job_log(job_id, f"[{i+1}/{len(results)}] AI warning: {warning}", "warning")
            title = metadata["title"]
            description = metadata["description"]
            tags = metadata["tags"]
            shorts_list.append({"path": short_path, "title": title, "description": description, "tags": tags})
            jobs[job_id].setdefault("shorts", []).append({
                "index": i, "filename": Path(short_path).name,
                "filepath": short_path, "title": title,
                "description": description, "tags": tags
            })
        jobs[job_id]["progress"] = 20 + min(70, len(results) * 70 // max(1, len(segments)))
        save_jobs()

        if _cancel_flag:
            jobs[job_id]["status"] = "cancelled"
            add_job_log(job_id, "Cancelled by user", "warning")
        else:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["progress"] = 100
            add_job_log(job_id, f"Completed! Created {len(shorts_list)} shorts", "success")
        save_jobs()
        save_job_logs()
    except Exception as e:
        jobs[job_id]["status"] = "cancelled" if _cancel_flag else "failed"
        jobs[job_id]["error"] = str(e)
        add_job_log(job_id, f"Error: {e}", "error")
        save_jobs()
        save_job_logs()
        import traceback
        traceback.print_exc()
    finally:
        loop.close()
        if jobs.get(job_id, {}).get("delete_after_finish"):
            _delete_job_artifacts(job_id)
            save_jobs()
            save_job_logs()


def _allocate_folder_shorts(durations: list[float], total: int, adaptive: bool = True) -> list[int]:
    """Distribute a folder-wide quota by source duration, keeping short files represented."""
    count = len(durations)
    quotas = [0] * count
    if count == 0 or total <= 0:
        return quotas

    normalized = [max(0.0, float(duration or 0.0)) for duration in durations]
    if total < count:
        order = sorted(range(count), key=lambda i: normalized[i], reverse=True) if adaptive else list(range(count))
        for index in order[:total]:
            quotas[index] = 1
        return quotas

    quotas = [1] * count
    extra = total - count
    weight_sum = sum(normalized)
    weights = normalized if adaptive and weight_sum > 0 else [1.0] * count
    weight_sum = sum(weights)
    exact = [extra * weight / weight_sum for weight in weights]
    floors = [int(value) for value in exact]
    quotas = [base + addition for base, addition in zip(quotas, floors)]
    left = extra - sum(floors)
    order = sorted(range(count), key=lambda i: (exact[i] - floors[i], weights[i]), reverse=True)
    for index in order[:left]:
        quotas[index] += 1
    return quotas


def _process_folder_thread(job_id: str, video_paths: list, short_length: int, shorts_count: int,
                           crop_mode: str, blurred_bg: bool, smart_selection: str,
                           save_video: bool, save_folder: str,
                           banner_enabled: bool, banner_x: int, banner_y: int,
                           banner_w: int, banner_h: int, banner_opacity: int,
                           filename_keywords: str = "",
                           banner_path: str = None, banner_style: str = "overlay",
                           banner_position: int = 50, banner_duration: int = 3,
                           banner_full_duration: bool = False,
                           min_short_length: int = 30, max_short_length: int = 60,
                           auto_duration: bool = False,
                           music_path: str = None, music_volume: float = 0.7,
                           music_start: float = 0.0, music_end: float = 0.0,
                           replace_audio: bool = False, scene_start: bool = False,
                           subtitle_font_name: str = None,
                           adaptive_folder_allocation: bool = True):
    """Process multiple videos, distributing shorts_count across them"""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    jobs[job_id]["status"] = "processing"
    jobs[job_id]["started_at"] = time.time()
    total_made = 0
    try:
        video_infos = []
        durations = []
        for _, vpath in video_paths:
            info = loop.run_until_complete(processor.get_video_info(vpath))
            video_infos.append(info)
            durations.append(max(0.0, float(info.get("duration", 0) or 0)))

        initial_quotas = _allocate_folder_shorts(durations, shorts_count, adaptive_folder_allocation)
        allocation = ", ".join(str(quota) for quota in initial_quotas)
        allocation_mode = "by duration" if adaptive_folder_allocation else "equally"
        add_job_log(job_id, f"Folder quota {allocation_mode}: {allocation} (total {sum(initial_quotas)})", "info")

        for vidx, (fname, vpath) in enumerate(video_paths):
            if _cancel_flag:
                add_job_log(job_id, "Cancelled by user", "warning")
                break
            if total_made >= shorts_count:
                add_job_log(job_id, f"Reached target {shorts_count} shorts, stopping")
                break

            remaining = shorts_count - total_made
            remaining_quotas = _allocate_folder_shorts(durations[vidx:], remaining, adaptive_folder_allocation)
            per_video = remaining_quotas[0] if remaining_quotas else 0
            if per_video <= 0:
                continue
            add_job_log(job_id, f"[Video {vidx+1}/{len(video_paths)}] {fname} вЂ” {per_video} shorts", "info")

            video_info = video_infos[vidx]
            dur = durations[vidx]
            add_job_log(job_id, f"[Video {vidx+1}] Duration: {dur:.1f}s", "info")
            add_job_log(job_id, f"[Video {vidx+1}] Format: {crop_mode}", "info")

            if scene_start and (smart_selection or "off") == "off":
                smart_selection = "global"
            use_smart = (smart_selection or "off") != "off"
            if scene_start:
                add_job_log(job_id, f"[Video {vidx+1}] Scene start enabled", "info")
            whisper_model = _read_env("WHISPER_MODEL", "base")
            full_subtitles = None
            if use_smart:
                add_job_log(job_id, f"[Video {vidx+1}] Scanning full video (base model) for smart selection...", "info")
                def _trans_progress(pct):
                    jobs[job_id]["progress"] = max(jobs[job_id].get("progress", 0), 5 + int(pct * 0.1))
                    save_jobs()
                    add_job_log(job_id, f"[Video {vidx+1}] Scanning full video... {pct}%", "progress")
                full = loop.run_until_complete(
                    processor.get_subtitles(vpath, 0, dur, model_size="base", progress_cb=_trans_progress)
                )
                full_subtitles = full.get("segments", [])
                add_job_log(job_id, f"[Video {vidx+1}] Scan done: {len(full_subtitles)} words", "info")

            segments = loop.run_until_complete(
                processor.extract_segments(
                    vpath, short_length, per_video,
                    subtitle_segments=full_subtitles,
                    smart_selection=smart_selection,
                    auto_duration=auto_duration,
                    min_length=min_short_length, max_length=max_short_length,
                    scene_start=scene_start
                )
            )
            add_job_log(job_id, f"[Video {vidx+1}] Found {len(segments)} segments", "info")

            for i, seg in enumerate(segments):
                if _cancel_flag:
                    add_job_log(job_id, "Cancelled by user", "warning")
                    break
                if total_made >= shorts_count:
                    break
                idx = total_made
                add_job_log(job_id, f"[{idx+1}/{shorts_count}] Processing {seg['start']:.1f}s-{seg['end']:.1f}s", "progress")

                if use_smart and full_subtitles and whisper_model == "base":
                    seg_subtitles = []
                    for w in full_subtitles:
                        if w.get("end", 0) >= seg["start"] and w.get("start", 0) <= seg["end"]:
                            seg_subtitles.append({
                                "start": max(0.0, w["start"] - seg["start"]),
                                "end": min(seg["end"] - seg["start"], w["end"] - seg["start"]),
                                "text": w.get("text", "")
                            })
                    subtitle_segments = seg_subtitles
                else:
                    subtitle_data = loop.run_until_complete(
                        processor.get_subtitles(vpath, seg["start"], seg["end"])
                    )
                    subtitle_segments = subtitle_data.get("segments", [])
                add_job_log(job_id, f"[{idx+1}/{shorts_count}] Subtitles: {len(subtitle_segments)} words", "info")

                short_path = loop.run_until_complete(
                    processor.create_short(
                        vpath, seg, idx, job_id,
                        subtitle_segments,
                        crop_mode, blurred_bg, filename_keywords,
                        banner_enabled, banner_path, banner_x, banner_y,
                        banner_w, banner_h, banner_opacity,
                        banner_style, banner_position, banner_duration,
                        banner_full_duration,
                        music_path, music_volume, music_start, music_end, replace_audio,
                        subtitle_font_name
                    )
                )

                if not short_path or not Path(short_path).exists():
                    add_job_log(job_id, f"[{idx+1}/{shorts_count}] Video not created", "warning")
                    continue

                add_job_log(job_id, f"[{idx+1}/{shorts_count}] Video created", "success")
                total_made += 1

                transcript_text = " ".join(
                    item.get("text", "").strip() for item in subtitle_segments
                    if item.get("text", "").strip()
                )
                add_job_log(job_id, f"[{idx+1}/{shorts_count}] Generating AI metadata...", "info")
                metadata = loop.run_until_complete(
                    ai_service.generate_metadata(transcript_text, idx + 1, video_info)
                )
                if metadata.get("_ai_error"):
                    add_job_log(
                        job_id,
                        f"[{idx+1}/{shorts_count}] AI fallback: {metadata['_ai_error']}",
                        "warning"
                    )
                for warning in metadata.get("_ai_warnings", []):
                    add_job_log(job_id, f"[{idx+1}/{shorts_count}] AI warning: {warning}", "warning")
                title = metadata["title"]
                description = metadata["description"]
                tags = metadata["tags"]

                jobs[job_id].setdefault("shorts", []).append({
                    "index": idx, "filename": Path(short_path).name,
                    "filepath": short_path, "title": title,
                    "description": description, "tags": tags,
                    "source_name": fname
                })
                jobs[job_id]["progress"] = min(95, 20 + (idx + 1) * 70 // shorts_count)
                save_jobs()

                if save_video:
                    saved = SAVED_DIR / (save_folder or "saved")
                    saved.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(short_path, saved / f"short_{job_id}_{idx}.mp4")
                    add_job_log(job_id, f"[{idx+1}/{shorts_count}] Saved", "success")

            if total_made >= shorts_count:
                break

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        add_job_log(job_id, f"Completed! Created {total_made} shorts from {len(video_paths)} videos", "success")
        save_jobs()
        save_job_logs()
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        add_job_log(job_id, f"Error: {e}", "error")
        save_jobs()
        save_job_logs()
        import traceback
        traceback.print_exc()
    finally:
        loop.close()
        if jobs.get(job_id, {}).get("delete_after_finish"):
            _delete_job_artifacts(job_id)
            save_jobs()
            save_job_logs()


@app.post("/api/upload-file")
async def upload_file(
    file: UploadFile = File(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    smart_selection: str = Form("off"),
    scene_start: bool = Form(False),
    subtitle_font: str = Form(""),
    blurred_bg: bool = Form(False),
    crop_mode: str = Form("square"),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    banner_enabled: bool = Form(False),
    banner_x: int = Form(0), banner_y: int = Form(0),
    banner_w: int = Form(1080), banner_h: int = Form(200), banner_opacity: int = Form(100),
    banner_file: UploadFile = File(None),
    banner_style: str = Form("overlay"),
    banner_position: int = Form(50), banner_duration: int = Form(3),
    banner_full_duration: bool = Form(False),
    min_short_length: int = Form(30), max_short_length: int = Form(60),
    auto_duration: bool = Form(False),
    filename_keywords: str = Form(""),
    audio_file: UploadFile = File(None),
    enable_audio: bool = Form(False),
    music_volume: float = Form(0.7),
    audio_start: float = Form(0.0), audio_end: float = Form(0.0),
    replace_audio: bool = Form(False)
):
    job_id = str(uuid.uuid4())
    safe = f"{job_id}_input.mp4"
    video_path = str(UPLOAD_DIR / safe)
    banner_path = await _save_banner_upload(banner_file, job_id)
    music_path = await _save_music_upload(audio_file, job_id) if enable_audio else None

    file_size = 0
    with open(video_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            f.write(chunk)
            file_size += len(chunk)

    file_size_mb = file_size / (1024*1024)
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0,
                     "shorts_count": shorts_count, "short_length": short_length,
                     "source": "file", "filename": file.filename,
                     "file_size_mb": round(file_size_mb, 1),
                     "created_at": now_str, "shorts": []}
    save_jobs()
    add_job_log(job_id, f"File: {file.filename} ({file_size_mb:.1f} MB)", "info")
    if music_path:
        add_job_log(job_id, "Music track added (volume {:.0f}%)".format(music_volume * 100), "info")

    started = _enqueue_job(_process_job_thread, (
        job_id, video_path, short_length, shorts_count,
        crop_mode, blurred_bg, smart_selection,
        save_video, save_folder,
        banner_enabled, banner_x, banner_y,
        banner_w, banner_h, banner_opacity,
        filename_keywords,
        banner_path, banner_style, banner_position, banner_duration,
        banner_full_duration,
        min_short_length, max_short_length, auto_duration,
        music_path, music_volume, audio_start, audio_end, replace_audio,
        scene_start, subtitle_font or None
    ))

    return {"job_id": job_id, "status": "started" if started else "queued"}


@app.post("/api/upload-folder")
async def upload_folder(
    files: List[UploadFile] = File(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    smart_selection: str = Form("off"),
    scene_start: bool = Form(False),
    subtitle_font: str = Form(""),
    blurred_bg: bool = Form(False),
    crop_mode: str = Form("square"),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    banner_enabled: bool = Form(False),
    banner_x: int = Form(0), banner_y: int = Form(0),
    banner_w: int = Form(1080), banner_h: int = Form(200), banner_opacity: int = Form(100),
    banner_file: UploadFile = File(None),
    banner_style: str = Form("overlay"),
    banner_position: int = Form(50), banner_duration: int = Form(3),
    banner_full_duration: bool = Form(False),
    min_short_length: int = Form(30), max_short_length: int = Form(60),
    auto_duration: bool = Form(False),
    filename_keywords: str = Form(""),
    audio_file: UploadFile = File(None),
    enable_audio: bool = Form(False),
    music_volume: float = Form(0.7),
    audio_start: float = Form(0.0), audio_end: float = Form(0.0),
    replace_audio: bool = Form(False),
    adaptive_folder_allocation: bool = Form(True)
):
    job_id = str(uuid.uuid4())
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    banner_path = await _save_banner_upload(banner_file, job_id)
    music_path = await _save_music_upload(audio_file, job_id) if enable_audio else None
    jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0,
                     "shorts_count": shorts_count, "short_length": short_length,
                     "source": "folder", "created_at": now_str, "shorts": []}
    save_jobs()
    add_job_log(job_id, f"Folder: {len(files)} videos", "info")
    if music_path:
        add_job_log(job_id, "Music track added (volume {:.0f}%)".format(music_volume * 100), "info")

    # Save all files first
    video_paths = []
    for i, f in enumerate(files):
        safe = f"{job_id}_input_{i}.mp4"
        path = str(UPLOAD_DIR / safe)
        with open(path, "wb") as fh:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk: break
                fh.write(chunk)
        video_paths.append((f.filename or f"video_{i}", path))
        add_job_log(job_id, f"Saved: {video_paths[-1][0]}", "info")

    add_job_log(job_id, f"All {len(video_paths)} videos saved, starting processing", "info")

    started = _enqueue_job(_process_folder_thread, (
        job_id, video_paths, short_length, shorts_count,
        crop_mode, blurred_bg, smart_selection,
        save_video, save_folder,
        banner_enabled, banner_x, banner_y,
        banner_w, banner_h, banner_opacity,
        filename_keywords,
        banner_path, banner_style, banner_position, banner_duration,
        banner_full_duration,
        min_short_length, max_short_length, auto_duration,
        music_path, music_volume, audio_start, audio_end, replace_audio,
        scene_start, subtitle_font or None, adaptive_folder_allocation
    ))

    return {"job_id": job_id, "status": "started" if started else "queued"}


# в”Ђв”Ђ Docs page в”Ђв”Ђ
DOCS_DIR = BASE_DIR / "docs"
DOCS_DIR.mkdir(exist_ok=True)


@app.get("/api/docs-list")
async def docs_list():
    docs = []
    for f in sorted(DOCS_DIR.iterdir()) if DOCS_DIR.exists() else []:
        if f.is_file():
            name = f.name.replace("_", " ").replace(".md", "").replace(".txt", "")
            docs.append({"file": f.name, "name": name, "desc": _DOC_DESCRIPTIONS.get(f.name, "")})
    return {"status": "success", "docs": docs}


_DOC_DESCRIPTIONS = {
    "full_pipeline.md": "Как работает полный цикл: от загрузки видео до готовых шортсов",
    "git_workflow.md": "Работа с Git: коммиты, ветки, push и деплой",
    "optimal_settings.md": "Настройки для разной длины и типа исходного видео",
    "smart_selection.md": "Smart Selection и «Авто-длительность»: руководство пользователя",
    "smart_selection_algo.md": "Smart Selection: расширенное описание алгоритмов и Auto-duration",
    "termux_setup.md": "Запуск бота на Android через Termux",
    "youtube_api_credentials.txt": "Получение credentials для YouTube API: пошаговая инструкция",
}


@app.get("/docs-local", response_class=HTMLResponse)
async def docs_page():
    files = sorted(DOCS_DIR.iterdir()) if DOCS_DIR.exists() else []
    links = "".join(
        f'<a href="/docs-file/{f.name}" class="doc-link">'
        f'<div class="name">{f.name.replace("_", " ").replace(".md","").replace(".txt","")}</div>'
        f'<div class="desc">{_DOC_DESCRIPTIONS.get(f.name, "")}</div></a>'
        for f in files if f.is_file()
    )
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Документация</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh}}
.header{{background:linear-gradient(135deg,#1f2937,#111827);padding:2rem 1rem;text-align:center;border-bottom:1px solid #30363d}}
.header h1{{font-size:1.8rem;font-weight:700;margin-bottom:.5rem}}
.header p{{color:#8b949e;font-size:.95rem}}
.container{{max-width:800px;margin:0 auto;padding:1.5rem 1rem}}
.doc-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1rem}}
.doc-link{{display:block;background:#161b22;border:1px solid #30363d;border-radius:12px;padding:1.2rem;text-decoration:none;color:#e6edf3;transition:all .2s}}
.doc-link:hover{{border-color:#58a6ff;background:#1c2333;transform:translateY(-2px)}}
.doc-link .name{{font-size:1.05rem;font-weight:600;color:#58a6ff}}
.doc-link .desc{{font-size:.85rem;color:#8b949e;margin-top:.3rem}}
.back{{display:inline-block;margin-bottom:1rem;color:#8b949e;text-decoration:none;font-size:.9rem}}
.back:hover{{color:#58a6ff}}
</style></head>
<body>
<div class="header"><h1>📖 Документация</h1><p>Руководства и справка по Video to Shorts Bot</p></div>
<div class="container"><div class="doc-grid">{links}</div></div>
</body></html>""")


@app.get("/docs-file/{filename}")
async def docs_file(filename: str):
    f = DOCS_DIR / filename
    if not f.exists() or not f.is_file():
        return _err("Not found", 404)
    import markdown
    content_raw = f.read_text(encoding="utf-8")
    # If it's a .md file, render as markdown
    if filename.endswith(".md"):
        html_body = markdown.markdown(content_raw, extensions=["fenced_code", "codehilite"])
    else:
        html_body = f"<pre style='background:#161b22;padding:1.5rem;border-radius:8px;overflow-x:auto;font-size:.9rem;line-height:1.5'>{content_raw}</pre>"
    name_display = filename.replace("_", " ").replace(".md","").replace(".txt","")
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{name_display}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh;padding:2rem 1rem}}
.container{{max-width:900px;margin:0 auto}}
h1{{font-size:1.5rem;margin-bottom:1rem;padding-bottom:.5rem;border-bottom:1px solid #30363d}}
h2{{font-size:1.2rem;margin:1.5rem 0 .5rem;color:#58a6ff}}
h3{{font-size:1.05rem;margin:1rem 0 .5rem;color:#79c0ff}}
p{{margin:.5rem 0;line-height:1.6;color:#c9d1d9}}
code{{background:#1f2937;padding:.15em .4em;border-radius:4px;font-size:.88em;color:#f0c674}}
pre code{{background:none;padding:0;color:inherit}}
pre{{background:#161b22;padding:1.2rem;border-radius:8px;overflow-x:auto;margin:.8rem 0;border:1px solid #30363d;font-size:.88rem;line-height:1.5}}
ul,ol{{margin:.5rem 0;padding-left:1.5rem;line-height:1.6}}
li{{margin:.3rem 0}}
a{{color:#58a6ff;text-decoration:none}}
a:hover{{text-decoration:underline}}
blockquote{{border-left:3px solid #30363d;padding:.5rem 1rem;margin:.8rem 0;color:#8b949e;background:#161b22;border-radius:0 8px 8px 0}}
.back{{display:inline-block;margin-bottom:1rem;color:#8b949e;text-decoration:none;font-size:.9rem}}
.back:hover{{color:#58a6ff}}
.nav{{margin-bottom:1.5rem}}
</style></head>
<body>
<div class="container">
<div class="nav"><a href="/docs-local" class="back">← Назад к списку</a></div>
<h1>{name_display}</h1>
{html_body}
</div>
</body></html>""")
