"""Verify and pin the actual Alpine continuation inputs before submitting them."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import struct
import tempfile
from types import SimpleNamespace
import uuid

from backend.core.md_image_clearance import require_image_clearance, record_clearance_review
from backend.core.md_plan import parse_conf_directives


def _relative_input(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(c in value for c in "$[]{}\n\r"):
        raise ValueError(f"Cannot verify dynamic or external resume input: {value!r}")
    return str(path)


async def verify_resume_inputs(job, workspace, conn, stage_name, conf_text, *, allow=False,
                               expected_step=None):
    """Freeze the stopped job's checkpoint, inspect it, and submit those SAME files.

    The remote copies persist as attempt evidence. Temporary local downloads are
    removed even on refusal. A transport failure cannot become an unchecked submit.
    """
    options = parse_conf_directives(conf_text)
    if "bincoordinates" not in options:
        # First-stage rerun before a checkpoint: the prepared seed is still the input.
        view = SimpleNamespace(package_dir=job.package_dir,
                               minimization=SimpleNamespace(name=stage_name),
                               segments=job.segments)
        report = await asyncio.to_thread(require_image_clearance, view, workspace, allow=allow)
        record_clearance_review(job, workspace, report, allow=allow)
        return conf_text
    if "extendedsystem" not in options:
        raise ValueError("Resume coordinates have no matching checkpoint cell")
    token = uuid.uuid4().hex
    remote_dir = f".resume-inputs/{token}"
    inputs = {key: _relative_input(options[key]) for key in
              ("bincoordinates", "extendedsystem", "binvelocities") if key in options}
    destinations = {key: f"{remote_dir}/{Path(value).name}" for key, value in inputs.items()}
    commands = [f"cd {shlex.quote(job.remote_scratch_dir)}", f"mkdir -p {shlex.quote(remote_dir)}"]
    commands += [f"cp -- {shlex.quote(value)} {shlex.quote(destinations[key])}"
                 for key, value in inputs.items()]
    result = await conn.run(" && ".join(commands))
    if result.rc:
        raise RuntimeError(f"Could not preserve resume checkpoint: {result.stderr or result.stdout}")
    pkg = job.package_dir(workspace)
    with tempfile.TemporaryDirectory(prefix=".resume-review-", dir=pkg) as tmp:
        local_dir = Path(tmp)
        local_inputs = {}
        fingerprints = {}
        for key in inputs:
            local = local_dir / Path(destinations[key]).name
            await conn.sftp_get(f"{job.remote_scratch_dir}/{destinations[key]}", str(local))
            local_inputs[key] = str(local.relative_to(pkg))
            with local.open("rb") as stream:
                fingerprints[destinations[key]] = hashlib.file_digest(stream, "sha256").hexdigest()
        if "binvelocities" in local_inputs:
            counts = []
            for key in ("bincoordinates", "binvelocities"):
                path = pkg / local_inputs[key]
                with path.open("rb") as stream:
                    raw = stream.read(4)
                if len(raw) != 4:
                    raise ValueError("Incomplete continuation coordinates/velocities")
                count = struct.unpack("<i", raw)[0]
                if count <= 0 or path.stat().st_size != 4 + count * 24:
                    raise ValueError("Incomplete continuation coordinates/velocities")
                counts.append(count)
            if counts[0] != counts[1]:
                raise ValueError("Continuation coordinates and velocities disagree")
        if expected_step is not None:
            from backend.core.remote_resume_conf import restart_step_of
            actual = restart_step_of((pkg / local_inputs["extendedsystem"]).read_text())
            if actual != expected_step:
                raise RuntimeError("Checkpoint changed during resume review; refresh and retry")
        # Keep topology/restraint paths relative to the package, as in the real config.
        review_name = f".resume-review-{token}"
        review_path = pkg / f"{review_name}.conf"
        try:
            review_path.write_text(_replace_inputs(conf_text, local_inputs))
            view = SimpleNamespace(package_dir=job.package_dir,
                                   minimization=SimpleNamespace(name=review_name),
                                   segments=job.segments)
            report = await asyncio.to_thread(require_image_clearance, view, workspace, allow=allow)
            report.update(config_source=f"{stage_name}.resume.conf",
                          coordinate_source=destinations["bincoordinates"],
                          cell_source=destinations["extendedsystem"],
                          restart_step=expected_step)
            record_clearance_review(job, workspace, report, allow=allow)
        finally:
            review_path.unlink(missing_ok=True)
    metadata = dict(step=expected_step, sha256=fingerprints)
    return "# NADOC_REVIEWED_RESUME " + json.dumps(metadata) + "\n" + _replace_inputs(conf_text, destinations)


def _replace_inputs(text, values):
    lines = []
    for line in text.splitlines():
        fields = line.split()
        key = fields[0].lower() if fields else ""
        lines.append(f"{fields[0]} {values[key]}" if key in values else line)
    return "\n".join(lines) + "\n"
