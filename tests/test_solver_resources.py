"""Resource admission uses count-only stand-ins; no molecular files are authored."""

from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from backend.core import solver_resources as r


def design(n=1000, copies=1):
    return NS(
        strands=[NS(domains=[NS(start_bp=0, end_bp=n - 1)]) for _ in range(copies)],
        helices=[],
        crossovers=[],
        extensions=[],
    )


def options(**kw):
    return NS(**dict(execution_target="local", **kw))


@pytest.fixture(autouse=True)
def capacity(monkeypatch):
    monkeypatch.setattr(r, "available_for_work", lambda *args: 64 * r.GIB)
    monkeypatch.setattr(r, "cgroup_available", lambda: 64 * r.GIB)
    monkeypatch.setattr(r.shutil, "disk_usage", lambda _: NS(free=1024 * r.GIB))
    monkeypatch.setattr(
        "backend.core.md_vram.detect_gpu_activity",
        lambda **_: dict(total_mb=24000, used_mb=1000),
    )


@pytest.mark.parametrize("engine", ["snupi", "mrdna"])
def test_small_fits_large_part_and_assembly_denied(engine, tmp_path):
    r.check_resources(engine, design(), options(), tmp_path)
    for d in (design(10_000_000), design(10000, 1000)):
        with pytest.raises(r.MemoryBudgetExceeded, match="RAM: estimated"):
            r.check_resources(engine, d, options(), tmp_path)


def test_dynamic_friction_and_fragmented_blobs():
    d = design(1000)
    exact = r.estimate_resources("snupi", d, options(dynamics=True, hydrodynamics=True))
    coarse = r.estimate_resources(
        "snupi", d, options(dynamics=True, hydrodynamics=True, hydro_coarse_bp=8)
    )
    fragmented = r.estimate_resources(
        "snupi",
        design(1, 1000),
        options(dynamics=True, hydrodynamics=True, hydro_coarse_bp=8),
    )
    assert coarse.ram < exact.ram == fragmented.ram


def test_gpu_unknown_or_full_denies(monkeypatch, tmp_path):
    for gpu in (None, dict(total_mb=1000, used_mb=900)):
        monkeypatch.setattr("backend.core.md_vram.detect_gpu_activity", lambda **_: gpu)
        with pytest.raises(r.MemoryBudgetExceeded, match="GPU memory"):
            r.check_resources("mrdna", design(), options(), tmp_path)


def test_cgroup_and_disk_denial(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "cgroup_available", lambda: r.GIB)
    with pytest.raises(r.MemoryBudgetExceeded, match="RAM: estimated"):
        r.check_resources("snupi", design(), options(), tmp_path)
    monkeypatch.setattr(r, "cgroup_available", lambda: 64 * r.GIB)
    monkeypatch.setattr(r.shutil, "disk_usage", lambda _: NS(free=r.GIB))
    with pytest.raises(r.MemoryBudgetExceeded, match="disk space"):
        r.check_resources("snupi", design(), options(), tmp_path)


def test_sampling_and_fine_increase_requirements():
    coarse = r.estimate_resources("mrdna", design(), options())
    fine = r.estimate_resources(
        "mrdna", design(), options(fine_steps=1000000, output_period=100)
    )
    assert fine.gpu > coarse.gpu and fine.disk > coarse.disk


@pytest.mark.parametrize("engine", ["snupi", "mrdna"])
def test_restart_denied_before_launch_or_status_change(engine, monkeypatch, tmp_path):
    import importlib

    runner = importlib.import_module(f"backend.core.{engine}_runner")
    monkeypatch.setattr(runner, "is_running", lambda *args: False)
    monkeypatch.setattr(runner, "_load_snapshot_design", lambda _: design(10_000_000))
    launch = Mock()
    monkeypatch.setattr(
        runner.runtime,
        "launch_detached" if engine == "snupi" else "launch_thread",
        launch,
    )
    job = NS(
        execution_target="local",
        job_id="test",
        job_dir=lambda _: tmp_path,
        status="stopped",
    )
    with pytest.raises(r.MemoryBudgetExceeded):
        runner.start_job(job, tmp_path)
    launch.assert_not_called()
    assert job.status == "stopped"


def test_remote_uses_allocation(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "available_for_work", lambda: 2 * r.GIB)
    from backend.core.solver_cluster_config import SolverClusterSettings
    remote = NS(execution_target="alpine", cluster_settings=SolverClusterSettings(python="/bin/python", mem_gb=64, cores=32))
    r.check_resources("snupi", design(), remote, tmp_path)
    remote.cluster_settings.mem_gb = 1
    with pytest.raises(r.MemoryBudgetExceeded):
        r.check_resources("snupi", design(), remote, tmp_path)


