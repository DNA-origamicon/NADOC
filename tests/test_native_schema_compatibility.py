"""Spawned schema-transition admissibility against unchanged native kernels.

These are same-installed-kernel parity checks, not historical binary or runtime
oracles. The first worker authors real outputs and runtime/template pins. Only
the implementation hash is then substituted with its captured historical value;
independent workers must reproduce the exact same complete authoring state.
"""

from copy import deepcopy
from importlib import import_module
import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

import pytest

from backend.api.part_evaluation_worker import EvaluationWorker
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, import_root
from backend.core.part_verification_capture import capture


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "docs/audits/feature_history_20261014/grouping_schema_compatibility_before.json"
DISSOLVE_BEFORE = ROOT / "docs/audits/feature_history_20261014/cluster_dissolve_schema_compatibility_before.json"
ORGANIZATION_BEFORE = ROOT / "docs/audits/feature_history_20261014/group_organization_schema_compatibility_before.json"


def _fixture(family):
    if family == "duplex":
        from tests.test_part_duplex_relax_contract import connected

        source = connected()
        source.recipe_root = import_root(source)
        return source, {"operation": "append", "kind": "duplex-relax",
            "params": {"source": {"kind": "native"}, "duplex_id": "duplex"}}, "part_duplex_relax_contract"
    if family == "cpd":
        from backend.core.part_cpd_contract import TEMPLATE_PATH
        from backend.core.photoproduct_registry import REGISTRY_PATH
        from tests.test_cpd_design import KEYS, fixture

        # Reuse the existing tiny fixture and its real pinned template. A missing
        # installation is explicit coverage debt, never a replacement molecule.
        if not (REGISTRY_PATH.parent / TEMPLATE_PATH).is_file():
            pytest.skip("Existing pinned CPD template is unavailable; native old-pin parity remains unqualified")
        source = fixture()
        source.recipe_root = import_root(source)
        return source, {"operation": "append", "kind": "photoproduct-create",
            "params": {"source": {"kind": "native"}, "base_keys": list(KEYS)}}, "part_cpd_contract"
    return create_empty_part("One coating compatibility", "HONEYCOMB"), {
        "operation": "append", "kind": "streptavidin-coating", "expected_revision": 7,
        "params": {"action": "create", "diameter_nm": 20.0,
                   "coating": {"mode": "adsorption", "count_override": 1, "seed": 1}},
    }, "part_streptavidin_contract"


def _cold(source, request, *, family):
    options = {}
    if family == "coating":
        # Existing qualification profile, only inside this explicit test. The
        # production capture and 2 MB actual worker input bounds are unchanged.
        options = {"max_nodes": 100_000, "max_bytes": 4_000_000, "seconds": 1.0}
    isolated = capture(source, preserve_entry_types=True, **options)
    worker = EvaluationWorker(isolated, {"request": request, "header": {
        "identity": "a8a3bea5-1a9d-43cc-a70b-61e0c7736bd6", "timestamp": "2026-10-16T00:00:00Z",
        "source_design_id": source.id, "source_revision": 7,
    }})
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        # Match the existing CPD worker allowance; no solver setting is changed.
        assert worker.wait(180 if family == "cpd" else 30)
        return worker.result()
    finally:
        worker.close()
        assert worker._closed and worker._process_closed and not worker.is_alive()
        for name in names:
            try:
                leaked = SharedMemory(name=name)
            except FileNotFoundError:
                continue
            leaked.close()
            leaked.unlink()
            pytest.fail("Native schema-compatibility worker leaked its transport buffer")


