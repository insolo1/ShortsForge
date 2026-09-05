import uuid
import time
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.config import settings
from app.repositories.job_repo import JobRepository
from app.repositories.preset_repo import PresetRepository
from app.tasks.video_tasks import process_video_task
from app.integrations.groq import generate_metadata
from app.processor import VideoProcessor
from app.youtube_api import YouTubeAPI

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/upload-url")
async def upload_url(
    url: str = Form(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    session: AsyncSession = Depends(get_session)
):
    job_id = str(uuid.uuid4())
    repo = JobRepository(session)
    await repo.create(
        id=job_id, status="starting", shorts_count=shorts_count,
        short_length=short_length, source="url"
    )
    await repo.add_log(job_id, f"Downloading: {url}", "info")

    process_video_task.delay(
        job_id=job_id, source="url", video_url=url,
        short_length=short_length, shorts_count=shorts_count
    )
    return {"job_id": job_id, "status": "started"}


@router.post("/upload-file")
async def upload_file(
    video_file: UploadFile = File(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    session: AsyncSession = Depends(get_session)
):
    job_id = str(uuid.uuid4())
    repo = JobRepository(session)

    safe_filename = f"{job_id}_input.mp4"
    video_path = settings.UPLOAD_DIR / safe_filename
    content = await video_file.read()
    with open(video_path, "wb") as f:
        f.write(content)

    await repo.create(
        id=job_id, status="starting", shorts_count=shorts_count,
        short_length=short_length, source="file"
    )
    await repo.add_log(job_id, f"File saved: {video_file.filename}", "info")

    process_video_task.delay(
        job_id=job_id, source="file", video_file_path=str(video_path),
        short_length=short_length, shorts_count=shorts_count
    )
    return {"job_id": job_id, "status": "started"}


@router.post("/integration/start")
async def start_integration(
    source: str = Form(...),
    video_url: str = Form(None),
    video_file: UploadFile = File(None),
    accounts: str = Form(...),
    short_length: int = Form(45),
    shorts_count: int = Form(5),
    distribution_mode: str = Form("equal"),
    blurred_bg: bool = Form(False),
    crop_mode: str = Form("square"),
    save_video: bool = Form(False),
    save_folder: str = Form("saved"),
    banner_enabled: bool = Form(False),
    banner_x: int = Form(0), banner_y: int = Form(0),
    banner_w: int = Form(1080), banner_h: int = Form(200), banner_opacity: int = Form(100),
    banner_file: UploadFile = File(None),
    smart_selection: str = Form("off"),
    scene_start: bool = Form(False),
    subtitle_font: str = Form("Montserrat"),
    enable_scheduled: bool = Form(False),
    schedule_start_date: str = Form(None),
    schedule_start_time: str = Form(None),
    schedule_interval: int = Form(60),
    session: AsyncSession = Depends(get_session)
):
    job_id = str(uuid.uuid4())
    repo = JobRepository(session)

    account_list = [{"email": line.strip()} for line in accounts.strip().split("\n") if line.strip() and "@" in line]
    if not account_list:
        raise HTTPException(status_code=400, detail="No accounts provided")

    video_file_path = None
    if source == "file" and video_file:
        safe_filename = f"{job_id}_input.mp4"
        video_file_path = str(settings.UPLOAD_DIR / safe_filename)
        content = await video_file.read()
        with open(video_file_path, "wb") as f:
            f.write(content)

    banner_path = None
    if banner_enabled and banner_file:
        ext = Path(banner_file.filename).suffix or ".png"
        banner_path = str(settings.UPLOAD_DIR / "banners" / f"banner_{job_id}{ext}")
        Path(settings.UPLOAD_DIR / "banners").mkdir(exist_ok=True)
        content = await banner_file.read()
        with open(banner_path, "wb") as f:
            f.write(content)

    await repo.create(
        id=job_id, status="starting", is_integration=True,
        shorts_count=shorts_count, short_length=short_length,
        source=source, save_video=save_video, save_folder=save_folder,
        enable_scheduled=enable_scheduled, schedule_interval=schedule_interval
    )
    await repo.add_log(job_id, f"Integration started: {len(account_list)} accounts", "info")

    process_video_task.delay(
        job_id=job_id, source=source, video_url=video_url,
        video_file_path=video_file_path,
        short_length=short_length, shorts_count=shorts_count,
        blurred_bg=blurred_bg, crop_mode=crop_mode,
        save_video=save_video, save_folder=save_folder,
        banner_enabled=banner_enabled, banner_path=banner_path,
        banner_x=banner_x, banner_y=banner_y,
        banner_w=banner_w, banner_h=banner_h, banner_opacity=banner_opacity,
        smart_selection=smart_selection,
        scene_start=scene_start, subtitle_font=subtitle_font,
        distribution_mode=distribution_mode, accounts=account_list,
        enable_scheduled=enable_scheduled,
        schedule_start_date=schedule_start_date,
        schedule_start_time=schedule_start_time,
        schedule_interval=schedule_interval
    )
    return {"job_id": job_id, "status": "started"}


@router.get("/jobs")
async def list_jobs(session: AsyncSession = Depends(get_session)):
    repo = JobRepository(session)
    jobs = await repo.list(limit=50)
    return {
        "jobs": [{
            "id": j.id, "status": j.status, "progress": j.progress,
            "shorts_count": j.shorts_count,
            "created_at": j.created_at.isoformat() if j.created_at else None
        } for j in jobs]
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    shorts = await repo.get_shorts(job_id)
    return {
        "id": job.id, "status": job.status, "progress": job.progress,
        "error": job.error, "shorts_count": job.shorts_count,
        "short_length": job.short_length,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "shorts": [{
            "index": s.index, "filename": s.filename, "title": s.title,
            "description": s.description, "tags": s.tags, "youtube_url": s.youtube_url
        } for s in shorts]
    }


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, session: AsyncSession = Depends(get_session)):
    repo = JobRepository(session)
    logs = await repo.get_logs(job_id)
    return {
        "logs": [{"message": l.message, "type": l.log_type,
                   "timestamp": l.timestamp.isoformat() if l.timestamp else None}
                 for l in logs]
    }


@router.post("/cleanup")
async def cleanup(session: AsyncSession = Depends(get_session)):
    repo = JobRepository(session)
    await repo.cleanup_old(hours=24)
    return {"status": "ok"}
