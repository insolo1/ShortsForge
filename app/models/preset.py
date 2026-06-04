from sqlalchemy import Column, Integer, String, Text, JSON
from app.core.database import Base


class Preset(Base):
    __tablename__ = "presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    data = Column(JSON, nullable=False, default=dict)
