"""Native bundle construction is reproducible from parameters and stable IDs."""
import json
from uuid import uuid4

import pytest

from backend.api import state
from backend.api.crud import BundleRequest, EditFeatureBody, create_bundle, edit_feature
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history, create_empty_part


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-bundle-proof-test")
    try:
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize("separate", [False, True])
@pytest.mark.parametrize("cells", [[[0, 0], [0, 1]], [[0, 0], [4, 4]]])
def test_native_route_rebuilds_exact_authoring_state_without_payloads(separate, cells):
    create_bundle(BundleRequest(cells=cells, length_bp=21, separate_fresh_extrusions=separate))
    current = state.get_or_404()
    entry = current.feature_log[0]
    assert entry.params["history_seed"]
    entry.design_snapshot_gz_b64 = ""
    entry.post_state_gz_b64 = ""
    result = verify_current_part()
    assert result["status"] == "verified", result
    assert result["native_editable"]
    assert result["checked_commands"] == 1
    reloaded = type(current).model_validate_json(current.model_dump_json())
    assert assess_part_history(reloaded, execute=execute, dependencies=dependencies)["status"] == "verified"


def test_parameter_edit_keeps_seed_and_remains_reproducible():
    create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21))
    current = state.get_or_404()
    seed = current.feature_log[0].params["history_seed"]
    cluster = current.cluster_transforms[0].id
    edit_feature(0, EditFeatureBody(params={"cells": [[0, 0]], "length_bp": 32, "name": "Bundle"}))
    updated = state.get_or_404()
    assert updated.helices[0].length_bp == 32
    assert updated.cluster_transforms[0].id == cluster
    assert updated.feature_log[0].params["history_seed"] == seed
    assert verify_current_part()["status"] == "verified"


def test_unlogged_geometry_edit_is_detected():
    create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21))
    state.get_or_404().helices[0].length_bp = 32
    assert verify_current_part()["status"] == "mismatch"


def test_separate_commands_get_separate_identity_namespaces():
    params = {"cells": [[0, 0]], "length_bp": 21, "_proof_version": 1}
    root = create_empty_part("Bundle", "HONEYCOMB")
    a = execute("bundle-create", root, {**params, "history_seed": str(uuid4())})
    b = execute("bundle-create", root, {**params, "history_seed": str(uuid4())})
    assert a.cluster_transforms[0].id != b.cluster_transforms[0].id
    assert a.lattice_frames[0].id != b.lattice_frames[0].id
    assert a.helices[0].axis_start == b.helices[0].axis_start
    assert a.helices[0].axis_end == b.helices[0].axis_end


def test_bundle_and_joint_form_a_native_dependency_chain():
    from backend.api.routes_cluster_joints import _build_add_joint
    create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21))
    design = state.get_or_404()
    params = {"joint_id": "joint", "cluster_id": design.cluster_transforms[0].id,
              "local_axis_origin": [0, 0, 0], "local_axis_direction": [0, 0, 1]}
    state.mutate_with_minor_log(op_subtype="joint-place", label="Joint", params=params,
                                fn=lambda d: _build_add_joint(d, params))
    result = verify_current_part()
    assert result["status"] == "verified", json.dumps(result)
    first, cluster = state.get_or_404().feature_log
    assert result["dependencies"]["parents"][cluster.children[0].id] == [first.id]


def test_work_budget_is_unverified_not_invalid_geometry():
    create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21))
    state.get_or_404().feature_log[0].params["length_bp"] = 1_000_000
    result = verify_current_part()
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "command_limit"


def test_seeded_bundle_is_identical_across_python_hash_seeds():
    import os
    import subprocess
    import sys
    code = '''
from backend.api.part_proof_commands import execute
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, digest
params = {"cells": [[0, 0], [0, 1], [4, 4]], "length_bp": 21,
          "separate_fresh_extrusions": False, "_proof_version": 1,
          "history_seed": "12345678-1234-5678-1234-567812345678"}
d = execute("bundle-create", create_empty_part("Bundle", "HONEYCOMB"), params)
print(digest(d.model_dump(mode="json", include=AUTHORING_FIELDS)))
'''
    outputs = [subprocess.check_output([sys.executable, "-c", code], text=True,
               env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("1", "2")]
    assert outputs[0] == outputs[1]


def test_capabilities_distinguish_executors_from_proof_contracts():
    from backend.api.routes_feature_log import get_part_feature_capabilities
    result = get_part_feature_capabilities()
    assert "bundle-create" in result["proof_commands"]
    assert "nick" in result["minor_commands"]
    assert "nick" in result["proof_commands"]
    assert "crossover-place" in result["proof_commands"]
    assert "overhang-extrude" in result["proof_commands"]
    assert "nanoparticle-create" in result["proof_commands"]
    # Coverage membership does not upgrade older receipts to a native contract.
    from backend.api.part_proof_commands import dependencies
    assert not dependencies("nanoparticle-create", {"_proof_version": 1}).known
    assert result["nanoparticle_contract"]["scope"].startswith("uncoated gold")
    assert result["certifies_history"] is False
    assert result["command_editors"]["extrude-frame"]["history_ui"] == "complete_native_inputs"
    assert result["command_editors"]["circle-segment"]["history_ui"] == "complete_native_inputs"
    assert "expected_feature_id" in result["extrusion_history_editor"]["requires"]


def test_fresh_bundle_is_one_revision_and_undo_restores_the_exact_empty_part():
    source = create_empty_part("Empty source", "HONEYCOMB")
    state.load_design(source)
    session = state._session()
    revision = session.revision
    before = source.model_dump()
    create_bundle(BundleRequest(cells=[[0, 0]], length_bp=14))
    assert session.revision == revision + 1
    assert session.design.id == source.id
    assert len(session.history) == 1
    assert verify_current_part()["status"] == "verified"
    state.undo()
    assert session.design.model_dump() == before
    state.redo()
    assert verify_current_part()["status"] == "verified"


def test_replacement_bundle_has_an_empty_recipe_and_one_undo_to_the_previous_part():
    create_bundle(BundleRequest(cells=[[0, 0]], length_bp=14))
    session = state._session()
    before, revision, history_count = session.design.model_dump(), session.revision, len(session.history)
    create_bundle(BundleRequest(cells=[[0, 1]], length_bp=21))
    assert session.revision == revision + 1
    assert len(session.history) == history_count + 1
    assert len(session.design.feature_log) == 1
    assert verify_current_part()["status"] == "verified"
    state.undo()
    assert session.design.model_dump() == before


@pytest.mark.parametrize("existing", [False, True])
def test_refused_bundle_build_preserves_source_and_undo_redo(monkeypatch, existing):
    from backend.api import crud

    if existing:
        create_bundle(BundleRequest(cells=[[0, 0]], length_bp=14))
        state.undo()
    session = state._session()
    def signature():
        return (None if session.design is None else session.design.model_dump(), session.revision,
                [d.model_dump() for d in session.history], [d.model_dump() for d in session.redo])
    before = signature()
    native = crud._build_bundle
    def fail(*args):
        native(*args)
        raise RuntimeError("refused completed private build")
    monkeypatch.setattr(crud, "_build_bundle", fail)
    with pytest.raises(RuntimeError, match="refused completed"):
        create_bundle(BundleRequest(cells=[[0, 0]], length_bp=14))
    assert signature() == before
