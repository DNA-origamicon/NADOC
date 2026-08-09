"""Associate workspace design files with their MD / oxDNA job folders.

Every MD (NAMD) and oxDNA job stores a workspace-relative ``design_source_path``
pointing back at the ``.nadoc`` file it was generated from (e.g.
``"3x6Sq_oxDNA.nadoc"`` or ``"subfolder/beam.nadoc"``). When that file — or a
whole folder of files — is deleted from the workspace library, the generated
job folders under ``workspace/md_jobs`` and ``workspace/oxdna_jobs`` are left
orphaned.

This module finds the jobs associated with a deleted path so the API can offer
to remove their folders too. The path-matching rule (:func:`path_matches`) is a
pure string comparison and is unit-tested; :func:`find_associated_jobs` is the
thin disk-touching wrapper that loads the job lists and filters them.

One reason to change: how a deleted library path maps onto its job folders.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.core.md_job import MdJob
from backend.core.oxdna_job import OxdnaJob


def _job_classes():
    """Return every simulation job type that carries design provenance."""
    from backend.core.blade_job import BladeJob
    from backend.core.cando_job import CandoJob
    from backend.core.lammps_job import LammpsJob
    from backend.core.mrdna_job import MrdnaJob
    from backend.core.snupi_job import SnupiJob

    return (MdJob, OxdnaJob, MrdnaJob, CandoJob, SnupiJob, BladeJob, LammpsJob)


def _norm(p: Optional[str]) -> str:
    """Normalise a workspace path for comparison: forward slashes, no trailing
    ``/``. Mirrors the frontend ``normalizeWorkspacePath`` so both ends agree."""
    return str(p).replace("\\", "/").rstrip("/") if p else ""


def path_matches(
    design_source_path: Optional[str], target: str, target_is_dir: bool
) -> bool:
    """True if a job's ``design_source_path`` belongs to the deleted ``target``.

    For a file target the (normalised) paths must be equal. For a folder target
    the source path must lie inside the folder (the folder itself or any
    descendant). Empty/None source paths never match — those jobs aren't tied to
    a library file.
    """
    src = _norm(design_source_path)
    tgt = _norm(target)
    if not src or not tgt:
        return False
    if target_is_dir:
        return src == tgt or src.startswith(tgt + "/")
    return src == tgt


def find_associated_jobs(workspace_dir: Path, target: str, target_is_dir: bool) -> dict:
    """Return MD + oxDNA jobs whose ``design_source_path`` matches ``target``.

    ``target`` is a workspace-relative path (file or folder). Returns
    ``{"md": [MdJob, ...], "oxdna": [OxdnaJob, ...]}``.
    """
    md = [
        j
        for j in MdJob.list_jobs(workspace_dir)
        if path_matches(j.design_source_path, target, target_is_dir)
    ]
    ox = [
        j
        for j in OxdnaJob.list_jobs(workspace_dir)
        if path_matches(j.design_source_path, target, target_is_dir)
    ]
    return {"md": md, "oxdna": ox}


def remap_design_source_paths(
    workspace_dir: Path, old_path: str, new_path: str, *, old_is_dir: bool = False
) -> int:
    """Move job provenance with a renamed/moved design (all simulation engines)."""
    old, new = _norm(old_path), _norm(new_path)
    changed = 0
    for cls in _job_classes():
        for job in cls.list_jobs(workspace_dir):
            source = _norm(getattr(job, "design_source_path", None))
            if source == old:
                replacement = new
            elif old_is_dir and source.startswith(old + "/"):
                replacement = new + source[len(old) :]
            else:
                continue
            job.design_source_path = replacement
            job.save(workspace_dir)
            changed += 1
    return changed


def reassign_job_snapshot_identity(
    workspace_dir: Path, source_path: str, old_id: str, new_id: str
) -> int:
    """Re-key frozen snapshots belonging to a legacy file that was identified as a copy.

    Jobs are selected by their workspace-relative provenance path.  Their simulation
    data and Feature Log are untouched; only the UUID in the frozen ``design.json``
    is changed so rolling that job cannot resurrect the copied file's former UUID.
    """
    from backend.core.models import Design

    source_path = _norm(source_path)
    changed = 0
    for cls in _job_classes():
        for job in cls.list_jobs(workspace_dir):
            if _norm(getattr(job, "design_source_path", None)) != source_path:
                continue
            snapshot_path = job.job_dir(workspace_dir) / "design.json"
            if not snapshot_path.is_file():
                continue
            try:
                snapshot = Design.from_json(snapshot_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if snapshot.id != old_id:
                continue
            snapshot.id = new_id
            snapshot_path.write_text(snapshot.to_json(), encoding="utf-8")
            changed += 1
    return changed
