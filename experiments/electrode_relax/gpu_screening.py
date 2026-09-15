"""Retained, serial, user-requested screening through the ordinary NADOC start API."""

import argparse
import copy
import json
import re
import shutil
import time
import urllib.request
from pathlib import Path

from backend.core.md_job import MdJob, MdStatus, MdSegmentStatus, new_job

WS = Path("workspace").resolve()
SOURCE_ID = "2fb3c67ae5d9"


def set_key(text, key, value):
    pattern = r"(?mi)^" + re.escape(key) + r"\s+[^\n]+"
    return (
        re.sub(pattern, f"{key} {value}", text)
        if re.search(pattern, text)
        else f"{key} {value}\n" + text
    )


def prepare(source_id, dt, duration, seed, label, out, elapsed):
    source = MdJob.load(source_id, WS)
    origin = source.package_dir(WS)
    parent = json.loads((origin / "manifest.json").read_text())
    previous = parent["segments"][-1]["name"]
    job = new_job(
        label,
        "electrode_equilibration_namd",
        "system",
        "package/system_namd_solvated",
        threads=1,
        devices="0",
        design_source_path="2electrode_solvent_only.nadoc",
        namd_seed=seed,
        run_kind="validation",
        parent_job_id=source_id,
    )
    dest = job.package_dir(WS)
    shutil.copytree(
        origin,
        dest,
        ignore=shutil.ignore_patterns(
            "output", "*.log", "*.dcd", ".gpu_resident_probe.json"
        ),
    )
    shutil.copy2(source.job_dir(WS) / "design.json", job.job_dir(WS) / "design.json")
    (dest / "output").mkdir()
    # Both the seed and minimization slot point to the already relaxed checkpoint.
    for ext in ("coor", "vel", "xsc"):
        shutil.copy2(
            origin / "output" / f"{previous}.{ext}", dest / "output" / f"gpu_seed.{ext}"
        )
    if (dest / "electrode_forces.original.tcl").exists():
        shutil.copy2(
            dest / "electrode_forces.original.tcl", dest / "electrode_forces.tcl"
        )
    original = MdJob.load(SOURCE_ID, WS).package_dir(WS)
    base = (original / "system_validation_p3.conf").read_text()
    name = f"system_gpu_{job.job_id}_p100"
    text = base.replace("system_validation_p3", name).replace(
        "system_validation_p2", "gpu_seed"
    )
    values = dict(
        timestep=dt,
        run=round(duration * 1e6 / dt / 20) * 20,
        seed=seed,
        dcdFreq=round(2000 / dt),
        outputEnergies=round(2000 / dt),
        xstFreq=round(2000 / dt),
        restartfreq=round(20000 / dt),
        outputTiming=1000,
        fullElectFrequency=round(4 / dt),
    )
    for key, value in values.items():
        text = set_key(text, key, value)
    (dest / f"{name}.conf").write_text(text)
    # A probe-compatible seed config; the runner sees the complete existing checkpoint.
    (dest / "gpu_seed.conf").write_text(
        set_key(set_key(text.replace(name, "gpu_seed"), "GPUresident", "off"), "run", 0)
    )
    m = copy.deepcopy(parent)
    m.pop("electrode_gpu", None)
    m.pop("experimental_validation", None)
    row = copy.deepcopy(parent["segments"][-1])
    row.update(
        name=name,
        previous="gpu_seed",
        steps=values["run"],
        percent=100,
        timestep_fs=dt,
        dcd_freq=values["dcdFreq"],
        gentle=False,
        soft_start=False,
        stage=label,
        reinit=False,
    )
    m["segments"] = [row]
    m["minimization"] = {
        "name": "gpu_seed",
        "steps": 0,
        "stage": "Prepared checkpoint reuse",
    }
    m["package_dir"] = str(dest)
    m["early_stop_relax"] = False
    for key in (
        "relax_integrator",
        "fast_relaxation",
        "gpu_resident",
        "relax_protocol_settings",
    ):
        if isinstance(m.get(key), dict):
            m[key]["timestep_fs"] = dt
    if isinstance(m.get("relax_integrator"), dict):
        m["relax_integrator"].update(
            hmr=False, timestep_explicit=True, hmr_explicit=True
        )
    m["gpu_screening"] = dict(
        source_job=source_id,
        initial_source_job=SOURCE_ID,
        timestep_fs=dt,
        frame_interval_ps=2,
        full_electrostatics_interval_fs=4,
        seed=seed,
        start_time_ns=elapsed,
        duration_ns=duration,
        hmr_atoms=0,
        mass_policy="Rigid water retains ordinary masses; this solvent-only system has no nonwater hydrogens.",
    )
    for fn in ("manifest.json", "nadoc_md_run.json"):
        (dest / fn).write_text(json.dumps(m, indent=2) + "\n")
    job.minimization = MdSegmentStatus(
        "gpu_seed", "Prepared checkpoint reuse", 100, 0, status="done"
    )
    job.segments = [MdSegmentStatus(name, label, 100, values["run"])]
    job.prep_params = dict(
        protocol=job.protocol,
        gpu_resident_mode="on",
        gpu_fallback_policy="ask",
        relax_timestep_fs=dt,
        relax_rigid_bonds="all",
        relax_hmr=False,
        early_stop_relax=False,
        two_electrodes=source.prep_params.get("two_electrodes"),
        ion_conc_mM=300,
        mg_conc_mM=0,
    )
    job.status = MdStatus.stopped
    job.user_stopped = True
    job.early_stop_relax = False
    job.save(WS)
    return job, dict(
        job_id=job.job_id,
        package=str(dest),
        segment=name,
        start_time_ns=elapsed,
        duration_ns=duration,
        timestep_fs=dt,
        seed=seed,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--pilot-only", action="store_true")
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = (
        json.loads((out / "jobs.json").read_text())
        if (out / "jobs.json").exists()
        else []
    )
    # Separate stochastic streams, shared initial coordinates/velocities: not independently equilibrated replicas.
    cases = [("pilot", 4, 0.24, 431, SOURCE_ID, 0.0)]
    if not args.pilot_only:
        cases += [
            ("replica_a", 4, 1.2, 432, None, 0.24),
            ("replica_a", 4, 1.2, 433, None, 1.44),
            ("replica_a", 4, 1.2, 434, None, 2.64),
            ("replica_a", 4, 1.2, 435, None, 3.84),
            ("replica_b", 4, 1.2, 831, SOURCE_ID, 0.0),
            ("replica_b", 4, 1.2, 832, None, 1.2),
            ("replica_b", 4, 1.2, 833, None, 2.4),
            ("replica_b", 4, 1.2, 834, None, 3.6),
            ("control_2fs", 2, 1.2, 431, SOURCE_ID, 0.0),
        ]
    prior = SOURCE_ID
    for index, (label, dt, duration, seed, source, elapsed) in enumerate(cases):
        if index < len(records):
            rec = records[index]
            job = MdJob.load(rec["job_id"], WS)
            if rec.get("status"):
                if not rec.get("health", {}).get("confined"):
                    return
                prior = job.job_id
                continue
        else:
            job, rec = prepare(
                source or prior,
                dt,
                duration,
                seed,
                f"Debye GPU {dt} fs: {label} seed {seed}",
                out,
                elapsed,
            )
            rec["series"] = label
            records.append(rec)
        (out / "jobs.json").write_text(json.dumps(records, indent=2) + "\n")
        request = urllib.request.Request(
            f"http://127.0.0.1:8000/api/md/jobs/{job.job_id}/start",
            data=b"",
            method="POST",
        )
        print(
            "START",
            rec,
            json.load(urllib.request.urlopen(request, timeout=30)),
            flush=True,
        )
        started = time.time()
        while True:
            current = MdJob.load(job.job_id, WS)
            if current.status in (
                MdStatus.completed,
                MdStatus.failed,
                MdStatus.stopped,
                MdStatus.paused,
            ):
                break
            time.sleep(5)
        rec.update(
            status=current.status.value,
            error=current.error,
            wall_seconds=time.time() - started,
        )
        health_path=current.package_dir(WS)/'output'/f"{rec['segment']}.electrode-health.json"
        report=json.loads(health_path.read_text()) if health_path.exists() else {}
        native_log=(current.package_dir(WS)/f"{rec['segment']}.log").read_text() if current.segments[0].status=='done' else ''
        timing=re.findall(r'WallClock: ([\d.]+)',native_log)
        rec['native_wall_seconds']=float(timing[-1]) if timing else None
        rec["health"] = report
        (out / "jobs.json").write_text(json.dumps(records, indent=2) + "\n")
        print("FINISH", rec, flush=True)
        if (
            current.status in (MdStatus.stopped, MdStatus.paused)
            or not report.get("confined")
            or not report.get("bulk_reference_validated")
        ):
            print("HALTED: native/confinement/density/user gate", flush=True)
            break
        prior = job.job_id


if __name__ == "__main__":
    main()
