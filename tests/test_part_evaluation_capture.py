"""Bounded profile selection without atom preparation, runtime probes or jobs."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_evaluation_capture as policy
from backend.api.part_streptavidin_commands import PDB_SHA256, PDB_SIZE
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import EmbeddedInput
from backend.core.part_verification_capture import CaptureLimit


def gold_params(**extra):
    return {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", **extra}


def set_params(**extra):
    return {"_proof_version": 1, "coating_version": 1, "importer_version": 1,
        "engine": {"id": "nadoc.streptavidin-native.v1", "implementation_sha256": "0" * 64,
                   "runtime_sha256": "0" * 64},
        "action": "set", "nanoparticle_id": "gold", "pdb_source": {
            "version": 1, "sha256": PDB_SHA256, "size_bytes": PDB_SIZE,
            "format": "pdb", "media_type": "chemical/x-pdb"},
        "coverage_source": None, "coverage_reference": None, "mode": "adsorption",
        "footprint_nm2": 40.0, "spacer_nm": 0.3, "seed": 1, "count_override": 1, **extra}


def row(identity, kind, params):
    return m.SnapshotLogEntry(id=identity, op_kind=kind, params=params, label=identity)


def source(*, coated=True, removed=False):
    design = create_empty_part("Profile selection only", "HONEYCOMB")
    design.id = "part"
    # Small declared materialized state, not a native/coating proof fixture.
    coating = m.StreptavidinCoating(target_count=1, poses=[m.Mat4x4()], protein=m.ProteinAsset(
        id="streptavidin-1stp-assembly1-adsorption", metadata={"source_sha256": PDB_SHA256})) if coated else None
    design.nanoparticles = [m.Nanoparticle(id="gold", diameter_nm=20.0, coating=coating)]
    design.feature_log = [row("gold-row", "nanoparticle-create", gold_params(diameter_nm=20.0)),
                          row("coating-row", "nanoparticle-patch", set_params())]
    if removed:
        design.nanoparticles = []
        design.feature_log += [row("remove-row", "nanoparticle-patch", {
            "_proof_version": 1, "coating_version": 1, "nanoparticle_id": "gold", "action": "remove"}),
            row("delete-row", "nanoparticle-delete", gold_params())]
    return design


def request(**extra):
    return {"operation": "verify", "expected_revision": 7, **extra}


def repair_request(**extra):
    return {"operation": "repair", "repair": {"repair_version": 1, "expected_design_id": "part",
        "expected_revision": 7, "actions": [{"action": "set_input", "feature_id": "coating-row",
            "parameter_path": ["seed"], "expected_old": 1, "value": 2}], **extra}}


def selection_request(**extra):
    return {"operation": "selection", "selection": {"selection_version": 1,
        "expected_design_id": "part", "expected_revision": 7, "feature_id": "coating-row",
        "parameter_path": ["nanoparticle_id"], "expected_old": "gold", **extra}}


@pytest.fixture
def captures(monkeypatch):
    calls = []

    def capture(design, **options):
        calls.append((design, options))
        return "isolated"

    monkeypatch.setattr(policy, "capture", capture)
    return calls


def test_noncoating_jobs_retain_ordinary_defaults_and_optional_revision(captures):
    design = create_empty_part("Ordinary", "HONEYCOMB")
    design.helices = [object()]  # Policy does not inspect unrelated job models.
    assert policy.capture_for_evaluation(design, request={"operation": "verify"}, revision=7) == "isolated"
    assert captures == [(design, {"preserve_entry_types": True})]


@pytest.mark.parametrize("removed", [False, True])
@pytest.mark.parametrize("preserve", [False, True])
def test_coating_recipe_selects_fixed_profile_once_even_after_final_removal(captures, removed, preserve):
    design = source(removed=removed)
    assert policy.capture_for_evaluation(design, request=request(), revision=7,
        preserve_entry_types=preserve) == "isolated"
    assert captures == [(design, {"preserve_entry_types": preserve, **policy.COATING_PROFILE})]
    assert dict(policy.COATING_PROFILE) == {"max_nodes": 100_000, "max_bytes": 4_000_000, "seconds": 0.100}


@pytest.mark.parametrize("body,revision,code", [
    (request(), True, "invalid_capture_context"), (request(), -1, "invalid_capture_context"),
    (request(), 8, "source_changed"), (request(expected_revision=None), 7, "invalid_capture_context"),
    (repair_request(expected_design_id="other"), 7, "repair_conflict"),
    (repair_request(expected_revision=6), 7, "repair_conflict"),
    (selection_request(expected_design_id="other"), 7, "selection_conflict"),
    (selection_request(expected_revision=6), 7, "selection_conflict"),
])
def test_revision_and_document_guards_precede_scope_and_copy(captures, monkeypatch, body, revision, code):
    monkeypatch.setattr(policy, "_scope", lambda *_a: pytest.fail("Stale request inspected geometry"))
    with pytest.raises(CommandContractError) as error:
        policy.capture_for_evaluation(source(), request=body, revision=revision)
    assert error.value.code == code and not captures


def test_missing_and_small_corrupt_sources_are_preserved_for_explicit_repair(captures, monkeypatch):
    from backend.core import part_input_sources, part_streptavidin_contract, streptavidin

    def forbidden(*_a, **_k):
        pytest.fail("Capture selection parsed sources, prepared atoms or probed runtime")

    monkeypatch.setattr(part_input_sources, "decode", forbidden)
    monkeypatch.setattr(part_input_sources, "verify", forbidden)
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", forbidden)
    monkeypatch.setattr(part_streptavidin_contract, "runtime_fingerprint", forbidden)
    design = source()
    assert not design.input_sources
    policy.capture_for_evaluation(design, request=repair_request(), revision=7)
    design.input_sources[PDB_SHA256] = EmbeddedInput(data_b64="not base64")
    policy.capture_for_evaluation(design, request=repair_request(), revision=7)
    assert len(captures) == 2
    assert captures[-1][0].input_sources[PDB_SHA256].data_b64 == "not base64"


@pytest.mark.parametrize("fault", ["no_root", "import_root", "root_version", "cursor", "subcursor",
    "second_particle", "dna", "protein", "thiol", "physical", "loadout", "presentation",
    "quantum_dot", "diameter", "pose", "unknown_asset", "count", "poses", "atoms", "bonds"])
def test_larger_profile_rejects_unqualified_scope_without_capture(captures, fault):
    design = source()
    particle = design.nanoparticles[0]
    if fault == "no_root":
        design.recipe_root = None
    elif fault == "import_root":
        design.recipe_root = design.recipe_root.model_copy(update={"kind": "import"})
    elif fault == "root_version":
        design.recipe_root = design.recipe_root.model_copy(update={"version": 2})
    elif fault == "cursor":
        design.feature_log_cursor = 0
    elif fault == "subcursor":
        design.feature_log_sub_cursor = 0
    elif fault == "second_particle":
        design.nanoparticles.append(m.Nanoparticle(id="other", diameter_nm=20.0))
    elif fault in {"dna", "protein", "thiol", "loadout"}:
        field = {"dna": "helices", "protein": "protein_assets", "thiol": "nanoparticle_conjugations",
                 "loadout": "loadouts"}[fault]
        setattr(design, field, [object()])
    elif fault == "physical":
        design.atomistic_reference = object()
    elif fault == "presentation":
        design.annotations_enabled = False
    elif fault == "quantum_dot":
        particle.kind = "quantum_dot"
    elif fault == "diameter":
        particle.diameter_nm = float("inf")
    elif fault == "pose":
        particle.pose.values[3] = float("nan")
    elif fault == "unknown_asset":
        particle.coating.protein.metadata["source_sha256"] = "0" * 64
    elif fault == "count":
        particle.coating.target_count = 65
    elif fault == "poses":
        particle.coating.poses *= 2
    elif fault == "atoms":
        particle.coating.protein.atoms = [object()] * 4101
    else:
        particle.coating.protein.bonds = [(0, 1)] * 5001
    with pytest.raises(CommandContractError) as error:
        policy.capture_for_evaluation(design, request=request(), revision=7)
    assert error.value.code == "unsupported_coating_scope" and not captures


@pytest.mark.parametrize("fault", ["legacy", "marker", "unknown_kind", "unknown_field", "wrong_family",
    "duplicate_row", "row_limit", "header_budget", "count", "descriptor", "feature_type", "no_coating_row"])
def test_history_must_be_bounded_flat_strict_gold_and_coating_definitions(captures, fault):
    design = source()
    params = design.feature_log[1].params
    if fault == "legacy":
        params.pop("_proof_version")
    elif fault == "marker":
        params["coating_version"] = None
    elif fault == "unknown_kind":
        design.feature_log[0].op_kind = "sweep"
    elif fault == "unknown_field":
        params["sampled_poses"] = []
    elif fault == "wrong_family":
        design.feature_log[0].params["thiol_version"] = 1
    elif fault == "duplicate_row":
        design.feature_log[1].id = design.feature_log[0].id
    elif fault == "row_limit":
        design.feature_log *= 17
    elif fault == "header_budget":
        design.feature_log[0].label = "x" * 256_001
    elif fault == "count":
        params["count_override"] = 65
    elif fault == "descriptor":
        params["pdb_source"]["sha256"] = "0" * 64
    elif fault == "no_coating_row":
        design.feature_log = design.feature_log[:1]
    else:
        design.feature_log[0].feature_type = "minor"
    with pytest.raises(CommandContractError):
        policy.capture_for_evaluation(design, request=request(), revision=7)
    assert not captures


@pytest.mark.parametrize("fault", ["many", "pdb_bytes", "coverage_bytes", "record", "key"])
def test_input_envelope_is_bounded_without_decoding(captures, fault):
    design = source()
    if fault == "many":
        design.input_sources = {f"{index:064x}": EmbeddedInput(data_b64="") for index in range(34)}
    elif fault == "pdb_bytes":
        design.input_sources = {PDB_SHA256: EmbeddedInput(data_b64="A" * 440_000)}
    elif fault == "coverage_bytes":
        design.input_sources = {"0" * 64: EmbeddedInput(data_b64="A" * 5_468)}
    elif fault == "record":
        design.input_sources = {PDB_SHA256: object()}
    else:
        design.input_sources = {"bad": EmbeddedInput(data_b64="")}
    with pytest.raises(CommandContractError):
        policy.capture_for_evaluation(design, request=request(), revision=7)
    assert not captures


def test_capture_refusal_never_retries_or_changes_source(monkeypatch):
    design = source()
    before = design.model_dump_json()
    calls = []

    def refusing(*_args, **options):
        calls.append(options)
        raise CaptureLimit("Cooperative deadline exceeded")

    monkeypatch.setattr(policy, "capture", refusing)
    with pytest.raises(CaptureLimit):
        policy.capture_for_evaluation(design, request=request(), revision=7)
    assert calls == [{"preserve_entry_types": True, **policy.COATING_PROFILE}]
    assert design.model_dump_json() == before


def test_real_capture_keeps_isolation_and_strips_recovery_without_proof():
    class Recovery:
        def __deepcopy__(self, _memo):
            pytest.fail("Capture inspected recovery")

    design = source()
    design.feature_log[0].design_snapshot_gz_b64 = Recovery()
    isolated = policy.capture_for_evaluation(design, request=request(), revision=7)
    assert not isolated.feature_log[0].design_snapshot_gz_b64
    assert isolated.feature_log[1].params == design.feature_log[1].params
    isolated.nanoparticles[0].diameter_nm = 25.0
    isolated.feature_log[1].params["seed"] = 9
    assert design.nanoparticles[0].diameter_nm == 20.0
    assert design.feature_log[1].params["seed"] == 1


@pytest.mark.parametrize("field", ["profile", "max_nodes", "max_bytes", "seconds"])
def test_request_cannot_control_capture_limits(captures, field):
    with pytest.raises(ValidationError):
        policy.capture_for_evaluation(source(), request=request(**{field: 999_999}), revision=7)
    assert not captures


def test_unrelated_append_cannot_use_a_coating_profile(captures):
    with pytest.raises(CommandContractError):
        policy.capture_for_evaluation(source(), request=request(operation="append",
            kind="duplex-relax", params={}), revision=7)
    assert not captures


@pytest.mark.parametrize("outer_revision", [None, 7])
def test_coating_selection_cannot_use_a_larger_profile(captures, outer_revision):
    body = selection_request()
    body["expected_revision"] = outer_revision
    with pytest.raises(CommandContractError) as error:
        policy.capture_for_evaluation(source(), request=body, revision=7)
    assert error.value.code == "unsupported_reference_slot" and not captures


def test_ordinary_selection_checks_nested_guard_then_retains_default_capture(captures):
    design = create_empty_part("Selection", "HONEYCOMB")
    design.id = "part"
    with pytest.raises(CommandContractError) as error:
        policy.capture_for_evaluation(design, request=selection_request(expected_revision=6), revision=7)
    assert error.value.code == "selection_conflict" and not captures
    policy.capture_for_evaluation(design, request=selection_request(), revision=7)
    assert captures == [(design, {"preserve_entry_types": True})]


def test_profile_constants_are_not_mutable():
    with pytest.raises(TypeError):
        policy.COATING_PROFILE["seconds"] = 999


def test_small_coverage_history_with_implicit_count_is_left_to_worker_admission(captures):
    design = source()
    params = deepcopy(design.feature_log[1].params)
    params.update(count_override=None, coverage_reference="gold_2007", coverage_source={
        "version": 1, "sha256": "1" * 64, "size_bytes": 20, "format": "json", "media_type": "application/json"})
    design.feature_log[1].params = params
    policy.capture_for_evaluation(design, request=request(), revision=7)
    assert len(captures) == 1
