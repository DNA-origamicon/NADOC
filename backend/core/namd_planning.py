"""Shared planning inputs for local, SLURM and Runpod resource previews.

Memory is an admission allowance. Timing remains a hardware-specific estimate;
memory qualification never certifies throughput or an economic upper bound.
"""

import math
from pathlib import Path
import shlex
from functools import lru_cache
import json
import hashlib
import struct

from pydantic import BaseModel, Field

from backend.core.namd_resources import (
    estimate_memory,
    health_memory_mib,
    preparation_memory_mib,
)


def timing_provenance_valid(proof):
    from backend.core.namd_allocation_model import QUALIFIED_ENGINE

    return bool(
        isinstance(proof, dict)
        and proof.get("engine_sha256") == QUALIFIED_ENGINE
        and proof.get("completed") is True
        and proof.get("outputs_verified") is True
        and proof.get("gpu")
        and proof.get("driver")
        and proof.get("configuration_sha256")
    )


def qualified_job_timing(package, manifest):
    """Newest clean stage with launch identity and intact final outputs, or None.

    Callers also require successful parent completion. Never recover provenance
    from the currently installed binary or from an unrelated metrics stream.
    """
    from backend.core.namd_script import log_completed
    from backend.core.namd_metrics import benchmark_ns_per_day
    from backend.core.namd_resources import psf_atoms

    package = Path(package)
    names = {s["name"] for s in manifest.get("segments", []) if s.get("name")}
    logs = [p for p in package.glob("*.log") if p.stem.split(".resume")[0] in names]
    for log in sorted(
        logs,
        key=lambda p: ("production" in p.stem.lower(), p.stat().st_mtime),
        reverse=True,
    ):
        try:
            receipt = json.loads(log.with_suffix(".resources.json").read_text())
            conf = package / Path(receipt["configuration"]["path"]).name
            if receipt.get("errors") or receipt.get("missing_provenance"):
                continue
            content = conf.read_bytes()
            if hashlib.sha256(content).hexdigest() != receipt["configuration"][
                "sha256"
            ] or not log_completed(log):
                continue
            opts = {
                s[0].lower(): " ".join(s[1:])
                for line in content.decode().splitlines()
                if len(s := shlex.split(line, comments=True)) >= 2
            }
            final_step = int(opts.get("firsttimestep", 0)) + int(opts["run"])
            atoms = psf_atoms(package / opts["structure"])
            base = package / opts["outputname"]
            xsc = [
                l.split()
                for l in Path(str(base) + ".xsc").read_text().splitlines()
                if l.strip() and not l.startswith("#")
            ]
            if int(xsc[-1][0]) != final_step:
                continue
            for ext in ("coor", "vel"):
                path = Path(str(base) + "." + ext)
                with path.open("rb") as stream:
                    if struct.unpack("i", stream.read(4))[0] != atoms:
                        raise ValueError("Output atom mismatch")
                if path.stat().st_size != 4 + atoms * 24:
                    raise ValueError("Incomplete output")
            proof = dict(
                engine_sha256=receipt["engine"]["sha256"],
                configuration_sha256=receipt["configuration"]["sha256"],
                gpu=receipt["gpu"]["name"],
                driver=receipt["gpu"]["driver"],
                threads=receipt.get("threads"),
                completed=True,
                outputs_verified=True,
            )
            if not timing_provenance_valid(proof):
                continue
            rate = benchmark_ns_per_day(log)
            dt = float(opts["timestep"])
            from backend.core.namd_timing import sustained_timing
            sustained = sustained_timing(log)
            if sustained and dt > 0:
                rate = dt * .0864 / sustained["seconds_per_step"]
            if rate and rate > 0 and dt > 0:
                return dict(
                    ns_per_day=rate,
                    timestep_fs=dt,
                    segment=log.stem,
                    n_atoms=atoms,
                    gpu_resident=opts.get("gpuresident", "off").lower()
                    in ("on", "yes", "1", "true"),
                    provenance=proof,
                    sustained_timing=sustained,
                )
        except (OSError, ValueError, KeyError, TypeError, IndexError, struct.error):
            continue
    return None


class PlanningStage(BaseModel):
    role: str | None = None
    steps: int = Field(0, ge=0)
    ns: float = Field(0, ge=0, allow_inf_nan=False)
    timestep_fs: float = Field(4, gt=0, allow_inf_nan=False)
    dcd_freq: int = Field(0, ge=0)
    gpu_resident: bool | None = None
    pairlistdist: float = Field(13.5, gt=0, allow_inf_nan=False)
    pmegridspacing: float = Field(1.5, gt=0, allow_inf_nan=False)
    margin: float = Field(3, ge=0, allow_inf_nan=False)
    extra_bonds: int = Field(2_600_000, ge=0)


def stage_dicts(stages):
    return [
        s.model_dump() if isinstance(s, BaseModel) else dict(s) for s in (stages or [])
    ]


def stage_resident(stage, default=True):
    if stage.get("role") == "minimization":
        return False
    return default if stage.get("gpu_resident") is None else bool(stage["gpu_resident"])


