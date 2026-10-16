"""Public coating compilation: strict choices, provenance, identities and no geometry."""

from copy import deepcopy
from dataclasses import replace
import json
import pickle
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.api import part_coating_append as compiler
from backend.api import part_streptavidin_commands as coating
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_input_sources import EmbeddedInput, EmbeddedResolver, SourceContractError, describe, embed


SEED = "843430b3-57b8-4311-b8fa-75fdc8cad475"
OTHER_SEED = "9077512c-0aee-466a-af65-c76bdfe5d674"
PIN = {"_proof_version": 1, "coating_version": 1, "importer_version": 1,
       "engine": {"id": "nadoc.streptavidin-native.v1", "implementation_sha256": "1" * 64,
                  "runtime_sha256": "2" * 64}}


@pytest.fixture
def no_geometry(monkeypatch):
    from backend.core import part_streptavidin_contract, streptavidin

    def forbidden(*_a, **_k):
        pytest.fail("Input compilation performed geometry, runtime work or recipe execution")

    for name in ("streptavidin_asset_from_text", "streptavidin_asset", "build_streptavidin_coating",
                 "build_streptavidin_coating_from_inputs"):
        monkeypatch.setattr(streptavidin, name, forbidden)
    monkeypatch.setattr(coating, "build", forbidden)
    monkeypatch.setattr(compiler.gold, "build", forbidden)
    monkeypatch.setattr(part_streptavidin_contract, "runtime_fingerprint", forbidden)
    pins = []

    def current_pin():
        pins.append(True)
        return deepcopy(PIN)

    monkeypatch.setattr(compiler, "contract_defaults", current_pin)
    return pins


def request(action="set", **extra):
    return {"action": action, **({} if action == "create" else {"nanoparticle_id": "gold"}), **extra}


def row(identity, kind, params):
    return m.SnapshotLogEntry(id=identity, label=kind, op_kind=kind, params=params,
        design_snapshot_gz_b64="not executable evidence", post_state_gz_b64="not an input")


