"""Closed ordinary extrusion edits; no state, numerical replay or disk fixtures."""

from copy import deepcopy

import pytest

from backend.core import lattice, models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


SEED = "2345ee56-bb57-44e7-8a2b-a3548a5d213b"
KINDS = ("bundle-create", "extrude-segment", "extrude-continuation",
         "extrude-deformed-continuation", "extrude-frame", "circle-segment", "overhang-extrude")


def module():
    from backend.api import part_extrusion_edit_inputs
    return part_extrusion_edit_inputs


def inputs(kind):
    value = {"_proof_version": 1, "history_seed": SEED,
             "cells": [[0, 0]], "length_bp": 12, "plane": "XY"}
    if kind == "circle-segment":
        value.pop("length_bp")
        value["cell_lengths"] = [12]
    elif kind == "extrude-deformed-continuation":
        value.update(grid_origin=[0, 0, 0], axis_dir=[0, 0, 1],
                     frame_right=[1, 0, 0], frame_up=[0, 1, 0],
                     ref_helix_id=None, source_bp=None)
    elif kind == "extrude-frame":
        value.update(expected_design_id="old-design", expected_revision=7)
    elif kind == "extrude-continuation":
        value.update(expected_design_id="old-design", expected_revision=7,
                     source_frame_id=None, _source_helix_ids=["original-source"])
    elif kind == "overhang-extrude":
        value = {"_proof_version": 1, "history_seed": SEED, "helix_id": "source",
                 "bp_index": 10, "direction": "FORWARD", "is_five_prime": False,
                 "neighbor_row": 1, "neighbor_col": 0, "length_bp": 12,
                 "reuse_existing_helix": True}
    return value


PATCHES = {
    "bundle-create": {"cells": [[1, 2]], "length_bp": -9, "name": "Edited", "plane": "YZ",
                      "strand_filter": "scaffold", "lattice_type": "SQUARE",
                      "ligate_adjacent": False, "separate_fresh_extrusions": False},
    "extrude-segment": {"cells": [[1, 2]], "length_bp": -9, "plane": "YZ", "offset_nm": 2.5,
                        "strand_filter": "staples", "ligate_adjacent": False,
                        "separate_fresh_extrusions": False},
    "extrude-continuation": {"cells": [[1, 2]], "length_bp": -9, "plane": "YZ", "offset_nm": 2.5,
                             "strand_filter": "staples", "ligate_adjacent": False,
                             "separate_fresh_extrusions": False, "extend_inplace": False,
                             "source_frame_id": "frame-b"},
    "extrude-deformed-continuation": {"cells": [[1, 2]], "length_bp": -9, "plane": "YZ",
                                      "ref_helix_id": "another-helix", "source_bp": 17,
                                      "grid_origin": [1, 2, 3], "axis_dir": [1, 0, 0],
                                      "frame_right": [0, 1, 0], "frame_up": [0, 0, 1],
                                      "separate_fresh_extrusions": False},
    "extrude-frame": {"cells": [[1, 2]], "length_bp": -9, "plane": "YZ", "name": "Placed",
                      "translation_nm": [1, 2, 3], "rotation_xyzw": [0, 0, 0.6, 0.8],
                      "source_frame_id": None, "source_legacy_plane": False,
                      "separate_fresh_extrusions": False},
    "circle-segment": {"cells": [[1, 2], [1, 3]], "cell_lengths": [9, 11], "plane": "YZ",
                       "offset_nm": 2.5, "strand_filter": "staples", "ligate_adjacent": False,
                       "separate_fresh_extrusions": False},
    "overhang-extrude": {"helix_id": "another-helix", "bp_index": 17, "direction": "REVERSE",
                         "is_five_prime": True, "neighbor_row": -1, "neighbor_col": 2,
                         "length_bp": 9, "reuse_existing_helix": False},
}


@pytest.mark.parametrize("kind", KINDS)
def test_complete_native_controls_remain_editable_and_owned(kind):
    previous, patch = inputs(kind), deepcopy(PATCHES[kind])
    before, requested = deepcopy(previous), deepcopy(patch)
    result = module().normalize(kind, previous, patch)
    assert all(result[key] == value for key, value in patch.items())
    assert result["history_seed"] == SEED and result["_proof_version"] == 1
    for key in ("expected_design_id", "expected_revision", "_source_helix_ids"):
        assert (key in result) == (key in previous)
        if key in previous:
            assert result[key] == previous[key]
    result["history_seed"] = "changed"
    if "cells" in result:
        result["cells"][0][0] = 99
    assert previous == before and patch == requested


@pytest.mark.parametrize("field,value", [
    ("history_seed", "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"), ("_proof_version", 2),
    ("_proof_version", True), ("expected_design_id", "new"), ("expected_revision", 8),
    ("expected_revision", True), ("_source_helix_ids", ["new-source"]),
])
def test_output_contract_and_transport_expectations_cannot_be_edited(field, value):
    previous = inputs("extrude-continuation")
    before = deepcopy(previous)
    with pytest.raises(CommandContractError):
        module().normalize("extrude-continuation", previous, {field: value})
    assert previous == before


@pytest.mark.parametrize("extra", [{"future_field": 1}, {"_generated_scope": {}}, {"_generator": {"kind": "test"}}])
def test_unknown_or_generated_prior_definition_is_not_silently_stripped(extra):
    with pytest.raises(CommandContractError):
        module().normalize("extrude-segment", {**inputs("extrude-segment"), **extra}, {"length_bp": 8})


