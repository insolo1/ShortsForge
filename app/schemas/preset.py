from pydantic import BaseModel


class PresetOut(BaseModel):
    name: str
    data: dict