def memory_plan(n_atoms, *, stages=None, box_nm=None, resident=True, threads=16):
    """Stage maxima with one concurrent compact health check, never summed stages."""
    rows = []
    for stage in stage_dicts(stages) or [dict(extra_bonds=2_600_000)]:
        mode = stage_resident(stage, resident)
        estimate = estimate_memory(
            n_atoms,
            gpu_resident=mode,
            extra_bonds=stage.get("extra_bonds", 2_600_000),
            pairlist=stage.get("pairlistdist", 13.5),
            pme_spacing=stage.get("pmegridspacing", 1.5),
            margin=stage.get("margin", 3),
            box_angstrom=tuple(v * 10 for v in box_nm) if box_nm else None,
            threads=threads,
            check_patch=False,
        )
        rows.append(estimate.as_dict())
    if any(r["ram_mib"] <= 0 or r["gpu_mib"] <= 0 for r in rows):
        raise ValueError("Cannot calculate memory from invalid resource settings")
    if any(
        "box dimensions required for finer PME grid" in r["limitations"] for r in rows
    ):
        raise ValueError("Box dimensions are required to estimate a fine PME grid")
    health = health_memory_mib(n_atoms)
    return dict(
        basis=rows[0]["basis"],
        estimate_kind="admission_allowance",
        confidence=None,
        engine_ram_mib=max(r["ram_mib"] for r in rows),
        gpu_mib=max(r["gpu_mib"] for r in rows),
        health_ram_mib=health,
        workflow_ram_mib=max(r["ram_mib"] for r in rows) + health,
        preparation_ram_mib=preparation_memory_mib(n_atoms),
        expected_peak_ram_mib=None,
        expected_peak_gpu_mib=None,
        in_measured_domain=all(r["supported"] for r in rows),
        limitations=sorted({s for r in rows for s in r["limitations"]}),
        qualification="Planning allowance; exact prepared configuration and target engine/device still require launch preflight.",
    )


def phase_work(
    stages,
    *,
    relax_ns=0,
    production_ns=0,
    relax_timestep_fs=4,
    production_timestep_fs=4,
    resident=True,
):
    """Exact planned step counts; add intended production only when no stage exists."""
    rows = stage_dicts(stages)
    # Older clients supplied only disk-output fields. Do not treat their
    # production steps as relaxation and then add production a second time.
    if not rows or not any(s.get("role") for s in rows):
        return [
            dict(
                role=role,
                steps=ns * 1e6 / dt,
                ns=ns,
                timestep_fs=dt,
                gpu_resident=resident,
            )
            for role, ns, dt in [
                ("relaxation", relax_ns, relax_timestep_fs),
                ("production", production_ns, production_timestep_fs),
            ]
            if ns > 0
        ]
    if production_ns > 0 and not any(
        s.get("role") == "production" and s.get("steps", 0) > 0 for s in rows
    ):
        rows.append(
            dict(
                role="production",
                steps=production_ns * 1e6 / production_timestep_fs,
                ns=production_ns,
                timestep_fs=production_timestep_fs,
                gpu_resident=resident,
            )
        )
    return rows


def work_hours(stages, milliseconds_per_step, *, resident=True):
    """Sum per-stage work. Caller supplies the target hardware's rate function."""
    totals = {"relaxation": 0.0, "production": 0.0}
    for stage in stage_dicts(stages):
        if stage.get("steps", 0) <= 0:
            continue
        key = "production" if stage.get("role") == "production" else "relaxation"
        rate = milliseconds_per_step(stage_resident(stage, resident))
        if rate is None or not math.isfinite(rate) or rate <= 0:
            return None
        totals[key] += stage["steps"] * rate / 3_600_000
    return totals


@lru_cache(maxsize=128)
def _bond_count(path, size, mtime):
    with Path(path).open() as stream:
        return sum(line.split()[:1] == ["bond"] for line in stream)


def prepared_stages(package, manifest):
    """Read the actual emitted timestep/mode and measured restraint counts."""
    package = Path(package)
    rows = []
    minimum = manifest.get("minimization") or {}
    records = (
        [{**minimum, "role": "minimization"}] if minimum.get("name") else []
    ) + list(manifest.get("segments") or [])
    for record in records:
        name = record.get("name")
        path = package / f"{name}.conf"
        if not name or not path.exists():
            raise ValueError("Prepared stage configuration is unavailable")
        options = {}
        bond_files = []
        for line in path.read_text().splitlines():
            fields = shlex.split(line, comments=True)
            if len(fields) == 2:
                options[fields[0].lower()] = fields[1]
                if fields[0].lower() == "extrabondsfile":
                    bond_files.append(package / fields[1])
        role = (
            "minimization"
            if record.get("role") == "minimization"
            else "production"
            if "production" in name.lower()
            else "relaxation"
        )
        steps = int(
            options.get(
                "minimize" if role == "minimization" else "run", record.get("steps", 0)
            )
        )
        dt = float(options.get("timestep", record.get("timestep_fs") or 2))
        bond_count = 0
        if options.get("extrabonds", "off").lower() in ("on", "yes", "1", "true"):
            for path in bond_files:
                stat = path.stat()
                bond_count += _bond_count(str(path), stat.st_size, stat.st_mtime_ns)
        rows.append(
            dict(
                name=name,
                role=role,
                steps=steps,
                ns=0 if role == "minimization" else steps * dt / 1e6,
                timestep_fs=dt,
                dcd_freq=int(options.get("dcdfreq", 0)),
                gpu_resident=options.get("gpuresident", "off").lower()
                in ("on", "yes", "1", "true"),
                pairlistdist=float(options.get("pairlistdist", 13.5)),
                pmegridspacing=float(options.get("pmegridspacing", 1.5)),
                margin=float(options.get("margin", 3)),
                extra_bonds=bond_count,
            )
        )
    return rows
