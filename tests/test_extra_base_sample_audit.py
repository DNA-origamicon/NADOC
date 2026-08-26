import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.extra_base_position_clusters import reciprocal_crossover_sides
from backend.core.extra_base_sample_audit import (
    build_extra_base_sample_audit,
    build_extra_base_sample_catalog,
)
from backend.core.models import Design


def _sample(offset: float) -> dict:
    # Five measured anchors in a non-degenerate rigid arrangement, expressed in the
    # canonical fixed-ID helix-pair frame used by xb_observables.
    return {
        "g_ih_c1": offset + 1.0, "g_ax_c1": 0.5, "g_pp_c1": -0.2,
        "g_ih_base": offset + 2.2, "g_ax_base": 0.8, "g_pp_base": -0.1,
        "L": 1.0, "h1_c1": 1.0, "h2_c1": 0.5, "h3_c1": -0.2,
        "h1_P": 0.0, "h2_P": 0.0, "h3_P": 0.0,
        "h1_C5'": 0.4, "h2_C5'": 0.2, "h3_C5'": 0.1,
        "h1_C3'": 0.8, "h2_C3'": 0.4, "h3_C3'": -0.1,
        "interhelix": 25.0, "pose_rmsd": 0.4,
        "bp_src": 10.2, "bp_dst": 10.4, "bond_src": 1.6, "bond_dst": 1.7,
    }


def _fixture(tmp_path: Path) -> tuple[str, list[str]]:
    source_id = "fixture__trajectory"
    design = Design.model_validate_json(
        (Path(__file__).parents[1] / "workspace/2hb_1xT.nadoc").read_text()
    )
    side_map = reciprocal_crossover_sides(design)
    pairs = {}
    for crossover_id, side in side_map.items():
        pairs.setdefault(side["pair_id"], []).append(crossover_id)
    crossover_ids = next(ids for ids in pairs.values() if len(ids) == 2)
    job = tmp_path / "job"
    job.mkdir()
    (job / "design.json").write_text(design.model_dump_json())
    crossovers = {crossover.id: crossover for crossover in design.crossovers}
    inserts = []
    for number, crossover_id in enumerate(crossover_ids):
        crossover = crossovers[crossover_id]
        inserts.append({
            "crossover_id": crossover_id, "k": 0, "base": "T",
            "src": [
                crossover.half_a.helix_id, crossover.half_a.index,
                crossover.half_a.strand.value,
            ],
            "dst": [
                crossover.half_b.helix_id, crossover.half_b.index,
                crossover.half_b.strand.value,
            ],
            "samples": [_sample(number * 3.0), _sample(number * 3.0 + 0.25)],
        })
    metrics = {
        "job": str(job), "frames": [100, 120], "stride": 20,
        "paired_fraction": [0.99, 0.98], "inserts": inserts,
    }
    (tmp_path / f"{source_id}__metrics.json").write_text(json.dumps(metrics))
    state = {
        "pooled_positions": {"sides": [{
            "side": "i", "label": "Left crossover · i", "clusters": [{
                "rank": 0, "population": 1.0,
                "medoid": {"sample_index": 1, "frame": 120,
                           "crossover_id": crossover_ids[0]},
            }],
        }]},
    }
    (tmp_path / f"{source_id}__states.json").write_text(json.dumps(state))
    return source_id, crossover_ids


def test_catalog_lists_frames_crossovers_and_suggested_medoids(tmp_path):
    source_id, crossover_ids = _fixture(tmp_path)
    catalog = build_extra_base_sample_catalog(source_id, tmp_path)

    assert catalog["frames"] == [100, 120]
    assert {row["crossover_id"] for row in catalog["crossovers"]} == set(crossover_ids)
    assert catalog["suggestions"][0]["sample_index"] == 1
    assert catalog["suggestions"][0]["paired_with"] in crossover_ids


def test_sample_feed_adds_partner_and_returns_measured_atomistic_poses(tmp_path):
    source_id, crossover_ids = _fixture(tmp_path)
    result = build_extra_base_sample_audit(
        source_id, [crossover_ids[0]], sample_index=1,
        include_reciprocal_partners=True, results_dir=tmp_path,
    )

    assert result["frame"] == 120
    assert set(result["resolved_crossover_ids"]) == set(crossover_ids)
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["reciprocal_pair"] is True
    assert np.isfinite(group["directed_normal_separation_deg"])
    assert len(group["records"]) == 2
    assert all(record["atomistic"]["atoms"] for record in group["records"])
    assert all(record["quality"]["global_paired_fraction"] == 0.98
               for record in group["records"])


def test_sample_feed_resolves_nearest_dcd_frame(tmp_path):
    source_id, crossover_ids = _fixture(tmp_path)
    result = build_extra_base_sample_audit(
        source_id, [crossover_ids[0]], frame=118,
        include_reciprocal_partners=False, results_dir=tmp_path,
    )
    assert result["sample_index"] == 1 and result["frame"] == 120
    assert result["resolved_crossover_ids"] == [crossover_ids[0]]


def test_routes_validate_registered_sources(monkeypatch, tmp_path):
    source_id, crossover_ids = _fixture(tmp_path)
    import backend.core.extra_base_sample_audit as module

    monkeypatch.setattr(module, "RESULTS_DIR", tmp_path)
    client = TestClient(app)
    catalog = client.get(
        "/api/design/extra-base-sample-audit/catalog", params={"source_id": source_id}
    )
    assert catalog.status_code == 200
    sample = client.post("/api/design/extra-base-sample-audit", json={
        "source_id": source_id, "crossover_ids": [crossover_ids[0]],
        "sample_index": 0, "include_reciprocal_partners": True,
    })
    assert sample.status_code == 200 and sample.json()["groups"]
    missing = client.get(
        "/api/design/extra-base-sample-audit/catalog", params={"source_id": "../bad"}
    )
    assert missing.status_code == 404
