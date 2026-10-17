"""Real native CPD placement replays independently of saved output and physics.

The existing molecular fixture is an explicit imported basis. These tests claim
reproducibility from that basis, not a native recipe for its original topology.
"""

import pytest
from uuid import UUID, uuid5

from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import execute_long
from backend.core.models import Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_cpd_contract import (
    CPDContractError, ENGINE_ID, TEMPLATE_SHA256, native_source,
)
from backend.core.part_history_proof import AUTHORING_FIELDS, import_root
from backend.core.part_verification_capture import capture
from tests.test_cpd_design import KEYS, fixture


SEED = "a8a3bea5-1a9d-43cc-a70b-61e0c7736bd6"


class _UnusablePhysicalOutput:
    def __deepcopy__(self, memo):
        raise AssertionError("Physical output was copied into the native recipe")

    def __reduce__(self):
        raise AssertionError("Physical output was transported to the worker")


def _run(source, request):
    worker = EvaluationWorker(capture(source, preserve_entry_types=True), {
        "request": request,
        "header": {"identity": SEED if not source.feature_log else str(uuid5(UUID(SEED), str(len(source.feature_log)))),
                   "timestamp": "2026-10-15T00:00:00Z"},
    })
    try:
        worker.start()
        assert worker.wait(180), "Native CPD evaluation exceeded its production job deadline"
        return worker.result()
    finally:
        worker.close()


def test_native_cpd_append_and_independent_cold_proof_ignore_recovery_and_physics():
    source = fixture()
    source.recipe_root = import_root(source)
    original = source.model_dump(mode="json", include=AUTHORING_FIELDS)
    physical = _UnusablePhysicalOutput()
    source.atomistic_reference = physical
    assert native_source(source).atomistic_reference is None

    result = _run(source, {
        "operation": "append", "kind": "photoproduct-create",
        "params": {"source": {"kind": "native"}, "base_keys": list(KEYS)},
    })
    assert result["status"] == "ready", result.get("issues")
    raw = result["candidate"]
    candidate = Design.model_validate(raw)
    # The publication boundary may not normalize or otherwise alter evaluated
    # geometry; the subsequent proof must compare the same complete authoring.
    assert candidate.model_dump(mode="json", include=AUTHORING_FIELDS) == {
        name: raw[name] for name in AUTHORING_FIELDS
    }
    assert source.model_dump(mode="json", include=AUTHORING_FIELDS) == original
    assert source.atomistic_reference is physical
    assert not source.feature_log
    assert candidate.recipe_root.kind == "import"
    assert candidate.atomistic_reference is None
    assert len(candidate.photoproduct_junctions) == 1
    assert len(candidate.nucleotide_transforms) == 2
    assert len(candidate.feature_log) == 1
    entry = candidate.feature_log[0]
    assert entry.params["source"] == {"kind": "native"}
    assert entry.params["history_seed"] == SEED
    assert set(entry.params) == {
        "_proof_version", "conversion_version", "method", "product",
        "stereochemistry", "source", "template", "engine", "base_keys", "history_seed",
    }
    assert entry.design_snapshot_gz_b64 and entry.post_state_gz_b64
    entry.design_snapshot_gz_b64 = "not a decodable recovery snapshot"
    entry.post_state_gz_b64 = "not a decodable saved output"
    candidate.atomistic_reference = physical
    proof = _run(candidate, {"operation": "verify"})
    assert proof["status"] == "reproduced_import", proof.get("issues")
    assert proof["checked_commands"] == 1
    assert proof["native_editable"] is False
    assert "physical" in proof["excluded_roles"]

    relaxed = _run(candidate, {
        "operation": "append", "kind": "photoproduct-relax",
        "params": {"source": {"kind": "native"},
                   "photoproduct_id": candidate.photoproduct_junctions[0].id},
    })
    assert relaxed["status"] == "ready", relaxed.get("issues")
    raw = relaxed["candidate"]
    candidate = Design.model_validate(raw)
    assert candidate.model_dump(mode="json", include=AUTHORING_FIELDS) == {
        name: raw[name] for name in AUTHORING_FIELDS
    }
    assert len(candidate.feature_log) == 2
    for entry in candidate.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    proof = _run(candidate, {"operation": "verify"})
    assert proof["status"] == "reproduced_import", proof.get("issues")
    assert proof["checked_commands"] == 2


def _incorrect_engine_params():
    # Complete authored schema with a deliberately wrong implementation pin.
    # This requires no placement or numerical-runtime initialization.
    return {
        "_proof_version": 1, "conversion_version": 1,
        "method": "convert", "product": "TT-CPD", "stereochemistry": "cis-syn",
        "source": {"kind": "native"}, "base_keys": list(KEYS), "history_seed": SEED,
        "template": {"product_id": "tt-cpd-cis-syn",
                     "schema": "nadoc.photoproduct-coordinate-template.v1",
                     "sha256": TEMPLATE_SHA256},
        "engine": {"id": ENGINE_ID, "implementation_sha256": "0" * 64,
                   "runtime_sha256": "0" * 64},
    }


@pytest.mark.parametrize("missing_endpoint", [False, True])
def test_native_cpd_rejects_engine_and_missing_endpoint_before_placement(monkeypatch, missing_endpoint):
    from backend.core import atomistic, cpd_design

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid CPD inputs reached native placement or optimization")

    monkeypatch.setattr(cpd_design, "convert_extra_pair", forbidden)
    monkeypatch.setattr(atomistic, "build_atomistic_model", forbidden)
    source = fixture()
    before = source.model_dump_json()
    params = _incorrect_engine_params()
    if missing_endpoint:
        params["base_keys"][1] = "__xb__:missing-crossover:1"
        with pytest.raises(ReferenceResolutionError) as error:
            execute_long("photoproduct-create", source, params)
        assert error.value.as_issue()["references"] == [{
            "kind": "base_key", "identity": "__xb__:missing-crossover:1",
            "parameter_path": ["base_keys", 1],
        }]
    else:
        with pytest.raises(CPDContractError) as error:
            execute_long("photoproduct-create", source, params)
        assert error.value.as_issue()["code"] == "engine_mismatch"
    assert source.model_dump_json() == before
