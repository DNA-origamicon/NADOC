"""Registered coating replay; experimental captures do not enable a live profile."""

import pytest
from uuid import uuid4

from backend.api.part_evaluation import evaluate
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import dependencies, execute, execute_long
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedInput, SourceContractError, command_sources, portable_sources
from backend.core.part_verification_capture import CaptureLimit, capture
from tests.test_part_streptavidin_commands import action, block_bundle, inputs, sources as sources


def append(design, kind, params):
    candidate = execute_long(kind, design, params)
    return candidate.copy_with(feature_log=[*design.feature_log, SnapshotLogEntry(
        op_kind=kind, label=kind, params=params,
        design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output")])


def gold_recipe(sources):
    design = create_empty_part("Coating recipe", "HONEYCOMB").copy_with(input_sources=dict(sources["table"]))
    return append(design, "nanoparticle-create", {"_proof_version": 1, "nanoparticle_version": 1,
        "nanoparticle_id": "gold", "diameter_nm": 20.0})


def recipe(sources, mode="adsorption"):
    return append(gold_recipe(sources), "nanoparticle-patch", inputs(sources, mode=mode,
        spacer_nm=0.3 if mode == "adsorption" else 4.0, coverage_reference="gold_2007",
        coverage_source=sources["coverage_source"].model_dump()))


def proof(design, executor=execute_long):
    return assess_part_history(design, execute=executor, dependencies=dependencies)


def operation(name, **changes):
    return {"header": {"identity": "008e59fe-ded1-424a-9276-c8509dbf563d", "timestamp": "2026-10-15T00:00:00Z"},
            "request": {"operation": name, **changes}}


def cold(design, request=None):
    # Qualification only. This test does not install a server-owned profile or
    # change ordinary capture defaults. Generous clock avoids a CI timing test;
    # the benchmark separately measures the prospective 100 ms profile.
    isolated = capture(design, max_nodes=100_000, max_bytes=4_000_000, seconds=1.0,
                       preserve_entry_types=request is not None)
    envelope = operation("verify") if request is None else {
        "request": request, "header": {"identity": str(uuid4()), "timestamp": "2026-10-15T00:00:00Z",
            "source_design_id": design.id, "source_revision": 7}}
    worker = EvaluationWorker(isolated, envelope)
    try:
        worker.start()
        assert worker.wait(30)
        return worker.result()
    finally:
        worker.close()


def test_explicit_coating_upgrade_rebuilds_old_pin_even_after_coating_removal(sources):
    design = append(recipe(sources), "nanoparticle-patch", action("remove"))
    entry = design.feature_log[1]
    entry.params["engine"] = {**entry.params["engine"], "implementation_sha256": "0" * 64}
    before = design.model_dump_json()
    old_engine = dict(entry.params["engine"])
    assert proof(design)["issues"][0]["code"] == "engine_mismatch"
    request = {"operation": "repair", "repair": {"repair_version": 1,
        "expected_design_id": design.id, "expected_revision": 7,
        "actions": [{"action": "upgrade_numerical_contract", "feature_id": entry.id,
                     "expected_engine": old_engine}]}}
    # Removal leaves a small materialized state. This deliberately fits the
    # unchanged ordinary capture envelope; no larger live profile is enabled.
    worker = EvaluationWorker(capture(design, preserve_entry_types=True), {
        "request": request, "header": {"source_design_id": design.id, "source_revision": 7}})
    try:
        worker.start()
        assert worker.wait(30)
        result = worker.result()
        assert result["status"] == "ready", result
    finally:
        worker.close()
    candidate = Design.model_validate(result["candidate"])
    assert candidate.nanoparticles[0].coating is None
    assert candidate.feature_log[1].id == entry.id
    assert result["repair"]["numerical_upgrades"][0]["before"]["engine"] == old_engine
    assert candidate.feature_log[1].params["engine"] != old_engine
    assert design.model_dump_json() == before
    assert cold(Design.model_validate_json(candidate.model_dump_json()))["status"] == "reproduced_import"


@pytest.mark.parametrize("mode", ["adsorption", "biotin_tether"])
def test_registered_lifecycle_cold_rebuilds_pinned_inputs_and_ignores_recovery(sources, mode, monkeypatch):
    # A parent with unrelated imported BLAS/OpenMP libraries is not the worker
    # runtime. Author both numerical steps in the actual worker; never swap a
    # worker pin onto coordinates produced in the parent to make replay pass.
    from backend.core import part_streptavidin_contract
    monkeypatch.setattr(part_streptavidin_contract, "runtime_fingerprint",
        lambda: pytest.fail("Cold lifecycle authored or checked a numerical pin in the parent"))
    created = cold(gold_recipe(sources), {
        "operation": "append", "kind": "streptavidin-coating", "expected_revision": 7,
        "params": {"action": "set", "nanoparticle_id": "gold", "coating": {
            "mode": mode, "spacer_nm": 0.3 if mode == "adsorption" else 4.0,
            "coverage_reference": "gold_2007", "count_override": 1, "seed": 1}}})
    assert created["status"] == "ready", created.get("issues", created)
    design = Design.model_validate(created["candidate"])
    for row in design.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
    expected_sources = sorted(sources["table"])
    set_result = cold(Design.model_validate_json(design.model_dump_json()))
    assert set_result["status"] == "reproduced_import", set_result.get("issues", set_result)
    assert set_result["imported_sources"] == [{"kind": "input_source", "identity": identity}
                                               for identity in expected_sources]
    assert not set_result["native_editable"]
    original = design.nanoparticles[0]
    design = append(design, "nanoparticle-patch", action("move", gizmo_move={
        "pivot": [0, 0, 0], "translation": [2, -1, 3], "rotation": [0, 0, 0, 1]}))
    assert design.nanoparticles[0].pose != original.pose
    assert design.nanoparticles[0].coating == original.coating
    repacked = cold(design, {"operation": "append", "kind": "streptavidin-coating", "expected_revision": 7,
        "params": {"action": "repack", "nanoparticle_id": "gold", "diameter_nm": 22.0}})
    assert repacked["status"] == "ready", repacked.get("issues", repacked)
    design = Design.model_validate(repacked["candidate"])
    assert design.feature_log[3].params["engine"] == design.feature_log[1].params["engine"]
    for row in design.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
    assert design.nanoparticles[0].coating.poses != original.coating.poses
    assert design.nanoparticles[0].diameter_nm == 22.0
    result = cold(Design.model_validate_json(design.model_dump_json()))
    assert result["status"] == "reproduced_import", result
    assert result["checked_commands"] == 4
    design = append(design, "nanoparticle-patch", action("remove"))
    assert design.nanoparticles[0].coating is None
    design = append(design, "nanoparticle-delete", {"_proof_version": 1, "nanoparticle_version": 1,
        "nanoparticle_id": "gold"})
    assert not design.nanoparticles
    result = cold(Design.model_validate_json(design.model_dump_json()))
    assert result["status"] == "reproduced_import", result
    assert result["checked_commands"] == 6
    assert result["imported_sources"] == set_result["imported_sources"]


def test_parameter_edit_rebuilds_coating_and_retains_particle_identity(sources):
    design = recipe(sources)
    before = design.model_dump_json()
    result = evaluate(design, operation("edit", index=1, params={"seed": 2, "diameter_nm": 22.0,
        "coating_version": 99, "importer_version": 99, "engine": {"id": "attempted-repin"}}))
    assert result["status"] == "ready", result
    candidate = Design.model_validate(result["candidate"])
    assert candidate.nanoparticles[0].id == "gold"
    assert candidate.nanoparticles[0].diameter_nm == 22.0
    assert candidate.nanoparticles[0].coating.poses != design.nanoparticles[0].coating.poses
    assert candidate.feature_log[1].params["coating_version"] == candidate.feature_log[1].params["importer_version"] == 1
    assert candidate.feature_log[1].params["engine"] == design.feature_log[1].params["engine"]
    assert proof(candidate)["status"] == "reproduced_import"
    assert design.model_dump_json() == before


def test_repair_target_edit_remains_explicit_and_missing_particle_rejects_atomically(sources):
    design = recipe(sources)
    before = design.model_dump_json()
    result = evaluate(design, operation("edit", index=1, params={"nanoparticle_id": "missing"}))
    assert result["status"] == "failed", result
    assert result["issues"][0]["code"] == "evaluation_rejected"
    detail = result["issues"][0]["detail"]
    assert detail["code"] == "missing_reference"
    assert detail["references"][0]["parameter_path"] == ["nanoparticle_id"]
    assert design.model_dump_json() == before


@pytest.mark.parametrize("operation_name", ["set", "move", "remove"])
def test_ordinary_executor_requires_explicit_job_without_atom_preparation(sources, monkeypatch, operation_name):
    from backend.core import streptavidin

    design = recipe(sources)
    params = (design.feature_log[1].params if operation_name == "set" else action(operation_name,
        **({"pose": [1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]} if operation_name == "move" else {})))
    before = design.model_dump_json()
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Ordinary executor parsed atoms"))
    with pytest.raises(CommandContractError) as error:
        execute("nanoparticle-patch", design, params)
    assert error.value.code == "long_job_required"
    assert design.model_dump_json() == before
    with pytest.raises(CaptureLimit):
        capture(design)


def test_registered_replay_has_no_bundle_fallback_and_detects_unlogged_atom_changes(sources, monkeypatch):
    design = recipe(sources)
    block_bundle(monkeypatch)
    assert proof(design)["status"] == "reproduced_import"
    tampered = design.model_copy(deep=True)
    tampered.nanoparticles[0].coating.protein.atoms[0].x += 0.1
    result = proof(tampered)
    assert result["status"] == "mismatch", result
    assert result["issues"][0]["fields"] == ["nanoparticles"]


@pytest.mark.parametrize("source_name", ["pdb_source", "coverage_source"])
@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_or_corrupt_source_never_uses_installed_bundle_or_current_geometry(sources, monkeypatch, source_name, corrupt):
    design = recipe(sources)
    block_bundle(monkeypatch)
    identity = design.feature_log[1].params[source_name]["sha256"]
    if corrupt:
        design.input_sources[identity] = EmbeddedInput(data_b64="AAAA")
    else:
        design.input_sources.pop(identity)
    result = proof(design)
    assert result["status"] == "unverified", result
    issue = result["issues"][0]
    assert issue["code"] == ("source_integrity_mismatch" if corrupt else "source_unavailable")
    assert issue["references"] == [{"kind": "input_source", "identity": identity,
                                     "parameter_path": [source_name]}]
    with pytest.raises(SourceContractError):
        portable_sources(design)


@pytest.mark.parametrize("marker", [None, False, True, "1", 0, 2])
def test_marker_presence_never_falls_through_to_source_free_gold(sources, marker):
    params = {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold",
              "diameter_nm": 22.0, "coating_version": marker}
    assert not dependencies("nanoparticle-patch", params).known
    with pytest.raises(NotImplementedError):
        execute_long("nanoparticle-patch", recipe(sources), params)


def test_both_sources_are_owned_dependencies_and_survive_portable_save_after_removal(sources, tmp_path):
    from backend.core import native_part_package as package

    design = recipe(sources)
    params = design.feature_log[1].params
    expected = {source.sha256 for source in command_sources("nanoparticle-patch", params)}
    assert expected == set(sources["table"])
    contract = dependencies("nanoparticle-patch", params)
    assert {resource.identity for resource in contract.imported_sources} == expected
    design = append(design, "nanoparticle-patch", action("remove"))
    assert command_sources("nanoparticle-patch", design.feature_log[-1].params) == ()
    assert set(portable_sources(design)) == expected
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "coating.nadoc").write_text(design.to_json())
    archive = tmp_path / "coating.nadocpkg"
    manifest = package.create_package(workspace, "coating.nadoc", archive, mode="thin")
    assert {source["sha256"] for source in manifest["authoring_inputs"]} == expected
    destination = tmp_path / "restored"
    package.import_package(destination, archive, "coating.nadoc")
    restored = Design.from_json((destination / "coating.nadoc").read_text())
    assert restored.input_sources == design.input_sources
    assert proof(restored)["status"] == "reproduced_import"
