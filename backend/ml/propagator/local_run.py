"""Run a SHORT explicit-solvent duplex MD locally on the GPU, capturing the full
microstate (positions + velocities + forces) as reference data for the propagator.

The stock ``prepare_propagator_reference`` ladder is a ~57 ns production workflow
(12 segments × 2.4M steps). That's the right thing for a real reference run but far
too long for a first local pilot, and there is no kwarg to shrink the production
chunks. So we prepare the full ladder (which does the careful solvate → minimize →
restraint-release plumbing correctly) and then **trim** it: re-emit each segment's
``.conf`` with a small step count, keeping the ladder's semantics intact (segment
order, soft-first, restraint scales, NPT flags, continuation pointers) and enabling
velocity/force capture only on the UNRESTRAINED production chunks — where the
equilibrated duplex actually fluctuates and where we want dense frames.

Split into ``prepare_local_reference`` (solvate + trim; ~minutes, validate cheaply
before spending GPU time) and ``run_prepared_job`` (the blocking GPU run — launch in
the background). ``run_local_reference`` chains both.

Real NAMD execution here is a legitimate *production compute* task, not the test
suite — it does not need a test-dedicated session. Never run ``just test``/``test-slow``.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional


def trim_ladder_for_pilot(
    package_dir: str | Path,
    name_stem: str,
    *,
    restrained_steps: int = 2000,
    production_steps: int = 6000,
    production_dcd_freq: int = 10,
    restrained_dcd_freq: Optional[int] = None,
) -> list:
    """Rewrite a prepared ladder's segment confs + manifest into a short pilot.

    Shrinks every segment's step count and turns on velocity/force capture on the
    unrestrained (``scale is None``) production chunks only, keeping intermediate
    (restrained) segments capture-free with ~1 frame so their DCDs stay tiny.
    Preserves all other ladder semantics. Returns the trimmed ``SegmentSpec`` list.
    """
    from backend.core.md_protocols import (  # noqa: PLC0415
        _round_up_to_cycle, _segment_conf, segments_from_manifest,
    )

    pkg = Path(package_dir)
    manifest_path = pkg / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    box = tuple(manifest["box_ang"])
    mgh = bool(manifest.get("mgh_extrabonds", False))
    _min_name, segments = segments_from_manifest(manifest_path)

    trimmed = []
    for spec in segments:
        unrestrained = spec.scale is None
        steps = _round_up_to_cycle(production_steps if unrestrained else restrained_steps)
        if unrestrained:
            freq = production_dcd_freq
        else:
            freq = restrained_dcd_freq if restrained_dcd_freq is not None else steps
        freq = max(1, min(freq, steps))
        s2 = dataclasses.replace(spec, steps=steps, dcd_freq=freq)
        trimmed.append(s2)
        conf = _segment_conf(
            s2, name_stem, box, mgh,
            fast=False, carved=False, structure_psf=None,
            anchors_file=None, field=None,
            capture_vel_force=unrestrained,
        )
        (pkg / f"{s2.name}.conf").write_text(conf)

    # Keep the manifest's per-segment steps/dcd_freq in sync so run_job's progress
    # accounting and segments_from_manifest agree with the confs on disk.
    by_name = {s.name: s for s in trimmed}
    for seg in manifest["segments"]:
        s2 = by_name.get(seg["name"])
        if s2 is not None:
            seg["steps"] = s2.steps
            seg["dcd_freq"] = s2.dcd_freq
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return trimmed


def prepare_local_reference(
    design,
    job_dir: str | Path,
    *,
    ion_conc_mM: float = 150.0,
    mg_conc_mM: float = 0.0,
    minimize_steps: int = 2400,
    restrained_steps: int = 2000,
    production_steps: int = 6000,
    production_dcd_freq: int = 10,
) -> tuple[str, str, list]:
    """Solvate the design + build the trimmed short-pilot ladder in ``job_dir``.

    Returns ``(package_subdir, name_stem, trimmed_segments)``. Runs GROMACS
    solvation + psfgen full topology (~1-3 min); does NOT run NAMD.
    """
    from backend.core.md_protocols import prepare_propagator_reference  # noqa: PLC0415

    job_dir = Path(job_dir)
    subdir, name_stem, _segments = prepare_propagator_reference(
        design, job_dir,
        ion_conc_mM=ion_conc_mM, mg_conc_mM=mg_conc_mM, salt_mode="custom",
        minimize_steps=minimize_steps,
    )
    trimmed = trim_ladder_for_pilot(
        job_dir / subdir, name_stem,
        restrained_steps=restrained_steps,
        production_steps=production_steps,
        production_dcd_freq=production_dcd_freq,
    )
    return subdir, name_stem, trimmed


def new_local_job(design_name: str = "propagator_pilot", *, devices: str = "0",
                  threads: int = 16):
    """A fresh local MdJob for the propagator-reference protocol."""
    from backend.core.md_job import new_job  # noqa: PLC0415
    return new_job(design_name, "propagator_reference", name_stem="pilot",
                   package_subdir="", threads=threads, devices=devices)


def attach_and_queue(job, workspace_dir: str | Path, subdir: str, name_stem: str,
                     segments: list) -> None:
    """Mirror routes_md's post-prep wiring: attach package + segments, queue, save."""
    from backend.core.md_job import MdSegmentStatus, MdStatus  # noqa: PLC0415
    job.package_subdir = subdir
    job.name_stem = name_stem
    job.segments = [
        MdSegmentStatus(name=s.name, stage=s.stage, percent=s.percent,
                        steps=s.steps, status="pending")
        for s in segments
    ]
    job.status = MdStatus.queued
    job.save(Path(workspace_dir))


