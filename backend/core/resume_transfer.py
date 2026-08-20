"""Integrity rules for resumable downloads — *is this ``.part`` a genuine prefix?*

A 181 GB NAMD trajectory arrives over a Duo-gated SSH link that cannot reconnect
headlessly, so a transfer is interrupted many times and the ``.part`` file is the only
thing standing between an interruption and hours of re-transfer.  Appending to a partial
is therefore a *trust* decision, and this module owns it.

Three independent checks, because each catches what the others miss:

* **Sidecar identity** — the partial records which remote file, size and mtime it was
  built from.  A remote file that was regenerated (resubmit, re-run) invalidates it.
* **Tail verification** — re-read the last mebibyte from the remote at the resume offset
  and byte-compare.  Catches a partial built from a different file, or a truncated write.
* **Structural validation** — for a format we understand (NAMD DCD) walk the frame
  boundaries.  This is the only check that catches a corrupt *head*, which is exactly how
  the live-frame stand-in used to destroy a download: it shared the ``.part`` path, so a
  refresh truncated the partial to one frame, and the next fetch appended real bytes onto
  a file whose first 16 MB were a different DCD entirely.  Size matched, so it verified.

Pure decision logic here; the transport lives in ``cluster_ssh``.
"""

from __future__ import annotations

import json
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path

# Re-read this much from the remote at the resume offset and byte-compare before
# appending.  One MiB is a rounding error against a 181 GB transfer and is far larger
# than any plausible partial-write window.
TAIL_VERIFY_BYTES = 1024 * 1024

# fsync + sidecar checkpoint interval.  A hard kill then costs at most this much, versus
# the whole in-flight buffer.
CHECKPOINT_BYTES = 64 * 1024 * 1024

SIDECAR_SUFFIX = ".resume.json"

# Below this a DCD cannot hold even a minimal header (84-byte CORD record + the two
# short records after it), so no verdict is possible.  Claiming corruption there would
# quarantine a legitimately empty trajectory — NAMD creates the file before the first
# dcdfreq step, so a run killed early leaves exactly that.
_DCD_MIN_HEADER = 116

# A DCD is a stream of fixed-size frames, so a sampled boundary walk is nearly as strong
# as an exhaustive one and costs ~60 seeks instead of ~11,000 (the archive volume is
# spinning rust; an exhaustive walk there takes minutes).
_DCD_BOUNDARY_SAMPLES = 64


@dataclass(frozen=True)
class ResumePlan:
    """What to do with an existing partial: append at ``offset``, or start over."""

    offset: int
    verify_from: int  # tail-verify remote[verify_from:offset]; == offset means no check
    reason: str

    @property
    def restarts(self) -> bool:
        return self.offset == 0


# ── sidecar ───────────────────────────────────────────────────────────────────────


def sidecar_path(local_path: str | Path) -> Path:
    return Path(str(local_path) + SIDECAR_SUFFIX)


def read_sidecar(local_path: str | Path) -> dict | None:
    try:
        return json.loads(sidecar_path(local_path).read_text())
    except (OSError, ValueError):
        return None


def write_sidecar(
    local_path: str | Path,
    *,
    remote_path: str,
    remote_size: int,
    remote_mtime: float | None,
    offset: int,
) -> None:
    """Record what the partial is, so a later resume can prove it is still the same file.

    Best-effort: a sidecar that cannot be written must never fail a transfer that is
    otherwise fine — the tail check still runs, it just starts from less information.
    """
    payload = {
        "remote_path": remote_path,
        "remote_size": int(remote_size),
        "remote_mtime": remote_mtime,
        "offset": int(offset),
        "updated_at": time.time(),
    }
    try:
        tmp = sidecar_path(local_path).with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(sidecar_path(local_path))
    except OSError:
        pass


def clear_sidecar(local_path: str | Path) -> None:
    try:
        sidecar_path(local_path).unlink(missing_ok=True)
    except OSError:
        pass


# ── resume decision (pure) ────────────────────────────────────────────────────────


def plan_resume(
    *,
    part_size: int,
    remote_path: str,
    remote_size: int,
    remote_mtime: float | None,
    sidecar: dict | None,
) -> ResumePlan:
    """Decide the append offset for a partial of ``part_size`` bytes.  Pure.

    Returns offset 0 whenever the partial cannot be trusted; the caller then truncates
    and starts over.  Never returns an offset past ``remote_size``.
    """
    if part_size <= 0:
        return ResumePlan(0, 0, "no partial on disk")
    if part_size > remote_size:
        return ResumePlan(0, 0, f"partial ({part_size}) exceeds remote ({remote_size})")
    if sidecar:
        if sidecar.get("remote_path") not in (None, remote_path):
            return ResumePlan(0, 0, "partial belongs to a different remote path")
        recorded_size = sidecar.get("remote_size")
        if isinstance(recorded_size, int) and recorded_size != remote_size:
            return ResumePlan(
                0, 0, f"remote grew/shrank ({recorded_size} -> {remote_size})"
            )
        recorded_mtime = sidecar.get("remote_mtime")
        if (
            remote_mtime is not None
            and isinstance(recorded_mtime, (int, float))
            and abs(float(recorded_mtime) - float(remote_mtime)) > 1.0
        ):
            return ResumePlan(0, 0, "remote file was rewritten since this partial")
    verify_from = max(0, part_size - TAIL_VERIFY_BYTES)
    return ResumePlan(part_size, verify_from, "resuming verified partial")


