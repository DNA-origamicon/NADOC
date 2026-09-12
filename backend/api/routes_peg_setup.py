"""Engine-independent PEG setup review. Never builds particles or creates a job."""
from typing import Literal
import math

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.physics.oxdna_peg import PegParameters
from backend.physics.oxdna_surface_strands import strand_count

router = APIRouter(prefix="/oxdna/peg", tags=["PEG setup"])


class PegCoating(PegParameters):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    material: Literal["PEG"] = "PEG"
    enabled: Literal[True] = True
    shape: Literal["square", "circle"] = "square"
    sizeNm: float = Field(12, ge=2, le=1e6)
    densityPerUm2: float = Field(27778, gt=0, le=1e12)
    offsetXNm: float = Field(0, ge=-1e6, le=1e6)
    offsetYNm: float = Field(0, ge=-1e6, le=1e6)
    seed: int = Field(17, ge=0, le=4294967295)
    subjectToField: Literal[False] = False

    @model_validator(mode="after")
    def check_count(self):
        count = strand_count(self.shape, self.sizeNm, self.densityPerUm2)
        if count < 1:
            raise ValueError("Coverage rounds to zero PEG chains; increase density or patch size")
        if count * (self.segments + 1) > 100_000:
            raise ValueError("PEG setup supports at most 100,000 surface beads")
        return self


from backend.physics.oxdna_surface_geometry import SurfaceGeometry


class PegSurface(SurfaceGeometry):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    dir: tuple[float, float, float]
    offset_nm: float = 0
    stiff: float = Field(5, gt=0)

    @model_validator(mode="after")
    def check_direction(self):
        if self.position_nm is None and self.plane_point_nm is None:
            raise ValueError("PEG setup requires an explicit surface plane")
        if not math.isclose(math.hypot(*self.dir), 1, abs_tol=1e-6):
            raise ValueError("Surface direction must be a unit vector")
        return self


class PegSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    surface: PegSurface
    surface_strands: PegCoating
    backend: Literal["CPU", "CUDA"] = "CPU"
    execution_target: Literal["local"] = "local"
    interaction_type: Literal["DNA2"] = "DNA2"


@router.post("/setup")
def review_peg_setup(body: PegSetupRequest) -> dict:
    """Validate a draft, returning a job-request fragment, never launch readiness.

    Counts use the existing engine builder's rounding. Placement, clearance,
    design compatibility, hardware and scientific validation remain separate.
    """
    coating = body.surface_strands
    count = strand_count(coating.shape, coating.sizeNm, coating.densityPerUm2)
    barriers = [
        {"code": "model_validation", "message": "Experimental bead–spring PEG is not chemically calibrated; coating validation is incomplete."},
        {"code": "geometry_preflight", "message": "DNA probe, protein compatibility, graft placement and PEG/DNA clearance still require build-time checks."},
        {"code": "engine_preflight", "message": "Local DNA2PEG binary and CPU/CUDA capability have not been checked."},
        {"code": "namd_mapping", "message": "NAMD coating setup needs a separate atomistic parameterization and grafting workflow; no validated mapping from these statistical segments exists."},
    ]
    if coating.terminalChargeE:
        barriers.append({"code": "terminal_field", "message": "Terminal charge needs a physical electric field in V/m; this setup does not configure or validate that field."})
    return {
        "schema_version": 1,
        "status": "setup_only",
        "launch_ready": False,
        "summary": {"requested_chains": count, "beads_per_chain": coating.segments + 1,
                    "requested_beads": count * (coating.segments + 1)},
        "job_request_fragment": {**body.model_dump(mode="json"), "autostart": False},
        "barriers": barriers,
    }


class PegSeedReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_job_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    target_representation: Literal["coarse_grained", "atomistic"] | None = None


@router.post("/namd-seed")
def review_peg_namd_seed(body: PegSeedReviewRequest):
    from fastapi import HTTPException
    from backend.api.routes_oxdna import _workspace
    from backend.core.peg_seed_source import inspect_peg_job
    try:
        return inspect_peg_job(body.source_job_id, _workspace(), body.target_representation)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
