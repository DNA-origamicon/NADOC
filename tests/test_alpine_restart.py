"""Outage recovery contracts: no seed fallback, preserved data, durable notices."""

import json
import os
import struct
from pathlib import Path

import pytest

from backend.core import alpine_restart as control
from backend.core import remote_alpine_restart as node
from backend.core.md_job import MdJob, MdStatus
from tests.test_resume_transfer import build_dcd


def dcd(frames, first=5000):
    raw = bytearray(build_dcd(2, frames))
    struct.pack_into("<iii", raw, 12, first, 5000, first + (frames - 1) * 5000)
    return bytes(raw)


def package(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "s.conf").write_text("""structure s.psf
binCoordinates seed.coor
binVelocities seed.vel
extendedSystem seed.xsc
timestep 4
langevinPiston on
langevinPistonPeriod 200
constraints on
consKFile anchors.pdb
consRef anchors.pdb
outputName output/s
dcdFile output/s.dcd
xstFile output/s.xst
restartfreq 5000
dcdFreq 5000
outputEnergies 5000
xstFreq 2500
firsttimestep 0
run 50000
""")
    (tmp_path / "s.psf").write_text("PSF\n\n       2 !NATOM\n")
    return tmp_path


def write_checkpoint(p, step=20000, suffix="", times=(1, 2, 3)):
    out = p / "output"
    xsc = out / ("s.restart.xsc" + suffix)
    xsc.write_text("%d 10 0 0 0 10 0 0 0 10 0 0 0\n" % step)
    for ext in ("coor", "vel"):
        (out / ("s.restart." + ext + suffix)).write_bytes(
            struct.pack("<i6d", 2, *range(6))
        )
    for ext, stamp in zip(("xsc", "coor", "vel"), times):
        os.utime(out / ("s.restart." + ext + suffix), ns=(stamp, stamp))


def test_restart_resumes_remaining_steps_preserving_prior_trajectory(
    tmp_path, monkeypatch
):
    p = package(tmp_path)
    write_checkpoint(p)
    (p / "output/s.dcd").write_bytes(dcd(4))
    (p / "s.log").write_text("old log")
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("SLURM_RESTART_COUNT", "1")
    ident = node.begin(p)
    conf = node.prepare(p, "s", "s", 50000)
    text = (p / (conf + ".conf")).read_text()
    assert "firsttimestep      20000" in text
    assert "run                30000" in text
    assert "constraints on" in text and "consRef anchors.pdb" in text
    assert "timestep 4" in text and "langevinPistonPeriod 200" in text
    assert "output/s.cont1.dcd" in text
    assert (p / "output/s.dcd").read_bytes() == dcd(4)
    assert (p / "output/attempts" / ident / "s.log").read_text() == "old log"
    assert "attempts/" + ident + "/s/input.coor" in text
    write_checkpoint(p, 30000, times=(4, 5, 6))
    (p / "output/s.cont1.dcd").write_bytes(dcd(2, 25000))
    monkeypatch.setenv("SLURM_RESTART_COUNT", "2")
    node.begin(p)
    conf = node.prepare(p, "s", "s", 50000)
    assert "output/s.cont2.dcd" in (p / (conf + ".conf")).read_text()
    assert "run                20000" in (p / (conf + ".conf")).read_text()
    assert (
        node.restart_step_of(
            (p / "output/attempts" / ident / "s/input.xsc").read_text()
        )
        == 20000
    )


def test_partial_generation_falls_back_to_consistent_old(tmp_path):
    p = package(tmp_path)
    write_checkpoint(p, 20000, times=(9, 10, 3))
    write_checkpoint(p, 15000, ".old", times=(1, 2, 3))
    node.begin(p)
    node.prepare(p, "s", "s", 50000)
    event = json.loads((p / node.JOURNAL).read_text())["attempts"][-1]["segments"][0]
    assert event["checkpoint_step"] == 15000
    assert event["checkpoint_generation"] == ".old"


def test_no_checkpoint_stops_without_overwriting(tmp_path):
    p = package(tmp_path)
    (p / "output/s.dcd").write_bytes(b"old")
    node.begin(p)
    with pytest.raises(ValueError, match="no complete"):
        node.prepare(p, "s", "s", 50000)
    assert not (p / "s.alpine_resume.conf").exists()
    assert (
        json.loads((p / node.JOURNAL).read_text())["attempts"][-1]["segments"][0][
            "mode"
        ]
        == "blocked"
    )


