"""
SNUPI FEM Job — persistent model for a managed SNUPI shape-prediction run.

Sibling of ``cando_job.py``.  SNUPI is the SAME native FEM shape predictor as CanDo
(``backend.physics.fem_solver.predict_shape``), run with the anisotropic, sequence-
dependent SNUPI material law (``material="snupi"``: per-motif 6×6 stiffness + the
twist–stretch couplings + compliant crossover beams) instead of CanDo's isotropic rod.
Validated ≥ CanDo vs MD at $0 new MD (see ``memory/project_snupi_mimic.md``).

Jobs live in ``workspace/snupi_jobs/{job_id}/job.json`` and survive server restarts.

Like CanDo — and unlike oxDNA/mrDNA/NAMD — a SNUPI job is a PURE in-process Python
solve (scipy sparse), so there is no subprocess, no CUDA device, and no availability
probe.  The two "engines" are the two solver modes:

  • **Coarse** = the LINEAR solve (``nonlinear=False``) — seconds, interactive preview.
  • **Fine**   = the geometrically-NONLINEAR corotational solve (``nonlinear=True``) —
    ~1 min on a 6HB/210; the accurate shape.

``material`` selects the intra-helix beam constitutive law threaded into
``predict_shape``: "snupi" (default — the anisotropic SNUPI material) or "cando" (the
isotropic baseline, for an in-tab A/B comparison against the same solver).

Architecture note: FEM output is **Physical-layer / display state only**.  A job's
predicted positions are read back for display (deforming the NADOC model, flex/deviation
maps) but are NEVER written into Design topology.  See CLAUDE.md Three-Layer Law.
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


class SnupiStatus(str, Enum):
    queued    = "queued"
    preparing = "preparing"   # writing the design snapshot
    running   = "running"     # FEM solving
    failed    = "failed"
    stopped   = "stopped"     # manually stopped
    completed = "completed"   # solve done + positions/RMSF extracted


@dataclass
class SnupiStageStatus:
    name:       str          # "linear" (coarse) or "nonlinear" (fine)
    status:     str = "pending"   # pending / running / done / failed
    started_at: Optional[float] = None   # wall time the stage began (for the ETA bar)


@dataclass
class SnupiJob:
    job_id:              str
    design_name:         str
    status:              SnupiStatus
    created_at:          float
    n_nucleotides:       int = 0
    # Solver mode: nonlinear=True is the "Fine" corotational solve (default); nonlinear=False
    # is the fast "Coarse" linear preview.
    nonlinear:           bool = True
    n_steps:             int = 20     # corotational load-step count (nonlinear only)
    with_rmsf:           bool = True  # also compute the free-free NMA per-bp RMSF
    # Intra-helix beam material threaded into predict_shape: "snupi" (default) or "cando"
    # (isotropic baseline for an in-tab comparison).  Never a topology edit.
    material:            str = "snupi"
    # MgCl₂ molarity (mol/L) setting the Debye length of the inter-helix electrostatics (G12).
    # Default 0.02 = SNUPI's 20 mM buffer; raise to match a run's actual salt.  snupi-only.
    mgcl2_M:             float = 0.02
    # Langevin structural DYNAMICS (project_snupi_dynamics): instead of the static equilibrium
    # solve, run a thermal trajectory and report its time-MEAN shape + TRAJECTORY RMSF (same
    # display payload).  hydrodynamics=True uses the full Rotne–Prager–Yamakawa friction matrix
    # (coupled) vs the diagonal Stokes drag.  Physical-layer/display-only.
    dynamics:            bool = False
    hydrodynamics:       bool = False
    # ── Job-request annotations (C1/C2): anchors + uniform E-field, NEVER a topology edit ──
    # anchors: shared oxDNA scope descriptors (overhang/cluster/domain/strand/base) held fixed
    # (Dirichlet BC) during the FEM solve.  field: {"field_pN": <force/nt, pN>, "dir": [x,y,z]} —
    # the same per-nucleotide force oxDNA applies.  A field needs ≥1 anchor (COM drift).  Both are
    # threaded into predict_shape(...) (Three-Layer Law: display-only, read-only over the design).
    anchors:             Optional[list] = None
    field:               Optional[dict] = None
    stages:              list[SnupiStageStatus] = dc_field(default_factory=list)
    error:               Optional[str] = None
    design_source_path:  Optional[str] = None
    doc_id:              Optional[str] = None
    # Populated on completion — surfaced in the panel detail block.
    sim_seconds:         Optional[float] = None   # wall time inside predict_shape()
    n_nodes:             Optional[int]   = None   # duplex-core FEM nodes (= base pairs)
    rmsf_min_nm:         Optional[float] = None
    rmsf_max_nm:         Optional[float] = None
    # Out-of-date detection (design edited after the solve ran); shares the oxDNA
    # staleness fingerprint so an edit invalidates the predicted display.
    design_fingerprint:  Optional[str] = None
    feature_log_position: Optional[int] = None
    # Archival parity with oxDNA/mrDNA/CanDo jobs (job_archive is kind-generic).
    archived:            bool = False
    archive_path:        Optional[str] = None

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        if self.archived and self.archive_path:
            return Path(self.archive_path)
        return workspace_dir / "snupi_jobs" / self.job_id

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
    def load(cls, job_id: str, workspace_dir: Path) -> "SnupiJob":
        from backend.core.job_archive import resolve_job_json
        path = resolve_job_json(workspace_dir, "snupi_jobs", job_id)
        data = json.loads(path.read_text())
        data["status"] = SnupiStatus(data["status"])
        data["stages"] = [SnupiStageStatus(**s) for s in data.get("stages", [])]
        data.setdefault("nonlinear", True)
        data.setdefault("n_steps", 20)
        data.setdefault("with_rmsf", True)
        data.setdefault("material", "snupi")
        data.setdefault("mgcl2_M", 0.02)
        data.setdefault("dynamics", False)
        data.setdefault("hydrodynamics", False)
        data.setdefault("anchors", None)
        data.setdefault("field", None)
        data.setdefault("design_source_path", None)
        data.setdefault("doc_id", None)
        data.setdefault("sim_seconds", None)
        data.setdefault("n_nodes", None)
        data.setdefault("rmsf_min_nm", None)
        data.setdefault("rmsf_max_nm", None)
        data.setdefault("design_fingerprint", None)
        data.setdefault("feature_log_position", None)
        data.setdefault("archived", False)
        data.setdefault("archive_path", None)
        return cls(**data)

    @classmethod
    def list_jobs(cls, workspace_dir: Path) -> list["SnupiJob"]:
        from backend.core.job_archive import archived_job_ids
        result: list[SnupiJob] = []
        seen: set[str] = set()
        jobs_dir = workspace_dir / "snupi_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        result.append(cls.load(jdir.name, workspace_dir))
                        seen.add(jdir.name)
                    except Exception:
                        pass
        for jid in archived_job_ids(workspace_dir, "snupi_jobs"):
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


def new_snupi_job(
    design_name: str,
    *,
    nonlinear: bool = True,
    n_steps: int = 20,
    with_rmsf: bool = True,
    material: str = "snupi",
    mgcl2_M: float = 0.02,
    dynamics: bool = False,
    hydrodynamics: bool = False,
    anchors: Optional[list] = None,
    field: Optional[dict] = None,
    n_nucleotides: int = 0,
    design_source_path: Optional[str] = None,
    design_fingerprint: Optional[str] = None,
    feature_log_position: Optional[int] = None,
    doc_id: Optional[str] = None,
) -> SnupiJob:
    stage_name = "nonlinear" if nonlinear else "linear"
    return SnupiJob(
        job_id             = uuid.uuid4().hex[:12],
        design_name        = design_name,
        status             = SnupiStatus.queued,
        created_at         = time.time(),
        n_nucleotides      = n_nucleotides,
        nonlinear          = nonlinear,
        n_steps            = n_steps,
        with_rmsf          = with_rmsf,
        material           = material if material in ("snupi", "cando") else "snupi",
        mgcl2_M            = mgcl2_M,
        dynamics           = dynamics,
        hydrodynamics      = hydrodynamics,
        anchors            = anchors,
        field              = field,
        stages             = [SnupiStageStatus(name=stage_name)],
        design_source_path = design_source_path,
        design_fingerprint = design_fingerprint,
        feature_log_position = feature_log_position,
        doc_id             = doc_id,
    )
