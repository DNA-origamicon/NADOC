"""Managed bare-gold qualification jobs using the ordinary process/status machinery.

The UI can list retained jobs. New preparation is a Python/CLI API until physical
qualification supports exposing material controls. No production promotion occurs.
"""

import asyncio
import json
from pathlib import Path

import numpy as np

from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.namd_gold_package import build_package, config, verify_package, sha

PROTOCOL = "gold_qualification_v1"


def _write_manifest(package, manifest):
    text = json.dumps(manifest, indent=2)+"\n"
    for name in ("manifest.json", "nadoc_md_run.json"):
        tmp = package/(name+".gold.tmp")
        tmp.write_text(text)
        tmp.replace(package/name)


def prepare_job(workspace, geometry, *, design_name="Gold interface qualification",
                steps=10000, timestep_fs=1., **options):
    """Create a normal MdJob without changing any DNA document or launching compute."""
    if type(steps) is not int or not 10 <= steps <= 100000 or steps % 10:
        raise ValueError("Managed gold qualification accepts 10..100000 steps in multiples of 10")
    if timestep_fs not in (.5, 1., 2.):
        raise ValueError("Gold qualification timestep must be 0.5, 1 or 2 fs")
    workspace = Path(workspace)
    job = new_job(design_name, PROTOCOL, "system", "package", threads=2,
                  devices="0", run_kind="qualification")
    package = job.package_dir(workspace)
    manifest = build_package(package, geometry, **options)
    job.prep_params = {"gold_geometry": geometry, "gold_model_id": manifest["gold_model"]["id"],
                       "steps": steps, "timestep_fs": timestep_fs, **options}
    manifest.update(name="system", protocol=PROTOCOL, qualification_only=True,
                    minimization={"name": "minimize", "stage": "Minimization", "steps": 200, "percent": 100},
                    segments=[])
    (package/"minimize.conf").write_text(config(manifest, minimize=200, steps=0, prefix="minimize"))
    manifest["minimization"]["config_sha256"] = sha(package/"minimize.conf")
    job.minimization = MdSegmentStatus("minimize", "Minimization", 100, 200)
    _add_segment(package, manifest, job, steps, timestep_fs, "minimize", 200)
    _write_manifest(package, manifest)
    job.save(workspace)
    return job


def _add_segment(package, manifest, job, steps, dt, previous, first_step):
    name = f"gold_{len(job.segments)+1:03d}"
    row = dict(name=name, stage="Gold qualification", percent=100., steps=steps,
               temp=manifest["temperature_K"], damping=1., scale=1., npt=False,
               previous=previous, reinit=False, dcd_freq=100, timestep_fs=dt,
               first_step=first_step)
    text = config(manifest, prefix=name, restart=previous, first_step=first_step, steps=steps, timestep_fs=dt)
    (package/f"{name}.conf").write_text(text)
    row["config_sha256"] = sha(package/f"{name}.conf")
    manifest["segments"].append(row)
    job.segments.append(MdSegmentStatus(name, row["stage"], 100, steps))


def checkpoint(package, prefix, n_atoms):
    """Verify binary checkpoint integrity; native exit status alone is insufficient."""
    for suffix in ("coor", "vel"):
        data = (package/"output"/f"{prefix}.{suffix}").read_bytes()
        if (len(data) != 4+24*n_atoms or int.from_bytes(data[:4], "little") != n_atoms
                or not np.isfinite(np.frombuffer(data[4:], dtype="<f8")).all()):
            raise ValueError(f"Gold checkpoint invalid/nonfinite: {prefix}.{suffix}")
    xsc = (package/"output"/f"{prefix}.xsc").read_text()
    return int(next(r.split()[0] for r in xsc.splitlines() if r.strip() and not r.startswith("#")))


def extend_job(job_id, workspace, *, steps=10000):
    """Continue a completed qualification, preserving previous outputs and atom order."""
    if type(steps) is not int or not 10 <= steps <= 100000 or steps % 10:
        raise ValueError("Gold continuation requires 10..100000 steps in multiples of 10")
    workspace = Path(workspace)
    job = MdJob.load(job_id, workspace)
    if job.protocol != PROTOCOL or job.status != MdStatus.completed:
        raise ValueError("Only a completed gold qualification can be extended")
    package = job.package_dir(workspace)
    m = verify_package(package)
    previous = m["segments"][-1]
    first = checkpoint(package, previous["name"], m["n_atoms"])
    _add_segment(package, m, job, steps, previous["timestep_fs"], previous["name"], first)
    _write_manifest(package, m)
    job.status = MdStatus.queued
    job.current_segment_idx = len(job.segments)-1
    job.save(workspace)
    return job


async def run_job(job, workspace):
    """Use NAMD's shared cancellable subprocess; reject fallback/remote execution."""
    from backend.core.namd_runner import _run_namd_async, find_namd

    package = job.package_dir(workspace)
    try:
        if job.devices != "0" or job.execution_target != "local":
            raise ValueError("Gold qualification currently requires local GPU 0; remote target qualification is pending")
        binary = find_namd()
        m = verify_package(package, binary)
        m["runtime_engine_sha256"] = sha(binary)
        _write_manifest(package, m)
        items = [(job.minimization, 200)] + [(s, r["first_step"]+r["steps"])
                                             for s, r in zip(job.segments, m["segments"])]
        job.status = MdStatus.running
        job.save(workspace)
        for index, (segment, expected_step) in enumerate(items):
            if segment.status == "done":
                if checkpoint(package, segment.name, m["n_atoms"]) != expected_step:
                    raise ValueError("Completed gold checkpoint has the wrong step")
                continue
            if index:
                row = m["segments"][index-1]
                if sha(package/f"{segment.name}.conf") != row["config_sha256"]:
                    raise ValueError("Gold configuration differs from prepared manifest")
                checkpoint(package, row["previous"], m["n_atoms"])
            elif sha(package/"minimize.conf") != m["minimization"]["config_sha256"]:
                raise ValueError("Gold minimization configuration differs from prepared manifest")
            log = package/f"{segment.name}.log"
            if log.exists():
                raise ValueError("Interrupted gold stage retained; partial-stage automatic restart is not yet qualified")
            segment.status = "running"
            job.current_segment_idx = max(0, index-1)
            job.save(workspace)

            def persist(pid):
                job.namd_pid = pid
                job.save(workspace)

            rc, _ = await _run_namd_async(binary, segment.name, package, log, job.threads,
                                          job.devices, job.job_id, on_spawn=persist)
            text = log.read_text()
            if rc or "End of program" not in text or "Running with GPU-resident mode" not in text:
                raise ValueError(f"Gold native stage failed or lost resident mode: {segment.name}")
            if checkpoint(package, segment.name, m["n_atoms"]) != expected_step:
                raise ValueError("Gold checkpoint step mismatch")
            segment.status = "done"
            job.save(workspace)
        m["validation"]["runtime"] = "passed native resident/checkpoint integrity; physical validation pending"
        _write_manifest(package, m)
        job.status = MdStatus.completed
        job.error = None
    except asyncio.CancelledError:
        job.status = MdStatus.stopped
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        job.status = MdStatus.failed
        job.error = str(exc)
        job.failure_kind = "gold_qualification"
    finally:
        job.save(workspace)
