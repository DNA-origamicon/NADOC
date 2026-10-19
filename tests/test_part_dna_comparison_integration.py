"""Version-two private transport and gated existing-owner integration."""

from copy import deepcopy
import json
from multiprocessing.shared_memory import SharedMemory

from fastapi.testclient import TestClient
import pytest

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

from backend.api import part_evaluation_comparison as owner, part_evaluation_jobs as jobs, state
from backend.api.part_comparison_worker import ComparisonWorker
from backend.api.part_verification_worker import _result_bytes, MAX_RESULT_BYTES
from backend.api.part_proof_commands import execute
from backend.core.part_comparison_projection import compare, parse_request, project
from backend.core.part_dna_comparison_codec import unpack_records
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from tests.test_part_comparison_projection import asset_part
from tests.test_part_comparison_routes import app, JOBS
from tests.test_part_dna_comparison import small
from tests.test_part_recipe_repair import row, set_input
import tests.test_part_evaluation_comparison as existing


def recipe():
    params = {"_proof_version": 1, "history_seed": "7070aa9b-0d7c-4aac-b0a7-2993a77c5ffe",
        "nominal_length_bp": 21, "tracks": [{"key": "a", "cell": [0, 0],
            "intervals": [{"key": "body", "lo_bp": 0, "hi_bp": 11}]}]}
    source = execute("branch-seed", create_empty_part("DNA comparison", "HONEYCOMB"), params)
    source.feature_log = [row("seed", "branch-seed", params)]
    source.repair_draft = RepairDraft.model_validate({"version": 1, "draft_id": "dna-proposal", "generation": 3,
        "base_design_id": source.id, "base": repair_base_fingerprint(source).model_dump(mode="json"),
        "repair_version": 1, "actions": [set_input("seed", ["tracks", 0, "intervals", 0, "hi_bp"], 11, 15)]})
    return source


@pytest.fixture
def dna_ready(monkeypatch, request):
    monkeypatch.setattr(existing, "saved_source", recipe)
    # Reuse all existing owner admission/source/session/catalog setup and its
    # failure-safe teardown; only the submitted recipe and projection differ.
    monkeypatch.setattr(owner, "DNA_COMPARISON_ENABLED", True)
    harness = request.getfixturevalue("ready")
    harness.body = {**harness.body, "projection_version": 2}

    class Worker:
        def __init__(self, source, candidate, *, projection_version):
            assert projection_version == 2
            assert not state._lock.locked() and not jobs._lock.locked()
            assert source is not harness.source
            self.source, self.candidate = source, deepcopy(candidate)
            self.alive = False
            harness.captured = source
            harness.opened += 1

        def start(self):
            self.alive = True

        def wait(self, _timeout):
            self.alive = False
            return True

        def is_alive(self):
            return self.alive

        def result(self):
            result = compare(self.source, self.candidate, projection_version=2)
            harness.before_result()
            return result

        def close(self):
            self.alive = False
            harness.closed += 1

    monkeypatch.setattr(owner, "ComparisonWorker", Worker)
    yield harness


# Register the reused fixture normally so pytest owns its lifecycle.
ready = existing.ready


def test_dna_version_is_explicit_and_v1_remains_unchanged():
    body = {"projection_version": 2, "expected_design_id": "part", "expected_revision": 1,
            "expected_draft_id": "proposal", "expected_generation": 0}
    assert parse_request(body).projection_version == 2
    assert "dna" not in project(asset_part())
    assert compare(asset_part(), asset_part().model_dump(mode="json"))["projection_version"] == 1


def test_mixed_complete_pane_uses_exact_existing_asset_projection_and_native_dna():
    design = small("bend")
    assets = asset_part()
    design.nanoparticles, design.protein_assets, design.protein_attachments = assets.nanoparticles, assets.protein_assets, assets.protein_attachments
    result = project(design, projection_version=2)
    for field in ("particles", "proteins", "unplaced_asset_ids"):
        assert result[field] == project(assets)[field]
    assert result["dna"]["nucleotides"]
    for layer_bounds in (project(assets)["bounds_nm"], result["dna"]["bounds_nm"]):
        assert all(result["bounds_nm"]["minimum"][i] <= layer_bounds["minimum"][i]
                   and result["bounds_nm"]["maximum"][i] >= layer_bounds["maximum"][i] for i in range(3))


