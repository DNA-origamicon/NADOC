from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

from backend.core import md_executor, remote_live_health
from backend.core.md_health import HealthCheckResult
from backend.core.md_job import new_job


def test_collector_emits_compact_all_scalar_health(tmp_path, monkeypatch):
    (tmp_path / "seg.log").write_text("running\n")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "name": "seg",
                        "stage": "production",
                        "min_c1_paired": 0.91,
                        "min_wc_ref_relative": 0.72,
                    }
                ]
            }
        )
    )
    seen = {}

    def run(*args, **kwargs):
        seen.update(kwargs)
        return HealthCheckResult(
            passed=True,
            c1_paired_fraction=0.97,
            wc_ref_relative_fraction=0.88,
            broken_bp_count=1,
            charge_within_shell_e=23.5,
            per_frame_ran=True,
            wc_per_frame=[0.1] * 1000,
            broken_bp_per_frame=[1] * 1000,
            charge_per_frame=[23.5] * 1000,
        )

    monkeypatch.setitem(sys.modules, "md_health", SimpleNamespace(run_health_check=run))
    out = remote_live_health.collect(str(tmp_path), "design")
    assert out["ready"] is True
    assert out["stage"] == "production"
    assert out["health"]["broken_bp_count"] == 1
    assert out["health"]["charge_within_shell_e"] == 23.5
    assert "wc_per_frame" not in out["health"], "bundle must stay metadata-sized"
    assert seen["safe_back"] == 1
    assert seen["per_frame"] is False
    assert seen["min_c1_paired"] == 0.91


def test_atomic_writer_leaves_no_torn_temp(tmp_path):
    path = tmp_path / "output" / "live_health.json"
    remote_live_health._write_atomic(path, {"ready": True})  # noqa: SLF001
    assert json.loads(path.read_text()) == {"ready": True}
    assert not path.with_suffix(".json.tmp").exists()


def test_not_ready_result_is_explicit_not_a_false_failure(tmp_path, monkeypatch):
    (tmp_path / "seg.log").write_text("running\n")
    monkeypatch.setitem(
        sys.modules,
        "md_health",
        SimpleNamespace(
            run_health_check=lambda *a, **k: HealthCheckResult(
                passed=False, not_ready=True, error="DCD has no frames yet"
            )
        ),
    )
    out = remote_live_health.collect(str(tmp_path), "design")
    assert out["ready"] is False
    assert "waiting" in out["reason"]


def test_collector_log_cannot_be_mistaken_for_active_segment(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"segments": [{"name": "job_01_production"}]})
    )
    (tmp_path / "job_01_production.log").write_text("ENERGY")
    collector = tmp_path / "nadoc_live_health.log"
    collector.write_text("collector output")
    os.utime(collector, None)

    assert remote_live_health._active_segment(tmp_path) == "job_01_production"


def test_retrieved_bundle_populates_health_sample_and_probe():
    job = new_job("d", "equilibrium_aware_namd", "d", "pkg")
    blob = json.dumps(
        {
            "collected_at": 123.0,
            "ready": True,
            "segment": "seg",
            "stage": "production",
            "health": {
                "passed": True,
                "blocking": False,
                "reason": "",
                "error": None,
                "c1_paired_fraction": 0.96,
                "c1_mean_ang": 10.2,
                "c1_p90_ang": 11.1,
                "wc_ref_relative_fraction": 0.84,
                "wc_mean_hbond_ang": 3.1,
                "broken_bp_count": 2,
                "charge_within_shell_e": 18.0,
                "diagnostics_error": None,
                "per_frame_ran": True,
            },
        }
    )
    assert md_executor.apply_live_health(job, blob) is True
    assert job.health_samples[-1].c1_paired_fraction == 0.96
    assert job.health_samples[-1].broken_bp_count == 2
    assert job.health_probe["latest"]["charge_within_shell_e"] == 18.0
    assert md_executor.apply_live_health(job, blob) is False
