import os
import sys
import json
import time
import uuid
import hashlib
import threading
import asyncio
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

os.environ["PATH"] = ";".join([
    r"C:\Users\DOM\AppData\Roaming\Python\Python311\site-packages\nvidia\cublas\bin",
    r"C:\Users\DOM\AppData\Roaming\Python\Python311\site-packages\nvidia\cuda_nvrtc\bin",
    r"C:\Users\DOM\AppData\Roaming\Python\Python311\site-packages\nvidia\cuda_runtime\bin",
    r"C:\Users\DOM\AppData\Roaming\Python\Python311\site-packages\nvidia\cudnn\bin",
    os.environ.get("PATH", ""),
])

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

from processor import VideoProcessor, _read_env
from ai_service import AIService
from youtube_api import YouTubeAPI
from api_keys import get_keys, add_key, remove_key, masked_keys, set_keys

BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
USERS_FILE = BASE_DIR / "users.json"
SESSIONS_FILE = BASE_DIR / "sessions.json"
JOBS_FILE = BASE_DIR / "jobs.json"
JOB_LOGS_FILE = BASE_DIR / "job_logs.json"
PRESETS_FILE = BASE_DIR / "presets.json"
FONTS_DIR = BASE_DIR / "fonts"
BANNER_DIR = UPLOAD_DIR / "banners"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
BANNER_DIR.mkdir(exist_ok=True)

processor = VideoProcessor(str(UPLOAD_DIR), str(OUTPUT_DIR))
ai_service = AIService()
youtube_api = YouTubeAPI(
    client_secret_file=str(BASE_DIR / "client_secret.json"),
    tokens_dir=str(BASE_DIR / "tokens")
)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

ROLES = {
    "admin": ["create_shorts", "delete_shorts", "manage_accounts", "settings", "cleanup", "view_all", "delete_all"],
    "editor": ["create_shorts", "view_all"],
    "viewer": ["view_all"]
}


def _ok(data):
    return JSONResponse({"status": "success", **data})


def _err(msg, code=400):
    return JSONResponse({"status": "error", "message": msg}, status_code=code)


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
    if len(job_logs[job_id]) > 10000:
        job_logs[job_id] = job_logs[job_id][-10000:]
    now = time.time()
    if now - _last_log_save > 5.0:
        _last_log_save = now
        save_job_logs()


def load_users():
    return _load_json(USERS_FILE)


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


# ── Попробуем подключить новые модули (необязательно) ──
_use_db = False
try:
    from app.core.database import init_db, close_db, get_session
    from app.core.redis import init_redis, close_redis
    _use_db = True
except Exception as e:
    print(f"[DB] Not available (non-fatal): {e}")

# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
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


# ── Старые (JSON-based) роуты ──

def verify(request: Request):
    token = request.headers.get('Authorization') or request.cookies.get('token')
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return sessions[token]


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
    user = next((u for u in users if u['username'] == username and u['password'] == hsh(password)), None)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = str(uuid.uuid4())
    sessions[token] = {"username": username, "role": user.get("role", "viewer")}
    _save_json(SESSIONS_FILE, sessions)
    resp = JSONResponse({"token": token, "username": username, "role": user.get("role", "viewer")})
    resp.set_cookie("token", token, httponly=False, max_age=86400*30, path="/", samesite="lax")
    return resp


@app.post("/api/logout")
async def logout(request: Request):
    t = request.cookies.get('token')
    sessions.pop(t, None)
    _save_json(SESSIONS_FILE, sessions)
    resp = JSONResponse({"status": "success"})
    resp.delete_cookie("token")
    return resp


@app.get("/api/users")
async def get_users():
    return {"status": "success", "users": [{"username": u["username"], "role": u.get("role", "viewer")} for u in load_users()]}


@app.post("/api/users")
async def create_user(username: str = Form(...), password: str = Form(...), role: str = Form("viewer")):
    users = load_users()
    i = next((idx for idx, u in enumerate(users) if u["username"] == username), -1)
    d = {"username": username, "password": hsh(password), "role": role}
    if i >= 0:
        users[i] = d
    else:
        users.append(d)
    save_users(users)
    return {"status": "success"}


@app.delete("/api/users/{username}")
async def delete_user(username: str):
    save_users([u for u in load_users() if u["username"] != username])
    return {"status": "success"}


@app.get("/api/roles")
async def get_roles():
    return {"roles": ROLES}


@app.get("/api/fonts")
async def get_fonts():
    return {"fonts": ["Arial", "Verdana", "Impact", "Montserrat", "Bebas Neue", "Russo One", "Obelix Pro", "Intro Rust"]}


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


