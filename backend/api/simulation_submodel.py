"""Job-owned region selection only; this does not author or extract a structure."""
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SubmodelBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: Literal["box"] = "box"
    shell_nm: float = Field(3.0, ge=0, le=1000, allow_inf_nan=False)
    visible: bool = True
    min_corner: tuple[float, float, float]
    max_corner: tuple[float, float, float]
    rotation: tuple[float, float, float, float] = (0, 0, 0, 1)

    @field_validator("min_corner", "max_corner", "rotation")
    @classmethod
    def finite(cls, value):
        if not all(math.isfinite(x) for x in value):
            raise ValueError("Box coordinates must be finite")
        return value

    @model_validator(mode="after")
    def valid_box(self):
        if any(b - a < 0.05 - 1e-9 for a, b in zip(self.min_corner, self.max_corner)):
            raise ValueError("Each box dimension must be at least 0.05 nm")
        if abs(sum(x*x for x in self.rotation) - 1) > 1e-5:
            raise ValueError("Rotation must be a unit quaternion")
        return self


class SubmodelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    box: SubmodelBox | None = None


def read_selection(directory: Path) -> dict:
    if not directory.is_dir():
        raise HTTPException(409, "Job storage is unavailable")
    path = directory / "submodel_selection.json"
    if not path.exists():
        return {"box": None}
    return SubmodelSelection.model_validate_json(path.read_text()).model_dump(mode="json")


def save_selection(directory: Path, selection: SubmodelSelection) -> dict:
    # A separate, atomic UI record avoids racing runner writes to job.json. It
    # travels with the job directory and never changes frozen simulation inputs.
    if not directory.is_dir():
        raise HTTPException(409, "Job storage is unavailable")
    data = selection.model_dump(mode="json")
    fd, name = tempfile.mkstemp(prefix=".submodel-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
        os.replace(name, directory / "submodel_selection.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return data
