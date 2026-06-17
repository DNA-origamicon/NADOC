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


def _norm(p: Optional[str]) -> str:
    """Normalise a workspace path for comparison: forward slashes, no trailing
    ``/``. Mirrors the frontend ``normalizeWorkspacePath`` so both ends agree."""
    return str(p).replace("\\", "/").rstrip("/") if p else ""


def path_matches(design_source_path: Optional[str], target: str, target_is_dir: bool) -> bool:
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
        j for j in MdJob.list_jobs(workspace_dir)
        if path_matches(j.design_source_path, target, target_is_dir)
    ]
    ox = [
        j for j in OxdnaJob.list_jobs(workspace_dir)
        if path_matches(j.design_source_path, target, target_is_dir)
    ]
    return {"md": md, "oxdna": ox}
