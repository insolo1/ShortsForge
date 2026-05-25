import os
import sys
import threading
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

import uuid
import asyncio
import json
import hashlib
import time
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import aiofiles

from processor import VideoProcessor
from ai_service import AIService
from youtube_api import YouTubeAPI
try:
    from google_cloud_automation import GoogleCloudAutomation
except:
    GoogleCloudAutomation = None

try:
    from disabled.playwright_automation import GoogleCloudAutomation as PlaywrightAutomation
except:
    PlaywrightAutomation = None

import logging
logging.getLogger("uvicorn.access").disabled = True
logging.getLogger("uvicorn").setLevel(logging.WARNING)

app = FastAPI(title="Video to Shorts Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
USERS_FILE = BASE_DIR / "users.json"
SESSIONS_FILE = BASE_DIR / "sessions.json"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

processor = VideoProcessor(str(UPLOAD_DIR), str(OUTPUT_DIR))
ai_service = AIService()
youtube_api = YouTubeAPI(client_secret_file=str(BASE_DIR / "client_secret.json"), tokens_dir=str(BASE_DIR / "tokens"))


def safe_account_email(email: str) -> str:
    return email.replace('@', '_at_').replace('.', '_')


def get_account_credentials_file(email: str) -> Path:
    account_file = BASE_DIR / "google_credentials" / f"{safe_account_email(email)}.json"
    if account_file.exists():
        return account_file
    return BASE_DIR / "client_secret.json"


def load_users():
    if USERS_FILE.exists():
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


ROLES = {
    "admin": ["create_shorts", "delete_shorts", "manage_accounts", "settings", "cleanup", "view_all", "delete_all"],
    "editor": ["create_shorts", "view_all"],
    "viewer": ["view_all"]
}


def check_permission(role: str, action: str) -> bool:
    return action in ROLES.get(role, [])


def save_users(users: list):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)


def load_sessions():
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

JOBS_FILE = BASE_DIR / "jobs.json"


def load_jobs():
    if JOBS_FILE.exists():
        try:
            with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_jobs():
    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
        json.dump(jobs, f)


def load_job_logs():
    logs_file = BASE_DIR / "job_logs.json"
    if logs_file.exists():
        try:
            with open(logs_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


_job_logs_lock = threading.Lock()

def save_job_logs():
    with _job_logs_lock:
        try:
            logs_file = BASE_DIR / "job_logs.json"
            with open(logs_file, 'w', encoding='utf-8') as f:
                json.dump(job_logs, f)
        except Exception:
            pass


jobs = load_jobs()
sessions = load_sessions()
job_logs = load_job_logs()

def add_job_log(job_id: str, message: str, log_type: str = "info"):
    """Добавить лог для задачи"""
    if job_id not in job_logs:
        job_logs[job_id] = []
    
    job_logs[job_id].append({
        "message": message,
        "type": log_type,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    })
    
    if len(job_logs[job_id]) > 10000:
        job_logs[job_id] = job_logs[job_id][-10000:]
    
    save_job_logs()

def save_sessions():
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sessions, f)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_token(request: Request):
    token = request.headers.get('Authorization')
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return sessions[token]  # Returns {"username": ..., "role": ...}


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # Проверяем токен из cookie или localStorage
    token = request.cookies.get('token')
    if not token or token not in sessions:
        return RedirectResponse(url='/login')
    
    async with aiofiles.open(BASE_DIR / "static" / "index.html", "r", encoding="utf-8") as f:
        content = await f.read()
    return HTMLResponse(content=content, media_type="text/html; charset=utf-8")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    async with aiofiles.open(BASE_DIR / "static" / "login.html", "r", encoding="utf-8") as f:
        content = await f.read()
    return HTMLResponse(content=content, media_type="text/html; charset=utf-8")


@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...)):
    users = load_users()
    password_hash = hash_password(password)
    
    user = next((u for u in users if u['username'] == username and u['password'] == password_hash), None)
    
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    token = str(uuid.uuid4())
    sessions[token] = {"username": username, "role": user.get("role", "viewer")}
    save_sessions()
    
    print(f"[LOGIN] User {username} (role: {user.get('role', 'viewer')}) logged in with token {token}")
    
    response = JSONResponse({"token": token, "username": username, "role": user.get("role", "viewer")})
    response.set_cookie(
        key="token", 
        value=token, 
        httponly=False,  # Разрешаем доступ из JS
        max_age=86400*30,
        path="/",
        samesite="lax"
    )
    return response


@app.get("/api/roles")
async def get_roles():
    return JSONResponse({"roles": ROLES})


@app.get("/api/users")
async def get_users():
    users = load_users()
    return JSONResponse({"status": "success", "users": [{"username": u["username"], "role": u.get("role", "viewer")} for u in users]})


@app.post("/api/users")
async def create_or_update_user(username: str = Form(...), password: str = Form(...), role: str = Form("viewer")):
    users = load_users()
    existing = next((i for i, u in enumerate(users) if u["username"] == username), -1)
    user_data = {"username": username, "password": hash_password(password), "role": role}
    if existing >= 0:
        users[existing] = user_data
    else:
        users.append(user_data)
    save_users(users)
    return {"status": "success", "message": f"User {username} saved with role {role}"}


