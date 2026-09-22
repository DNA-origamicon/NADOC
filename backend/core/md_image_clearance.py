"""Submission-time image clearance, independent of the rotational envelope.

The axis-aligned envelope gap is a conservative lower bound on atom-image
separation, not an exact contact distance. No rigid-body rotations are applied.
The recommendation is an engineering buffer, not a convergence criterion for PME
or a prediction of future deformation. Unknown inputs require acknowledgment.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np

from backend.core.md_charge import ION_RESNAMES, WATER_RESNAMES
from backend.core.md_plan import parse_conf_directives
from backend.core.md_shell_reprep import read_namd_coor

RECOMMENDED_GAP_ANG = 24.0
_BATH = (
    WATER_RESNAMES
    | ION_RESNAMES
    | {
        "TIP3P",
        "TIP4",
        "SPC",
        "SPCE",
        "SOL",
        "NA",
        "CL",
        "K",
        "CAL",
        "MGHH",
    }
)


def clearance_report(xyz, cell, *, cutoff_ang: float) -> dict:
    """Conservative fixed-pose clearance using orthorhombic cell lengths (Å)."""
    xyz, cell = np.asarray(xyz, dtype=float), np.asarray(cell, dtype=float)
    if (
        xyz.ndim != 2
        or xyz.shape[1] != 3
        or len(xyz) == 0
        or cell.shape != (3,)
        or not np.isfinite(xyz).all()
        or not np.isfinite(cell).all()
        or np.any(cell <= 0)
        or not np.isfinite(cutoff_ang)
        or cutoff_ang <= 0
    ):
        raise ValueError("Invalid solute coordinates, cell lengths, or cutoff")
    span = np.ptp(xyz, axis=0)
    gaps = cell - span
    recommended = max(RECOMMENDED_GAP_ANG, 2 * cutoff_ang)
    ok = bool(np.min(gaps) >= recommended - 1e-6)
    return {
        "status": "pass" if ok else "insufficient",
        "requires_override": not ok,
        "method": "fixed_pose_envelope",
        "cell_nm": (cell / 10).tolist(),
        "solute_span_nm": (span / 10).tolist(),
        "axis_gaps_nm": (gaps / 10).tolist(),
        "minimum_gap_nm": float(np.min(gaps) / 10),
        "recommended_gap_nm": recommended / 10,
        "cutoff_nm": cutoff_ang / 10,
        "n_solute_heavy_atoms": len(xyz),
        "detail": (
            "Fixed-pose envelope clearance; overall rotational diffusion is excluded. "
            "Recommended gap: at least 2.4 nm or twice the short-range cutoff, whichever "
            "is larger, to leave room for internal fluctuations and cell contraction. "
            "A negative envelope gap does not by itself prove atomic overlap. "
            "Passing does not guarantee clearance after deformation or PME convergence."
        ),
    }


def _path(pkg: Path, value: str) -> Path:
    if not isinstance(value, str) or any(c in value for c in "$[];\n"):
        raise ValueError("Cannot resolve dynamic NAMD input path")
    path = (pkg / value.strip('"{}')).resolve()
    if not path.is_relative_to(pkg.resolve()):
        raise ValueError("NAMD input is outside the prepared package")
    return path


def _solute_indices(psf: Path) -> tuple[np.ndarray, int]:
    # Stream NATOM instead of allocating a million Python atom records.
    with psf.open() as handle:
        for line in handle:
            if "!NATOM" in line:
                n = int(line.split()[0])
                break
        else:
            raise ValueError("Topology has no NATOM section")
        if n <= 0:
            raise ValueError("Topology has no valid atoms")
        indices = []
        for i in range(n):
            fields = next(handle).split()
            if len(fields) < 8 or int(fields[0]) != i + 1:
                raise ValueError("Incomplete or unordered PSF atom table")
            if fields[3].upper() not in _BATH and not fields[4].lstrip(
                "0123456789"
            ).upper().startswith(("H", "D")):
                indices.append(i)
    return np.asarray(indices, dtype=int), n


def _read_cell(path: Path) -> np.ndarray:
    lines = [
        ln.split()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if not lines or len(lines[-1]) < 10:
        raise ValueError("Checkpoint cell is missing or incomplete")
    matrix = np.asarray(lines[-1][1:10], dtype=float).reshape(3, 3)
    if not np.allclose(matrix, np.diag(np.diag(matrix)), atol=1e-6):
        raise ValueError("Clearance check currently requires an orthorhombic cell")
    return np.diag(matrix)


def job_image_clearance(job, workspace: Path, *, resume: bool = False) -> dict:
    """Inspect the actual initial config/checkpoint, never an ancestor's stale box.

    Remote resumes select their checkpoint on the cluster. Without fetching and
    validating that exact checkpoint, a local copy cannot certify the resumed pose.
    """
    try:
        if resume:
            raise ValueError(
                "The resume checkpoint is selected on Alpine; its current coordinates "
                "and cell have not been verified locally. Download and inspect that "
                "checkpoint, or explicitly accept unverified clearance to resume."
            )
        pkg = job.package_dir(workspace)
        stage = job.minimization or (job.segments[0] if job.segments else None)
        if stage is None:
            raise ValueError("No prepared starting stage")
        conf_path = _path(pkg, f"{stage.name}.conf")
        conf = parse_conf_directives(conf_path.read_text())
        if any(key in conf for key in ("source", "include")):
            raise ValueError(
                "Included NAMD configuration needs manual clearance review"
            )
        if str(conf.get("gbis", "")).lower() in ("on", "yes", "true"):
            return {
                "status": "not_applicable",
                "requires_override": False,
                "detail": "Implicit-solvent run: no periodic solvent cell.",
            }
        topology = _path(pkg, conf["structure"])
        indices, n_atoms = _solute_indices(topology)
        if not len(indices):
            return {
                "status": "not_applicable",
                "requires_override": False,
                "detail": "No solute heavy atoms in the prepared topology.",
            }
        coordinate_path = _path(pkg, conf.get("bincoordinates") or conf["coordinates"])
        if "bincoordinates" in conf:
            xyz = read_namd_coor(coordinate_path)
            if "extendedsystem" not in conf:
                raise ValueError(
                    "Binary starting coordinates have no matching checkpoint cell"
                )
        else:
            with coordinate_path.open() as handle:
                xyz = np.asarray(
                    [
                        (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
                        for ln in handle
                        if ln.startswith(("ATOM  ", "HETATM"))
                    ]
                )
        if len(xyz) != n_atoms:
            raise ValueError(
                "Starting coordinates do not match the topology atom count"
            )
        if "extendedsystem" in conf:
            cell_path = _path(pkg, conf["extendedsystem"])
            cell = _read_cell(cell_path)
            cell_source = str(cell_path.relative_to(pkg.resolve()))
        else:
            matrix = np.asarray(
                [conf[f"cellbasisvector{i}"].split() for i in (1, 2, 3)], dtype=float
            )
            if matrix.shape != (3, 3) or not np.allclose(
                matrix, np.diag(np.diag(matrix)), atol=1e-6
            ):
                raise ValueError("Clearance check requires an orthorhombic cell")
            cell, cell_source = np.diag(matrix), conf_path.name
        # Use the largest configured cutoff across all stages being submitted.
        cutoffs = [float(conf["cutoff"])]
        for segment in job.segments:
            directives = parse_conf_directives(
                _path(pkg, f"{segment.name}.conf").read_text()
            )
            cutoffs.append(float(directives["cutoff"]))
        report = clearance_report(xyz[indices], cell, cutoff_ang=max(cutoffs))
        report.update(
            coordinate_source=str(coordinate_path.relative_to(pkg.resolve())),
            cell_source=cell_source,
            config_source=conf_path.name,
        )
        return report
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as exc:
        return {
            "status": "unknown",
            "requires_override": True,
            "recommended_gap_nm": RECOMMENDED_GAP_ANG / 10,
            "detail": f"Periodic-image clearance could not be verified: {exc}",
        }


def require_image_clearance(
    job, workspace: Path, *, allow: bool, resume: bool = False
) -> dict:
    """Recheck immediately before submission; an old rotation override never applies."""
    from fastapi import HTTPException

    report = job_image_clearance(job, workspace, resume=resume)
    if report["requires_override"] and not allow:
        gap = report.get("minimum_gap_nm")
        detail = (
            f"Minimum fixed-pose envelope gap is {gap:.2f} nm; recommended "
            f"at least {report['recommended_gap_nm']:.2f} nm. "
            if gap is not None
            else ""
        )
        raise HTTPException(
            409,
            detail
            + report["detail"]
            + " Re-prepare with more solvent padding, or explicitly submit "
            "with allow_small_image_gap=true.",
        )
    return report


def record_clearance_review(job, workspace: Path, report: dict, *, allow: bool) -> None:
    """Keep the measured verdict and explicit override with the job, not its defaults."""
    path = job.job_dir(workspace) / "image_clearance_reviews.jsonl"
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "reviewed_at": time.time(),
                    "allow_small_image_gap": allow,
                    "report": report,
                }
            )
            + "\n"
        )


def ensemble_image_clearance(job, workspace: Path) -> dict:
    """Review the worst verdict across every eligible replica, not just the sizing child."""
    from backend.core.md_job import MdJob

    replicas = [
        child
        for child in MdJob.list_jobs(workspace)
        if child.parent_job_id == job.parent_job_id
        and child.ensemble_seed is not None
        and child.execution_target == "alpine"
        and not child.slurm_job_id
    ]
    if not job.parent_job_id or not replicas:
        return job_image_clearance(job, workspace)
    reports = [
        (child.job_id, job_image_clearance(child, workspace)) for child in replicas
    ]
    child_id, worst = min(
        reports,
        key=lambda item: (
            0 if item[1]["requires_override"] else 1,
            item[1].get("minimum_gap_nm", float("-inf")),
        ),
    )
    return {
        **worst,
        "checked_jobs": len(replicas),
        "review_job_id": child_id,
        "detail": f"Checked all {len(replicas)} unsubmitted replicas. "
        f"Showing the limiting or unverified verdict ({child_id}). " + worst["detail"],
    }
