"""Resource previews must charge actual work and reject unusable evidence."""

import hashlib
import json
import struct

import pytest

from backend.core.namd_allocation_model import QUALIFIED_ENGINE
from backend.core.namd_planning import (
    PlanningStage,
    memory_plan,
    phase_work,
    prepared_stages,
    qualified_job_timing,
    work_hours,
)
from backend.core import cluster_throughput, namd_timing
from backend.core.runpod_select import plan_options, ms_per_matom, record_rate


PROOF = dict(
    engine_sha256=QUALIFIED_ENGINE,
    gpu="test GPU",
    driver="test driver",
    configuration_sha256="a" * 64,
    completed=True,
    outputs_verified=True,
)


def test_mixed_stages_count_steps_including_minimization_once():
    stages = [
        dict(role="minimization", steps=1000),
        dict(role="relaxation", steps=10000, timestep_fs=2, gpu_resident=False),
        dict(role="production", steps=20000, timestep_fs=4, gpu_resident=True),
    ]
    hours = work_hours(
        phase_work(stages, production_ns=0.08), lambda resident: 10 if resident else 26
    )
    assert hours["relaxation"] == pytest.approx(11000 * 26 / 3600000)
    assert hours["production"] == pytest.approx(20000 * 10 / 3600000)


def test_old_disk_only_stages_do_not_double_count_production():
    work = phase_work(
        [PlanningStage(steps=100000, dcd_freq=1000)],
        production_ns=0.4,
        production_timestep_fs=4,
    )
    assert sum(s["steps"] for s in work) == 100000


def test_intended_production_is_added_only_if_absent():
    stage = dict(role="relaxation", steps=20000)
    work = phase_work([stage], production_ns=1, production_timestep_fs=2)
    assert work[-1]["steps"] == 500000
    assert len(phase_work(work, production_ns=1)) == 2


def test_memory_is_maximum_stage_plus_one_health_worker():
    stages = [
        dict(gpu_resident=False, extra_bonds=2000000),
        dict(gpu_resident=True, extra_bonds=0),
    ]
    combined = memory_plan(1000000, stages=stages)
    separate = [memory_plan(1000000, stages=[s]) for s in stages]
    assert combined["engine_ram_mib"] == max(s["engine_ram_mib"] for s in separate)
    assert (
        combined["workflow_ram_mib"]
        == combined["engine_ram_mib"] + combined["health_ram_mib"]
    )
    assert combined["confidence"] is None


def test_resolved_fine_pme_and_wide_neighbors_increase_vram():
    base = memory_plan(600000, box_nm=[40] * 3)
    stress = memory_plan(
        600000, box_nm=[40] * 3, stages=[dict(pairlistdist=24, pmegridspacing=0.75)]
    )
    assert stress["gpu_mib"] > base["gpu_mib"] * 2
    with pytest.raises(ValueError, match="Box dimensions"):
        memory_plan(600000, stages=[dict(pmegridspacing=0.75)])
    with pytest.raises(ValueError, match="invalid"):
        memory_plan(600000, box_nm=[float("nan")] * 3)


def test_prepared_plan_reads_actual_modes_bonds_and_disabled_dcd(tmp_path):
    (tmp_path / "bonds.extra").write_text(
        "# comment\nbond 1 2 1.0 3.0\nbond 2 3 1.0 3.0\n"
    )
    (tmp_path / "min.conf").write_text("minimize 1000\ntimestep 1\ndcdfreq 0\n")
    (tmp_path / "production.conf").write_text(
        "run 20000\ntimestep 2\ngpuResident on\nextraBonds on\nextraBondsFile bonds.extra\nPMEGridSpacing 0.75\npairlistdist 24\ndcdFreq 1000\n"
    )
    stages = prepared_stages(
        tmp_path,
        dict(
            minimization=dict(name="min", role="minimization"),
            segments=[dict(name="production")],
        ),
    )
    assert stages[0]["steps"] == 1000 and stages[0]["dcd_freq"] == 0
    assert stages[1]["ns"] == 0.04 and stages[1]["extra_bonds"] == 2
    assert stages[1]["gpu_resident"] and stages[1]["pmegridspacing"] == 0.75


