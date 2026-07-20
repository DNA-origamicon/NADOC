"""
BLADE Job — persistent model for a managed BLADE implicit-solvent relax run.

BLADE = **b**ox-free **l**earned **a**tomistic **D**NA **e**ngine: a CHARMM36 + OBC2
implicit-solvent atomistic propagator with NO periodic box and NO explicit water, plus an
optional learned solvent correction (``correction="unified"`` — the unified duplex+ssDNA
ForceNet).  See ``memory/project_atomistic_propagator.md`` for the science and
``memory/project_blade_frontend.md`` for this tab's build plan.

Jobs live in ``workspace/blade_jobs/{job_id}/job.json`` and survive server restarts.

Unlike CanDo/SNUPI (pure in-process scipy solves), a BLADE job's compute is **OpenMM in the
micromamba ``gpu`` environment** — openmm/parmed are NOT installed in the uv backend env.  So
a job is a DETACHED subprocess (``backend.core.blade_worker``, ``start_new_session=True``)
which in turn shells into the gpu-env interpreter to run
``backend/ml/propagator/blade_relax_gpu.py``.  Liveness is the persisted ``pid``
(``os.kill(pid, 0)``), so a run survives a ``uvicorn --reload``.

MVP mode is ``relax`` only: idealized geometric coords → minimize + short Langevin →
relaxed solute PDB + a relaxation trajectory (DCD) for in-app playback.  ``seed_namd``
(relax → solvate → NAMD equilibration) is reserved but not yet implemented.

Architecture note: relaxed coordinates are **Physical-layer / display state only**.  They are
read back for trajectory display but are NEVER written into Design topology.  See CLAUDE.md
Three-Layer Law.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from enum import Enum
from pathlib import Path
from typing import Optional


class BladeStatus(str, Enum):
    queued    = "queued"
    preparing = "preparing"   # writing the design snapshot + building solute PDB/PSF
    running   = "running"     # OpenMM minimize + Langevin
    failed    = "failed"
    stopped   = "stopped"     # manually stopped
    completed = "completed"   # relax done + trajectory cached


@dataclass
class BladeStageStatus:
    name:       str          # "build" | "relax"
    status:     str = "pending"   # pending / running / done / failed
    started_at: Optional[float] = None   # wall time the stage began (for the ETA bar)


@dataclass
class BladeJob:
    job_id:              str
    design_name:         str
    status:              BladeStatus
    created_at:          float
    n_nucleotides:       int = 0
    # ── Mode ───────────────────────────────────────────────────────────────────
    # "relax" = the shipped MVP (implicit-solvent relax + trajectory).  "seed_namd" is
    # reserved for the relax→solvate→NAMD equilibration leg (not yet implemented).
    mode:                str = "relax"
    # Force model: "baseline" = pure CHARMM36+OBC2 (training-free); "unified" = baseline +
    # the learned unified duplex+ssDNA ForceNet solvent correction.
    correction:          str = "baseline"
    # ── Relax knobs (mode="relax") ─────────────────────────────────────────────
    minimize_iters:      int   = 400     # OpenMM L-BFGS minimization cap
    langevin_ps:         float = 3.0     # Langevin settling time (picoseconds)
    nb_cutoff_A:         float = 18.0    # CutoffNonPeriodic radius — keeps GBSA ~O(N)
    temp_K:              float = 300.0
    traj_frames:         int   = 60      # DCD frames captured across the Langevin leg
    # Compute platform requested of OpenMM.  "CUDA" ties up the local card; the worker
    # falls back to CPU (and records it in platform_used) if CUDA is unavailable.
    platform:            str = "CUDA"
    # Per-atom uncertainty overlay: run the EnsembleForceNet over the captured frames and
    # cache a per-atom scalar for the display's uncertainty colouring.  Display-only.
    uncertainty:         bool = False
    stages:              list[BladeStageStatus] = dc_field(default_factory=list)
    error:               Optional[str] = None
    # PID of the detached worker (backend.core.blade_worker) — see module docstring.
    pid:                 Optional[int] = None
    design_source_path:  Optional[str] = None
    doc_id:              Optional[str] = None
    # Populated on completion — surfaced in the panel detail block.
    sim_seconds:         Optional[float] = None   # wall time inside the relax
    n_atoms:             Optional[int]   = None   # solute atom count
    platform_used:       Optional[str]   = None   # "CUDA" or "CPU" (fallback tell)
    rmsd_moved_A:        Optional[float] = None   # how far the structure travelled
    rg_before_A:         Optional[float] = None
    rg_after_A:          Optional[float] = None
    # Out-of-date detection (design edited after the run); shares the oxDNA staleness
    # fingerprint so an edit invalidates the displayed trajectory.
    design_fingerprint:  Optional[str] = None
    feature_log_position: Optional[int] = None
    # Archival parity with oxDNA/mrDNA/CanDo/SNUPI jobs (job_archive is kind-generic).
    archived:            bool = False
    archive_path:        Optional[str] = None

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        if self.archived and self.archive_path:
            return Path(self.archive_path)
        return workspace_dir / "blade_jobs" / self.job_id

    # ── Persistence (atomic write — runner saves while pollers read) ────────────

    def save(self, workspace_dir: Path) -> None:
        jd = self.job_dir(workspace_dir)
        jd.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["status"] = self.status.value
        tmp = jd / f"job.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, jd / "job.json")

    @classmethod
    def load(cls, job_id: str, workspace_dir: Path) -> "BladeJob":
        from backend.core.job_archive import resolve_job_json
        path = resolve_job_json(workspace_dir, "blade_jobs", job_id)
        data = json.loads(path.read_text())
        data["status"] = BladeStatus(data["status"])
        data["stages"] = [BladeStageStatus(**s) for s in data.get("stages", [])]
        data.setdefault("pid", None)
        data.setdefault("mode", "relax")
        data.setdefault("correction", "baseline")
        data.setdefault("minimize_iters", 400)
        data.setdefault("langevin_ps", 3.0)
        data.setdefault("nb_cutoff_A", 18.0)
        data.setdefault("temp_K", 300.0)
        data.setdefault("traj_frames", 60)
        data.setdefault("platform", "CUDA")
        data.setdefault("uncertainty", False)
        data.setdefault("design_source_path", None)
        data.setdefault("doc_id", None)
        data.setdefault("sim_seconds", None)
        data.setdefault("n_atoms", None)
        data.setdefault("platform_used", None)
        data.setdefault("rmsd_moved_A", None)
        data.setdefault("rg_before_A", None)
        data.setdefault("rg_after_A", None)
        data.setdefault("design_fingerprint", None)
        data.setdefault("feature_log_position", None)
        data.setdefault("archived", False)
        data.setdefault("archive_path", None)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["BladeJob"]:
        from backend.core.job_archive import archived_job_ids
        result: list[BladeJob] = []
        seen: set[str] = set()
        jobs_dir = workspace_dir / "blade_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        result.append(cls.load(jdir.name, workspace_dir))
                        seen.add(jdir.name)
                    except Exception:
                        pass
        for jid in archived_job_ids(workspace_dir, "blade_jobs"):
            if jid in seen:
                continue
            try:
                result.append(cls.load(jid, workspace_dir))
            except Exception:
                pass
        return result

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def new_blade_job(
    design_name: str,
    *,
    mode: str = "relax",
    correction: str = "baseline",
    minimize_iters: int = 400,
    langevin_ps: float = 3.0,
    nb_cutoff_A: float = 18.0,
    temp_K: float = 300.0,
    traj_frames: int = 60,
    platform: str = "CUDA",
    uncertainty: bool = False,
    n_nucleotides: int = 0,
    design_source_path: Optional[str] = None,
    design_fingerprint: Optional[str] = None,
    feature_log_position: Optional[int] = None,
    doc_id: Optional[str] = None,
) -> BladeJob:
    return BladeJob(
        job_id             = uuid.uuid4().hex[:12],
        design_name        = design_name,
        status             = BladeStatus.queued,
        created_at         = time.time(),
        n_nucleotides      = n_nucleotides,
        mode               = mode if mode in ("relax", "seed_namd") else "relax",
        correction         = correction if correction in ("baseline", "unified") else "baseline",
        minimize_iters     = minimize_iters,
        langevin_ps        = langevin_ps,
        nb_cutoff_A        = nb_cutoff_A,
        temp_K             = temp_K,
        traj_frames        = traj_frames,
        platform           = platform if platform in ("CUDA", "CPU") else "CUDA",
        uncertainty        = uncertainty,
        # Two stages: build the solute PDB/PSF in the uv env, then relax in the gpu env.
        stages             = [BladeStageStatus(name="build"), BladeStageStatus(name="relax")],
        design_source_path = design_source_path,
        design_fingerprint = design_fingerprint,
        feature_log_position = feature_log_position,
        doc_id             = doc_id,
    )