@pytest.mark.parametrize("family", ["duplex", "coating", "cpd"])
def test_spawned_numerical_schema_transition_preserves_exact_authored_outputs(family, monkeypatch):
    from backend.core.part_group_model import GroupOrganization, PartGroup

    source, request, contract_name = _fixture(family)
    # Organization is independently authored selection/style metadata. The
    # existing ordered placement owners and molecular inputs remain unchanged.
    organization = GroupOrganization(groups=[PartGroup(
        id="organization-only", name="Preserved organization", color="#123456", opacity=0.4,
        helix_ids=[source.helices[0].id] if source.helices else [])])
    if family != "coating":
        source.group_organization = organization
        source.recipe_root = import_root(source.copy_with(recipe_root=None))
    contract = import_module(f"backend.core.{contract_name}")
    # Parent imports can load different BLAS/OpenMP pools. Never author or
    # normalize a numerical pin here; every real pin comes from the child.
    monkeypatch.setattr(contract, "runtime_fingerprint",
        lambda: pytest.fail("Parent authored or validated a numerical runtime pin"))
    original = source.model_dump_json()
    created = _cold(source, request, family=family)
    assert created["status"] == "ready", created
    candidate = Design.model_validate(created["candidate"])
    assert source.model_dump_json() == original
    assert candidate.group_organization == source.group_organization
    assert candidate.model_dump(mode="json", include=AUTHORING_FIELDS) == {
        name: created["candidate"][name] for name in AUTHORING_FIELDS}
    entries = [row for row in candidate.feature_log if "engine" in row.params]
    assert len(entries) == 1
    entry = entries[0]
    if family == "coating":
        # Public append intentionally admits only its empty-root gold history.
        # Qualify the actual pinned set command over an independently imported
        # uncoated gold + organization source without widening that append gate.
        candidate.group_organization = organization
        uncoated = candidate.copy_with(nanoparticles=[
            item.model_copy(update={"coating": None}) for item in candidate.nanoparticles],
            feature_log=[], recipe_root=None)
        candidate.recipe_root = import_root(uncoated)
        candidate.feature_log = [entry]
    authored = candidate.model_dump(mode="json", include=AUTHORING_FIELDS)
    params = deepcopy(entry.params)
    current_pin = params["engine"]["implementation_sha256"]
    for row in candidate.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery is not an input"

    current = _cold(candidate, {"operation": "verify"}, family=family)
    assert current["status"] == "reproduced_import", current
    assert not current.get("numerical_compatibility", {}).get("transitions")

    for generation, path in (("grouping-v1", BEFORE), ("grouping-v2", DISSOLVE_BEFORE),
                             ("cluster-dissolve-v1", ORGANIZATION_BEFORE)):
        historical = json.loads(path.read_text())["engines"][contract.ENGINE_ID]["implementation_sha256"]
        assert current_pin != historical
        entry.params = {**params, "engine": {**params["engine"], "implementation_sha256": historical}}
        before_old = candidate.model_dump_json()
        approved = _cold(candidate, {"operation": "verify"}, family=family)
        assert approved["status"] == current["status"], (generation, approved)
        assert approved["checked_commands"] == current["checked_commands"] == len(candidate.feature_log)
        assert approved["authoring_fingerprint"] == current["authoring_fingerprint"]
        assert approved["numerical_compatibility"] == {"transitions": [{
            "transition_id": f"group-organization-v1.from-{generation}.{contract.ENGINE_ID}",
            "engine_id": contract.ENGINE_ID, "from_sha256": historical, "to_sha256": current_pin,
        }], "truncated": False}
        assert candidate.model_dump_json() == before_old
        assert candidate.model_dump(mode="json", include=AUTHORING_FIELDS) == authored
        assert entry.params["engine"]["runtime_sha256"] == params["engine"]["runtime_sha256"]
        assert {key: value for key, value in entry.params.items() if key != "engine"} == {
            key: value for key, value in params.items() if key != "engine"}

    entry.params = {**params, "engine": {**params["engine"], "implementation_sha256": "0" * 64}}
    unknown = _cold(candidate, {"operation": "verify"}, family=family)
    assert unknown["status"] == "unverified", unknown
    assert any(issue["code"] == "engine_mismatch" for issue in unknown["issues"])
    assert not unknown.get("numerical_compatibility", {}).get("transitions")
    assert source.model_dump_json() == original