def test_runpod_cost_includes_minimization_and_stage_mode():
    kw = dict(relax_ns=0.2, production_ns=0.4)
    base = plan_options(1000000, **kw)[0]
    stages = [
        dict(role="minimization", steps=10000),
        dict(role="relaxation", steps=100000, gpu_resident=False),
        dict(role="production", steps=100000, gpu_resident=True),
    ]
    planned = next(
        r for r in plan_options(1000000, stages=stages, **kw) if r["key"] == base["key"]
    )
    assert planned["production_cost"] == base["production_cost"]
    assert planned["relax_cost"] > base["relax_cost"] * 2
    assert planned["planning_cost"] == pytest.approx(
        planned["total_cost"] * planned["planning_factor"], abs=0.02
    )


def test_old_and_failed_rates_do_not_seed_current_registry(tmp_path):
    legacy = {"sm_89": {"ms_per_matom": 0.001, "n": 100}}
    assert ms_per_matom("sm_89", registry=legacy) == ms_per_matom("sm_89")
    path = tmp_path / "rates.json"
    record_rate(
        "sm_89", 1000000, 1, path=path, provenance={**PROOF, "completed": False}
    )
    assert not path.exists()
    cluster_throughput.record_throughput(
        tmp_path,
        cluster="a",
        partition="gpu",
        n_atoms=150000,
        ns_per_day=20,
        timestep_fs=2,
        provenance=PROOF,
    )
    assert (
        cluster_throughput.lookup_throughput(
            tmp_path, cluster="a", partition="gpu", n_atoms=150000
        )
        == 40
    )


def _timing_package(path):
    conf = "structure test.psf\noutputName production\nfirsttimestep 0\nrun 100\ntimestep 2\ngpuResident on\n"
    (path / "production.conf").write_text(conf)
    (path / "test.psf").write_text("PSF\n1 !NATOM\n")
    for ext in ("coor", "vel"):
        (path / f"production.{ext}").write_bytes(struct.pack("i", 1) + bytes(24))
    (path / "production.xsc").write_text("# header\n100 1 0 0\n")
    (path / "production.log").write_text(
        "TIMING: 100 CPU: 1, 0.1/step Wall: 1, 0.1/step, 20 ns/days, 0 hours remaining\nEnd of program\n"
    )
    receipt = dict(
        engine={"sha256": QUALIFIED_ENGINE},
        configuration=dict(
            path="production.conf", sha256=hashlib.sha256(conf.encode()).hexdigest()
        ),
        gpu=dict(name="test GPU", driver="driver"),
        threads=16,
    )
    (path / "production.resources.json").write_text(json.dumps(receipt))
    return dict(segments=[dict(name="production")])


def test_timing_requires_matching_config_clean_log_and_intact_outputs(tmp_path):
    manifest = _timing_package(tmp_path)
    result = qualified_job_timing(tmp_path, manifest)
    assert result and result["ns_per_day"] == 20 and result["timestep_fs"] == 2
    (tmp_path / "production.coor").write_bytes(b"broken")
    assert qualified_job_timing(tmp_path, manifest) is None
    _timing_package(tmp_path)
    with (tmp_path / "production.conf").open("a") as stream:
        stream.write("margin 5\n")
    assert qualified_job_timing(tmp_path, manifest) is None
    _timing_package(tmp_path)
    with (tmp_path / "production.log").open("a") as stream:
        stream.write("FATAL ERROR: failed\n")
    assert qualified_job_timing(tmp_path, manifest) is None


