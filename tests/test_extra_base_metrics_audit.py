import json

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.extra_base_metrics_audit import build_extra_base_metrics_audit


def test_compacts_state_evidence_without_frame_lists(tmp_path):
    state = {
        "job": "/archive/job",
        "dcd": ["run.dcd"],
        "n_frames": 100,
        "stride": 2,
        "filters": {"global_paired_min": 0.9},
        "inserts": [
            {
                "crossover_id": "xo",
                "insert_k": 0,
                "base": "T",
                "src": ["h0", 1, "F"],
                "dst": ["h1", 2, "R"],
                "n_samples": 50,
                "n_valid": 40,
                "valid_fraction": 0.8,
                "failure_counts": {"global_pairing": 10},
                "stable_windows": [
                    {
                        "sample_start": 0,
                        "sample_stop": 31,
                        "frame_start": 0,
                        "frame_stop": 30,
                    }
                ],
                "n_stable_samples": 31,
                "panel_agreement_ari": {"a__b": 0.7},
                "panels": {
                    "hop_position": {
                        "ready": True,
                        "verdict": "switching",
                        "k": 2,
                        "transitions": 4,
                        "metrics": ["t_c1"],
                        "pc1_series": [1, 2, 3],
                        "clusters": [{"population": 0.7, "frames": list(range(30))}],
                    }
                },
            }
        ],
    }
    (tmp_path / "2hb_1xT__long__states.json").write_text(json.dumps(state))
    metrics = {
        "paired_fraction": [1.0] * 50,
        "inserts": [
            {
                "crossover_id": "xo",
                "k": 0,
                "samples": [{"t_c1": i / 50, "bow_sd_c1": -0.2} for i in range(50)],
            }
        ],
    }
    (tmp_path / "2hb_1xT__long__metrics.json").write_text(json.dumps(metrics))
    (tmp_path / "2hb_1xT__long__topology.txt").write_text("OK seed piercings=0")

    result = build_extra_base_metrics_audit(tmp_path)

    assert result["ready"] and result["sources"][0]["topology_pass"]
    panel = result["sources"][0]["inserts"][0]["panels"]["hop_position"]
    assert "pc1_series" not in panel
    assert "frames" not in panel["clusters"][0]
    assert panel["clusters"][0]["population"] == 0.7
    assert result["sources"][0]["inserts"][0]["state_cloud"]["points"]
    assert result["sources"][0]["cpd_reference"]["reactive_corner"]["n"] == 0


def test_empty_results_are_honestly_not_ready(tmp_path):
    result = build_extra_base_metrics_audit(tmp_path)
    assert result["ready"] is False and result["sources"] == []


def test_read_only_route_serves_the_registered_evidence():
    response = TestClient(app).get("/api/design/extra-base-metrics-audit")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "nadoc.extra-base-metrics-audit.v1"
    assert all(source["part"] != "24hb_1xT" for source in body["sources"])
