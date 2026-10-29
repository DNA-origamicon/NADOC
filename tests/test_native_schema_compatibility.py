"""Spawned current-source parity and exact rejection of retired schema pins.

The first worker authors real outputs and runtime/template pins. Independent
workers reproduce current inputs and refuse captured historical source pins.
No historical equivalence authorizes an unreviewed transition to today's source;
all refusal checks preserve the complete authored state and original runtime pin.
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
LOAD_BEFORE = ROOT / "docs/audits/feature_history_20261014/group_organization_load_schema_compatibility_before.json"
LINEAGE_BEFORE = ROOT / "docs/audits/feature_history_20261014/domain_lineage_compatibility_before.json"
VISIBILITY_BEFORE = ROOT / "docs/audits/feature_history_20261014/group_visibility_schema_compatibility_before.json"
POSES_BEFORE = ROOT / "docs/audits/feature_history_20261014/placement_poses_schema_compatibility_before.json"
EXTENSIONS_BEFORE = ROOT / "docs/audits/feature_history_20261014/extension_schema_compatibility_before.json"


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
def test_spawned_current_pins_reproduce_and_retired_schema_pins_refuse(family, monkeypatch):
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
    assert current["checked_commands"] == len(candidate.feature_log)
    assert not current.get("numerical_compatibility", {}).get("transitions")

    generations = [("grouping-v1", BEFORE), ("grouping-v2", DISSOLVE_BEFORE),
                   ("cluster-dissolve-v1", ORGANIZATION_BEFORE),
                   ("group-organization-v1", LOAD_BEFORE)]
    if family != "coating":
        generations.append(("organization-load-v1", LINEAGE_BEFORE))
    # The coating capture at LINEAGE_BEFORE equals VISIBILITY_BEFORE; include
    # that real source pin once under the latest captured generation.
    generations.append(("native-domain-lineage-v1", VISIBILITY_BEFORE))
    generations.append(("group-visibility-v1", POSES_BEFORE))
    generations.append(("placement-poses-v1", EXTENSIONS_BEFORE))
    historical_pins = [json.loads(path.read_text())["engines"][contract.ENGINE_ID]["implementation_sha256"]
                       for _, path in generations]
    assert len(set(historical_pins)) == len(generations) == (7 if family == "coating" else 8)
    for generation, path in generations:
        historical = json.loads(path.read_text())["engines"][contract.ENGINE_ID]["implementation_sha256"]
        assert current_pin != historical
        entry.params = {**params, "engine": {**params["engine"], "implementation_sha256": historical}}
        before_old = candidate.model_dump_json()
        refused = _cold(candidate, {"operation": "verify"}, family=family)
        assert refused["status"] == "unverified", (generation, refused)
        assert refused["checked_commands"] == 0
        assert any(issue["code"] == "engine_mismatch" for issue in refused["issues"])
        assert refused["authoring_fingerprint"] == current["authoring_fingerprint"]
        assert not refused.get("numerical_compatibility", {}).get("transitions")
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
