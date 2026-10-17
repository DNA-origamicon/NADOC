"""Native uncoated particle CRUD, independent proof and reference diagnostics."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api import part_nanoparticle_commands as commands
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.api.routes_nanoparticles import (
    GoldNanosphereCreate, NanoparticlePatch, create_nanosphere,
    delete_nanoparticle, patch_nanoparticle,
)
from backend.core.models import (
    BiotinDNA, Design, NanoparticleConjugation, NanoparticleConnectionVersion,
)
from backend.core.nanoparticle import create_gold_nanosphere, replace_gold_nanosphere
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture


def _params(**values):
    return {"_proof_version": 1, "nanoparticle_version": 1,
            "nanoparticle_id": "gold", **values}


def _source():
    return Design(nanoparticles=[create_gold_nanosphere(10, nanoparticle_id="gold")])


def test_native_particle_builders_match_existing_geometry_and_preserve_input():
    source = Design(metadata={"unrelated": "gold"})
    before = source.model_dump_json()
    created = commands.build("nanoparticle-create", source, _params(diameter_nm=10))
    assert created.nanoparticles == [create_gold_nanosphere(10, nanoparticle_id="gold")]
    assert source.model_dump_json() == before
    settings = {"diameter_nm": 12, "gizmo_move": {
        "pivot": [2, 1, 3], "translation": [4, 5, -2], "rotation": [0, 0, 1, 1],
    }}
    original = created.model_dump_json()
    expected = replace_gold_nanosphere(created, "gold", **settings)
    updated = commands.build("nanoparticle-patch", created, _params(**settings))
    assert updated == expected
    assert created.model_dump_json() == original
    assert updated.metadata == source.metadata
    assert not commands.build("nanoparticle-delete", updated, _params()).nanoparticles
    assert updated.nanoparticles


@pytest.mark.parametrize("kind", ["nanoparticle-patch", "nanoparticle-delete"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_target_fails_before_builder(kind, duplicate, monkeypatch):
    source = _source()
    source.nanoparticles = source.nanoparticles * 2 if duplicate else []
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Ambiguous target reached native geometry"))
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build(kind, source, _params())
    assert error.value.code == ("invalid_selection" if duplicate else "missing_reference")
    assert error.value.as_issue()["references"] == [{
        "kind": "nanoparticle", "identity": "gold", "parameter_path": ["nanoparticle_id"],
    }]


def _decorate(source, family):
    if family == "coating":
        source.nanoparticles[0].coating = object()
    elif family == "quantum_dot":
        source.nanoparticles[0].kind = "quantum_dot"
    elif family == "biotin_dna":
        source.nanoparticles[0].biotin_dna = [BiotinDNA(strand_id="strand", helix_id="helix", chain="A")]
    elif family == "conjugation":
        source.nanoparticle_conjugations = [NanoparticleConjugation(
            nanoparticle_id="gold", sequence="T", requested_count=1,
            estimated_capacity=1, density_per_nm2=.1)]
    else:
        source.nanoparticle_connection_versions = [NanoparticleConnectionVersion(
            nanoparticle_id="gold", strand_id="strand", overhang_id="overhang", duplex_id="duplex")]


@pytest.mark.parametrize("family", ["coating", "quantum_dot", "biotin_dna", "conjugation", "connection"])
@pytest.mark.parametrize("kind", ["nanoparticle-patch", "nanoparticle-delete"])
def test_native_contract_rejects_decorated_or_owned_particle(family, kind):
    source = _source()
    _decorate(source, family)
    assert not commands.source_free_target(source, "gold")
    with pytest.raises(ReferenceResolutionError, match="without DNA or connection ownership"):
        commands.build(kind, source, _params())
    assert source.nanoparticles[0].id == "gold"


@pytest.mark.parametrize("family", ["existing", "conjugation", "connection"])
def test_create_cannot_reuse_existing_or_dangling_owned_identity(family):
    source = _source()
    if family != "existing":
        _decorate(source, family)
        source.nanoparticles = []
    with pytest.raises(ReferenceResolutionError, match="dependent ownership"):
        commands.build("nanoparticle-create", source, _params(diameter_nm=10))


@pytest.mark.parametrize("change", [
    lambda p: p.pop("nanoparticle_version"),
    lambda p: p.update(nanoparticle_version=True),
    lambda p: p.update(_proof_version=True),
    lambda p: p.update(diameter_nm=float("inf")),
    lambda p: p.update(coating={"seed": 1}),
    lambda p: p.update(saved_particle={}),
])
def test_create_requires_exact_source_free_schema(change):
    params = _params(diameter_nm=10)
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("nanoparticle-create", params)


@pytest.fixture
def document():
    token = set_current_doc("native-particle-proof")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def _proof():
    result = assess_part_history(state.get_or_404(), execute=execute, dependencies=dependencies)
    assert result["status"] == "verified", result.get("issues")


def test_particle_route_edit_and_cold_proof_preserve_independent_dna(document):
    dna = state.get_or_404().model_dump(mode="json", include=AUTHORING_FIELDS)
    identity = create_nanosphere(GoldNanosphereCreate(diameter_nm=10))["nanoparticle_id"]
    patch_nanoparticle(identity, NanoparticlePatch(gizmo_move={
        "pivot": [0, 0, 0], "translation": [2, 3, 4], "rotation": [0, 0, 0, 1],
    }))
    before = state.get_or_404()
    ids = [entry.id for entry in before.feature_log]
    old_pose = before.nanoparticles[0].pose
    crud.edit_feature(1, crud.EditFeatureBody(params={"diameter_nm": 14}))
    updated = state.get_or_404()
    assert updated.nanoparticles[0].id == identity
    assert updated.nanoparticles[0].diameter_nm == 14
    assert updated.nanoparticles[0].pose == old_pose
    assert [entry.id for entry in updated.feature_log] == ids
    assert updated.model_dump(mode="json", include=AUTHORING_FIELDS - {"nanoparticles"}) == {
        name: value for name, value in dna.items() if name != "nanoparticles"
    }
    isolated = updated.model_copy(deep=True)
    for entry in isolated.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(isolated))
    try:
        worker.start()
        assert worker.wait(5)
        proof = worker.result()
        assert proof["status"] == "verified", proof.get("issues")
    finally:
        worker.close()
    state.undo()
    assert state.get_or_404().nanoparticles[0].diameter_nm == 10
    state.redo()
    assert state.get_or_404().nanoparticles[0].diameter_nm == 14


def test_particle_delete_feature_has_actual_reference_cascade(document):
    identity = create_nanosphere(GoldNanosphereCreate(diameter_nm=10))["nanoparticle_id"]
    patch_nanoparticle(identity, NanoparticlePatch(diameter_nm=11))
    source, revision = state.get_design_with_revision()
    preview = crud.delete_feature(1)
    assert preview["needs_cascade_decision"]
    assert preview["dependents"][0]["index"] == 2
    issues = list(preview["dependents"][0]["issues"].values())
    assert any(issue["code"] == "missing_reference" and issue["references"][0]["identity"] == identity
               for issue in issues)
    assert state.get_design_with_revision() == (source, revision)
    crud.delete_feature(1, cascade=True)
    assert not state.get_or_404().nanoparticles
    assert len(state.get_or_404().feature_log) == 1
    _proof()


def test_native_particle_delete_replays_and_undoes(document):
    identity = create_nanosphere(GoldNanosphereCreate(diameter_nm=10))["nanoparticle_id"]
    delete_nanoparticle(identity)
    assert not state.get_or_404().nanoparticles
    _proof()
    state.undo()
    assert state.get_or_404().nanoparticles[0].id == identity
    _proof()


def test_native_particle_record_failure_restores_all_document_state(document, monkeypatch):
    original = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    encode = state.encode_design_snapshot
    calls = 0

    def fail_post(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("post-state encoding failed")
        return encode(design)

    monkeypatch.setattr(state, "encode_design_snapshot", fail_post)
    with pytest.raises(RuntimeError, match="encoding failed"):
        create_nanosphere(GoldNanosphereCreate(diameter_nm=10))
    assert state.get_or_404().model_dump_json() == original
    assert state.revision() == revision and state.undo_depth() == depth


def test_legacy_same_kind_receipts_do_not_gain_proof_from_kind_registration():
    native = _params(diameter_nm=10)
    assert dependencies("nanoparticle-create", native).known
    for change in (lambda p: p.pop("nanoparticle_version"),
                   lambda p: p.update(coating={"seed": 1}),
                   lambda p: p.update(catalog_id="legacy-quantum-dot")):
        legacy = deepcopy(native)
        change(legacy)
        assert not dependencies("nanoparticle-create", legacy).known
