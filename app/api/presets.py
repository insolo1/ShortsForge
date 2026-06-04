from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories.preset_repo import PresetRepository

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("/list")
async def list_presets(session: AsyncSession = Depends(get_session)):
    repo = PresetRepository(session)
    presets = await repo.list()
    return {"status": "success", "presets": [{"name": p.name, "data": p.data} for p in presets]}


@router.post("/save")
async def save_preset(name: str, data: dict, session: AsyncSession = Depends(get_session)):
    repo = PresetRepository(session)
    await repo.upsert(name, data)
    return {"status": "success"}


@router.get("/load")
async def load_preset(name: str, session: AsyncSession = Depends(get_session)):
    repo = PresetRepository(session)
    preset = await repo.get_by_name(name)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"status": "success", "preset": {"name": preset.name, "data": preset.data}}
