import os
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from celery import states
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.celery_app import celery_app
from app.core.database import get_session_factory

async_session_factory = get_session_factory()
from app.core.database import init_db
from app.core.config import settings
from app.repositories.job_repo import JobRepository
from app.processor import VideoProcessor
from app.integrations import groq
from app.integrations.whisper import transcribe as whisper_transcribe
from app.youtube_api import YouTubeAPI


def _sync_init():
    import asyncio
    try:
        asyncio.run(init_db())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(init_db())
        loop.close()


async def _process_segment(processor, video_path, segment, i, job_id, subtitle_data, crop_mode, blurred_bg, banner_enabled, banner_path, banner_x, banner_y, banner_w, banner_h, banner_opacity, subtitle_font="Montserrat"):
    short_path = await processor.create_short(
        video_path, segment, i, job_id, subtitle_data,
        crop_mode, blurred_bg, "",
        banner_enabled, banner_path, banner_x, banner_y,
        banner_w, banner_h, banner_opacity,
        subtitle_font_name=subtitle_font
    )
    return short_path


async def _run_job(job_id: str, source: str, video_url: str, video_file_path: str,
                    short_length: int, shorts_count: int,
                    crop_mode: str, blurred_bg: bool,
                    save_video: bool, save_folder: str,
                    banner_enabled: bool, banner_path: str,
                    banner_x: int, banner_y: int, banner_w: int, banner_h: int, banner_opacity: int,
                    smart_selection: str, scene_start: bool, subtitle_font: str,
                    distribution_mode: str, accounts: list,
                    enable_scheduled: bool, schedule_start_date: str, schedule_start_time: str, schedule_interval: int):
    """Core job logic - runs inside asyncio loop"""
    async with async_session_factory() as session:
        repo = JobRepository(session)
        processor = VideoProcessor(str(settings.UPLOAD_DIR), str(settings.OUTPUT_DIR))
        youtube_api = YouTubeAPI(
            client_secret_file=str(settings.BASE_DIR / "client_secret.json"),
            tokens_dir=str(settings.TOKENS_DIR)
        )

        try:
            await repo.update_progress(job_id, 5, "processing")
            await repo.add_log(job_id, f"Job started: {job_id}", "info")

            if source == "url" and video_url:
                video_path = await processor.download_video(video_url, job_id)
                await repo.add_log(job_id, "Video downloaded", "success")
            else:
                video_path = video_file_path
                await repo.add_log(job_id, "Using local file", "info")

            video_info = await processor.get_video_info(video_path)
            await repo.add_log(job_id, f"Duration: {video_info.get('duration', 0):.1f}s", "info")

            await repo.add_log(job_id, f"Extracting {shorts_count} segments x {short_length}s", "progress")

            from app.segment_scorer import extract_features_for_windows
            from app.segment_scorer import SegmentScorer

            if smart_selection and smart_selection != "off":
                segments, _ = await _smart_select_segments(
                    processor, video_path, video_info["duration"],
                    short_length, shorts_count, smart_selection, scene_start
                )
            else:
                segments = await processor.extract_segments(video_path, short_length, shorts_count)

            await repo.add_log(job_id, f"Found {len(segments)} segments", "success")

            shorts = []
            for i, segment in enumerate(segments):
                await repo.add_log(job_id, f"[{i+1}/{len(segments)}] Processing {segment['start']:.1f}s-{segment['end']:.1f}s", "progress")

                subtitle_data = await processor.get_subtitles(video_path, segment["start"], segment["end"])
                await repo.add_log(job_id, f"[{i+1}/{len(segments)}] Subtitles: {len(subtitle_data.get('segments', []))} phrases", "info")

                short_path = await _process_segment(
                    processor, video_path, segment, i, job_id,
                    subtitle_data.get("segments"),
                    crop_mode, blurred_bg, banner_enabled, banner_path,
                    banner_x, banner_y, banner_w, banner_h, banner_opacity,
                    subtitle_font
                )

                if not short_path or not Path(short_path).exists():
                    await repo.add_log(job_id, f"[{i+1}/{len(segments)}] Video not created", "warning")
                    continue

                await repo.add_log(job_id, f"[{i+1}/{len(segments)}] Video created", "success")

                transcript_text = subtitle_data.get("text", "")
                try:
                    metadata = await groq.generate_metadata(
                        transcript_text, i + 1, video_info
                    )
                    if metadata.get("_ai_error"):
                        await repo.add_log(
                            job_id,
                            f"[{i+1}/{len(segments)}] AI fallback: {metadata['_ai_error']}",
                            "warning"
                        )
                    await repo.add_log(job_id, f"[{i+1}/{len(segments)}] Title: {metadata['title'][:50]}...", "info")
                except Exception as e:
                    metadata = {"title": f"#shorts #{i+1}", "description": "Video short", "tags": ["#shorts"]}
                    await repo.add_log(job_id, f"[{i+1}/{len(segments)}] AI fallback: {e}", "warning")

                shorts.append({
                    "path": short_path,
                    "title": metadata["title"],
                    "description": metadata["description"],
                    "tags": metadata["tags"]
                })

                await repo.add_short(
                    job_id, i,
                    filename=Path(short_path).name,
                    filepath=short_path,
                    title=metadata["title"],
                    description=metadata["description"],
                    tags=metadata["tags"]
                )

                progress = 20 + (i + 1) * 40 // len(segments)
                await repo.update_progress(job_id, progress)

                if save_video:
                    saved_dir = settings.BASE_DIR / "saved" / (save_folder or "saved")
                    saved_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(short_path, saved_dir / f"short_{job_id}_{i}.mp4")
                    await repo.add_log(job_id, f"[{i+1}/{len(segments)}] Saved to {save_folder}", "success")

            await repo.update_progress(job_id, 60, "uploading")
            await repo.add_log(job_id, f"Uploading {len(shorts)} videos...", "info")

            if accounts:
                video_index = 0
                for acc in accounts:
                    email = acc["email"]
                    await repo.add_log(job_id, f"Authorizing: {email}", "progress")
                    youtube_api.client_secret_file = str(
                        settings.GOOGLE_CREDENTIALS_DIR / f"{email.replace('@', '_at_').replace('.', '_')}.json"
                    )
                    if not youtube_api.authenticate(email):
                        await repo.add_log(job_id, f"Auth failed: {email}", "error")
                        continue

                    if video_index < len(shorts):
                        short = shorts[video_index]
                        video_id = youtube_api.upload_video(
                            short["path"], short["title"],
                            short["description"], short["tags"],
                            category_id="22", privacy_status="public"
                        )
                        if video_id:
                            await repo.add_log(job_id, f"Uploaded: https://youtube.com/watch?v={video_id}", "success")
                        else:
                            await repo.add_log(job_id, f"Upload failed", "error")
                        video_index += 1

            await repo.update_progress(job_id, 100, "completed")
            await repo.add_log(job_id, f"Job completed! Uploaded {video_index}/{len(shorts)}", "success")

        except Exception as e:
            await repo.add_log(job_id, f"Error: {e}", "error")
            await repo.update_progress(job_id, 0, "failed")
            import traceback
            traceback.print_exc()


