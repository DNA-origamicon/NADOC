"""Persisted sweep geometry; authoring intent lives in its snapshot feature."""
from typing import Literal
from pydantic import BaseModel, Field


class SweepParams(BaseModel):
    kind: Literal['sweep'] = 'sweep'
    points_nm: list[tuple[float, float, float]] = Field(min_length=2, max_length=256)
    origin_nm: tuple[float, float, float]
    initial_rotation: list[float] = Field(min_length=9, max_length=9)
    initial_tangent: tuple[float, float, float] | None = None
    preceding_op_ids: list[str] = Field(default_factory=list)
    direction: Literal[-1, 1] = 1
    start_step: int = 0
    steps: int = Field(ge=1)
    path_length_nm: float = Field(gt=0)
