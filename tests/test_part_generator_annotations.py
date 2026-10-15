"""ISSUE-89: annotations are retained evidence, never native builder inputs."""

from copy import deepcopy
from uuid import UUID

import pytest

from backend.api import part_nanoparticle_commands as gold
from backend.api.generated_native_scope import namespaced
from backend.api.part_proof_commands import dependencies, execute, execute_long
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import SnapshotLogEntry
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import capture


GROUP = str(UUID(int=89))
ANNOTATION = {"nanoparticle_id": "forged", "_proof_version": 900,
    "nanoparticle_version": 900, "_generated_scope": {"input_ids": ["forged"]},
    "description": "This text is gold; keep it verbatim."}


def params(**extra):
    return {"_proof_version": 1, "nanoparticle_version": 1,
            "nanoparticle_id": "gold", **extra}


def recipe():
    root = create_empty_part("Annotated recipe", "HONEYCOMB")
    create, patch = params(diameter_nm=10.0), params(diameter_nm=12.0)
    # Expected output comes from the unchanged native builder, independently of
    # the shared replay boundary. Recovery cannot supply execution evidence.
    result = gold.build("nanoparticle-create", root, create)
    result = gold.build("nanoparticle-patch", result, patch)
    result.feature_log = [SnapshotLogEntry(id=identity, op_kind=kind, label=identity,
        params={**values, "_generator": deepcopy(ANNOTATION)},
        design_snapshot_gz_b64="not executable evidence", post_state_gz_b64="not executable evidence")
        for identity, kind, values in (("create", "nanoparticle-create", create),
                                       ("patch", "nanoparticle-patch", patch))]
    return result


@pytest.mark.parametrize("cold_worker", [False, True])
def test_valid_annotated_gold_recipe_regenerates_without_recovery(cold_worker):
    source = recipe()
    before = source.model_dump_json()
    if cold_worker:
        worker = VerificationWorker(capture(source))
        try:
            worker.start()
            assert worker.wait(5)
            result = worker.result()
        finally:
            worker.close()
    else:
        result = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 2
    assert source.model_dump_json() == before
    assert all(row.params["_generator"] == ANNOTATION for row in source.feature_log)


@pytest.mark.parametrize("executor", [execute, execute_long])
def test_annotation_is_removed_before_reference_admission_and_native_build(executor, monkeypatch):
    from backend.api import part_command_references as references

    values = params(diameter_nm=10.0, _generator=deepcopy(ANNOTATION))
    original, seen = deepcopy(values), []
    real_references, real_build = references.validate_command_references, gold.build

    def checked(kind, design, inputs):
        assert "_generator" not in inputs and "_generated_scope" not in inputs
        seen.append("references")
        return real_references(kind, design, inputs)

    def native(kind, design, inputs, **options):
        assert inputs == params(diameter_nm=10.0)
        seen.append("build")
        return real_build(kind, design, inputs, **options)

    monkeypatch.setattr(references, "validate_command_references", checked)
    monkeypatch.setattr(gold, "build", native)
    result = executor("nanoparticle-create", create_empty_part("Gold", "HONEYCOMB"), values)
    assert seen == ["references", "build"]
    assert result.nanoparticles[0].id == "gold" and values == original


@pytest.mark.parametrize("field,value", [("_proof_version", None), ("_proof_version", True),
    ("_proof_version", 2), ("nanoparticle_version", None), ("nanoparticle_id", None)])
def test_annotation_cannot_supply_missing_or_forged_native_authority(field, value, monkeypatch):
    values = params(diameter_nm=10.0, _generator={**ANNOTATION,
        "_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold"})
    if value is None:
        values.pop(field)
    else:
        values[field] = value
    assert not dependencies("nanoparticle-create", values).known
    monkeypatch.setattr(gold, "build", lambda *_a, **_kw: pytest.fail("Annotation supplied native authority"))
    with pytest.raises(NotImplementedError, match="versioned proof contract"):
        execute("nanoparticle-create", create_empty_part("Gold", "HONEYCOMB"), values)


@pytest.mark.parametrize("version", [1, 2])
def test_real_generated_scope_still_controls_identity_and_preserves_independent_gold(version):
    root = create_empty_part("Scoped", "HONEYCOMB")
    root = gold.build("nanoparticle-create", root, params(nanoparticle_id="independent", diameter_nm=8.0))
    values = params(diameter_nm=10.0, _generator=deepcopy(ANNOTATION),
        _generated_scope={"version": version, "group_id": GROUP, "input_ids": []})
    original = deepcopy(values)
    result = execute("nanoparticle-create", root, values)
    assert [(item.id, item.diameter_nm) for item in result.nanoparticles] == [
        ("independent", 8.0), (namespaced("gold", GROUP), 10.0)]
    assert result.nanoparticles[0] == root.nanoparticles[0] and values == original


@pytest.mark.parametrize("scope", [None, {}, {"version": 3, "group_id": GROUP, "input_ids": []},
    {"version": 2, "group_id": "invalid", "input_ids": []}])
def test_annotation_does_not_strip_or_replace_invalid_real_scope(scope):
    values = params(diameter_nm=10.0, _generator=deepcopy(ANNOTATION), _generated_scope=scope)
    with pytest.raises((ValueError, NotImplementedError)):
        execute("nanoparticle-create", create_empty_part("Gold", "HONEYCOMB"), values)


def test_annotation_does_not_broaden_command_fields_or_retarget_missing_consumers():
    root = gold.build("nanoparticle-create", create_empty_part("Gold", "HONEYCOMB"), params(diameter_nm=10.0))
    values = params(nanoparticle_id="missing", diameter_nm=12.0,
                    _generator={"nanoparticle_id": "gold"})
    with pytest.raises(ReferenceResolutionError) as error:
        execute("nanoparticle-patch", root, values)
    assert error.value.code == "missing_reference"
    unknown = params(diameter_nm=10.0, _generator=ANNOTATION, saved_output={"id": "gold"})
    assert not dependencies("nanoparticle-create", unknown).known
    with pytest.raises(NotImplementedError):
        execute("nanoparticle-create", root, unknown)