def test_wrong_atom_count_and_truncated_binary_rejected(tmp_path):
    p = package(tmp_path)
    write_checkpoint(p)
    with pytest.raises(ValueError, match="atom counts"):
        node.checkpoint(p, "s", expected_atoms=3)
    (p / "output/s.restart.vel").write_bytes(b"bad")
    with pytest.raises(ValueError, match="truncated"):
        node.checkpoint(p, "s")


def test_fresh_and_checkpoint_at_total(tmp_path):
    p = package(tmp_path)
    node.begin(p)
    assert node.prepare(p, "s", "s", 50000) == "s"
    write_checkpoint(p, 50000)
    node.begin(p)
    node.prepare(p, "s", "s", 50000)
    assert "run 0" in (p / "s.alpine_resume.conf").read_text()


def job(tmp_path):
    j = MdJob(
        job_id="abc",
        design_name="test",
        protocol="test",
        status=MdStatus.running,
        created_at=1,
        package_subdir="package/test",
        name_stem="test",
    )
    j.save(tmp_path)
    return j


def test_scheduler_restart_same_id_and_idempotent_acknowledgment(tmp_path):
    j = job(tmp_path)
    sched = control.scheduler_evidence(
        "JobId=123 JobState=RUNNING Restarts=1 StartTime=2026-09-11T18:59:54"
    )
    assert control.record_events(j, {}, sched)
    assert len(j.restart_events) == 1
    assert not control.record_events(j, {}, sched)
    control.acknowledge(j, [{"id": "123-r1", "revision": 1}], tmp_path)
    # A stale observer cannot erase the acknowledgment by saving older job.json.
    j.restart_events[0]["acknowledged_at"] = None
    j.save(tmp_path)
    assert MdJob.load("abc", tmp_path).restart_events[0]["acknowledged_at"]
    journal = {
        "attempts": [
            {
                "id": "a1",
                "slurm_job_id": "123",
                "restart_count": 1,
                "segments": [{"mode": "continued", "checkpoint_step": 20000}],
            }
        ]
    }
    assert control.record_events(j, journal, sched)
    assert len(j.restart_events) == 1
    assert j.restart_events[0]["mode"] == "continued"
    assert j.restart_events[0]["acknowledged_at"] is None
    with pytest.raises(ValueError, match="changed"):
        control.acknowledge(j, [{"id": "123-r1", "revision": 1}], tmp_path)


def test_new_restart_requires_new_acknowledgment(tmp_path):
    j = job(tmp_path)
    control.record_events(j, {}, dict(slurm_job_id="123", restart_count=1))
    control.acknowledge(j, [{"id": "123-r1", "revision": 1}], tmp_path)
    control.record_events(j, {}, dict(slurm_job_id="123", restart_count=2))
    assert len(j.restart_events) == 2
    assert j.restart_events[1]["acknowledged_at"] is None


def test_snapshot_owns_no_scheduler_handle_or_original_directory(tmp_path):
    j = job(tmp_path)
    j.slurm_job_id = "123"
    j.package_subdir = "package/test"
    j.package_dir(tmp_path).mkdir(parents=True)
    (j.package_dir(tmp_path) / "s.psf").write_text("topology")
    evidence = dict(
        remote_directory="/scratch/a/output/attempts/legacy-123-r1", records=[]
    )
    event = {"id": "123-r1"}
    sid = control.snapshot_job(j, event, evidence, tmp_path)
    prior = MdJob.load(sid, tmp_path)
    assert prior.restart_snapshot and prior.slurm_job_id is None
    assert prior.parent_job_id == j.job_id
    assert prior.package_dir(tmp_path) != j.package_dir(tmp_path)
    assert prior.remote_scratch_dir == evidence["remote_directory"]
    assert control.snapshot_job(j, event, evidence, tmp_path) == sid


def test_rollback_trims_overlap_and_preserves_original_bytes(tmp_path):
    p = package(tmp_path)
    write_checkpoint(p, 15000)
    original = dcd(4) + b"partial final write"
    (p / "output/s.dcd").write_bytes(original)
    ident = node.begin(p)
    node.prepare(p, "s", "s", 50000)
    repaired = (p / "output/s.dcd").read_bytes()
    assert struct.unpack_from("<i", repaired, 8)[0] == 3
    assert struct.unpack_from("<i", repaired, 20)[0] == 15000
    assert (p / "output/attempts" / ident / "s/s.dcd.original").read_bytes() == original