@pytest.mark.parametrize("kind,patch", [
    ("bundle-create", {"cells": []}), ("bundle-create", {"cells": [[0, 0, 0]]}),
    ("bundle-create", {"cells": [[True, 0]]}), ("bundle-create", {"cells": [[0, 0], [0, 0]]}),
    ("bundle-create", {"cells": [[n, 0] for n in range(513)]}),
    ("extrude-segment", {"length_bp": 0}), ("extrude-segment", {"length_bp": True}),
    ("extrude-segment", {"length_bp": "12"}), ("extrude-segment", {"length_bp": 50_001}),
    ("extrude-segment", {"offset_nm": float("nan")}), ("extrude-segment", {"offset_nm": True}),
    ("extrude-segment", {"plane": "ZZ"}), ("extrude-segment", {"strand_filter": "anything"}),
    ("extrude-segment", {"ligate_adjacent": 1}),
    ("extrude-continuation", {"source_frame_id": ""}),
    ("extrude-deformed-continuation", {"source_bp": True}),
    ("extrude-deformed-continuation", {"axis_dir": [0, 1]}),
    ("extrude-deformed-continuation", {"frame_up": [0, True, 0]}),
    ("extrude-frame", {"rotation_xyzw": [0, 0, 0, 2]}),
    ("extrude-frame", {"source_frame_id": "frame", "translation_nm": [1, 0, 0]}),
    ("extrude-frame", {"source_frame_id": "frame", "source_legacy_plane": True}),
    ("circle-segment", {"cell_lengths": []}), ("circle-segment", {"cell_lengths": [-1]}),
    ("circle-segment", {"cell_lengths": [True]}),
    ("overhang-extrude", {"length_bp": -1}), ("overhang-extrude", {"neighbor_col": 1.5}),
    ("overhang-extrude", {"direction": "sideways"}), ("overhang-extrude", {"future": 1}),
])
def test_invalid_inputs_refuse_before_any_builder(kind, patch, monkeypatch):
    from backend.api import crud
    for name in ("_build_bundle", "_build_extrude_segment", "_build_extrude_continuation",
                 "_build_extrude_deformed_continuation", "_build_circle_segment", "_build_overhang_extrude"):
        monkeypatch.setattr(crud, name, lambda *a, **k: pytest.fail("native builder"))
    with pytest.raises(CommandContractError):
        module().normalize(kind, inputs(kind), patch)


def prefix():
    design = lattice.make_bundle_design([(0, 0), (1, 0)], 12)
    frames = [m.LatticeFrame(id="frame-a", placement_cluster_id="placement-a"),
              m.LatticeFrame(id="frame-b", placement_cluster_id="placement-b")]
    return design.copy_with(lattice_frames=frames, cluster_transforms=[
        m.ClusterRigidTransform(id="placement-a", helix_ids=[design.helices[0].id]),
        m.ClusterRigidTransform(id="placement-b", helix_ids=[design.helices[1].id])],
        helices=[h.model_copy(update={"lattice_frame_id": frames[i].id})
                 for i, h in enumerate(design.helices)])


def test_edited_continuation_refreshes_receipt_from_proved_prefix_not_old_source_ids():
    source = prefix()
    before = source.model_dump(mode="json")
    previous = inputs("extrude-continuation")
    normalized = module().normalize("extrude-continuation", previous,
                                    {"cells": [[1, 0]], "source_frame_id": "frame-b"})
    result = module().bind_prefix("extrude-continuation", normalized, source)
    assert result["_source_helix_ids"] == [source.helices[1].id]
    assert normalized["_source_helix_ids"] == previous["_source_helix_ids"] == ["original-source"]
    assert source.model_dump(mode="json") == before


def test_continuation_fresh_cells_produce_an_explicit_empty_source_receipt():
    source = prefix()
    normalized = module().normalize("extrude-continuation", inputs("extrude-continuation"),
                                    {"cells": [[8, 8]], "source_frame_id": "frame-a"})
    assert module().bind_prefix("extrude-continuation", normalized, source)["_source_helix_ids"] == []


@pytest.mark.parametrize("kind,patch,resource,path", [
    ("extrude-continuation", {"source_frame_id": "missing"}, "lattice_frame", ["source_frame_id"]),
    ("extrude-frame", {"source_frame_id": "missing"}, "lattice_frame", ["source_frame_id"]),
    ("extrude-deformed-continuation", {"ref_helix_id": "missing", "source_bp": 4}, "helix", ["ref_helix_id"]),
    ("overhang-extrude", {"helix_id": "missing"}, "helix", ["helix_id"]),
])
def test_prefix_source_errors_name_exact_authored_parameter(kind, patch, resource, path):
    normalized = module().normalize(kind, inputs(kind), patch)
    with pytest.raises(ReferenceResolutionError) as error:
        module().bind_prefix(kind, normalized, prefix())
    assert error.value.code == "missing_reference"
    assert list(error.value.references) == [{"kind": resource, "identity": "missing", "parameter_path": path}]


def test_prefix_binding_returns_owned_inputs_for_noncontinuation_too():
    normalized = module().normalize("extrude-segment", inputs("extrude-segment"), {})
    result = module().bind_prefix("extrude-segment", normalized, prefix())
    result["cells"][0][0] = 99
    assert normalized["cells"] == [[0, 0]]
