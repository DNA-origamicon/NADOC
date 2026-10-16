"""Thin ordinary history adapter for the owned extrusion input editor."""

from fastapi import HTTPException


def owns_edit(design, entry, body):
    from backend.api.part_extrusion_edit_inputs import KINDS

    return (getattr(entry, "op_kind", None) in KINDS
            and (design.group_organization is not None or body.expected_feature_id is not None))


def edit_response(index, body, *, sub_index=None):
    from backend.api.crud import _design_response_with_geometry
    from backend.api.part_extrusion_recording import edit

    if sub_index is not None:
        raise HTTPException(422, detail="An extrusion has no editable child feature.")
    candidate, report, entry = edit(index, body.params,
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision,
        expected_feature_id=body.expected_feature_id)
    # Native rebuild already owns the complete authoring result. Do not infer
    # legacy owners or ask the client to fetch geometry from a later revision.
    return _design_response_with_geometry(candidate, report, embed_straight=True,
        normalize_legacy=False, preserve_feature_log_id=entry.id)