@pytest.mark.parametrize("engine", ["snupi", "mrdna"])
def test_create_denies_before_job_or_preparation(engine, monkeypatch, tmp_path):
    import asyncio
    import importlib

    routes = importlib.import_module(f"backend.api.routes_{engine}")
    d = design(10_000_000)
    d.without_reference_geometry = lambda: d
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: d)
    monkeypatch.setattr(routes, "_workspace", lambda: tmp_path)
    if engine == "mrdna":
        monkeypatch.setattr(routes, "mrdna_available", lambda: {"available": True})
    create = Mock()
    prepare = Mock()
    monkeypatch.setattr(routes, f"new_{engine}_job", create)
    monkeypatch.setattr(routes, f"prepare_{engine}_job", prepare)
    body = getattr(
        routes,
        "CreateSnupiJobRequest" if engine == "snupi" else "CreateMrdnaJobRequest",
    )()
    with pytest.raises(r.MemoryBudgetExceeded):
        result = getattr(routes, f"create_{engine}_job")(body)
        if engine == "mrdna":
            asyncio.run(result)
    create.assert_not_called()
    prepare.assert_not_called()


def test_pending_launch_reservation_blocks_second_job(monkeypatch, tmp_path):
    from backend.core import memory_budget as budget

    monkeypatch.setenv("NADOC_MEMORY_BUDGET_DIR", str(tmp_path / "reservations"))
    monkeypatch.setattr(
        budget.psutil, "virtual_memory", lambda: NS(available=8 * r.GIB)
    )
    need = r.SolverResources(3 * r.GIB, 0, 0, 1)
    with r.reserve_resources(need, "SNUPI", options()):
        with pytest.raises(r.MemoryBudgetExceeded):
            with r.reserve_resources(need, "SNUPI", options()):
                pytest.fail("second allocation exceeded available memory")
    with r.reserve_resources(need, "SNUPI", options()):
        pass


def test_pending_reservations_respect_cgroup_capacity(monkeypatch, tmp_path):
    from backend.core import memory_budget as budget

    monkeypatch.setenv("NADOC_MEMORY_BUDGET_DIR", str(tmp_path / "reservations"))
    monkeypatch.setattr(
        budget.psutil, "virtual_memory", lambda: NS(available=64 * r.GIB)
    )
    monkeypatch.setattr(r, "available_for_work", budget.available_for_work)
    monkeypatch.setattr(r, "cgroup_available", lambda: 4 * r.GIB)
    need = r.SolverResources(3 * r.GIB, 0, 0, 1)
    with r.reserve_resources(need, "SNUPI", options()):
        with pytest.raises(r.MemoryBudgetExceeded, match="cgroup RAM limit"):
            with r.reserve_resources(need, "SNUPI", options()):
                pytest.fail("cgroup was overbooked")
    assert not list((tmp_path / "reservations").glob("*.json"))


@pytest.mark.parametrize("engine", ["snupi", "mrdna"])
def test_failed_launch_releases_reservation(engine, monkeypatch, tmp_path):
    from backend.core import memory_budget as budget, simulation_runtime as runtime

    monkeypatch.setenv("NADOC_MEMORY_BUDGET_DIR", str(tmp_path / "reservations"))
    monkeypatch.setattr(
        budget.psutil, "virtual_memory", lambda: NS(available=64 * r.GIB)
    )
    need = r.SolverResources(r.GIB, 0, 0, 1)
    job = NS(job_id="test", job_dir=lambda _: tmp_path, error="previous failure")
    method = "launch_detached" if engine == "snupi" else "launch_thread"
    monkeypatch.setattr(runtime, method, Mock(side_effect=RuntimeError("spawn failed")))
    with pytest.raises(RuntimeError, match="spawn failed"):
        if engine == "snupi":
            r.launch_reserved_detached(need, job, tmp_path, "unused", tmp_path, {})
        else:
            r.launch_reserved_thread(
                need, job, tmp_path, lambda: None, {}, None, None, None
            )
    assert not list((tmp_path / "reservations").glob("*.json"))


def test_recorded_large_origami_nma_peak_has_planning_margin():
    # Count-only model of BigO-poly: 30 copies, 14,112 domain nt each.
    need = r.estimate_resources("snupi", design(14112, 30), options())
    assert 46 * r.GIB * 1.2 < need.ram < 80 * r.GIB


def test_saved_snapshot_rejected_before_parsing(monkeypatch, tmp_path):
    snapshot = tmp_path / "design.json"
    snapshot.write_text("not molecular data")
    monkeypatch.setattr(r, "available_for_work", lambda: 128 * 1024**2)
    with pytest.raises(r.MemoryBudgetExceeded, match="reading its saved design"):
        r.check_snapshot_capacity(tmp_path)
