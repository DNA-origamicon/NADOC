"""Six ordinary native extrusion families for isolated desktop qualification."""
from backend.core.part_history_contract import create_empty_part
from tests.test_part_deformation_preview import _append
from tests.test_part_extrusion_edit_routes import recipe

FAMILIES = ("extrude-segment", "extrude-continuation", "extrude-deformed-continuation",
            "extrude-frame", "circle-segment", "overhang-extrude")


def fixture(kind):
    if kind not in FAMILIES:
        raise ValueError("Unknown extrusion matrix family")
    original, _ = recipe(kind, False)
    name = "__e2e__history-" + kind
    source = create_empty_part(name, original.lattice_type)
    source = source.copy_with(id=original.id)
    for i, row in enumerate(original.feature_log):
        if i == 0:
            row = row.model_copy(update={"params": {**row.params, "name": name}})
        source = _append(source, row)
    for row in source.feature_log:
        row.evicted = True
        row.design_snapshot_gz_b64 = "poisoned-before"
        row.post_state_gz_b64 = "poisoned-after"
    return source


def change(kind, source):
    patch = {"cell_lengths": [14]} if kind == "circle-segment" else {"length_bp": 14}
    if kind != "overhang-extrude":
        patch.update(cells=[[4, 5]], separate_fresh_extrusions=False)
    if kind in {"extrude-segment", "extrude-continuation", "circle-segment"}:
        patch.update(offset_nm=1.5, ligate_adjacent=False, strand_filter="staples")
    if kind == "extrude-continuation":
        patch.update(source_frame_id=source.lattice_frames[0].id, extend_inplace=False)
    elif kind == "extrude-deformed-continuation":
        patch.update(ref_helix_id=source.helices[0].id, source_bp=10)
    elif kind == "extrude-frame":
        patch.update(name="Edited Frame", translation_nm=[3, 2, 1],
                     rotation_xyzw=[0, 0, 0, 1], source_frame_id=None, source_legacy_plane=False)
    elif kind == "overhang-extrude":
        patch.update(reuse_existing_helix=False)
    return patch
