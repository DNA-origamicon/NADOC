"""Read-only hairpin / self-dimer check over the active design."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.core.hairpin_dimer import (
    DEFAULT_SEVERE_C,
    DEFAULT_THRESHOLD_C,
    ORIGAMI_BUFFER,
    Conditions,
    check_design,
)

router = APIRouter()


class HairpinDimerCheckRequest(BaseModel):
    # Both omitted → every overhang and linker strand in the design.
    overhang_ids: Optional[list[str]] = None
    strand_ids: Optional[list[str]] = None
    threshold_c: float = DEFAULT_THRESHOLD_C
    severe_threshold_c: float = DEFAULT_SEVERE_C
    # Optional overrides of the origami-buffer defaults (0 mM Na⁺, 10 mM Mg²⁺, 200 nM).
    na_mM: Optional[float] = None
    mg_mM: Optional[float] = None
    conc_nM: Optional[float] = None


@router.post("/design/hairpin-dimer-check", status_code=200)
def hairpin_dimer_check(body: Optional[HairpinDimerCheckRequest] = None) -> dict:
    """Hairpin + self-dimer Tm for overhangs and linker strands (no mutation)."""
    body = body or HairpinDimerCheckRequest()
    try:
        conditions = Conditions(
            na_mM=ORIGAMI_BUFFER.na_mM if body.na_mM is None else body.na_mM,
            mg_mM=ORIGAMI_BUFFER.mg_mM if body.mg_mM is None else body.mg_mM,
            conc_nM=ORIGAMI_BUFFER.conc_nM if body.conc_nM is None else body.conc_nM,
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    design = design_state.get_or_404()
    return check_design(
        design,
        overhang_ids=body.overhang_ids,
        strand_ids=body.strand_ids,
        threshold_c=body.threshold_c,
        severe_c=body.severe_threshold_c,
        conditions=conditions,
    )