@app.get("/api/settings")
async def get_settings():
    return JSONResponse({
        "settings": {
            "crop_mode": _read_env("VIDEO_CROP_MODE", "9:16"),
            "zoom_enabled": _read_env("VIDEO_ZOOM_ENABLE", "0") == "1",
            "font": _read_env("SUBTITLE_FONT", "Montserrat"),
            "style": _read_env("SUBTITLE_STYLE", "normal"),
            "fontsize": int(_read_env("SUBTITLE_FONTSIZE", "100")),
            "fontcolor": _read_env("SUBTITLE_FONTCOLOR", "white"),
            "position": int(_read_env("SUBTITLE_POSITION_Y", "1670")),
            "capitalize": _read_env("SUBTITLE_CAPITALIZE", "1") == "1",
            "borderw": int(_read_env("SUBTITLE_BORDERW", "3")),
            "bordercolor": _read_env("SUBTITLE_BORDERCOLOR", "black"),
            "boxborder": int(_read_env("SUBTITLE_BOX_BORDER", "0")),
            "boxcolor": _read_env("SUBTITLE_BOX_COLOR", "black@0.8"),
            "shadowx": int(_read_env("SUBTITLE_SHADOW_X", "2")),
            "shadowy": int(_read_env("SUBTITLE_SHADOW_Y", "2")),
            "shadowcolor": _read_env("SUBTITLE_SHADOW_COLOR", "black"),
            "words_count": int(_read_env("SUBTITLE_WORDS_COUNT", "3")),
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
    crop_mode: str = Form("9:16"), zoom_enabled: bool = Form(False),
    borderw: int = Form(3), bordercolor: str = Form("black"),
    boxborder: int = Form(0), boxcolor: str = Form("black@0.8"),
    shadowx: int = Form(2), shadowy: int = Form(2), shadowcolor: str = Form("black"),
    words_count: int = Form(3), word_fade: bool = Form(True),
    whisper_model: str = Form("base"),
    api_provider: Optional[str] = Form(None), api_key: Optional[str] = Form(None),
    banner_x: str = Form("0"), banner_y: str = Form("0"),
    banner_w: str = Form("1080"), banner_h: str = Form("200"), banner_opacity: str = Form("100")
):
    from dotenv import set_key, unset_key, load_dotenv

    # Сохраняем новый API-ключ в общий список ключей (failover)
    if api_key and api_provider in ("groq", "openai"):
        add_key(api_provider, api_key)

    _keys = {"groq": ",".join(get_keys("groq")), "openai": ",".join(get_keys("openai"))}

    keys_to_set = {
        "GROQ_API_KEY": _keys["groq"] or _read_env('GROQ_API_KEY', ''),
        "OPENAI_API_KEY": _keys["openai"] or _read_env('OPENAI_API_KEY', ''),
        "VIDEO_CROP_MODE": crop_mode,
        "VIDEO_ZOOM_ENABLE": '1' if zoom_enabled else '0',
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

    env_path = BASE_DIR / ".env"
    for key, val in keys_to_set.items():
        set_key(str(env_path), key, val)

    # Reload env
    load_dotenv(str(env_path), override=True)
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
    """Возвращает длительность видео по URL (YouTube и др.) через yt-dlp, без скачивания."""
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
        return _err(f"Не удалось получить данные: {e}")


# ── Jobs / Integration ──


# ── YouTube ──
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
async def get_logs(job_id: str):
    logs = job_logs.get(job_id, [])
    return {"logs": logs, "status": jobs.get(job_id, {}).get("status", "unknown"), "progress": jobs.get(job_id, {}).get("progress", 0)}


@app.get("/api/jobs")
async def list_jobs_api():
    return {"jobs": [{"id": jid, "status": j.get("status"), "progress": j.get("progress", 0), "shorts_count": len(j.get("shorts", [])), "created_at": j.get("created_at")} for jid, j in jobs.items()]}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    j = jobs.get(job_id)
    if not j:
        return _err("Not found", 404)
    shorts = j.get("shorts", [])
    return {
        "status": j.get("status", "unknown"),
        "progress": j.get("progress", 0),
        "error": j.get("error", ""),
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


@app.get("/api/download-zip/{job_id}")
async def download_job_zip(job_id: str):
    import tempfile, zipfile, functools
    j = jobs.get(job_id)
    if not j:
        return _err("Job not found", 404)
    shorts = j.get("shorts", [])
    if not shorts:
        return _err("No shorts", 404)

    # Проверяем что файлы существуют
    valid = [s for s in shorts if Path(s.get("filepath", "")).exists()]
    if not valid:
        return _err("No files found on disk", 404)

    total_gb = sum(Path(s["filepath"]).stat().st_size for s in valid) / (1024**3)
    print(f"[ZIP] Packing {len(valid)} files ({total_gb:.1f}GB) for job {job_id}...")

    # Генерируем ZIP в temp файле (в отдельном потоке, чтоб не блокировать event loop)
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, functools.partial(_build_zip, tmp.name, valid))
    print(f"[ZIP] Done, streaming {tmp.name}...")

    async def stream_file():
        with open(tmp.name, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk: break
                yield chunk
        os.unlink(tmp.name)

    return StreamingResponse(stream_file(), media_type="application/zip",
                              headers={"Content-Disposition": f'attachment; filename="shorts_{job_id}.zip"'})

def _build_zip(path: str, shorts: list):
    """Синхронная сборка ZIP (запускается в thread pool)"""
    import zipfile
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for s in shorts:
            fp = Path(s["filepath"])
            if fp.exists():
                zf.write(str(fp), arcname=s.get("filename", fp.name))


async def _save_banner_upload(banner_file, job_id: str) -> str:
    """Сохраняет загруженный баннер (изображение или видео) в BANNER_DIR."""
    if not banner_file or not banner_file.filename:
        return None
    ext = Path(banner_file.filename).suffix or ".png"
    path = BANNER_DIR / f"banner_{job_id}{ext}"
    with open(path, "wb") as f:
        while True:
            chunk = await banner_file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return str(path)


# ── Admin ──
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


# ── Missing frontend routes ──

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


# ── Processing endpoints (threaded) ──

def _process_job_thread(job_id: str, video_path: str, short_length: int, shorts_count: int,
                        blurred_bg: bool, crop_fill: bool, smart_selection: str,
                        save_video: bool, save_folder: str,
                        banner_enabled: bool, banner_x: int, banner_y: int,
                        banner_w: int, banner_h: int, banner_opacity: int,
                        filename_keywords: str = "",
                        banner_path: str = None, banner_style: str = "overlay",
                        banner_position: int = 50, banner_duration: int = 3,
                        min_short_length: int = 30, max_short_length: int = 60,
                        auto_duration: bool = False):
    """Run processing in a thread, updating jobs + job_logs"""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        jobs[job_id]["status"] = "processing"
        add_job_log(job_id, f"Processing: {video_path}", "progress")

        video_info = loop.run_until_complete(processor.get_video_info(video_path))
        dur = video_info.get("duration", 0)
        add_job_log(job_id, f"Duration: {dur:.1f}s", "info")

        # Для выбора лучших моментов сканируем видео целиком быстрой base-моделью
        use_smart = (smart_selection or "off") != "off" or auto_duration
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
                min_length=min_short_length, max_length=max_short_length
            )
        )
        add_job_log(job_id, f"Found {len(segments)} segments", "success")

        shorts_list = []
        for i, seg in enumerate(segments):
            if _cancel_flag:
                add_job_log(job_id, f"Cancelled at short {i+1}/{len(segments)}", "warning")
                break
            add_job_log(job_id, f"[{i+1}/{len(segments)}] Processing {seg['start']:.1f}s-{seg['end']:.1f}s", "progress")

            if use_smart and full_subtitles and whisper_model == "base":
                # базовая модель уже отсканировала видео — режем транскрипт под сегмент
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
                # транскрибируем сегмент выбранной моделью (для качества субтитров)
                subtitle_data = loop.run_until_complete(
                    processor.get_subtitles(video_path, seg["start"], seg["end"])
                )
                subtitle_segments = subtitle_data.get("segments", [])
            add_job_log(job_id, f"[{i+1}/{len(segments)}] Subtitles: {len(subtitle_segments)} words", "info")

            short_path = loop.run_until_complete(
                processor.create_short(
                    video_path, seg, i, job_id,
                    subtitle_segments,
                    blurred_bg, filename_keywords, crop_fill,
                    banner_enabled, banner_path, banner_x, banner_y,
                    banner_w, banner_h, banner_opacity,
                    banner_style, banner_position, banner_duration
                )
            )

            if not short_path or not Path(short_path).exists():
                add_job_log(job_id, f"[{i+1}/{len(segments)}] Video not created", "warning")
                continue

            add_job_log(job_id, f"[{i+1}/{len(segments)}] Video created", "success")

            title = f"#shorts #{i+1}"
            description = "Подпишись!"
            tags = ["#shorts", "#viral"]

            shorts_list.append({"path": short_path, "title": title, "description": description, "tags": tags})

            jobs[job_id].setdefault("shorts", []).append({
                "index": i, "filename": Path(short_path).name,
                "filepath": short_path, "title": title,
                "description": description, "tags": tags
            })
            jobs[job_id]["progress"] = 20 + (i + 1) * 40 // len(segments)
            save_jobs()

            if save_video:
                saved = SAVED_DIR / (save_folder or "saved")
                saved.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(short_path, saved / f"short_{job_id}_{i}.mp4")
                add_job_log(job_id, f"[{i+1}/{len(segments)}] Saved to {save_folder}", "success")

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


def _process_folder_thread(job_id: str, video_paths: list, short_length: int, shorts_count: int,
                           blurred_bg: bool, crop_fill: bool, smart_selection: str,
                           save_video: bool, save_folder: str,
                           banner_enabled: bool, banner_x: int, banner_y: int,
                           banner_w: int, banner_h: int, banner_opacity: int,
                           filename_keywords: str = "",
                           banner_path: str = None, banner_style: str = "overlay",
                           banner_position: int = 50, banner_duration: int = 3,
                           min_short_length: int = 30, max_short_length: int = 60,
                           auto_duration: bool = False):
    """Process multiple videos, distributing shorts_count across them"""
    import asyncio
    import math
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    jobs[job_id]["status"] = "processing"
    total_made = 0
    shorts_per_video_max = max(1, math.ceil(shorts_count / len(video_paths))) if shorts_count > 1 else shorts_count
    try:
        for vidx, (fname, vpath) in enumerate(video_paths):
            if _cancel_flag:
                add_job_log(job_id, "Cancelled by user", "warning")
                break
            if total_made >= shorts_count:
                add_job_log(job_id, f"Reached target {shorts_count} shorts, stopping")
                break

            remaining = shorts_count - total_made
            per_video = min(shorts_per_video_max, remaining)
            add_job_log(job_id, f"[Video {vidx+1}/{len(video_paths)}] {fname} — {per_video} shorts", "info")

            video_info = loop.run_until_complete(processor.get_video_info(vpath))
            dur = video_info.get("duration", 0)
            add_job_log(job_id, f"[Video {vidx+1}] Duration: {dur:.1f}s", "info")

            use_smart = (smart_selection or "off") != "off" or auto_duration
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
                    min_length=min_short_length, max_length=max_short_length
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
                        blurred_bg, filename_keywords, crop_fill,
                        banner_enabled, banner_path, banner_x, banner_y,
                        banner_w, banner_h, banner_opacity,
                        banner_style, banner_position, banner_duration
                    )
                )

                if not short_path or not Path(short_path).exists():
                    add_job_log(job_id, f"[{idx+1}/{shorts_count}] Video not created", "warning")
                    continue

                add_job_log(job_id, f"[{idx+1}/{shorts_count}] Video created", "success")
                total_made += 1

                title = f"#shorts #{idx+1}"
                description = "Подпишись!"
                tags = ["#shorts", "#viral"]

                jobs[job_id].setdefault("shorts", []).append({
                    "index": idx, "filename": Path(short_path).name,
                    "filepath": short_path, "title": title,
                    "description": description, "tags": tags
                })
                jobs[job_id]["progress"] = min(95, 20 + (idx + 1) * 70 // shorts_count)
                save_jobs()

                if save_video:
                    saved = SAVED_DIR / (save_folder or "saved")
                    saved.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(short_path, saved / f"short_{job_id}_{idx}.mp4")
                    add_job_log(job_id, f"[{idx+1}/{shorts_count}] Saved to {save_folder}", "success")

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


@app.post("/api/upload-url")
async def upload_url(
    url: str = Form(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    smart_selection: str = Form("off"),
    blurred_bg: bool = Form(False),
    crop_fill: bool = Form(False),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    banner_enabled: bool = Form(False),
    banner_x: int = Form(0), banner_y: int = Form(0),
    banner_w: int = Form(1080), banner_h: int = Form(200), banner_opacity: int = Form(100),
    banner_file: UploadFile = File(None),
    banner_style: str = Form("overlay"),
    banner_position: int = Form(50), banner_duration: int = Form(3),
    min_short_length: int = Form(30), max_short_length: int = Form(60),
    auto_duration: bool = Form(False),
    filename_keywords: str = Form("")
):
    job_id = str(uuid.uuid4())
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    banner_path = await _save_banner_upload(banner_file, job_id)
    jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0,
                     "shorts_count": shorts_count, "short_length": short_length,
                     "source": "url", "created_at": now_str, "shorts": []}
    save_jobs()
    add_job_log(job_id, f"Downloading: {url}", "info")

    # Download in thread
    def _dl_and_process():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            video_path = loop.run_until_complete(processor.download_video(url, job_id))
            add_job_log(job_id, "Video downloaded", "success")
            jobs[job_id]["progress"] = 5
            save_jobs()
            # Continue processing
            _process_job_thread(
                job_id, video_path, short_length, shorts_count,
                blurred_bg, crop_fill, smart_selection,
                save_video, save_folder,
                banner_enabled, banner_x, banner_y,
                banner_w, banner_h, banner_opacity,
                filename_keywords,
                banner_path, banner_style, banner_position, banner_duration,
                min_short_length, max_short_length, auto_duration
            )
        except Exception as e:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(e)
            add_job_log(job_id, f"Download error: {e}", "error")
            save_jobs()
            save_job_logs()
        finally:
            loop.close()
    queued = _enqueue_job(_dl_and_process, ())
    return {"job_id": job_id, "status": "queued" if not queued else "started"}


@app.post("/api/upload-file")
async def upload_file(
    file: UploadFile = File(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    smart_selection: str = Form("off"),
    blurred_bg: bool = Form(False),
    crop_fill: bool = Form(False),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    banner_enabled: bool = Form(False),
    banner_x: int = Form(0), banner_y: int = Form(0),
    banner_w: int = Form(1080), banner_h: int = Form(200), banner_opacity: int = Form(100),
    banner_file: UploadFile = File(None),
    banner_style: str = Form("overlay"),
    banner_position: int = Form(50), banner_duration: int = Form(3),
    min_short_length: int = Form(30), max_short_length: int = Form(60),
    auto_duration: bool = Form(False),
    filename_keywords: str = Form("")
):
    job_id = str(uuid.uuid4())
    safe = f"{job_id}_input.mp4"
    video_path = str(UPLOAD_DIR / safe)
    banner_path = await _save_banner_upload(banner_file, job_id)

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

    started = _enqueue_job(_process_job_thread, (
        job_id, video_path, short_length, shorts_count,
        blurred_bg, crop_fill, smart_selection,
        save_video, save_folder,
        banner_enabled, banner_x, banner_y,
        banner_w, banner_h, banner_opacity,
        filename_keywords,
        banner_path, banner_style, banner_position, banner_duration,
        min_short_length, max_short_length, auto_duration
    ))

    return {"job_id": job_id, "status": "started" if started else "queued"}


@app.post("/api/upload-folder")
async def upload_folder(
    files: List[UploadFile] = File(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    smart_selection: str = Form("off"),
    blurred_bg: bool = Form(False),
    crop_fill: bool = Form(False),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    banner_enabled: bool = Form(False),
    banner_x: int = Form(0), banner_y: int = Form(0),
    banner_w: int = Form(1080), banner_h: int = Form(200), banner_opacity: int = Form(100),
    banner_file: UploadFile = File(None),
    banner_style: str = Form("overlay"),
    banner_position: int = Form(50), banner_duration: int = Form(3),
    min_short_length: int = Form(30), max_short_length: int = Form(60),
    auto_duration: bool = Form(False),
    filename_keywords: str = Form("")
):
    job_id = str(uuid.uuid4())
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    banner_path = await _save_banner_upload(banner_file, job_id)
    jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0,
                     "shorts_count": shorts_count, "short_length": short_length,
                     "source": "folder", "created_at": now_str, "shorts": []}
    save_jobs()
    add_job_log(job_id, f"Folder: {len(files)} videos", "info")

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
        blurred_bg, crop_fill, smart_selection,
        save_video, save_folder,
        banner_enabled, banner_x, banner_y,
        banner_w, banner_h, banner_opacity,
        filename_keywords,
        banner_path, banner_style, banner_position, banner_duration,
        min_short_length, max_short_length, auto_duration
    ))

    return {"job_id": job_id, "status": "started" if started else "queued"}


# ── Docs page ──
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
    "git_workflow.md": "Работа с Git: коммиты, ветки, пуши, деплой",
    "optimal_settings.md": "Какие настройки ставить для разной длины и типа видео",
    "smart_selection.md": "Умный отбор сегментов: как и зачем",
    "smart_selection_algo.md": "Детальное описание алгоритмов скоринга и отбора",
    "termux_setup.md": "Запуск бота на Android через Termux",
    "youtube_api_credentials.txt": "Как получить credentials для YouTube API (пошагово)",
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
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Доки</title>
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
<div class="header"><h1>📖 Доки</h1><p>Руководства и справка по Video to Shorts Bot</p></div>
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