@app.delete("/api/users/{username}")
async def delete_user(username: str):
    users = load_users()
    users = [u for u in users if u["username"] != username]
    save_users(users)
    return {"status": "success", "message": f"User {username} deleted"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    token = request.cookies.get('token')
    if not token or token not in sessions:
        return RedirectResponse(url='/login')
    session_data = sessions[token]
    role = session_data.get("role", "viewer") if isinstance(session_data, dict) else "viewer"
    if role != "admin":
        return HTMLResponse("<h1>Доступ запрещён</h1><p>Только администраторы.</p><a href='/'>На главную</a>", status_code=403)
    async with aiofiles.open(BASE_DIR / "static" / "admin.html", "r", encoding="utf-8") as f:
        content = await f.read()
    return HTMLResponse(content=content, media_type="text/html; charset=utf-8")


@app.get("/notes", response_class=HTMLResponse)
async def notes_page(request: Request):
    # Проверяем токен
    token = request.cookies.get('token')
    print(f"[NOTES] Token from cookie: {token}")
    print(f"[NOTES] Active sessions: {list(sessions.keys())}")
    
    if not token or token not in sessions:
        print(f"[NOTES] Redirecting to login - token invalid")
        return RedirectResponse(url='/login')
    
    async with aiofiles.open(BASE_DIR / "static" / "notes.html", "r", encoding="utf-8") as f:
        content = await f.read()
    return HTMLResponse(content=content, media_type="text/html; charset=utf-8")


@app.get("/api/admin/analytics")
async def get_analytics(request: Request):
    # Проверяем авторизацию
    token = request.cookies.get('token')
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Реальные данные из jobs
    total_videos = 0
    all_shorts = []
    
    for job_id, job in jobs.items():
        if job.get("status") == "completed" and "shorts" in job:
            total_videos += len(job["shorts"])
            for short in job["shorts"]:
                all_shorts.append({
                    "job_id": job_id,
                    "title": short.get("title", "Без названия"),
                    "filename": short.get("filename", ""),
                    "filepath": short.get("filepath", "")
                })
    
    from datetime import datetime, timedelta
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%d.%m") for i in range(6, -1, -1)]
    
    analytics = {
        "total_videos": total_videos,
        "total_views": 0,
        "total_subscribers": 0,
        "avg_ctr": 0,
        "videos_today": 0,
        "views_today": 0,
        "subscribers_today": 0,
        "views_7days": [{"date": d, "count": 0} for d in dates],
        "subscribers_7days": [{"date": d, "count": 0} for d in dates],
        "accounts": [],
        "videos": [
            {
                "title": short["title"],
                "account": "Локальные видео",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "ctr": 0,
                "published_date": today.strftime("%d.%m.%Y"),
                "url": f"/api/download/{short['job_id']}_{i}",
                "thumbnail": "",
                "filename": short["filename"]
            }
            for i, short in enumerate(all_shorts[:20])  # Последние 20 видео
        ]
    }
    
    return analytics


@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get('token')
    if token in sessions:
        del sessions[token]
        save_sessions()
    
    response = JSONResponse({"status": "success"})
    response.delete_cookie("token")
    return response


@app.post("/api/youtube/authorize")
async def authorize_youtube(request: Request):
    """Авторизация YouTube аккаунта через API"""
    try:
        data = await request.json()
        email = data.get('email')
        
        if not email:
            return JSONResponse({"status": "error", "message": "Email required"})

        youtube_api.client_secret_file = str(get_account_credentials_file(email))
        
        # Проверяем есть ли уже токен
        token_file = youtube_api.get_token_file(email)
        if token_file.exists():
            # Пробуем использовать существующий токен
            if youtube_api.authenticate(email):
                return JSONResponse({"status": "success", "message": f"Already authorized: {email}"})
        
        # Запускаем OAuth flow
        success = youtube_api.authenticate(email)
        
        if success:
            return JSONResponse({"status": "success", "message": f"Authorized: {email}"})
        else:
            return JSONResponse({"status": "error", "message": "Authorization failed"})
            
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.post("/api/youtube/upload-credentials")
async def upload_youtube_credentials(request: Request):
    """Загрузка готовых credentials для аккаунта"""
    try:
        # multipart/form-data
        form = await request.form()
        email = form.get('email')
        credentials_file = form.get('credentials')
        
        if not email:
            return JSONResponse({"status": "error", "message": "Email required"})
        if not credentials_file:
            return JSONResponse({"status": "error", "message": "Credentials file required"})
        
        # Читаем содержимое файла
        contents = await credentials_file.read()
        
        # Валидируем что это JSON
        try:
            creds_data = json.loads(contents.decode('utf-8'))
        except:
            return JSONResponse({"status": "error", "message": "Invalid JSON file"})
        
        # Проверяем структуру
        if 'installed' not in creds_data and 'web' not in creds_data:
            return JSONResponse({"status": "error", "message": "Invalid client_secret format"})
        
        # Сохраняем в папку google_credentials
        creds_dir = BASE_DIR / "google_credentials"
        creds_dir.mkdir(exist_ok=True)
        
        # Имя файла - email без @ и .
        cred_file = creds_dir / f"{safe_account_email(email)}.json"
        
        with open(cred_file, 'w', encoding='utf-8') as f:
            f.write(contents.decode('utf-8'))
        
        return JSONResponse({
            "status": "success", 
            "message": f"Credentials saved for {email}",
            "file": str(cred_file)
        })
        
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.get("/api/youtube/accounts")
async def get_youtube_accounts():
    """Получить список аккаунтов с credentials"""
    try:
        creds_dir = BASE_DIR / "google_credentials"
        accounts = []
        
        if creds_dir.exists():
            for f in creds_dir.glob("*.json"):
                # Читаем email из имени файла
                email = f.stem.replace('_at_', '@').replace('_', '.')
                # Проверяем тот же OAuth-токен, который создает YouTubeAPI.authenticate()
                token_file = youtube_api.get_token_file(email)
                has_token = token_file.exists()
                accounts.append({
                    "email": email,
                    "credentials_file": str(f),
                    "has_token": has_token
                })
        
        return JSONResponse({"status": "success", "accounts": accounts})
        
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.delete("/api/youtube/accounts")
async def delete_youtube_account(request: Request):
    """Удалить сохраненный YouTube аккаунт: credentials и OAuth-токен"""
    try:
        data = await request.json()
        email = (data.get("email") or "").strip()

        if not email:
            return JSONResponse({"status": "error", "message": "Email required"})

        safe_email = safe_account_email(email)
        files_to_delete = [
            BASE_DIR / "google_credentials" / f"{safe_email}.json",
            youtube_api.get_token_file(email),
            BASE_DIR / "tokens" / f"{safe_email}.json",
        ]

        deleted = []
        for file_path in files_to_delete:
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
                deleted.append(str(file_path))

        return JSONResponse({
            "status": "success",
            "message": f"Account deleted: {email}",
            "deleted": deleted
        })

    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


# Автоматическая настройка перенесена в папку disabled/

@app.get("/api/logs/{job_id}")
async def get_job_logs(job_id: str):
    """Получить логи задачи"""
    if job_id not in job_logs:
        return JSONResponse({"logs": [], "status": "not_found", "total": 0})
    
    job_status = jobs.get(job_id, {}).get("status", "unknown")
    logs = job_logs[job_id]
    
    return JSONResponse({
        "logs": logs,
        "total": len(logs),
        "status": job_status,
        "progress": jobs.get(job_id, {}).get("progress", 0)
    })


# Схемы настроек (presets)
PRESETS_FILE = BASE_DIR / "presets.json"

def load_presets():
    if PRESETS_FILE.exists():
        try:
            with open(PRESETS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_presets_to_file(presets):
    with open(PRESETS_FILE, 'w', encoding='utf-8') as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)


@app.post("/api/presets/save")
async def save_preset(request: Request):
    """Сохранить схему настроек"""
    try:
        preset = await request.json()
        
        if not preset.get('name'):
            return JSONResponse({"status": "error", "message": "Name required"})
        
        presets = load_presets()
        
        # Проверяем существует ли схема с таким именем
        existing = [p for p in presets if p.get('name') == preset['name']]
        if existing:
            # Обновляем существующую
            for i, p in enumerate(presets):
                if p.get('name') == preset['name']:
                    presets[i] = preset
                    break
        else:
            # Добавляем новую
            presets.append(preset)
        
        save_presets_to_file(presets)
        
        return JSONResponse({"status": "success", "message": "Preset saved"})
        
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.get("/api/presets/list")
async def list_presets():
    """Получить список схем"""
    try:
        presets = load_presets()
        return JSONResponse({"status": "success", "presets": presets})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.get("/api/presets/load")
async def load_preset(name: str):
    """Загрузить схему по имени"""
    try:
        presets = load_presets()
        preset = next((p for p in presets if p.get('name') == name), None)
        
        if preset:
            return JSONResponse({"status": "success", "preset": preset})
        else:
            return JSONResponse({"status": "error", "message": "Preset not found"})
            
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


@app.get("/api/settings")
async def get_settings():
    """Получить текущие настройки"""
    return JSONResponse({
        "status": "success",
        "settings": {
            "crop_mode": os.getenv("VIDEO_CROP_MODE", "9:16"),
            "zoom_enabled": os.getenv("VIDEO_ZOOM_ENABLE", "0") == "1",
            "font": os.getenv("SUBTITLE_FONT", "Verdana"),
            "style": os.getenv("SUBTITLE_STYLE", "normal"),
            "fontsize": int(os.getenv("SUBTITLE_FONTSIZE", "75")),
            "fontcolor": os.getenv("SUBTITLE_FONTCOLOR", "white"),
            "position": int(os.getenv("SUBTITLE_POSITION_Y", "600")),
            "capitalize": os.getenv("SUBTITLE_CAPITALIZE", "1") == "1",
            "borderw": int(os.getenv("SUBTITLE_BORDERW", "0")),
            "bordercolor": os.getenv("SUBTITLE_BORDERCOLOR", "black"),
            "boxborder": int(os.getenv("SUBTITLE_BOX_BORDER", "0")),
            "boxcolor": os.getenv("SUBTITLE_BOX_COLOR", "black@0.8"),
            "shadowx": int(os.getenv("SUBTITLE_SHADOW_X", "0")),
            "shadowy": int(os.getenv("SUBTITLE_SHADOW_Y", "0")),
            "shadowcolor": os.getenv("SUBTITLE_SHADOW_COLOR", "black"),
            "words_count": int(os.getenv("SUBTITLE_WORDS_COUNT", "5")),
            "word_fade": os.getenv("SUBTITLE_WORD_FADE", "1") == "1",
            "api_provider": "groq" if os.getenv("GROQ_API_KEY") else ("openai" if os.getenv("OPENAI_API_KEY") else "groq"),
            "api_key_masked": "***" if (os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")) else ""
        }
    })


@app.post("/api/settings")
async def update_settings(
    font: str = Form("Verdana"),
    style: str = Form("normal"),
    fontsize: int = Form(75),
    fontcolor: str = Form("white"),
    position: int = Form(600),
    capitalize: bool = Form(True),
    crop_mode: str = Form("9:16"),
    zoom_enabled: bool = Form(False),
    borderw: int = Form(0),
    bordercolor: str = Form("black"),
    boxborder: int = Form(0),
    boxcolor: str = Form("black@0.8"),
    shadowx: int = Form(0),
    shadowy: int = Form(0),
    shadowcolor: str = Form("black"),
    api_provider: str = Form(None),
    api_key: str = Form(None),
    words_count: int = Form(5),
    word_fade: bool = Form(True)
):
    # Читаем существующие настройки из .env перед сохранением
    env_path = BASE_DIR / ".env"
    existing = {}
    
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, val = line.split('=', 1)
                    existing[key] = val.strip().strip('"')
    
    # Обновляем настройки
    existing['GROQ_API_KEY'] = os.getenv('GROQ_API_KEY', '')
    existing['VIDEO_CROP_MODE'] = crop_mode
    existing['VIDEO_ZOOM_ENABLE'] = '1' if zoom_enabled else '0'
    existing['SUBTITLE_FONT'] = font
    existing['SUBTITLE_STYLE'] = style
    existing['SUBTITLE_FONTSIZE'] = str(fontsize)
    existing['SUBTITLE_FONTCOLOR'] = fontcolor
    existing['SUBTITLE_POSITION_Y'] = str(position)
    existing['SUBTITLE_CAPITALIZE'] = '1' if capitalize else '0'
    existing['SUBTITLE_BORDERW'] = str(borderw)
    existing['SUBTITLE_BORDERCOLOR'] = bordercolor
    existing['SUBTITLE_BOX_BORDER'] = str(boxborder)
    existing['SUBTITLE_BOX_COLOR'] = boxcolor
    existing['SUBTITLE_SHADOW_X'] = str(shadowx)
    existing['SUBTITLE_SHADOW_Y'] = str(shadowy)
    existing['SUBTITLE_SHADOW_COLOR'] = shadowcolor
    existing['SUBTITLE_WORDS_COUNT'] = str(words_count)
    existing['SUBTITLE_WORD_FADE'] = '1' if word_fade else '0'

    if api_provider and api_key:
        if api_provider == 'groq':
            existing['GROQ_API_KEY'] = api_key
        elif api_provider == 'openai':
            existing['OPENAI_API_KEY'] = api_key
    
    # Записываем обновленный .env
    env_content = f"""GROQ_API_KEY="{existing['GROQ_API_KEY']}"
OPENAI_API_KEY="{existing.get('OPENAI_API_KEY', '')}"

# Настройки видео
VIDEO_CROP_MODE="{existing['VIDEO_CROP_MODE']}"
VIDEO_ZOOM_ENABLE={existing['VIDEO_ZOOM_ENABLE']}

# Настройки субтитров
SUBTITLE_FONT="{existing['SUBTITLE_FONT']}"
SUBTITLE_STYLE="{existing['SUBTITLE_STYLE']}"
SUBTITLE_FONTSIZE={existing['SUBTITLE_FONTSIZE']}
SUBTITLE_FONTCOLOR="{existing['SUBTITLE_FONTCOLOR']}"
SUBTITLE_POSITION_Y={existing['SUBTITLE_POSITION_Y']}
SUBTITLE_CAPITALIZE={existing['SUBTITLE_CAPITALIZE']}
SUBTITLE_BORDERW={existing['SUBTITLE_BORDERW']}
SUBTITLE_BORDERCOLOR="{existing['SUBTITLE_BORDERCOLOR']}"
SUBTITLE_BOX_BORDER={existing['SUBTITLE_BOX_BORDER']}
SUBTITLE_BOX_COLOR="{existing['SUBTITLE_BOX_COLOR']}"
SUBTITLE_SHADOW_X={existing['SUBTITLE_SHADOW_X']}
SUBTITLE_SHADOW_Y={existing['SUBTITLE_SHADOW_Y']}
SUBTITLE_SHADOW_COLOR="{existing['SUBTITLE_SHADOW_COLOR']}"
SUBTITLE_WORDS_COUNT={existing['SUBTITLE_WORDS_COUNT']}
SUBTITLE_WORD_FADE={existing['SUBTITLE_WORD_FADE']}
"""
    
    async with aiofiles.open(env_path, "w", encoding="utf-8") as f:
        await f.write(env_content)
    
    # Перезагружаем переменные окружения
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    return {"status": "success", "message": "Настройки сохранены"}


@app.post("/api/integration/start")
async def start_integration(
    source: str = Form(...),
    video_url: str = Form(None),
    video_file: UploadFile = File(None),
    accounts: str = Form(...),
    distribution_mode: str = Form("equal"),
    custom_distribution: str = Form(""),
    videos_per_day: int = Form(3),
    publish_time: str = Form("auto"),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    enable_scheduled: bool = Form(False),
    schedule_start_date: str = Form(None),
    schedule_start_time: str = Form(None),
    schedule_interval: int = Form(60),
    blurred_bg: bool = Form(False),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    filename_keywords: str = Form("")
):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "starting", "progress": 0, "shorts": [], "integration": True, "save_video": save_video, "save_folder": save_folder, "created_at": time.time()}
    save_jobs()
    job_logs[job_id] = []
    
    add_job_log(job_id, "Запуск интеграции...", "info")
    
    # Парсим аккаунты (теперь только email)
    account_list = []
    for line in accounts.strip().split('\n'):
        email = line.strip()
        if email and '@' in email:
            account_list.append({"email": email})
    
    if not account_list:
        add_job_log(job_id, "Ошибка: не указаны аккаунты", "error")
        raise HTTPException(status_code=400, detail="Не указаны аккаунты")
    
    add_job_log(job_id, f"Найдено {len(account_list)} аккаунтов", "success")
    
    # Сохраняем файл сразу, если это файл
    video_file_path = None
    if source == "file" and video_file:
        safe_filename = f"{job_id}_input.mp4"
        video_file_path = UPLOAD_DIR / safe_filename
        async with aiofiles.open(video_file_path, "wb") as f:
            content = await video_file.read()
            await f.write(content)
        video_file_path = str(video_file_path)
    
    # Запускаем задачу
    asyncio.create_task(process_integration(
        job_id, source, video_url, video_file_path, account_list,
        distribution_mode, custom_distribution, videos_per_day,
        publish_time, short_length, shorts_count,
        enable_scheduled, schedule_start_date, schedule_start_time, schedule_interval,
        blurred_bg, save_video, save_folder, filename_keywords
    ))
    
    return {"job_id": job_id, "status": "started"}


async def process_integration(
    job_id: str, source: str, video_url: str, video_file_path: str,
    accounts: list, distribution_mode: str, custom_distribution: str,
    videos_per_day: int, publish_time: str, short_length: int, shorts_count: int,
    enable_scheduled: bool = False, schedule_start_date: str = None, 
    schedule_start_time: str = None, schedule_interval: int = 60,
    blurred_bg: bool = False, save_video: bool = False, save_folder: str = "saved",
    filename_keywords: str = ""
):
    try:
        print(f"[INTEGRATION] Starting job: {job_id}")
        add_job_log(job_id, "Начало обработки видео", "info")
        
        # 1. Получаем видео
        if source == "url":
            add_job_log(job_id, f"Загрузка видео с URL: {video_url}", "progress")
            video_path = await processor.download_video(video_url, job_id)
            add_job_log(job_id, "Видео загружено", "success")
        else:
            video_path = video_file_path
            add_job_log(job_id, "Использование локального файла", "info")
        
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 20
        save_jobs()
        
        # 2. Создаём шорты
        add_job_log(job_id, "Получение информации о видео", "progress")
        video_info = await processor.get_video_info(video_path)
        add_job_log(job_id, f"Длительность видео: {video_info.get('duration', 0):.1f} сек", "info")
        
        add_job_log(job_id, f"Извлечение {shorts_count} сегментов по {short_length} сек", "progress")
        segments = await processor.extract_segments(video_path, short_length, shorts_count)
        add_job_log(job_id, f"Найдено {len(segments)} сегментов", "success")
        
        shorts = []
        for i, segment in enumerate(segments):
            add_job_log(job_id, f"[{i+1}/{len(segments)}] Обработка сегмента {segment['start']:.1f}s - {segment['end']:.1f}s", "progress")
            
            # Получаем субтитры
            subtitle_data = await processor.get_subtitles(video_path, segment["start"], segment["end"])
            add_job_log(job_id, f"[{i+1}/{len(segments)}] Субтитры: {len(subtitle_data.get('segments', []))} фраз", "info")
            
            # Создаём видео с субтитрами
            short_path = await processor.create_short(video_path, segment, i, job_id, subtitle_data.get("segments"), blurred_bg, filename_keywords)
            add_job_log(job_id, f"[{i+1}/{len(segments)}] Видео создано", "success")
            
            # Генерируем метаданные (без субтитров)
            try:
                add_job_log(job_id, f"[{i+1}/{len(segments)}] Генерация метаданных через AI", "progress")
                metadata = await ai_service.generate_metadata(f"Video segment {i+1}", i + 1, video_info)
                add_job_log(job_id, f"[{i+1}/{len(segments)}] Метаданные: {metadata['title'][:50]}...", "info")
            except Exception as e:
                add_job_log(job_id, f"[{i+1}/{len(segments)}] AI ошибка: {str(e)}", "warning")
                metadata = {
                    "title": f"#shorts #{i+1}",
                    "description": "Video short",
                    "tags": ["shorts", "viral", "trending"]
                }
            
            shorts.append({
                "path": short_path,
                "title": metadata["title"],
                "description": metadata["description"],
                "tags": metadata["tags"]
            })
            
            if jobs[job_id].get("save_video"):
                folder_name = jobs[job_id].get("save_folder", "saved") or "saved"
                saved_dir = BASE_DIR / "saved" / folder_name
                saved_dir.mkdir(parents=True, exist_ok=True)
                import shutil
                filename = f"short_{job_id}_{i}.mp4"
                dest = saved_dir / filename
                shutil.copy2(short_path, dest)
                add_job_log(job_id, f"[{i+1}/{len(segments)}] Сохранено в {folder_name}", "success")
            
            jobs[job_id]["progress"] = 20 + (i + 1) * 40 // len(segments)
            save_jobs()
        
        # 3. Распределяем видео по аккаунтам
        if distribution_mode == "equal":
            videos_per_account = [len(shorts) // len(accounts)] * len(accounts)
            for i in range(len(shorts) % len(accounts)):
                videos_per_account[i] += 1
        else:
            videos_per_account = [int(x) for x in custom_distribution.split(',')]
        
        add_job_log(job_id, f"Распределение: {videos_per_account}", "info")
        
        jobs[job_id]["status"] = "uploading"
        jobs[job_id]["progress"] = 60
        save_jobs()
        
        # 4. Загружаем на YouTube через API
        add_job_log(job_id, "Начало загрузки на YouTube", "info")
        video_index = 0
        
        for acc_idx, account in enumerate(accounts):
            if video_index >= len(shorts):
                break
            
            email = account["email"]
            add_job_log(job_id, f"Авторизация аккаунта: {email}", "progress")
            
            # Авторизация через API
            youtube_api.client_secret_file = str(get_account_credentials_file(email))
            if not youtube_api.authenticate(email):
                add_job_log(job_id, f"✗ Ошибка авторизации: {email}", "error")
                continue
            
            add_job_log(job_id, f"✓ Авторизован: {email}", "success")
            
            # Загружаем видео
            videos_to_upload = min(videos_per_account[acc_idx], len(shorts) - video_index)
            add_job_log(job_id, f"Загрузка {videos_to_upload} видео на {email}", "info")
            
            for i in range(videos_to_upload):
                short = shorts[video_index]
                
                add_job_log(job_id, f"[{video_index+1}/{len(shorts)}] Загрузка: {short['title'][:50]}...", "progress")
                
                # Определяем статус публикации и время
                privacy_status = "public"
                publish_at = None
                
                if enable_scheduled and schedule_start_date and schedule_start_time:
                    from datetime import datetime, timedelta
                    
                    # Парсим дату и время
                    start_datetime = datetime.fromisoformat(f"{schedule_start_date}T{schedule_start_time}")
                    
                    # Добавляем интервал для каждого видео
                    publish_datetime = start_datetime + timedelta(minutes=schedule_interval * video_index)
                    
                    # Если время в будущем - делаем private с отложенной публикацией
                    if publish_datetime > datetime.now():
                        privacy_status = "private"
                        publish_at = publish_datetime
                        add_job_log(job_id, f"[{video_index+1}/{len(shorts)}] Отложенная публикация: {publish_datetime.strftime('%Y-%m-%d %H:%M')}", "info")
                
                # Загружаем через API
                video_id = youtube_api.upload_video(
                    short["path"],
                    short["title"],
                    short["description"],
                    short["tags"],
                    category_id="22",
                    privacy_status=privacy_status,
                    publish_at=publish_at
                )
                
                if video_id:
                    add_job_log(job_id, f"✓ [{video_index+1}/{len(shorts)}] Загружено: https://youtube.com/watch?v={video_id}", "success")
                else:
                    add_job_log(job_id, f"✗ [{video_index+1}/{len(shorts)}] Ошибка загрузки", "error")
                
                video_index += 1
                jobs[job_id]["progress"] = 60 + (video_index * 40 // len(shorts))
        
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["finished_at"] = time.time()
        save_jobs()
        add_job_log(job_id, f"Интеграция завершена! Загружено {video_index}/{len(shorts)} видео", "success")
        print(f"[INTEGRATION] Job completed: {job_id}")
        
    except Exception as e:
        error_msg = f"Критическая ошибка: {str(e)}"
        print(f"[INTEGRATION] Error: {error_msg}")
        add_job_log(job_id, error_msg, "error")
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["finished_at"] = time.time()
        save_jobs()


@app.post("/api/upload-url")
async def upload_url(url: str = Form(...), short_length: int = Form(45), shorts_count: int = Form(5), smart_selection: bool = Form(False), blurred_bg: bool = Form(False), save_video: bool = Form(False), save_folder: str = Form("saved"), filename_keywords: str = Form("")):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "downloading", "progress": 0, "shorts": [], "save_video": save_video, "save_folder": save_folder, "created_at": time.time()}
    save_jobs()
    
    asyncio.create_task(process_video(job_id, url, short_length, shorts_count, smart_selection, blurred_bg, filename_keywords))
    
    return {"job_id": job_id, "status": "started"}


@app.post("/api/upload-file")
async def upload_file(file: UploadFile = File(...), short_length: int = Form(45), shorts_count: int = Form(5), smart_selection: bool = Form(False), blurred_bg: bool = Form(False), save_video: bool = Form(False), save_folder: str = Form("saved"), filename_keywords: str = Form("")):
    job_id = str(uuid.uuid4())
    
    print(f"[UPLOAD] Starting upload for job: {job_id}, file: {file.filename}")
    
    try:
        safe_filename = f"{job_id}_input.mp4"
        file_path = UPLOAD_DIR / safe_filename
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)
        
        print(f"[UPLOAD] File saved: {file_path}, size: {len(content)} bytes")
        
        jobs[job_id] = {"status": "processing", "progress": 0, "shorts": [], "created_at": time.time()}
        save_jobs()
        
        asyncio.create_task(process_video(job_id, str(file_path), short_length, shorts_count, smart_selection, blurred_bg, filename_keywords))
        
        return {"job_id": job_id, "status": "started"}
    except Exception as e:
        print(f"[UPLOAD] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete job and its output files"""
    global jobs
    if job_id in jobs:
        del jobs[job_id]
    job_output_dir = OUTPUT_DIR / job_id
    if job_output_dir.exists():
        shutil.rmtree(job_output_dir)
    for f in OUTPUT_DIR.glob(f"short_{job_id}_*.mp4"):
        f.unlink()
    upload_file_path = UPLOAD_DIR / f"{job_id}_input.mp4"
    if upload_file_path.exists():
        upload_file_path.unlink()
    return {"status": "success", "job_id": job_id}


@app.get("/api/projects")
async def get_projects():
    """Get list of all jobs/projects"""
    projects = []
    for job_id, job in jobs.items():
        shorts_count = len(job.get("shorts", []))
        projects.append({
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "progress": job.get("progress", 0),
            "shorts_count": shorts_count,
            "created_at": job.get("created_at", time.time()),
            "save_folder": job.get("save_folder", ""),
            "integration": job.get("integration", False)
        })
    projects.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"status": "success", "projects": projects}
    """Clean up jobs older than N days"""
    from datetime import datetime, timedelta
    cutoff = time.time() - (days_old * 86400)
    to_delete = []
    for job_id in list(jobs.keys()):
        job = jobs.get(job_id, {})
        if job.get("created_at", 0) < cutoff or (job.get("status") in ("completed", "failed") and job.get("finished_at", 0) < cutoff):
            to_delete.append(job_id)
    for job_id in to_delete:
        del jobs[job_id]
        for f in OUTPUT_DIR.glob(f"short_{job_id}_*.mp4"):
            f.unlink()
        (UPLOAD_DIR / f"{job_id}_input.mp4").unlink(missing_ok=True)
    return {"status": "success", "deleted": len(to_delete)}


@app.get("/api/download/{short_id}")
async def download_short(short_id: str):
    print(f"[DOWNLOAD] Requested short_id: {short_id}")
    
    # short_id уже содержит полное имя (job_id_index), например: 37ff49ce_0
    if not short_id.startswith('short_'):
        short_id = f"short_{short_id}"
    
    filename = f"{short_id}.mp4"
    file_path = OUTPUT_DIR / filename
    
    print(f"[DOWNLOAD] Looking for: {file_path}")
    print(f"[DOWNLOAD] Exists: {file_path.exists()}")
    
    if file_path.exists():
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="video/mp4"
        )
    
    # Пробуем найти файл без prefix
    for f in OUTPUT_DIR.glob("*.mp4"):
        print(f"[DOWNLOAD] Found: {f.name}")
    
    print(f"[DOWNLOAD] File not found: {file_path}")
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/api/download-zip/{job_id}")
async def download_zip(job_id: str):
    import zipfile
    import io
    
    print(f"[ZIP] Creating zip for job: {job_id}")
    
    job = jobs.get(job_id)
    if not job or not job.get("shorts"):
        raise HTTPException(status_code=404, detail="No videos found")
    
    zip_buffer = io.BytesIO()
    descriptions = []
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for idx, short in enumerate(job["shorts"], 1):
            filepath = short.get("filepath", "")
            orig_filename = short.get("filename", f"short_{job_id}.mp4")
            num_filename = f"{idx:02d}_video.mp4"
            if Path(filepath).exists():
                zip_file.write(filepath, num_filename)
                print(f"[ZIP] Added: {num_filename}")
            
            title = short.get("title", "")
            description = short.get("description", "")
            tags = ", ".join(short.get("tags", []))
            descriptions.append(f"--- #{idx} ---\nФайл: {num_filename}\nЗаголовок: {title}\nОписание: {description}\nТеги: {tags}\n")
        
        if descriptions:
            zip_file.writestr("descriptions.txt", "\n".join(descriptions))
            print("[ZIP] Added: descriptions.txt")
    
    zip_buffer.seek(0)
    
    from fastapi.responses import StreamingResponse
    
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=shorts_{job_id}.zip"}
    )