def test_local_timing_is_scoped_to_engine_device_threads_mode_and_size(monkeypatch):
    proof = namd_timing._evidence()["provenance"]
    monkeypatch.setattr(
        namd_timing,
        "local_identity",
        lambda _: {k: v for k, v in proof.items() if k != "threads"},
    )
    monkeypatch.setattr(namd_timing, "cpu_model", lambda: proof["cpu_model"])
    assert namd_timing.local_step_ms(472630) == pytest.approx(7.981545)
    assert namd_timing.local_step_ms(1000000) > 7.981545
    assert namd_timing.local_step_ms(1000000, threads=32) is None
    assert namd_timing.local_step_ms(1000000, resident=False) is None
    assert namd_timing.local_step_ms(60000) is None
    monkeypatch.setattr(namd_timing, "cpu_model", lambda: "different CPU")
    assert namd_timing.local_step_ms(1000000) is None
    monkeypatch.setattr(namd_timing, "cpu_model", lambda: proof["cpu_model"])
    monkeypatch.setattr(
        namd_timing, "local_identity", lambda _: {**proof, "engine_sha256": "obsolete"}
    )
    assert namd_timing.local_step_ms(1000000) is None


def test_disabled_trajectory_output_does_not_reserve_one_frame_per_step():
    from backend.core.disk_guard import namd_run_output_bytes

    disabled = namd_run_output_bytes([(1000000, 0)], 1000000)
    sparse = namd_run_output_bytes([(1000000, 10000)], 1000000)
    assert disabled < 100 * 1024**2  # only restart and fixed stage files
    assert sparse > 10 * disabled


def test_failed_parent_cannot_supply_local_timing(monkeypatch):
    from types import SimpleNamespace
    from backend.api.routes_md import _measured_ns_per_day

    assert _measured_ns_per_day(SimpleNamespace(status="failed")) is None


def test_completed_remote_job_learns_only_verified_timing_at_reference_timestep(
    tmp_path,
):
    from types import SimpleNamespace
    from backend.core.md_executor import _record_learned_throughput

    manifest = _timing_package(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    job = SimpleNamespace(
        status="completed",
        package_dir=lambda _: tmp_path,
        resources={"partition": "aa100"},
        cluster_name="alpine",
        job_id="test",
    )
    _record_learned_throughput(job, tmp_path)
    assert (
        cluster_throughput.lookup_throughput(
            tmp_path, cluster="alpine", partition="aa100", n_atoms=1
        )
        == 40
    )


def test_local_disk_quote_uses_actual_plan_and_reports_missing_hardware(
    tmp_path, monkeypatch
):
    import asyncio
    from types import SimpleNamespace
    from backend.api import routes_md, routes_md_plan
    from backend.core import md_vram
    from backend.core.disk_guard import namd_run_output_bytes

    design = SimpleNamespace(without_reference_geometry=lambda: object())
    monkeypatch.setattr(routes_md.design_state, "get_or_404", lambda: design)
    monkeypatch.setattr(
        md_vram,
        "estimate_profile_from_design",
        lambda *args, **kwargs: dict(
            dna_atoms=1000, full_water=100000, ion_atoms=0, atom_upper_bound=301000
        ),
    )
    stages = [
        dict(role="minimization", steps=1000, ns=0, params={"dcdfreq": "0"}),
        dict(
            role="production",
            steps=100000,
            ns=0.2,
            params={"dcdfreq": "1000", "gpuresident": "on"},
        ),
    ]

    async def plan(*args, **kwargs):
        return {"stages": stages}

    monkeypatch.setattr(routes_md_plan, "protocol_plan", plan)
    monkeypatch.setattr(
        namd_timing,
        "matches_local",
        lambda *args, **kwargs: False,
    )
    result = asyncio.run(
        routes_md.estimate_md_disk(routes_md.CreateJobRequest(run_dir=str(tmp_path)))
    )
    assert result["length_ns"] == 0.2
    assert result["predicted_bytes"] == namd_run_output_bytes(
        [(1000, 0), (100000, 1000)], 301000
    )
    assert (
        result["est_hours"] is None and "No timing coverage" in result["timing_note"]
    )
