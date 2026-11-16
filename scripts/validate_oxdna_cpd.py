"""Recorded CPD examples and real managed local oxDNA workflow validation."""

import argparse
import ctypes
import os
import select
import time
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.api.feature_recording import record_feature, record_minor
from backend.api.part_proof_commands import execute
from backend.api.state import _DesignSession
from backend.core.part_history_contract import create_empty_part
from backend.core.part_cpd_conversion import prepare
from scripts.agent_structure_guard import publish, audit


def example(
    *,
    name="CPD oxDNA validation",
    assign=True,
    isomer="cis-syn",
    sequence="GCGCGCTTGCGCGCGC",
):
    session = _DesignSession(design=create_empty_part(name, "HONEYCOMB"))

    def append(kind, params, label, major=False):
        params = {"_proof_version": 1, **params}
        recorder = record_feature if major else record_minor
        recorder(session, kind, label, params, lambda d: execute(kind, d, params))

    append(
        "helix-add",
        {
            "_helix_id": "38b9786d-4dcf-4a62-92a6-c90bc301961b",
            "axis_start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "axis_end": {"x": 0.0, "y": 0.0, "z": 5.44},
            "length_bp": 16,
            "phase_offset": 0.0,
        },
        "Add 16 bp helix",
    )
    if len(sequence) != 16:
        raise ValueError(
            "Validation duplex requires sixteen explicitly sequenced bases"
        )
    complement = sequence.translate(str.maketrans("ATCG", "TAGC"))[::-1]
    for direction, seq, start, end, identity, kind in (
        ("FORWARD", sequence, 0, 15, "cpd-forward", "scaffold"),
        ("REVERSE", complement, 15, 0, "cpd-reverse", "staple"),
    ):
        append(
            "strand-add",
            {
                "_strand_id": identity,
                "strand_type": kind,
                "sequence": seq,
                "domains": [
                    {
                        "helix_id": "38b9786d-4dcf-4a62-92a6-c90bc301961b",
                        "start_bp": start,
                        "end_bp": end,
                        "direction": direction,
                    }
                ],
            },
            "Add " + direction.lower() + " strand",
        )
    make = prepare
    if isomer != "cis-syn":
        from backend.core.part_cpd_conversion_isomers import prepare as prepare_isomer

        make = lambda keys, seed: prepare_isomer(keys, seed, isomer)
    params = make(
        [
            "38b9786d-4dcf-4a62-92a6-c90bc301961b:6:FORWARD",
            "38b9786d-4dcf-4a62-92a6-c90bc301961b:7:FORWARD",
        ],
        str(uuid5(NAMESPACE_URL, f"nadoc-cpd-oxdna-{isomer}-v1")),
    )
    if assign:
        append(
            "photoproduct-create", params, f"Assign {isomer} to the TT pair", major=True
        )
    return session.design