# ── NAMD DCD structural validation ────────────────────────────────────────────────


@dataclass(frozen=True)
class DcdLayout:
    header_size: int
    frame_size: int
    n_atoms: int
    has_cell: bool


def _record(fh, offset: int) -> tuple[int, bool]:
    """FORTRAN unformatted record at ``offset`` -> (payload length, markers agree)."""
    fh.seek(offset)
    head = fh.read(4)
    if len(head) < 4:
        return (0, False)
    (n,) = struct.unpack("<i", head)
    if n < 0 or n > 1 << 30:
        return (n, False)
    fh.seek(offset + 4 + n)
    tail = fh.read(4)
    if len(tail) < 4:
        return (n, False)
    return (n, struct.unpack("<i", tail)[0] == n)


def dcd_layout(path: str | Path) -> DcdLayout | None:
    """Header/frame geometry of a DCD, or ``None`` if the head is not a DCD at all."""
    try:
        with open(path, "rb") as fh:
            n, ok = _record(fh, 0)
            if not ok or n != 84:
                return None
            fh.seek(4)
            if fh.read(4) != b"CORD":
                return None
            fh.seek(8)
            ints = struct.unpack("<20i", fh.read(80))
            has_cell = bool(ints[10])
            title_len, ok = _record(fh, 92)
            if not ok:
                return None
            natom_off = 92 + 8 + title_len
            natom_len, ok = _record(fh, natom_off)
            if not ok or natom_len != 4:
                return None
            fh.seek(natom_off + 4)
            (n_atoms,) = struct.unpack("<i", fh.read(4))
            if n_atoms <= 0:
                return None
    except (OSError, struct.error):
        return None
    header_size = natom_off + 12
    frame_size = 3 * (8 + 4 * n_atoms) + (56 if has_cell else 0)
    return DcdLayout(header_size, frame_size, n_atoms, has_cell)


def dcd_prefix_is_valid(
    path: str | Path, *, samples: int = _DCD_BOUNDARY_SAMPLES
) -> tuple[bool, str]:
    """Is this file a structurally sound DCD *prefix* (last frame may be partial)?

    Samples frame boundaries rather than walking all of them — frames are fixed size, so
    a wrong-offset splice or a foreign head shows up at the very first boundary it
    touches.  Always checks the first boundaries and the last complete one.
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return (False, f"cannot stat partial: {exc}")
    if size < _DCD_MIN_HEADER:
        return (True, "too short to validate")
    layout = dcd_layout(path)
    if layout is None:
        return (False, "not a DCD (header did not parse)")
    body = size - layout.header_size
    if body < 0:
        return (True, "header still incomplete")
    n_frames = body // layout.frame_size
    if n_frames == 0:
        return (True, "no complete frame yet")
    probes = sorted(
        {0, 1, 2, 3, n_frames - 1}
        | {
            i * max(1, n_frames // max(1, samples))
            for i in range(min(samples, n_frames))
        }
    )
    with open(path, "rb") as fh:
        for idx in probes:
            if idx < 0 or idx >= n_frames:
                continue
            off = layout.header_size + idx * layout.frame_size
            if layout.has_cell:
                n, ok = _record(fh, off)
                if not ok or n != 48:
                    return (False, f"frame {idx}: bad unit-cell record at {off}")
                off += 56
            for axis in "xyz":
                n, ok = _record(fh, off)
                if not ok or n != 4 * layout.n_atoms:
                    return (False, f"frame {idx}: bad {axis} record at {off}")
                off += 8 + n
    return (True, f"{n_frames} complete frames validated")


def validate_partial(path: str | Path) -> tuple[bool, str]:
    """Format-aware structural check.  Unknown formats are accepted (nothing to check)."""
    if str(path).endswith(".dcd.part") or str(path).endswith(".dcd"):
        return dcd_prefix_is_valid(path)
    return (True, "no structural validator for this format")


def is_transfer_artifact(name: str) -> bool:
    """Is this filename transfer scratch rather than a result?

    ``.part`` partials, their quarantined siblings and their sidecars all live beside the
    real file in ``output/``.  Anything that inventories or uploads that directory must
    skip them, or a rejected 80 GB partial counts as a downloaded result.
    """
    return name.endswith((".part", ".part.rejected")) or ".part.resume." in name
