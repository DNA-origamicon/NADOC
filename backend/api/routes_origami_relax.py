"""Experimental pose-only backbone minimization in one undoable operation."""

from fastapi import APIRouter, HTTPException
from backend.api import state as design_state
from backend.api.crud import _design_response_with_geometry
from backend.core.origami_relax import relax_origami

router = APIRouter()
_VIEW_FIELDS = {
    "metadata",
    "camera_poses",
    "feature_log",
    "feature_log_cursor",
    "feature_log_sub_cursor",
}


@router.post("/design/relax-origami")
def relax():
    design_state.require_compatibility_write("relax_origami")
    source = design_state.get_or_404()
    if source.recipe_root is not None:
        from backend.api.part_import_relaxation import apply_native
        updated, validation, report = apply_native()
        response = _design_response_with_geometry(updated, validation)
        response["relaxation"] = report
        return response
    source_state = source.model_dump(exclude=_VIEW_FIELDS)
    try:
        candidate, report = relax_origami(source)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    def apply(current):
        current_state = current.model_dump(exclude=_VIEW_FIELDS)
        # The first autosave materializes Loadout 1 for legacy imports. This is
        # initialization of the same branch, not a user switching branches.
        if (
            not source_state["loadouts"]
            and source_state["active_loadout_id"] is None
            and len(current.loadouts) == 1
            and not current.loadouts[0].protected
            and current.active_loadout_id == current.loadouts[0].id
        ):
            current_state["loadouts"] = []
            current_state["active_loadout_id"] = None
        changed_fields = [
            key for key in source_state if source_state[key] != current_state[key]
        ]
        if changed_fields:
            raise HTTPException(
                409,
                detail="Design changed during relaxation; run again on the current design.",
            )
        # A camera/name update during the solve must survive the pose commit.
        return current.copy_with(cluster_transforms=candidate.cluster_transforms)

    updated, validation, _ = design_state.mutate_with_feature_log(
        "relax-origami",
        "Relax Origami",
        {"relaxation": report},
        apply,
    )
    response = _design_response_with_geometry(updated, validation)
    response["relaxation"] = report
    return response
