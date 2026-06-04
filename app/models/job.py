from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, JSON, DateTime, Enum as SAEnum
from app.core.database import Base
import enum


class JobStatus(str, enum.Enum):
    STARTING = "starting"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class Short(Base):
    __tablename__ = "shorts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False, index=True)
    index = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    title = Column(String(200), default="")
    description = Column(Text, default="")
    tags = Column(JSON, default=list)
    youtube_id = Column(String(50), default="")
    youtube_url = Column(String(255), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)
    status = Column(String(20), nullable=False, default=JobStatus.STARTING.value, index=True)
    progress = Column(Integer, default=0)
    error = Column(Text, default="")
    source = Column(String(10), default="file")
    video_title = Column(String(200), default="")
    video_duration = Column(Float, default=0)
    shorts_count = Column(Integer, default=5)
    short_length = Column(Integer, default=45)
    is_integration = Column(Boolean, default=False)
    save_video = Column(Boolean, default=False)
    save_folder = Column(String(100), default="saved")

    enable_scheduled = Column(Boolean, default=False)
    schedule_start = Column(DateTime, nullable=True)
    schedule_interval = Column(Integer, default=60)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False, index=True)
    message = Column(Text, nullable=False)
    log_type = Column(String(20), default="info")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
