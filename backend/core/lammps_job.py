"""LAMMPS (CG-DNA) job — persistent model for a managed parallel-oxDNA run.

Sibling of ``oxdna_job.py`` but deliberately **lean**: a LAMMPS run is a single MD
run (no staged relaxation, health gates, auto-retries, staleness fingerprints, or
archival — those live on the oxDNA job and don't apply here yet).  Jobs live in
``workspace/lammps_jobs/{job_id}/job.json`` and survive server restarts.

Phase 3 of ``project_lammps_oxdna`` — the job-system + REST layer over the Phase-2
converter/runner.  Trajectory read-back into NADOC's viewers is a later phase, so a
job's user-visible result is its status/progress + the ``traj.lammpstrj`` on disk.

Layer: Physical only — positions LAMMPS produces are never written into topology.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class LammpsStatus(str, Enum):
    queued    = "queued"
    preparing = "preparing"   # writing data + input files
    running   = "running"
    failed    = "failed"
    stopped   = "stopped"     # manually stopped
    completed = "completed"


@dataclass
class LammpsJob:
    job_id:             str
    design_name:        str
    status:             LammpsStatus
    created_at:         float
    n_atoms:            int = 0
    n_bonds:            int = 0
    # run parameters (mirror lammps_interface.LammpsInputParams + MPI ranks)
    steps:              int   = 100_000
    dump_every:         int   = 1000
    temperature:        float = 0.1     # oxDNA reduced units (~300 K)
    salt_molar:         float = 0.5
    ranks:              int   = 1        # MPI ranks (>1 needs an MPI-enabled lmp)
    # live progress + result
    current_step:       int   = 0
    frames:             int   = 0
    error:              Optional[str] = None
    lammps_pid:         Optional[int] = None
    lammps_path:        Optional[str] = None
    design_source_path: Optional[str] = None
    parent_job_id:      Optional[str] = None
    # External-force metadata for a steered run (from resolve_lammps_forces): the
    # applied E-field / surface wall / anchor summary, so the row/detail can show what
    # was applied.  None for a plain (unforced) run.  Display-layer only.
    forces:             Optional[dict] = None

    # ── paths ──────────────────────────────────────────────────────────────────
    def job_dir(self, workspace_dir: Path) -> Path:
        return workspace_dir / "lammps_jobs" / self.job_id

    # ── persistence (atomic write, like OxdnaJob) ──────────────────────────────
    def save(self, workspace_dir: Path) -> None:
        jd = self.job_dir(workspace_dir)
        jd.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["status"] = self.status.value
        tmp = jd / f"job.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, jd / "job.json")

    @classmethod
    def load(cls, job_id: str, workspace_dir: Path) -> "LammpsJob":
        path = workspace_dir / "lammps_jobs" / job_id / "job.json"
        data = json.loads(path.read_text())
        data["status"] = LammpsStatus(data["status"])
        for k, v in (("parent_job_id", None), ("design_source_path", None),
                     ("lammps_path", None), ("lammps_pid", None), ("frames", 0),
                     ("current_step", 0), ("ranks", 1), ("forces", None)):
            data.setdefault(k, v)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["LammpsJob"]:
        out: list[LammpsJob] = []
        jobs_dir = workspace_dir / "lammps_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        out.append(cls.load(jdir.name, workspace_dir))
                    except Exception:  # noqa: BLE001
                        pass
        return out

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def new_lammps_job(
    design_name: str,
    *,
    n_atoms: int = 0,
    n_bonds: int = 0,
    steps: int = 100_000,
    dump_every: int = 1000,
    temperature: float = 0.1,
    salt_molar: float = 0.5,
    ranks: int = 1,
    design_source_path: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    forces: Optional[dict] = None,
) -> LammpsJob:
    return LammpsJob(
        job_id             = uuid.uuid4().hex[:12],
        design_name        = design_name,
        status             = LammpsStatus.queued,
        created_at         = time.time(),
        n_atoms            = n_atoms,
        n_bonds            = n_bonds,
        steps              = steps,
        dump_every         = dump_every,
        temperature        = temperature,
        salt_molar         = salt_molar,
        ranks              = ranks,
        design_source_path = design_source_path,
        parent_job_id      = parent_job_id,
        forces             = forces,
    )