def test_legacy_snapshot_is_validated_and_survives_backup_replacement(tmp_path):
    p = package(tmp_path)
    original = dcd(4)
    (p / "output/s.dcd.BAK").write_bytes(original)
    evidence = node.inspect_legacy(p, "legacy-123-r1")
    assert evidence["records"][0]["step"] == 20000
    saved = Path(evidence["records"][0]["path"])
    # NAMD backs up by renaming the next trajectory over .BAK.
    replacement = p / "output/next.dcd"
    replacement.write_bytes(dcd(2))
    replacement.replace(p / "output/s.dcd.BAK")
    assert saved.read_bytes() == original
    assert node.inspect_legacy(p, "legacy-123-r1") == evidence


def test_generated_batch_restarts_from_checkpoint_without_nadoc(tmp_path, monkeypatch):
    import subprocess
    from dataclasses import replace
    from backend.core import cluster_config, slurm_script, remote_resume_conf

    p = package(tmp_path)
    write_checkpoint(p)
    (p / "output/s.dcd").write_bytes(dcd(4))
    (p / "output/min.coor").write_bytes(b"completed")
    fake = p / "fake_namd"
    fake.write_text('#!/bin/bash\ncp "${@: -1}" invoked.conf\ntouch output/s.coor\n')
    fake.chmod(0o755)
    for module, name in [
        (node, "nadoc_alpine_restart.py"),
        (remote_resume_conf, "nadoc_resume_conf.py"),
    ]:
        (p / name).write_text(Path(module.__file__).read_text())
    profile = replace(cluster_config.alpine_profile(), gpu_namd_bin=str(fake))
    script = slurm_script.generate_sbatch(
        dict(
            name_stem="s",
            minimization={"name": "min"},
            segments=[{"name": "s", "steps": 50000}],
        ),
        profile,
        dict(
            partition="ah200",
            cores=1,
            gpus=1,
            walltime="01:00:00",
            mem_gb=4,
            qos="gpu-normal",
        ),
        str(p),
    )
    # Execute startup journaling and the real emitted ladder; omit environment modules.
    assert script.index("nadoc_alpine_restart.py begin") < script.index(
        "# NADOC MD ladder:"
    )
    body = (
        "python3 nadoc_alpine_restart.py begin\n"
        + script[script.index("# NADOC MD ladder:") :]
    )
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("SLURM_RESTART_COUNT", "1")
    result = subprocess.run(
        ["bash", "-ec", body], cwd=p, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "firsttimestep      20000" in (p / "invoked.conf").read_text()
    assert "run                30000" in (p / "invoked.conf").read_text()


def test_legacy_tcl_guard_resumes_without_changing_open_config(tmp_path, monkeypatch):
    import shutil
    if shutil.which("tclsh") is None:
        pytest.skip("Tcl execution oracle requires tclsh; Python force oracles run separately")
    import subprocess
    from backend.core import remote_resume_conf

    p = package(tmp_path)
    write_checkpoint(p)
    (p / "output/s.dcd").write_bytes(dcd(4))
    for module, name in [
        (node, "nadoc_alpine_restart.py"),
        (remote_resume_conf, "nadoc_resume_conf.py"),
    ]:
        (p / name).write_text(Path(module.__file__).read_text())
    with (p / "s.conf").open() as existing_reader:
        original = existing_reader.read()
        existing_reader.seek(0)
        node.install_guard(p, "s")
        assert existing_reader.read() == original
    assert node.install_guard(p, "s")["already_installed"]
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("SLURM_RESTART_COUNT", "2")
    # Tcl runs the real wrapper and staged Python; NAMD directives are recorded,
    # not executed as molecular dynamics.
    tcl = "proc unknown {args} {puts $args}\nsource s.conf\n"
    result = subprocess.run(["tclsh"], input=tcl, cwd=p, text=True, capture_output=True)
    assert result.returncode == 0 and not result.stderr, result.stderr
    assert "firsttimestep 20000" in result.stdout
    assert "run 30000" in result.stdout
    assert "binCoordinates output/attempts/" in result.stdout


def test_regression_is_not_inferred_from_stale_metrics_or_a_new_segment(tmp_path):
    j = job(tmp_path)
    j.slurm_job_id = "123"
    old = dict(segment="prod", step=20000, collected_at=100)
    control.note_progress_regression(
        j, old, dict(segment="prod", step=10000, collected_at=90)
    )
    control.note_progress_regression(
        j, old, dict(segment="next", step=10000, collected_at=110)
    )
    assert not j.restart_events
    control.note_progress_regression(
        j, old, dict(segment="prod", step=10000, collected_at=110)
    )
    assert j.restart_events[0]["mode"] == "unknown"
    control.record_events(j, {}, dict(slurm_job_id="123", restart_count=1))
    assert len(j.restart_events) == 1
    assert j.restart_events[0]["id"] == "123-r1"


def test_preserved_attempt_files_are_downloaded_only_by_their_owner(tmp_path):
    j = job(tmp_path)
    j.remote_scratch_dir = "/scratch/test"
    j.restart_events = [
        dict(
            preserved_job_id="prior",
            evidence=dict(
                remote_directory="/scratch/test/output/attempts/legacy-123-r1",
                records=[dict(segment="s")],
            ),
        )
    ]
    inventory = {
        "output/s.dcd": 10,
        "output/s.dcd.BAK": 20,
        "output/attempts/legacy-123-r1/output/s.dcd": 20,
        "output/s.restart.coor": 30,
    }
    assert control.owned_inventory(j, inventory) == {
        "output/s.dcd": 10,
        "output/s.restart.coor": 30,
    }


def test_staged_helper_is_python36_compatible_and_health_follows_latest_piece(tmp_path):
    import ast

    ast.parse(Path(node.__file__).read_text(), feature_version=(3, 6))
    p = package(tmp_path)
    (p / "output/s.cont2.dcd").write_bytes(dcd(1))
    (p / "output/s.cont10.dcd").write_bytes(dcd(1))
    assert node.latest_dcd(p, "s").endswith("s.cont10.dcd")


def test_progress_in_later_stages_does_not_reopen_acknowledged_restart(tmp_path):
    j = job(tmp_path)
    attempt = dict(
        id="a1",
        slurm_job_id="123",
        restart_count=1,
        segments=[dict(mode="continued", checkpoint_step=20000)],
    )
    control.record_events(j, {"attempts": [attempt]}, None)
    revision = j.restart_events[0]["revision"]
    control.acknowledge(j, [dict(id="123-r1", revision=revision)], tmp_path)
    attempt["segments"].append(dict(mode="fresh", segment="next"))
    assert not control.record_events(j, {"attempts": [attempt]}, None)
    assert j.restart_events[0]["acknowledged_at"]


def test_acknowledgment_endpoint_is_mounted_and_rejects_changed_revision(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_cluster import router
    from backend.api import routes_md

    j = job(tmp_path)
    control.record_events(j, {}, dict(slurm_job_id="123", restart_count=1))
    j.save(tmp_path)
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    url = "/api/md/jobs/abc/restart-acknowledgment"
    assert (
        client.post(
            url, json={"events": [{"id": "123-r1", "revision": 99}]}
        ).status_code
        == 409
    )
    response = client.post(url, json={"events": [{"id": "123-r1", "revision": 1}]})
    assert response.status_code == 200
    assert MdJob.load("abc", tmp_path).restart_events[0]["acknowledged_at"]
    assert MdJob.load("abc", tmp_path).status == MdStatus.running


def test_rollback_excludes_a_piece_entirely_after_checkpoint(tmp_path):
    p = package(tmp_path)
    write_checkpoint(p, 15000)
    (p / "output/s.dcd").write_bytes(dcd(3))
    (p / "output/s.cont1.dcd").write_bytes(dcd(1, 20000))
    ident = node.begin(p)
    node.prepare(p, "s", "s", 50000)
    assert not (p / "output/s.cont1.dcd").exists()
    assert (
        p / "output/attempts" / ident / "s/s.cont1.dcd.original"
    ).read_bytes() == dcd(1, 20000)


def test_manual_resume_of_guarded_config_resolves_original_physics(tmp_path):
    p = package(tmp_path)
    write_checkpoint(p, 50000)
    node.install_guard(p, "s")
    node.begin(p)
    name = node.prepare(p, "s", "s", 50000)
    text = (p / (name + ".conf")).read_text()
    assert "exec python3" not in text
    assert "constraints on" in text and "run 0" in text