def main(output, production_steps, isomer="cis-syn"):
    from backend.api.headless_oxdna_build import (
        create_job,
        start_relaxation,
        append_production,
        read_relaxed_positions,
    )

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    design = example(name=f"{isomer} oxDNA validation", isomer=isomer)
    provenance = publish(design, output / f"{isomer}_duplex.nadoc")
    reopened = type(design).from_json((output / f"{isomer}_duplex.nadoc").read_text())
    provenance["reopened"] = audit(reopened)
    created = create_job(
        reopened,
        output,
        backend="CUDA",
        mc_steps=10000,
        md_relax_steps=1000000,
        equil_steps=100000,
        min_bp_retained=0.5,
        max_relax_retries=3,
    )
    job_id = created["job_id"]
    start_relaxation(job_id, output)
    job = wait_job(job_id, output)
    if job.status.value != "completed":
        raise RuntimeError(job.error)
    append_production(job_id, output, steps=production_steps)
    job = wait_job(job_id, output)
    display = read_relaxed_positions(job_id, output)
    result = {
        "provenance": provenance,
        "job_id": job.job_id,
        "status": job.status.value,
        "error": job.error,
        "production_steps": production_steps,
        "display_ready": display.get("ready"),
        "backend": job.backend,
        "stages": [s.__dict__ for s in job.stages],
    }
    (output / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if job.status.value != "completed" or not display.get("ready"):
        raise RuntimeError(job.error or "Completed trajectory was not readable")
    audit_outputs(job.job_id, output)


def audit_outputs(job_id, workspace):
    """Check every saved production row and permanent interaction input."""
    import numpy as np
    from backend.core.oxdna_job import OxdnaJob
    from backend.physics.oxdna_cpd import verify
    from backend.physics.oxdna_cpd_fit import distances

    workspace = Path(workspace).resolve()
    job = OxdnaJob.load(job_id, workspace)
    directory = job.job_dir(workspace)
    manifest = verify(directory)
    i, j = manifest["endpoints"][0]["particles"]
    pars = json.loads((directory / "cpd_model.json").read_text())["parameters"]
    count = int((directory / "topology.top").read_text().split()[0])
    outputs = []
    for stage in job.stages:
        if stage.kind != "production":
            continue
        stage_dir = directory / stage.name
        source = (stage_dir / "input.txt").read_text()
        assert "interaction_type = CpdDNA2" in source and "backend = CPU" in source
        assert "external_forces = true" not in source
        deviations, frame_count = [], 0
        with (stage_dir / "trajectory.dat").open() as stream:
            while header := stream.readline():
                assert header.startswith("t =")
                box = np.fromstring(stream.readline().split("=", 1)[1], sep=" ")
                assert stream.readline().startswith("E =")
                rows = np.array(
                    [list(map(float, stream.readline().split())) for _ in range(count)]
                )
                assert rows.shape == (count, 15) and np.isfinite(rows).all()
                a1, a3 = rows[:, 3:6], rows[:, 6:9]
                assert np.allclose(np.linalg.norm(a1, axis=1), 1, atol=1e-6)
                assert np.allclose(np.linalg.norm(a3, axis=1), 1, atol=1e-6)
                assert np.max(np.abs(np.sum(a1 * a3, axis=1))) < 1e-6
                r = np.stack((a1, np.cross(a3, a1), a3), axis=-1)
                delta = rows[j, :3] - rows[i, :3]
                delta -= np.rint(delta / box) * box
                d = distances(delta @ r[i], r[i].T @ r[j]) - pars["lengths"]
                deviations.append(float(np.sqrt(np.mean(d * d))))
                frame_count += 1
        assert frame_count > 1
        assert np.isfinite(np.loadtxt(stage_dir / "energy.dat")).all()
        outputs.append(
            {
                "stage": stage.name,
                "frames": frame_count,
                "all_rows_finite_and_orthonormal": True,
                "spring_distance_rms_nm_mean": float(np.mean(deviations) * 0.8518),
                "spring_distance_rms_nm_max": float(np.max(deviations) * 0.8518),
            }
        )
    assert outputs
    report = {
        "job_id": job_id,
        "permanent_interaction_verified": True,
        "production": outputs,
    }
    (directory / "cpd_output_audit.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def continue_job(job_id, workspace, steps):
    """Exercise the Dynamics Full Sim child, separately from append-production."""
    import asyncio
    from backend.api.headless_oxdna_build import (
        _use_workspace,
        _scratch_job_design,
        start_relaxation,
        read_relaxed_positions,
    )
    from backend.api.routes_oxdna import append_oxdna_run, RunRequest

    workspace = Path(workspace).resolve()
    with _use_workspace(workspace), _scratch_job_design(job_id, workspace):
        child = asyncio.run(append_oxdna_run(job_id, RunRequest(steps=steps)))
    start_relaxation(child["job_id"], workspace)
    job = wait_job(child["job_id"], workspace)
    display = read_relaxed_positions(job.job_id, workspace)
    result = {
        "parent_job_id": job_id,
        "job_id": job.job_id,
        "status": job.status.value,
        "error": job.error,
        "display_ready": display.get("ready"),
        "backend": job.backend,
        "production_steps": steps,
    }
    (workspace / "continuation_validation.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))
    if job.status.value != "completed" or not display.get("ready"):
        raise RuntimeError(job.error or "Continuation trajectory was not readable")
    audit_outputs(job.job_id, workspace)
    return result


def wait_job(job_id, workspace):
    """Wait on filesystem completion events, without status polling."""
    from backend.core.oxdna_job import OxdnaJob

    job = OxdnaJob.load(job_id, workspace)
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1")
    try:
        if (
            libc.inotify_add_watch(
                descriptor, str(job.job_dir(workspace)).encode(), 0x8 | 0x80
            )
            < 0
        ):
            raise OSError(ctypes.get_errno(), "inotify_add_watch")
        deadline = time.monotonic() + 3600
        while True:
            job = OxdnaJob.load(job_id, workspace)
            if job.status.value in {"completed", "failed", "stopped"}:
                return job
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Managed CPD job did not complete within its validation deadline"
                )
            if select.select([descriptor], [], [], min(60, remaining))[0]:
                os.read(descriptor, 65536)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--production-steps", type=int, default=1_000_000)
    parser.add_argument("--continue-job")
    parser.add_argument(
        "--isomer",
        choices=["cis-syn", "cis-anti-I", "trans-syn-I", "trans-syn-II"],
        default="cis-syn",
    )
    args = parser.parse_args()
    if args.continue_job:
        continue_job(args.continue_job, args.output, args.production_steps)
    else:
        main(args.output, args.production_steps, args.isomer)
