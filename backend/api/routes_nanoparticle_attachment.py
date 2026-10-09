"""One transaction for selecting, binding and fitting an existing NP handle."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.api import state
from backend.api.crud import _design_response
from backend.api.nanoparticle_attachment import attach_nanoparticle

router = APIRouter()


class AttachRequest(BaseModel):
    overhang_id: str
    strand_id: str | None = None
    fixed_center: bool = False
    expected_revision: int
    expected_design_id: str


@router.post("/design/nanoparticles/{nanoparticle_id}/attach-overhang")
def attach_overhang(nanoparticle_id: str, body: AttachRequest):
    design, revision = state.copy_for_persist()
    if design is None:
        raise HTTPException(404, "Open a design before attaching a nanoparticle.")
    if design.id != body.expected_design_id or revision != body.expected_revision:
        raise HTTPException(409, "Design changed before attachment.")
    try:
        result, diagnostics = attach_nanoparticle(
            design,
            nanoparticle_id,
            body.overhang_id,
            strand_id=body.strand_id,
            fixed_center=body.fixed_center,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    def commit(current):
        # Autosave advances persistence cursors during the numerical fit. Compare
        # actual content under the transaction lock, preserving those cursors.
        exclude = {
            "metadata": {"identity_confirmed_at", "identity_last_known_path"},
            "loadouts": {
                i: {
                    "head_revision_id",
                    "base_revision_id",
                    "design_snapshot_gz_b64",
                    "snapshot_size_bytes",
                }
                for i, item in enumerate(design.loadouts)
                if item.id == design.active_loadout_id
            },
        }
        if current.model_dump(exclude=exclude) != design.model_dump(exclude=exclude):
            raise HTTPException(
                409, "Design changed while attachment was being fitted."
            )
        return result.model_copy(
            update={
                "metadata": result.metadata.model_copy(
                    update={
                        "identity_confirmed_at": current.metadata.identity_confirmed_at,
                        "identity_last_known_path": current.metadata.identity_last_known_path,
                    }
                ),
                "loadouts": current.loadouts,
            }
        )

    updated, report, _ = state.mutate_with_feature_log(
        "nanoparticle-attach-overhang",
        "Attach nanoparticle to overhang",
        {
            "nanoparticle_id": nanoparticle_id,
            "overhang_id": body.overhang_id,
            **diagnostics,
        },
        commit,
    )
    response = _design_response(updated, report)
    response["attachment"] = diagnostics
    return response