def test_unqualified_public_version_refuses_before_capture_or_worker(dna_ready, monkeypatch):
    monkeypatch.setattr(owner, "DNA_COMPARISON_ENABLED", False)
    monkeypatch.setattr(owner, "_capture_source", lambda *_: pytest.fail("Unqualified public DNA captured"))
    with TestClient(app()) as client:
        response = client.post(f"{JOBS}/{dna_ready.id}/comparison", json=dna_ready.body,
                               headers={"X-NADOC-Doc": dna_ready.doc})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "comparison_not_qualified"
    assert dna_ready.opened == 0 and dna_ready.job.result["status"] == "ready"


def test_http_qualified_test_host_uses_same_owner_and_does_not_publish(dna_ready):
    h = dna_ready
    before = h.source.model_dump_json()
    candidate = h.job.result["candidate"]
    catalog = tuple(jobs._jobs)
    with TestClient(app()) as client:
        response = client.post(f"{JOBS}/{h.id}/comparison", json=h.body, headers={"X-NADOC-Doc": h.doc})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["projection_version"] == 2
    assert value["scope"] == "ordinary-dna-uncoated-particles-free-proteins-v2"
    assert len(value["published"]["dna"]["nucleotides"]) == 24
    assert len(value["proposed"]["dna"]["nucleotides"]) == 32
    assert value["repair_draft"] == {"draft_id": h.source.repair_draft.draft_id, "generation": 3}
    assert value["coverage"]["scientific_qualification"] is False
    assert value["coverage"]["presentation_policy"] == "all_authored_opaque_except_reference_strands"
    assert h.job.result["candidate"] is candidate and tuple(jobs._jobs) == catalog
    assert h.opened == h.closed == 1 and h.source.model_dump_json() == before
    assert state.get_design_with_revision() == (h.source, h.revision) and state.undo_depth() == 0
    committed = jobs.commit(h.id)
    assert committed["revision"] == h.revision + 1 and state.undo_depth() == 1


def test_v2_same_final_draft_generation_guard_discards_both_panes(dna_ready):
    from fastapi import HTTPException
    h = dna_ready
    def change():
        h.source.repair_draft = h.source.repair_draft.model_copy(update={"generation": 4})
    h.before_result = change
    with pytest.raises(HTTPException) as failure:
        jobs.comparison(h.id, h.body)
    assert failure.value.status_code == 409
    assert h.opened == h.closed == 1 and h.job.result["status"] == "ready" and state.undo_depth() == 0


def test_real_spawned_dna_projection_keeps_exact_native_coordinates_and_reaps_buffers():
    source = small("loops")
    candidate = source.model_copy(deep=True)
    candidate.cluster_transforms = small("cluster").cluster_transforms
    data = candidate.model_dump(mode="json")
    worker = ComparisonWorker(source, data, projection_version=2)
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(15), "Tiny DNA display worker did not finish"
        assert worker.result() == compare(source, data, projection_version=2)
    finally:
        worker.close()
    assert not worker.is_alive()
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)


@pytest.mark.parametrize("length,count", [(512, 1), (84, 6)])
def test_real_uuid_recipe_boundary_fits_existing_transport_without_coordinate_loss(length, count):
    from backend.core.design_geometry import _geometry_for_design
    from scripts.benchmark_dna_comparison import native_recipe

    source = native_recipe(length, count)
    value = compare(source, source.model_dump(mode="json"), projection_version=2)
    packed = _result_bytes(value)
    assert len(packed) < MAX_RESULT_BYTES
    decoded = json.loads(packed)
    assert decoded["status"] == "projected"
    assert unpack_records(decoded["published"]["dna"]["nucleotides"]) == _geometry_for_design(source)
    expanded = {**value, **{side: {**value[side], "dna": {**value[side]["dna"],
        "nucleotides": unpack_records(value[side]["dna"]["nucleotides"])}}
        for side in ("published", "proposed")}}
    assert len(json.dumps(expanded, separators=(",", ":"), allow_nan=False).encode()) > MAX_RESULT_BYTES


@pytest.mark.usefixtures("preview_test_scale_limits")
@pytest.mark.parametrize("rows", [None, {}, [[]], [[None] * 22], [[None] * 21] * 1025])
def test_fixed_row_codec_refuses_unknown_shape_or_unbounded_records(rows):
    # 1025 rows exceeds the test-scale 1024-slot allowance (tests/preview_test_limits.py).
    with pytest.raises(CommandContractError, match="fixed-row|compact"):
        unpack_records(rows)