def bare():
    design = create_empty_part("Public coating inputs", "HONEYCOMB")
    design.nanoparticles = [m.Nanoparticle(id="gold", diameter_nm=20.0)]
    design.feature_log = [row("gold-create", "nanoparticle-create", {
        "_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 20.0})]
    return design


def compiled(design, body, *, prepared=None, seed=SEED):
    if prepared is None:
        prepared = compiler.prepare_sources(body)
    return compiler.compile_steps(design, body, prepared, history_seed=seed)


def coated(*, publication=None):
    """Declared replayed prefix for compiler tests; no molecular asset built."""
    design = bare()
    body = request(coating={"mode": "biotin_tether", "seed": 7, "count_override": 1,
                            "coverage_reference": publication})
    result = compiled(design, body)
    step = result.steps[0]
    params = step.params
    design.feature_log.append(row(step.identity, step.kind, params))
    design.input_sources = result.input_sources
    design.nanoparticles[0].coating = m.StreptavidinCoating(
        **{field: params[field] for field in ("mode", "footprint_nm2", "spacer_nm", "seed",
                                             "coverage_reference", "count_override")},
        target_count=1, poses=[m.Mat4x4()], protein=m.ProteinAsset(
            id="streptavidin-1stp-assembly1-biotin_tether", metadata={"source_sha256": coating.PDB_SHA256}))
    return design


@pytest.mark.parametrize("mode,spacer", [("adsorption", 0.3), ("biotin_tether", 4.0)])
def test_native_defaults_become_explicit_inputs_with_worker_selected_pin(no_geometry, mode, spacer):
    design = bare()
    before = design.model_dump_json()
    result = compiled(design, request(coating={"mode": mode}))
    step, = result.steps
    assert step.kind == "nanoparticle-patch" and UUID(step.identity).version == 5
    assert step.params == {**PIN, "nanoparticle_id": "gold", "action": "set",
        "pdb_source": compiler._PDB.model_dump(), "coverage_source": None,
        "mode": mode, "footprint_nm2": 40.0, "spacer_nm": spacer, "seed": 1,
        "coverage_reference": None, "count_override": None, "diameter_nm": None}
    assert result.nanoparticle_id == "gold" and len(no_geometry) == 1
    assert design.model_dump_json() == before and not design.input_sources


def test_create_emits_two_definitions_with_stable_disjoint_host_identities(no_geometry):
    design = create_empty_part("Empty", "HONEYCOMB")
    body = request("create", diameter_nm=20.0, coating={"count_override": 1, "seed": 5})
    preparation = compiler.prepare_sources(body)
    result = compiled(design, body, prepared=pickle.loads(pickle.dumps(preparation)))
    assert result == compiled(design, body, prepared=preparation)
    changed = compiled(design, request("create", diameter_nm=22.0,
        coating={"count_override": 2, "seed": 9}), prepared=preparation)
    assert [step.kind for step in result.steps] == ["nanoparticle-create", "nanoparticle-patch"]
    identities = [result.nanoparticle_id, *(step.identity for step in result.steps)]
    assert len(set(identities)) == 3 and all(UUID(value).version == 5 for value in identities)
    assert changed.nanoparticle_id == result.nanoparticle_id
    assert [step.identity for step in changed.steps] == [step.identity for step in result.steps]
    assert all(step.params["nanoparticle_id"] == result.nanoparticle_id for step in result.steps)
    assert result.steps[0].params["diameter_nm"] == result.steps[1].params["diameter_nm"] == 20.0
    assert result.steps[1].params["seed"] == 5
    assert not design.nanoparticles and not design.feature_log and not design.input_sources


def test_preparation_reads_only_fixed_selected_assets_without_runtime(no_geometry, monkeypatch):
    original = compiler.Path.open
    reads = []

    def opening(path, *args, **kwargs):
        reads.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(compiler.Path, "open", opening)
    prepared = compiler.prepare_sources(request(coating={"coverage_reference": "gold_2017"}))
    assert reads == ["1STP-assembly1.pdb", "streptavidin_coverage.json"] and not no_geometry
    resolver = EmbeddedResolver(dict(prepared.entries))
    assert len(resolver(prepared.pdb_source)) == coating.PDB_SIZE
    assert json.loads(resolver(prepared.coverage_source))["presets"][2]["id"] == "gold_2017"
    reads.clear()
    compiler.prepare_sources(request())
    assert reads == ["1STP-assembly1.pdb"]


@pytest.mark.parametrize("fault", ["missing", "pdb_changed", "coverage_oversize", "coverage_unknown"])
def test_bundle_errors_refuse_preparation_without_runtime(no_geometry, monkeypatch, tmp_path, fault):
    pdb = (compiler._DATA / "1STP-assembly1.pdb").read_bytes()
    publication = (compiler._DATA / "streptavidin_coverage.json").read_bytes()
    if fault != "missing":
        (tmp_path / "1STP-assembly1.pdb").write_bytes(pdb[:-1] + b"X" if fault == "pdb_changed" else pdb)
    if fault == "coverage_oversize":
        publication = b" " * 4097
    elif fault == "coverage_unknown":
        publication = b'{"presets":[],"extra":1}'
    (tmp_path / "streptavidin_coverage.json").write_bytes(publication)
    monkeypatch.setattr(compiler, "_DATA", tmp_path)
    with pytest.raises(CommandContractError):
        compiler.prepare_sources(request(coating={"coverage_reference": "gold_2007"}))
    assert not no_geometry


def test_repack_uses_active_recipe_choices_and_pinned_publication_without_bundle(no_geometry, monkeypatch):
    design = coated(publication="gold_2007")
    active = design.feature_log[-1]
    old = deepcopy(active.params)
    publication = {"presets": [{"id": "gold_2007", "label": "Recorded publication",
        "effective_area_nm2": 90.0, "url": "https://example.test/original", "note": "Pinned input"}]}
    data = json.dumps(publication).encode()
    source = describe(data, format="json", media_type="application/json")
    active.params["coverage_source"] = source.model_dump()
    active.params["engine"]["implementation_sha256"] = "3" * 64
    design.input_sources[source.sha256] = embed(source, data)
    before = design.model_dump_json()

    def no_read(*_a, **_k):
        pytest.fail("Repack consulted the installed bundle")

    monkeypatch.setattr(compiler.Path, "open", no_read)
    result = compiled(design, request("repack", diameter_nm=22.0), seed=OTHER_SEED)
    params = result.steps[0].params
    assert params["coverage_source"] == source.model_dump() and params["pdb_source"] == old["pdb_source"]
    for field in ("seed", "mode", "footprint_nm2", "spacer_nm", "coverage_reference", "count_override"):
        assert params[field] == old[field]
    assert params["engine"] == PIN["engine"] and params["diameter_nm"] == 22.0
    assert design.model_dump_json() == before  # Never upgrades an old row.
    assert result.input_sources == design.input_sources


@pytest.mark.parametrize("action", ["move", "remove", "delete"])
def test_rigid_and_removal_actions_emit_steps_without_reads_or_new_pin(no_geometry, monkeypatch, action):
    design = coated()
    before = design.model_dump_json()

    def forbidden(*_a, **_k):
        pytest.fail("Rigid/removal compilation accessed a bundle or selected a numerical pin")

    monkeypatch.setattr(compiler.Path, "open", forbidden)
    monkeypatch.setattr(compiler, "contract_defaults", forbidden)
    motion = {"pose": list(m.Mat4x4().values), "gizmo_move": {
        "pivot": [1.0, 2.0, 3.0], "translation": [4.0, 5.0, 6.0], "rotation": [0.0, 0.0, 0.0, 1.0]}}
    result = compiled(design, request(action, **(motion if action == "move" else {})), seed=OTHER_SEED)
    assert [step.kind for step in result.steps] == (
        ["nanoparticle-patch", "nanoparticle-delete"] if action == "delete" else ["nanoparticle-patch"])
    assert result.steps[0].params["action"] == ("remove" if action == "delete" else action)
    if action == "move":
        assert result.steps[0].params["pose"] == motion["pose"]
        assert result.steps[0].params["gizmo_move"] == {**motion["gizmo_move"], "preconstrained": False}
    assert design.model_dump_json() == before and result.input_sources == design.input_sources


def test_uncoated_delete_is_one_feature_and_absent_coating_actions_are_errors(no_geometry):
    assert [step.kind for step in compiled(bare(), request("delete")).steps] == ["nanoparticle-delete"]
    for body in (request("remove"), request("repack", diameter_nm=22.0),
                 request("move", pose=list(m.Mat4x4().values))):
        with pytest.raises(ReferenceResolutionError) as error:
            compiled(bare(), body)
        assert error.value.code == "missing_reference"
    assert not no_geometry


@pytest.mark.parametrize("field", ["engine", "_proof_version", "coating_version", "history_seed", "pdb_source",
    "coverage_source", "input_sources", "source_path", "url", "poses", "protein", "profile"])
def test_public_request_cannot_supply_trust_identity_source_or_output_fields(field):
    for body in (request(**{field: {}}), request(coating={field: {}})):
        with pytest.raises(ValidationError):
            compiler.parse_request(body)


@pytest.mark.parametrize("body", [request(coating={"seed": True}), request(coating={"count_override": 65}),
    request(coating={"seed": "1"}), request(coating={"spacer_nm": float("nan")}),
    request(coating={"footprint_nm2": 0.0}), request(coating={"coverage_reference": "url"}),
    request("move"), request("move", pose=[0.0]), request("move", gizmo_move={
        "pivot": [0.0] * 3, "translation": [0.0] * 3, "rotation": [0.0] * 4}),
    request("repack", diameter_nm=20.0, coating={}), request("create", diameter_nm=20.0, nanoparticle_id="client"),
    {"action": []}, {"action": "other"}])
def test_public_choices_are_strict_and_actions_do_not_mix(body):
    with pytest.raises(ValueError):
        compiler.parse_request(body)


@pytest.mark.parametrize("fault", ["root", "cursor", "dna", "protein", "ownership", "multiple", "missing",
    "duplicate", "quantum_dot", "biotin", "bad_pose", "bad_diameter", "legacy", "row_limit"])
def test_unsupported_scope_or_rows_refuse_before_new_pin(no_geometry, fault):
    design = bare()
    if fault == "root":
        design.recipe_root = None
    elif fault == "cursor":
        design.feature_log_cursor = 0
    elif fault in {"dna", "protein", "ownership"}:
        setattr(design, {"dna": "helices", "protein": "protein_assets",
                        "ownership": "nanoparticle_conjugations"}[fault], [object()])
    elif fault == "multiple":
        design.nanoparticles.append(m.Nanoparticle(id="other", diameter_nm=20.0))
    elif fault == "missing":
        design.nanoparticles = []
    elif fault == "duplicate":
        design.nanoparticles *= 2
    elif fault == "quantum_dot":
        design.nanoparticles[0].kind = "quantum_dot"
    elif fault == "biotin":
        design.nanoparticles[0].biotin_dna = [object()]
    elif fault == "bad_pose":
        design.nanoparticles[0].pose.values[0] = float("nan")
    elif fault == "bad_diameter":
        design.nanoparticles[0].diameter_nm = float("inf")
    elif fault == "legacy":
        design.feature_log[0].params.pop("_proof_version")
    else:
        design.feature_log *= 33
    with pytest.raises((ValueError, ProofBudgetExceeded)):
        compiled(design, request(coating={"count_override": 1}))
    assert not no_geometry


def test_source_derived_work_refuses_without_capping_or_pinning(no_geometry):
    with pytest.raises(ProofBudgetExceeded, match="64 requested"):
        compiled(bare(), request(diameter_nm=100.0))
    assert not no_geometry


@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_new_set_cannot_silently_repair_old_source_evidence(no_geometry, fault):
    design = coated()
    if fault == "missing":
        design.input_sources.pop(coating.PDB_SHA256)
    else:
        design.input_sources[coating.PDB_SHA256] = EmbeddedInput(data_b64="bad")
    before = design.model_dump_json()
    with pytest.raises(SourceContractError) as error:
        compiled(design, request(coating={"count_override": 1}), seed=OTHER_SEED)
    assert error.value.code == ("source_unavailable" if fault == "missing" else "source_integrity_mismatch")
    assert design.model_dump_json() == before


def test_private_preparation_is_revalidated_and_bound_to_request(no_geometry):
    prepared = compiler.prepare_sources(request())
    malformed = [replace(prepared, entries=()), replace(prepared, entries=prepared.entries * 2),
        replace(prepared, entries=((coating.PDB_SHA256, EmbeddedInput(data_b64="bad")),)),
        replace(prepared, pdb_source=None)]
    for value in malformed:
        with pytest.raises(ValueError):
            compiled(bare(), request(), prepared=value)
    with pytest.raises(CommandContractError):
        compiled(bare(), request(coating={"coverage_reference": "gold_2007"}), prepared=prepared)
    with pytest.raises(CommandContractError):
        compiled(bare(), request("delete"), prepared=prepared)
    assert not no_geometry


@pytest.mark.parametrize("fault", ["missing_active", "removed_active", "settings_changed", "duplicate_row", "identity_reuse"])
def test_active_recipe_identity_and_choice_consistency_is_required(no_geometry, fault):
    design = coated()
    seed = OTHER_SEED
    if fault == "missing_active":
        design.feature_log.pop()
    elif fault == "removed_active":
        design.feature_log.append(row("remove", "nanoparticle-patch", {
            "_proof_version": 1, "coating_version": 1, "action": "remove", "nanoparticle_id": "gold"}))
    elif fault == "settings_changed":
        design.nanoparticles[0].coating.seed = 99
    elif fault == "duplicate_row":
        design.feature_log[-1].id = design.feature_log[0].id
    else:
        seed = SEED
    before = design.model_dump_json()
    with pytest.raises(CommandContractError):
        compiled(design, request("repack", diameter_nm=22.0), seed=seed)
    assert design.model_dump_json() == before


def test_combined_append_reserves_both_rows_and_preserves_recovery_opacity(no_geometry):
    design = coated()
    for index in range(29):
        design.feature_log.append(row(f"move-{index}", "nanoparticle-patch", {
            "_proof_version": 1, "coating_version": 1, "action": "move", "nanoparticle_id": "gold",
            "pose": list(m.Mat4x4().values)}))
    with pytest.raises(ProofBudgetExceeded, match="32 flat"):
        compiled(design, request("delete"), seed=OTHER_SEED)
    design.feature_log.pop()

    class Recovery:
        def __deepcopy__(self, _memo):
            pytest.fail("Compiler copied recovery")

    design.feature_log[0].design_snapshot_gz_b64 = Recovery()
    assert len(compiled(design, request("delete"), seed=OTHER_SEED).steps) == 2


@pytest.mark.parametrize("seed", [None, 1, "not a UUID"])
def test_host_identity_seed_must_be_a_uuid(no_geometry, seed):
    with pytest.raises(ValueError):
        compiled(bare(), request("delete"), seed=seed)

