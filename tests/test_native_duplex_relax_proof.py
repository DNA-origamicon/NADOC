"""Real native relaxation and fresh-process replay of its pinned input recipe."""

import pytest

from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_duplex_commands import build
from backend.core import part_duplex_relax_contract as contract
from backend.core.models import Design
from backend.core.part_history_proof import AUTHORING_FIELDS, import_root
from backend.core.part_verification_capture import capture
from tests.test_part_duplex_commands import SEED
from tests.test_part_duplex_relax_contract import connected, inputs


@pytest.mark.parametrize("joints", [False, True])
def test_relax_adapter_preserves_exact_existing_solver_output(monkeypatch, joints):
    from backend.core.direct_relax import relax_direct_binding

    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 1})
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": 1})
    source = connected(joints=joints)
    before = source.model_dump_json()
    params = contract.prepare_command(source, inputs())
    expected, info = relax_direct_binding(contract.native_source(source), "oh-a", "oh-b",
                                          joint_ids=params["joint_ids"])
    actual = build("duplex-relax", source, params)
    assert actual.overhangs == expected.overhangs
    assert actual.cluster_transforms == expected.cluster_transforms
    assert actual.feature_log == source.feature_log
    assert info["joint_ids"] == params["joint_ids"]
    for field in AUTHORING_FIELDS - {"overhangs", "cluster_transforms"}:
        assert getattr(actual, field) == getattr(source, field)
    assert source.model_dump_json() == before


class _PhysicalOutput:
    def __deepcopy__(self, memo):
        raise AssertionError("Physical output entered native relaxation")

    def __reduce__(self):
        raise AssertionError("Physical output entered worker transport")


def _run(source, request):
    worker = EvaluationWorker(capture(source, preserve_entry_types=True), {
        "request": request, "header": {"identity": SEED, "timestamp": "2026-10-15T00:00:00Z"},
    })
    try:
        worker.start()
        assert worker.wait(30), "Tiny duplex recipe exceeded its focused worker allowance"
        return worker.result()
    finally:
        worker.close()


def test_spawned_relax_append_and_cold_proof_ignore_recovery_and_physical_output():
    # The fixture's initial placement is an explicit imported basis; this test
    # claims reproducibility of relaxation, not native construction of that basis.
    source = connected()
    source.recipe_root = import_root(source)
    original = source.model_dump(mode="json", include=AUTHORING_FIELDS)
    physical = _PhysicalOutput()
    source.atomistic_reference = physical
    assert contract.native_source(source).atomistic_reference is None
    result = _run(source, {"operation": "append", "kind": "duplex-relax",
        "params": {"source": {"kind": "native"}, "duplex_id": "duplex"}})
    assert result["status"] == "ready", result.get("issues")
    raw = result["candidate"]
    candidate = Design.model_validate(raw)
    assert candidate.model_dump(mode="json", include=AUTHORING_FIELDS) == {name: raw[name] for name in AUTHORING_FIELDS}
    assert source.model_dump(mode="json", include=AUTHORING_FIELDS) == original
    assert source.atomistic_reference is physical
    assert not source.feature_log
    assert len(candidate.feature_log) == 1
    entry = candidate.feature_log[0]
    assert entry.op_kind == "duplex-relax"
    assert entry.params["engine"]["id"] == contract.ENGINE_ID
    assert entry.params["joint_ids"] == ["joint-b"]
    assert entry.params["driver_cluster_id"] == "parent-a"
    assert entry.params["driven_cluster_id"] == "parent-b"
    assert entry.params["history_seed"] == SEED
    assert entry.design_snapshot_gz_b64 and entry.post_state_gz_b64
    entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned saved output"
    candidate.atomistic_reference = physical
    proof = _run(candidate, {"operation": "verify"})
    assert proof["status"] == "reproduced_import", proof.get("issues")
    assert proof["checked_commands"] == 1
    assert "physical" in proof["excluded_roles"]
