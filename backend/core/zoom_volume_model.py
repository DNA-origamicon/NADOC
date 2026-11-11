"""Display-only inset definitions shared by parts and assemblies."""
from typing import Any

from pydantic import BaseModel, Field


class ZoomVolume(BaseModel):
    id: str
    name: str = "Zoom Volume"
    zoom_step: int = Field(default=0, ge=-8, le=8)
    targets: list[dict[str, Any]] = Field(default_factory=list)
    volume: dict[str, Any] | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    custom_position: dict[str, float] | None = None
