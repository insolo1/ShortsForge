from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, Short, JobLog
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    def __init__(self, session: AsyncSession):
        super().__init__(Job, session)

    async def get_by_status(self, status: str, limit: int = 10) -> List[Job]:
        stmt = select(Job).where(Job.status == status).order_by(Job.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_progress(self, job_id: str, progress: int, status: Optional[str] = None):
        job = await self.get(job_id)
        if job:
            job.progress = progress
            if status:
                job.status = status
            if status == "completed":
                job.finished_at = datetime.now(timezone.utc)
            await self.session.flush()

    async def add_log(self, job_id: str, message: str, log_type: str = "info"):
        log = JobLog(job_id=job_id, message=message, log_type=log_type)
        self.session.add(log)

    async def get_logs(self, job_id: str, limit: int = 100) -> List[JobLog]:
        stmt = select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.timestamp.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_short(self, job_id: str, index: int, filename: str, filepath: str, **kwargs) -> Short:
        short = Short(job_id=job_id, index=index, filename=filename, filepath=filepath, **kwargs)
        self.session.add(short)
        await self.session.flush()
        return short

    async def get_shorts(self, job_id: str) -> List[Short]:
        stmt = select(Short).where(Short.job_id == job_id).order_by(Short.index)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def cleanup_old(self, hours: int = 24):
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        stmt = delete(JobLog).where(JobLog.timestamp < cutoff)
        await self.session.execute(stmt)