@app.delete("/api/cleanup/uploads")
async def cleanup_uploads():
    count = 0
    for f in UPLOAD_DIR.glob("*.mp4"):
        f.unlink()
        count += 1
    return {"status": "success", "deleted": count}


@app.delete("/api/cleanup/output")
async def cleanup_output():
    count = 0
    for f in OUTPUT_DIR.glob("*.mp4"):
        f.unlink()
        count += 1
    return {"status": "success", "deleted": count}


@app.post("/api/update-short/{short_id}")
async def update_short(short_id: str, title: str = Form(...), description: str = Form(...), tags: str = Form(...)):
    for job in jobs.values():
        for short in job.get("shorts", []):
            if short["id"] == short_id:
                short["title"] = title
                short["description"] = description
                short["tags"] = [t.strip() for t in tags.split(",")]
                return {"status": "updated"}
    raise HTTPException(status_code=404, detail="Short not found")


async def process_video(job_id: str, source: str, short_length: int, shorts_count: int, smart_selection: bool = False, blurred_bg: bool = False, filename_keywords: str = ""):
    try:
        add_job_log(job_id, f"Старт задачи: {job_id}", "info")
        add_job_log(job_id, f"Источник: {source}", "info")
        
        if source.startswith("http"):
            jobs[job_id]["status"] = "downloading"
            jobs[job_id]["progress"] = 10
            save_jobs()
            
            try:
                video_path = await processor.download_video(source, job_id)
                add_job_log(job_id, f"Видео загружено: {video_path}", "success")
                print(f"[PROCESS] Video: {Path(video_path).name} — {source}")
                
                if not video_path or not Path(video_path).exists():
                    raise Exception("Видео не скачано")
            except Exception as e:
                add_job_log(job_id, f"Ошибка загрузки видео: {str(e)}", "error")
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["finished_at"] = time.time()
                save_jobs()
                return
        else:
            video_path = source
            add_job_log(job_id, f"Локальное видео: {video_path}", "info")
            print(f"[PROCESS] Video: {Path(video_path).name}")
            jobs[job_id]["status"] = "processing"
            jobs[job_id]["progress"] = 10
        
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["progress"] = 30
        save_jobs()
        
        video_info = await processor.get_video_info(video_path)
        add_job_log(job_id, f"Видео: {video_info['duration']:.0f}с", "info")
        
        # Smart selection
        subtitle_segments_all = None
        segments = []
        
        if smart_selection:
            add_job_log(job_id, "Смарт-отбор: поиск лучших фрагментов...", "progress")
            try:
                duration = video_info["duration"]
                
                parts = max(min(shorts_count, 200), 20)
                part_len = duration / parts
                max_analyze = min(part_len * 0.5, 1200)
                add_job_log(job_id, f"{parts} частей x {max_analyze:.0f}с анализ (tiny)", "info")
                
                all_segments = []
                scan_semaphore = asyncio.Semaphore(1)
                
                async def analyze_part(p: int) -> dict:
                    async with scan_semaphore:
                        try:
                            p_start = p * part_len
                            analyze_end = min(p_start + max_analyze, duration)
                            add_job_log(job_id, f"Часть {p+1}/{parts}: {p_start:.0f}с-{analyze_end:.0f}с", "info")
                            print(f"[SMART] Part {p+1}/{parts}: {p_start:.0f}s-{analyze_end:.0f}s")
                            part_sub = await processor.get_subtitles(video_path, p_start, analyze_end, model_size="tiny", word_timestamps=False)
                            part_segs = part_sub.get("segments", [])
                            
                            for s in part_segs:
                                all_segments.append({
                                    "start": s["start"] + p_start,
                                    "end": s["end"] + p_start,
                                    "text": s["text"]
                                })
                            
                            if part_segs:
                                best = processor._find_best_segments(max_analyze, short_length, 1, part_segs)
                                if best:
                                    best[0]["start"] += p_start
                                    best[0]["end"] += p_start
                                    add_job_log(job_id, f"Часть {p+1}: лучший {best[0]['start']:.0f}с", "success")
                                    print(f"[SMART] Part {p+1}: best at {best[0]['start']:.0f}s")
                                    return best[0]
                            mid = p_start + part_len / 2
                            return {"start": mid - short_length/2, "end": mid + short_length/2}
                        except Exception as e:
                            add_job_log(job_id, f"Часть {p+1}: ошибка {e}", "error")
                            mid = p_start + part_len / 2
                            return {"start": mid - short_length/2, "end": mid + short_length/2}
                
                results = await asyncio.gather(*[analyze_part(p) for p in range(parts)], return_exceptions=True)
                results = [r for r in results if isinstance(r, dict)]
                subtitle_segments_all = all_segments
                
                # Если нужно больше шортсов, ищем дополнительные среди всех сегментов
                if len(results) < shorts_count and all_segments:
                    need = shorts_count - len(results)
                    more = processor._find_best_segments(duration, short_length, need, all_segments, video_path)
                    for m in more:
                        overlap = any(m["start"] < r["end"] and m["end"] > r["start"] for r in results if r)
                        if not overlap:
                            results.append(m)
                        if len(results) >= shorts_count:
                            break
                
                segments = [r for r in results if r][:shorts_count]
                    
                add_job_log(job_id, f"Найдено {len(segments)} фрагментов", "success")
                
            except Exception as e:
                add_job_log(job_id, f"Ошибка смарт-отбора: {e}", "error")
        
        if not segments:
            add_job_log(job_id, "Обычное деление на сегменты", "info")
            segments = await processor.extract_segments(video_path, short_length, shorts_count, None, False)
        
        if not segments:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Не удалось найти сегменты для нарезки"
            jobs[job_id]["finished_at"] = time.time()
            add_job_log(job_id, "Не удалось найти сегменты", "error")
            save_jobs()
            return
        
        jobs[job_id]["progress"] = 60
        save_jobs()

        # Параллельный рендер с ограничением (6 потоков)
        render_semaphore = asyncio.Semaphore(1)
        completed_shorts = []
        total = len(segments)
        print(f"[RENDER] creating {len(segments)} shorts (shorts_count={shorts_count})")
        
        async def process_segment(i, segment):
            async with render_semaphore:
                add_job_log(job_id, f"Шортс {i+1}/{total}: {segment['start']:.0f}с - {segment['end']:.0f}с", "progress")
                print(f"[RENDER] Short {i+1}/{total}: {segment['start']:.0f}s-{segment['end']:.0f}s")
                
                # Транскрипция
                add_job_log(job_id, f"[{i+1}] Транскрипция...", "info")
                sub_data = await processor.get_subtitles(video_path, segment["start"], segment["end"])
                add_job_log(job_id, f"[{i+1}] Субтитры: {len(sub_data.get('segments', []))} фраз", "info")
                
                # Рендер
                add_job_log(job_id, f"[{i+1}] Рендер...", "progress")
                short_path = await processor.create_short(video_path, segment, i, job_id, sub_data.get("segments"), blurred_bg, filename_keywords)
                
                if not short_path or not Path(short_path).exists():
                    add_job_log(job_id, f"[{i+1}] Видео не создано", "warning")
                    return None
                
                add_job_log(job_id, f"[{i+1}] Видео создано", "success")
                
                # Метаданные
                try:
                    metadata = await ai_service.generate_metadata(f"Video segment {i+1}", i + 1, video_info)
                except Exception:
                    metadata = {"title": f"Short #{i+1}", "description": "", "tags": []}
                
                short_id = f"{job_id}_{i}"
                filename = f"short_{job_id}_{i}.mp4"
                
                result = {
                    "id": short_id,
                    "filename": filename,
                    "filepath": short_path,
                    "title": metadata.get("title", ""),
                    "description": metadata.get("description", ""),
                    "tags": metadata.get("tags", [])
                }
                
                # Сохранение
                if jobs[job_id].get("save_video"):
                    folder_name = jobs[job_id].get("save_folder", "saved") or "saved"
                    saved_dir = BASE_DIR / "saved" / folder_name
                    saved_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(short_path, saved_dir / filename)
                    add_job_log(job_id, f"[{i+1}] Сохранено в {saved_dir / filename}", "info")
                
                return result
        
        # Запускаем все параллельно
        tasks = [process_segment(i, seg) for i, seg in enumerate(segments)]
        results = await asyncio.gather(*tasks)
        
        # Собираем результаты
        for r in results:
            if r:
                completed_shorts.append(r)
                jobs[job_id]["shorts"].append(r)
                jobs[job_id]["progress"] = 60 + len(completed_shorts) * 30 // total
                save_jobs()
        
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["finished_at"] = time.time()
        add_job_log(job_id, "Готово!", "success")
        
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["finished_at"] = time.time()
        add_job_log(job_id, f"Ошибка: {str(e)}", "error")