async def _smart_select_segments(processor, video_path, duration, short_length, shorts_count, mode, scene_start=False):
    from app.processor import VideoProcessor
    segments = await processor.extract_segments(
        video_path, short_length, shorts_count,
        smart_selection=mode, scene_start=scene_start
    )
    return segments, []


@celery_app.task(bind=True, name="process_video", max_retries=3)
def process_video_task(self, job_id: str, source: str = "file",
                       video_url: str = None, video_file_path: str = None,
                       short_length: int = 45, shorts_count: int = 5,
                       crop_mode: str = "square", blurred_bg: bool = False,
                       save_video: bool = False, save_folder: str = "saved",
                       banner_enabled: bool = False, banner_path: str = None,
                       banner_x: int = 0, banner_y: int = 0,
                       banner_w: int = 1080, banner_h: int = 200, banner_opacity: int = 100,
                       smart_selection: str = "off",
                       scene_start: bool = False, subtitle_font: str = "Montserrat",
                       distribution_mode: str = "equal", accounts: list = None,
                       enable_scheduled: bool = False,
                       schedule_start_date: str = None,
                       schedule_start_time: str = None,
                       schedule_interval: int = 60):
    import asyncio
    try:
        asyncio.run(_run_job(
            job_id, source, video_url, video_file_path,
            short_length, shorts_count,
            crop_mode, blurred_bg, save_video, save_folder,
            banner_enabled, banner_path, banner_x, banner_y, banner_w, banner_h, banner_opacity,
            smart_selection, scene_start, subtitle_font, distribution_mode, accounts or [],
            enable_scheduled, schedule_start_date, schedule_start_time, schedule_interval
        ))
    except RuntimeError:
        # Already running in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_job(
                job_id, source, video_url, video_file_path,
                short_length, shorts_count,
                crop_mode, blurred_bg, save_video, save_folder,
                banner_enabled, banner_path, banner_x, banner_y, banner_w, banner_h, banner_opacity,
                smart_selection, scene_start, subtitle_font, distribution_mode, accounts or [],
                enable_scheduled, schedule_start_date, schedule_start_time, schedule_interval
            ))
        finally:
            loop.close()
