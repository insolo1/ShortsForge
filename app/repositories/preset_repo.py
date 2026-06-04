from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.preset import Preset
from app.repositories.base import BaseRepository


class PresetRepository(BaseRepository[Preset]):
    def __init__(self, session: AsyncSession):
        super().__init__(Preset, session)

    async def get_by_name(self, name: str) -> Optional[Preset]:
        stmt = select(Preset).where(Preset.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, name: str, data: dict) -> Preset:
        existing = await self.get_by_name(name)
        if existing:
            existing.data = data
            return existing
        return await self.create(name=name, data=data)
