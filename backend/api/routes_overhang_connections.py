"""CRUD routes for topology-backed overhang linker connections."""

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import _design_response

router = APIRouter()


class OverhangConnectionCreateRequest(BaseModel):
    overhang_a_id: str
    overhang_a_attach: Literal["root", "free_end"]
    overhang_b_id: str
    overhang_b_attach: Literal["root", "free_end"]
    linker_type: Literal["ss", "ds"]
    length_value: float
    length_unit: Literal["bp", "nm"]
    name: Optional[str] = None  # auto-assigned L1/L2/… if omitted
    # Optional bridge sequence supplied by the Connection Types tab's bridge
    # text box. When provided, it's stitched into the linker strand(s) after
    # topology creation: ss strand sequence = [comp_a, bridge, comp_b];
    # ds strand __a = [comp_a, bridge]; ds strand __b uses RC(bridge) so the
    # two halves pair on the virtual helix. Complement portions come from the
    # bound overhang sequence (RC), or N×L when the overhang has none.
    bridge_sequence: Optional[str] = None


class OverhangConnectionPatchRequest(BaseModel):
    name: Optional[str] = None
    length_value: Optional[float] = None
    length_unit: Optional[Literal["bp", "nm"]] = None
    # Sentinel-style update for the linker's bridge_sequence: omit the field
    # to leave it untouched; pass an empty string ("") to clear it; pass a
    # non-empty string to assign. Uppercased + stripped server-side; only
    # ACGTN characters survive.
    bridge_sequence: Optional[str] = None


@router.post("/design/overhang-connections", status_code=201)
def create_overhang_connection(body: OverhangConnectionCreateRequest) -> dict:
    """Create a validated connection and its native linker strand topology."""
    from backend.api.part_linker_commands import build
    from uuid import uuid4
    conn_id = str(uuid4())
    params = {**body.model_dump(mode="json", exclude_unset=True), "conn_id": conn_id}
    updated, report, _entry = design_state.mutate_with_feature_log(
        "linker-add", "Create linker", params, lambda d: build("linker-add", d, params))
    return _design_response(updated, report)


@router.patch("/design/overhang-connections/{conn_id}", status_code=200)
def patch_overhang_connection(
    conn_id: str, body: OverhangConnectionPatchRequest
) -> dict:
    """Update name / length_value / length_unit on an existing connection.

    Changing length_value or length_unit auto-rebuilds the linker topology
    (the old strand(s) and virtual helix are stripped and regenerated against
    the new length). Other fields (overhangs, attach points, linker_type) are
    immutable through this endpoint — to change them, delete and re-create.
    """
    from backend.api.part_linker_commands import build
    params = {**body.model_dump(mode="json", exclude_unset=True), "conn_id": conn_id}
    updated, report, _entry = design_state.mutate_with_feature_log(
        "linker-patch", "Patch linker", params, lambda d: build("linker-patch", d, params))
    return _design_response(updated, report)


@router.delete("/design/overhang-connections/{conn_id}", status_code=200)
def delete_overhang_connection(conn_id: str) -> dict:
    """Remove a single OverhangConnection by id, plus its linker topology.

    Emits a `linker-delete` SnapshotLogEntry so the deletion shows up on the
    feature-log timeline alongside the linker's `linker-add` entry — keeps
    the Overhangs Manager and the feature log in sync (any change in either
    surface is visible in the timeline). Reverting the delete entry brings
    the linker back exactly as it was.
    """
    from backend.api.part_linker_commands import build
    params = {"conn_id": conn_id}
    updated, report, _entry = design_state.mutate_with_feature_log(
        "linker-delete", "Delete linker", params, lambda d: build("linker-delete", d, params))
    return _design_response(updated, report)
