"""Display-only measured segments in desktop scene coordinates (nanometres)."""
import math
from pydantic import BaseModel, Field, field_validator


class Dimension(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(default='Dimension', max_length=128)
    a: tuple[float, float, float]
    b: tuple[float, float, float]
    visible: bool = True

    @field_validator('name')
    @classmethod
    def printable(cls, value):
        if any(ord(c)<32 for c in value):
            raise ValueError('Measurement names cannot contain control characters.')
        return value

    @field_validator('a', 'b')
    @classmethod
    def finite(cls, value):
        if not all(math.isfinite(v) and abs(v) <= 1e12 for v in value):
            raise ValueError('Measurement coordinates must be finite nanometres.')
        return value


class DimensionChanges(BaseModel):
    document_id: str = Field(min_length=1, max_length=128)
    upsert: list[Dimension] = Field(default_factory=list, max_length=2048)
    delete: list[str] = Field(default_factory=list, max_length=2048)


def merge_dimensions(existing, changes):
    """Per-record operations preserve unrelated desktop and VR edits."""
    merged = {item.id: item for item in existing}
    for key in changes.delete:
        merged.pop(key, None)
    for item in changes.upsert:
        merged[item.id] = item.model_copy(deep=True)
    if len(merged) > 2048:
        raise ValueError('At most 2048 dimensions can be saved.')
    return list(merged.values())
