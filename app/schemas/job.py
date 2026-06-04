from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ShortOut(BaseModel):
    id: int
    index: int
    filename: str
    title: str
    description: str
    tags: list
    youtube_url: str
    created_at: datetime


class JobOut(BaseModel):
    id: str
    status: str
    progress: int
    error: str
    shorts_count: int
    short_length: int
    created_at: datetime
    finished_at: Optional[datetime]
    shorts: list[ShortOut] = []


class JobLogOut(BaseModel):
    message: str
    log_type: str
    timestamp: datetime


class JobStatusOut(BaseModel):
    status: str
    progress: int
    total_shorts: int
    uploaded: int
