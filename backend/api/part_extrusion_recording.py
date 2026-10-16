"""Ordinary guarded extrusion history edits use the shared native recipe host."""


def edit(index, params, *, expected_feature_id, expected_design_id, expected_revision, cancelled=None):
    from backend.api.part_ordinary_recipe_recording import edit_extrusion

    return edit_extrusion(index, params, expected_feature_id=expected_feature_id,
        expected_design_id=expected_design_id, expected_revision=expected_revision,
        cancelled=cancelled)
