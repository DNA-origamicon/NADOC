"""Runtime accounting must not omit work or charge outside a rental lifetime."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.core.namd_runtime import (
    completion_quote,
    compute_estimate,
    local_compute,
    stage_rate,
)
from backend.core.namd_timing import sustained_timing


WORK = [
    dict(role="minimization", steps=4800),
    dict(role="production", steps=1_000_000, gpu_resident=True),
]


def compute(work=WORK):
    return compute_estimate(work, lambda s: stage_rate(1_000_000, s, resident_ms=20))


def quote(target="runpod", **kwargs):
    return completion_quote(
        compute(),
        target=target,
        n_atoms=1_000_000,
        stages=WORK,
        output_bytes=10 * 1024**3,
        package_bytes=1024**3,
        hourly_rate=0.5,
        **kwargs,
    )


def test_mixed_stage_accounting_and_range():
    result = compute()
    assert result["hours"] == pytest.approx((4800 * 52 + 1_000_000 * 20) / 3.6e6)
    assert result["high_hours"] == pytest.approx(
        (4800 * 52 * 3 + 1_000_000 * 20 * 2) / 3.6e6
    )
    assert result["low_hours"] < result["hours"] < result["high_hours"]


def test_s3_transfer_time_counts_without_gpu_billing():
    s3, ssh = quote(transfer_mode="s3"), quote(transfer_mode="ssh")
    assert s3["known_hours"] == ssh["known_hours"]
    transport = sum(
        c["hours"]
        for c in ssh["components"]
        if c["name"] in ["Upload", "Download results"]
    )
    assert ssh["billed_hours"] - s3["billed_hours"] == pytest.approx(transport)
    assert ssh["cost"] > s3["cost"]
    assert s3["high_cost"] >= s3["cost"]
    assert s3["container_disk_cost"] > 0
    assert s3["completion_hours"] is None  # capacity wait remains unknown


def test_alpine_queue_and_cost_are_different_clocks():
    r = quote("alpine", submissions=3)
    known = quote("alpine", submissions=3, queue_hours=2)
    assert r["completion_hours"] is None
    assert known["completion_hours"] == pytest.approx(known["known_hours"] + 6)
    assert r["cost"] == known["cost"]
    assert r["cost_unit"] == "SU"


def test_prepared_continuation_skips_prep():
    fresh, prepared = quote(), quote(prepared=True)
    assert fresh["known_hours"] > prepared["known_hours"]
    assert fresh["billed_hours"] == prepared["billed_hours"]


def test_storage_is_separate_and_persists():
    r = quote(volume_size_gb=50)
    assert r["storage_monthly_cost"] == pytest.approx(3.5)
    assert r["storage_window_cost"] > 0
    assert r["cost"] == quote()["cost"]
    assert quote(volume_size_gb=1500)["storage_monthly_cost"] == pytest.approx(95)


def test_forced_offload_is_the_same_work_on_every_target():
    from backend.api.routes_md_runtime import RuntimePreviewRequest, work_for

    body = RuntimePreviewRequest(
        n_atoms=1_000_000,
        gpu_resident_mode="off",
        stages=[dict(role="relaxation", steps=1000, gpu_resident=None)],
        production_ns=1,
    )
    work, resident = work_for(body, body.n_atoms)
    assert not resident and all(s["gpu_resident"] is False for s in work)
    assert len(work) == 2 and work[-1]["steps"] == 250000


def test_standard_probe_endpoint_is_not_excluded_by_smaller_geometry_fit(monkeypatch):
    from backend.core import namd_timing

    monkeypatch.setattr(namd_timing, "matches_local", lambda *a, **kw: True)
    r = local_compute(2_979_096, [dict(role="production", steps=32000)])
    assert r["calibrated"]
    assert r["stages"][0]["ms"] == pytest.approx(63.4523)


def test_local_cost_is_rental_only_and_unmatched_hardware_unknown(monkeypatch):
    from backend.core import namd_timing

    monkeypatch.setattr(namd_timing, "matches_local", lambda *a, **kw: False)
    assert local_compute(1_000_000, WORK) is None
    r = quote("local")
    assert r["cost"] == 0 and "electricity" in r["note"]


def test_current_local_stage_model_covers_minimization(monkeypatch):
    from backend.core import namd_timing

    monkeypatch.setattr(namd_timing, "matches_local", lambda *a, **kw: True)
    r = local_compute(1_000_000, WORK)
    assert r["calibrated"]
    assert r["stages"][0]["mode"] == "minimization"
    assert r["stages"][0]["ms"] > r["stages"][1]["ms"]


def test_nonstandard_local_threads_are_not_calibrated(monkeypatch):
    from backend.core import namd_timing

    monkeypatch.setattr(
        namd_timing, "matches_local", lambda p, **kw: p["threads"] == kw["threads"]
    )
    r = local_compute(1_000_000, WORK, threads=32)
    assert not r["calibrated"]


def test_unknown_phase_does_not_return_partial_total():
    assert (
        compute_estimate(WORK, lambda s: None if s["role"] == "minimization" else {})
        is None
    )


def test_tail_timing_uses_recent_windows_not_warmup(tmp_path):
    log = tmp_path / "run.log"
    log.write_text(
        "Benchmark time: 900 ns/day\n"
        + "padding\n" * 1000
        + "".join(
            f"TIMING: {i} CPU: 1, 1/step Wall: 10, {v}/step\n"
            for i, v in enumerate([0.03, 0.04, 0.08, 0.05])
        )
    )
    result = sustained_timing(log, max_bytes=512)
    assert result["seconds_per_step"] == pytest.approx(0.045)
    assert result["intervals"] == 4 and result["high_s"] == 0.08


def test_gpu_learning_does_not_cross_models_in_same_arch(tmp_path):
    from backend.core.runpod_select import record_rate, load_rate_registry, ms_per_matom
    from backend.core.namd_allocation_model import QUALIFIED_ENGINE

    proof = dict(
        engine_sha256=QUALIFIED_ENGINE,
        gpu="RTX 6000 Ada",
        driver="driver",
        configuration_sha256="a" * 64,
        completed=True,
        outputs_verified=True,
    )
    path = tmp_path / "rates.json"
    for _ in range(2):
        record_rate("sm_89", 1_000_000, 25, path=path, provenance=proof)
    registry = load_rate_registry(path)
    assert ms_per_matom("sm_89", registry=registry, gpu_key="RTX 6000 Ada") == 25
    assert ms_per_matom("sm_89", registry=registry, gpu_key="RTX 4090") == ms_per_matom(
        "sm_89"
    )


def test_runtime_preview_is_read_only_and_preserves_target_units(monkeypatch):
    from backend.api import routes_md_runtime as route, routes_runpod
    from backend.core import runpod_s3, namd_timing

    async def none(*a):
        return None

    monkeypatch.setattr(route, "live_stock", none)
    monkeypatch.setattr(routes_runpod, "_volume_info", none)
    monkeypatch.setattr(runpod_s3, "resolve_credentials", lambda: None)
    monkeypatch.setattr(namd_timing, "matches_local", lambda *a, **kw: True)
    body = route.RuntimePreviewRequest(
        n_atoms=1_000_000, stages=WORK, box_size_nm=[22, 22, 22]
    )
    r = asyncio.run(route.runtime_preview(body))
    assert r["sized"] and r["local"]["available"]
    assert r["alpine"]["completion"]["cost_unit"] == "SU"
    assert r["runpod"][0]["completion"]["cost_unit"] == "USD"


def test_prepared_parent_size_overrides_provided_and_open_design(monkeypatch, tmp_path):
    import json
    from backend.api import routes_md_runtime as route, routes_md

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            dict(
                box_ang=[100, 110, 120],
                charge_audit=dict(final_solvated=dict(n_atoms=123456)),
            )
        )
    )
    monkeypatch.setattr(
        routes_md,
        "_load_job",
        lambda _: SimpleNamespace(package_dir=lambda _: tmp_path),
    )
    body = route.RuntimePreviewRequest(n_atoms=999999, parent_job_id="parent")
    atoms, box, source = asyncio.run(route.resolve_size(body))
    assert atoms == 123456 and box == [10, 11, 12] and source == "prepared parent"


@pytest.mark.parametrize("field", ["upload_mbps", "download_mbps"])
def test_nonfinite_transfer_inputs_rejected(field):
    from pydantic import ValidationError
    from backend.api.routes_md_runtime import RuntimePreviewRequest

    with pytest.raises(ValidationError):
        RuntimePreviewRequest(**{field: float("nan")})
