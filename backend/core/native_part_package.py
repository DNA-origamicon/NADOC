"""Portable NADOC part archives containing a design and its simulation jobs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from backend.core.job_cleanup import _job_classes, _norm
from backend.core.models import Design

FORMAT = "nadoc.native-part-package"
VERSION = 1


def associated_job_dirs(workspace: Path, source_path: str):
    """Yield ``(tree, job, directory)`` for every supported simulation engine."""
    target = _norm(source_path)
    for cls in _job_classes():
        tree = cls.__module__.rsplit(".", 1)[-1].removesuffix("_job") + "_jobs"
        for job in cls.list_jobs(workspace):
            if _norm(getattr(job, "design_source_path", None)) == target:
                directory = job.job_dir(workspace)
                if directory.is_dir():
                    yield tree, job, directory


def create_package(workspace: Path, source_path: str, output: Path) -> dict:
    part = (workspace / source_path).resolve()
    try:
        part.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("part path escapes the workspace") from exc
    if not part.is_file() or part.suffix.lower() != ".nadoc":
        raise ValueError("package source must be an existing .nadoc part")
    Design.from_json(part.read_text(encoding="utf-8"))

    jobs = list(associated_job_dirs(workspace, source_path))
    active = [
        job.job_id for _, job, _ in jobs
        if str(getattr(getattr(job, "status", None), "value", getattr(job, "status", "")))
        in {"preparing", "running"}
    ]
    if active:
        raise ValueError("stop active simulation jobs before packaging: " + ", ".join(active))
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "part": {"archive_path": f"part/{part.name}", "source_path": _norm(source_path)},
        "simulations": [
            {"tree": tree, "job_id": job.job_id, "archive_path": f"simulations/{tree}/{job.job_id}"}
            for tree, job, _ in jobs
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2), compress_type=zipfile.ZIP_DEFLATED)
        archive.write(part, manifest["part"]["archive_path"], compress_type=zipfile.ZIP_DEFLATED)
        for tree, job, directory in jobs:
            prefix = PurePosixPath("simulations", tree, job.job_id)
            for file in sorted(directory.rglob("*")):
                if file.is_file():
                    # Trajectories are commonly already compressed/incompressible; STORE also
                    # avoids hours of CPU time while packaging multi-gigabyte simulations.
                    archive.write(file, str(prefix / file.relative_to(directory)), compress_type=zipfile.ZIP_STORED)
    return manifest


def _safe_members(archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or path.parts[:1] == ("",):
            raise ValueError(f"unsafe archive path: {info.filename}")
        if info.is_dir():
            continue
        # Reject Unix symlinks; extraction must only create regular files.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError(f"archive contains a symbolic link: {info.filename}")


def import_package(workspace: Path, package: Path, dest_path: str, *, overwrite_part: bool = False) -> dict:
    """Validate and unpack an archive. Existing job IDs are never overwritten."""
    destination = (workspace / dest_path).resolve()
    try:
        destination.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("destination escapes the workspace") from exc
    if destination.suffix.lower() != ".nadoc":
        raise ValueError("destination must end with .nadoc")
    if destination.exists() and not overwrite_part:
        raise FileExistsError(f"part already exists: {dest_path}")

    with zipfile.ZipFile(package) as archive:
        _safe_members(archive)
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("missing or invalid package manifest") from exc
        if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValueError("unsupported NADOC part package format")
        part_member = manifest.get("part", {}).get("archive_path")
        if not isinstance(part_member, str):
            raise ValueError("manifest does not identify a part file")
        try:
            design_text = archive.read(part_member).decode("utf-8")
            Design.from_json(design_text)
        except (KeyError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("package contains an invalid NADOC part") from exc

        simulations = manifest.get("simulations", [])
        targets = []
        allowed_trees = {c.__module__.rsplit(".", 1)[-1].removesuffix("_job") + "_jobs" for c in _job_classes()}
        for sim in simulations:
            tree, job_id, prefix = sim.get("tree"), sim.get("job_id"), sim.get("archive_path")
            if (tree not in allowed_trees or not isinstance(job_id, str) or not job_id
                    or "/" in job_id or "\\" in job_id or not isinstance(prefix, str)):
                raise ValueError("manifest contains an invalid simulation target")
            target = workspace / tree / job_id
            if target.exists():
                raise FileExistsError(f"simulation job already exists: {tree}/{job_id}")
            targets.append((tree, job_id, str(PurePosixPath(prefix)), target))

        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".nadoc-import-", dir=workspace) as temporary:
            staging = Path(temporary)
            staged_jobs = []
            for tree, job_id, prefix, target in targets:
                staged = staging / tree / job_id
                for info in archive.infolist():
                    member = PurePosixPath(info.filename)
                    base = PurePosixPath(prefix)
                    try:
                        relative = member.relative_to(base)
                    except ValueError:
                        continue
                    if info.is_dir():
                        continue
                    out = staged.joinpath(*relative.parts)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                job_json = staged / "job.json"
                if not job_json.is_file():
                    raise ValueError(f"simulation {tree}/{job_id} has no job.json")
                data = json.loads(job_json.read_text(encoding="utf-8"))
                data["design_source_path"] = _norm(dest_path)
                if "archived" in data or "archive_path" in data:
                    data["archived"] = False
                    data["archive_path"] = None
                job_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
                staged_jobs.append((staged, target))

            staged_part = staging / destination.name
            staged_part.write_text(design_text, encoding="utf-8")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_part, destination)
            installed = []
            for staged, target in staged_jobs:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged), str(target))
                installed.append(str(target.relative_to(workspace)))
    return {"path": _norm(dest_path), "name": destination.stem, "simulations": installed}
