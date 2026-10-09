"""Persisted sweep geometry; authoring intent lives in its snapshot feature."""

from typing import Literal
from pydantic import BaseModel, Field, model_validator


class SweepParams(BaseModel):
    kind: Literal["sweep"] = "sweep"
    points_nm: list[tuple[float, float, float]] = Field(min_length=2, max_length=256)
    origin_nm: tuple[float, float, float]
    initial_rotation: list[float] = Field(min_length=9, max_length=9)
    initial_tangent: tuple[float, float, float] | None = None
    point_frames: list[list[float] | None] | None = None
    warning_bps: list[int] = Field(default_factory=list)
    auto_loop_skips: bool = False
    loop_skip_warnings: list[str] = Field(default_factory=list)
    preceding_op_ids: list[str] = Field(default_factory=list)
    direction: Literal[-1, 1] = 1
    start_step: int = 0
    steps: int = Field(ge=1)
    path_length_nm: float = Field(gt=0)

    # Generator-authored common bp stations keep shared junctions registered.
    bp_positions_nm: list[tuple[float, float, float]] | None = Field(
        default=None, max_length=2048
    )
    bp_frames: list[list[float]] | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_bp_stations(self):
        import numpy as np

        if self.bp_positions_nm is None and self.bp_frames is None:
            return self
        if (
            self.bp_positions_nm is None
            or self.bp_frames is None
            or len(self.bp_positions_nm) != self.steps + 1
            or len(self.bp_frames) != self.steps + 1
        ):
            raise ValueError(
                "Indexed sweep requires one position and frame per bp station."
            )
        matrices = np.asarray(self.bp_frames)
        if (
            matrices.shape != (self.steps + 1, 9)
            or not np.isfinite(matrices).all()
            or not np.isfinite(self.bp_positions_nm).all()
        ):
            raise ValueError(
                "Indexed sweep stations must be finite positions and 3x3 frames."
            )
        r = matrices.reshape(-1, 3, 3)
        if not np.allclose(
            r.transpose(0, 2, 1) @ r, np.eye(3), atol=1e-6
        ) or not np.allclose(np.linalg.det(r), 1, atol=1e-6):
            raise ValueError("Indexed sweep frames must be proper rotations.")
        return self