@app.delete("/api/cleanup/uploads")
async def cleanup_uploads():
    count = 0
    for f in UPLOAD_DIR.glob("*.mp4"):
        f.unlink()
        count += 1
    return {"status": "success", "deleted": count}


@app.delete("/api/cleanup/output")
async def cleanup_output():
    count = 0
    for f in OUTPUT_DIR.glob("*.mp4"):
        f.unlink()
        count += 1
    return {"status": "success", "deleted": count}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)


SAVED_DIR = BASE_DIR / "saved"


@app.get("/api/saved-folders")
async def get_saved_folders():
    folders = []
    if SAVED_DIR.exists():
        for item in sorted(SAVED_DIR.iterdir()):
            if item.is_dir():
                folders.append(item.name)
    return {"status": "success", "folders": folders}


@app.post("/api/saved-folders")
async def create_saved_folder(request: Request):
    data = await request.json()
    folder = (data.get("folder") or "").strip()
    if not folder:
        return {"status": "error", "message": "Folder name required"}
    folder_path = SAVED_DIR / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    return {"status": "success", "folder": folder}


@app.delete("/api/saved-folders")
async def delete_saved_folder(request: Request):
    try:
        data = await request.json()
    except:
        body = await request.body()
        data = json.loads(body)
    folder = (data.get("folder") or "").strip()
    if not folder:
        return {"status": "error", "message": "Folder name required"}
    folder_path = SAVED_DIR / folder
    if not folder_path.exists():
        return {"status": "error", "message": "Folder not found"}
    import shutil
    shutil.rmtree(folder_path)
    print(f"[SAVED-FOLDERS] Deleted: {folder}")
    return {"status": "success", "folder": folder}