def run_prepared_job(job_id: str, workspace_dir: str | Path):
    """Run an already-prepared+queued job's full ladder locally, blocking to done.

    Reloads the job, runs ``run_job`` (GPU pre-flight + minimization + every
    segment) to completion, and returns the reloaded (final-status) job.
    """
    import asyncio  # noqa: PLC0415

    from backend.core.md_job import MdJob  # noqa: PLC0415
    from backend.core.namd_runner import run_job  # noqa: PLC0415

    ws = Path(workspace_dir)
    job = MdJob.load(job_id, ws)
    asyncio.run(run_job(job, ws))
    return MdJob.load(job_id, ws)


def captured_outputs(job, workspace_dir: str | Path) -> dict:
    """Locate the captured trajectory files for a finished job.

    Returns ``{segment_name: {dcd, veldcd, forcedcd}}`` for segments that carry a
    velocity/force capture (the unrestrained production chunks)."""
    ws = Path(workspace_dir)
    out = job.package_dir(ws) / "output"
    result: dict[str, dict] = {}
    for seg in job.segments:
        vel = out / f"{seg.name}.veldcd"
        frc = out / f"{seg.name}.forcedcd"
        dcd = out / f"{seg.name}.dcd"
        if vel.exists() or frc.exists():
            result[seg.name] = {
                "dcd": str(dcd) if dcd.exists() else None,
                "veldcd": str(vel) if vel.exists() else None,
                "forcedcd": str(frc) if frc.exists() else None,
            }
    return result


def run_local_reference(design, workspace_dir: str | Path, *,
                        design_name: str = "propagator_pilot",
                        devices: str = "0", threads: int = 16,
                        **prep_kwargs):
    """Full local pilot: create job → prepare (solvate+trim) → run → return job."""
    ws = Path(workspace_dir)
    job = new_local_job(design_name, devices=devices, threads=threads)
    job.save(ws)
    subdir, name_stem, trimmed = prepare_local_reference(
        design, job.job_dir(ws), **prep_kwargs)
    attach_and_queue(job, ws, subdir, name_stem, trimmed)
    return run_prepared_job(job.job_id, ws)
