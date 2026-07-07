"""
CanDo FEM Job — persistent model for a managed CanDo-replica shape-prediction run.

Sibling of ``mrdna_job.py`` / ``oxdna_job.py``.  Jobs live in
``workspace/cando_jobs/{job_id}/job.json`` and survive server restarts.  A CanDo
job runs the native FEM shape predictor (``backend.physics.fem_solver.predict_shape``)
on the active design and caches the deformed positions + per-bp RMSF for display.

Unlike oxDNA/mrDNA — which spawn external simulators (oxDNA binary, ARBD on a GPU) —
CanDo FEM is a PURE in-process Python solve (scipy sparse), so there is no subprocess,
no CUDA device, and no availability probe.  The two "engines" are the two solver modes:

  • **Coarse** = the LINEAR solve (``nonlinear=False``) — seconds, ~0.92·CanDo bend,
    for an interactive preview.
  • **Fine**   = the geometrically-NONLINEAR corotational solve (``nonlinear=True``) —
    ~1 min on a 6HB/210, validated ~0.95·CanDo bend; runs as a background job.

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


class CandoStatus(str, Enum):
    queued    = "queued"
    preparing = "preparing"   # writing the design snapshot
    running   = "running"     # FEM solving
    failed    = "failed"
    stopped   = "stopped"     # manually stopped
    completed = "completed"   # solve done + positions/RMSF extracted


@dataclass
class CandoStageStatus:
    name:       str          # "linear" (coarse) or "nonlinear" (fine)
    status:     str = "pending"   # pending / running / done / failed
    started_at: Optional[float] = None   # wall time the stage began (for the ETA bar)


@dataclass
class CandoJob:
    job_id:              str
    design_name:         str
    status:              CandoStatus
    created_at:          float
    n_nucleotides:       int = 0
    # Job kind: "predict" (default) = plain FEM shape prediction; "autorefine" = tune the loop/skip
    # program (density sweep + greedy), auto-apply it to the design (reversible feature-log entry),
    # THEN cache the FEM analysis of the refined design so all the display modes work on it.
    kind:                str = "predict"
    # Solver mode: nonlinear=True is the "Fine" corotational solve (default, ~0.95·CanDo);
    # nonlinear=False is the fast "Coarse" linear preview.  For an autorefine job it is the
    # per-trial ORACLE mode (Coarse/linear is the sensible fast inner loop).
    nonlinear:           bool = True
    n_steps:             int = 20     # corotational load-step count (nonlinear only)
    with_rmsf:           bool = True  # also compute the free-free NMA per-bp RMSF
    # ── Job-request annotations (C1/C2): anchors + uniform E-field, NEVER a topology edit ──
    # anchors: shared oxDNA scope descriptors (overhang/cluster/domain/strand/base) held fixed
    # (Dirichlet BC) during the FEM solve.  field: {"field_pN": <force/nt, pN>, "dir": [x,y,z]} —
    # the same per-nucleotide force oxDNA applies.  A field needs ≥1 anchor (COM drift).  Both are
    # threaded into predict_shape(...) (Three-Layer Law: display-only, read-only over the design).
    anchors:             Optional[list] = None
    field:               Optional[dict] = None
    stages:              list[CandoStageStatus] = dc_field(default_factory=list)
    error:               Optional[str] = None
    design_source_path:  Optional[str] = None
    # Document the job's design lives in (multi-doc): the autorefine runner sets this so its
    # auto-apply lands on the right document's active design + feature log from its worker thread.
    doc_id:              Optional[str] = None
    # ── Autorefine (kind == "autorefine") result summary ────────────────────────
    refine_applied:      bool = False           # did the refine improve + apply marks?
    refine_before_rmsd:  Optional[float] = None # FEM deviation RMSD (nm) before refining
    refine_after_rmsd:   Optional[float] = None # …and after (the applied result)
    refine_n_marks:      Optional[int] = None   # total loop/skip marks in the applied program
    refine_period:       Optional[int] = None   # SQUARE density-sweep winning period (None = n/a)
    # SQUARE twist objective (exp37) + HONEYCOMB coupled (twist,bend) SHAPE objective (exp38):
    # end-to-end twist/bend before/after vs the design's intended twist/bend.
    refine_twist_before: Optional[float] = None
    refine_twist_after:  Optional[float] = None
    refine_twist_target: Optional[float] = None
    refine_bend_before:  Optional[float] = None
    refine_bend_after:   Optional[float] = None
    refine_bend_target:  Optional[float] = None
    refine_note:         Optional[str] = None    # live status line while running / summary on done
    # Populated on completion — surfaced in the panel detail block.
    sim_seconds:         Optional[float] = None   # wall time inside predict_shape()
    n_nodes:             Optional[int]   = None   # duplex-core FEM nodes (= base pairs)
    rmsf_min_nm:         Optional[float] = None
    rmsf_max_nm:         Optional[float] = None
    # Out-of-date detection (design edited after the solve ran); shares the oxDNA
    # staleness fingerprint so an edit invalidates the predicted display.
    design_fingerprint:  Optional[str] = None
    feature_log_position: Optional[int] = None
    # Archival parity with oxDNA/mrDNA jobs (job_archive is kind-generic).
    archived:            bool = False
    archive_path:        Optional[str] = None

    # ── Paths ──────────────────────────────────────────────────────────────────

    def job_dir(self, workspace_dir: Path) -> Path:
        if self.archived and self.archive_path:
            return Path(self.archive_path)
        return workspace_dir / "cando_jobs" / self.job_id

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
    def load(cls, job_id: str, workspace_dir: Path) -> "CandoJob":
        from backend.core.job_archive import resolve_job_json
        path = resolve_job_json(workspace_dir, "cando_jobs", job_id)
        data = json.loads(path.read_text())
        data["status"] = CandoStatus(data["status"])
        data["stages"] = [CandoStageStatus(**s) for s in data.get("stages", [])]
        data.setdefault("kind", "predict")
        data.setdefault("nonlinear", True)
        data.setdefault("n_steps", 20)
        data.setdefault("with_rmsf", True)
        data.setdefault("anchors", None)
        data.setdefault("field", None)
        data.setdefault("design_source_path", None)
        data.setdefault("doc_id", None)
        data.setdefault("refine_applied", False)
        data.setdefault("refine_before_rmsd", None)
        data.setdefault("refine_after_rmsd", None)
        data.setdefault("refine_n_marks", None)
        data.setdefault("refine_period", None)
        data.setdefault("refine_twist_before", None)
        data.setdefault("refine_twist_after", None)
        data.setdefault("refine_twist_target", None)
        data.setdefault("refine_bend_before", None)
        data.setdefault("refine_bend_after", None)
        data.setdefault("refine_bend_target", None)
        data.setdefault("refine_note", None)
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
    def list_jobs(cls, workspace_dir: Path) -> list["CandoJob"]:
        from backend.core.job_archive import archived_job_ids
        result: list[CandoJob] = []
        seen: set[str] = set()
        jobs_dir = workspace_dir / "cando_jobs"
        if jobs_dir.exists():
            for jdir in sorted(jobs_dir.iterdir(), key=lambda p: p.name):
                if jdir.is_dir() and (jdir / "job.json").exists():
                    try:
                        result.append(cls.load(jdir.name, workspace_dir))
                        seen.add(jdir.name)
                    except Exception:
                        pass
        for jid in archived_job_ids(workspace_dir, "cando_jobs"):
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


def new_cando_job(
    design_name: str,
    *,
    kind: str = "predict",
    nonlinear: bool = True,
    n_steps: int = 20,
    with_rmsf: bool = True,
    anchors: Optional[list] = None,
    field: Optional[dict] = None,
    n_nucleotides: int = 0,
    design_source_path: Optional[str] = None,
    design_fingerprint: Optional[str] = None,
    feature_log_position: Optional[int] = None,
    doc_id: Optional[str] = None,
) -> CandoJob:
    # An autorefine job's single "stage" is the refine loop; a predict job's is the solve mode.
    stage_name = "autorefine" if kind == "autorefine" else ("nonlinear" if nonlinear else "linear")
    return CandoJob(
        job_id             = uuid.uuid4().hex[:12],
        design_name        = design_name,
        status             = CandoStatus.queued,
        created_at         = time.time(),
        n_nucleotides      = n_nucleotides,
        kind               = kind,
        nonlinear          = nonlinear,
        n_steps            = n_steps,
        with_rmsf          = with_rmsf,
        anchors            = anchors,
        field              = field,
        stages             = [CandoStageStatus(name=stage_name)],
        design_source_path = design_source_path,
        design_fingerprint = design_fingerprint,
        feature_log_position = feature_log_position,
        doc_id             = doc_id,
    )
