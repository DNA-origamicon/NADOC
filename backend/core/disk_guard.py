"""Disk-space policy + output-size estimation for long-running MD/oxDNA jobs.

Two jobs on one topic — "will this simulation run out of disk, and stop it if it
does":

  1. *Forecast* (before a run): estimate the trajectory + restart bytes a NAMD or
     oxDNA run will write, compare against free space, and flag when it would
     leave the disk below :data:`WARN_MIN_FREE_BYTES` (10 GB).  The panels turn a
     flagged forecast into a Continue/Cancel popup.
  2. *Guard* (during a run): poll free space while a segment/stage runs and abort
     the process when it drops below :data:`ABORT_MIN_FREE_BYTES` (5 GB), so a
     runaway solvated trajectory can't fill the disk and wedge the machine.

Pure accounting + a subprocess-wait wrapper — this module never mutates a job's
topology or status; the runners own that (three-layer law: physical layer only).

One reason to change: the disk-space policy (thresholds) or how output size is
estimated.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

# ── Thresholds ─────────────────────────────────────────────────────────────────
GiB = 1024 ** 3

#: Warn (Continue/Cancel popup) when a run's forecast would leave less than this
#: much free disk.
WARN_MIN_FREE_BYTES = 10 * GiB

#: Abort a running segment/stage when free disk drops below this floor.  Set below
#: the warn threshold so a run that was borderline-OK at launch still gets several
#: GB of runway before the guard trips.
ABORT_MIN_FREE_BYTES = 5 * GiB

#: How often the in-run guard samples free space (seconds).
GUARD_POLL_S = 15.0

#: Sentinel returncode meaning "the run was killed because free disk fell below
#: :data:`ABORT_MIN_FREE_BYTES`" — distinct from a real NAMD/oxDNA crash so the
#: runner can report it plainly instead of routing it through crash-retry logic.
DISK_ABORT_RC = -99


def free_bytes(path: Path) -> int:
    """Free bytes on the filesystem holding ``path`` (walks up to the nearest
    existing ancestor so a not-yet-created job/output dir still measures its
    target volume).  Returns a large sentinel if the volume can't be stat'd, so a
    stat hiccup never spuriously aborts a run."""
    p = Path(path)
    while not p.exists():
        if p.parent == p:
            break
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 1 << 62  # unknowable → treat as plenty; never abort on a stat error


# ── Output-size estimation ──────────────────────────────────────────────────────

# NAMD DCD: per frame, three single-precision coordinate blocks, each wrapped in
# 4-byte Fortran record markers (n_atoms*4 + 8), plus a ~56-byte periodic unit-cell
# block.  ≈ 12*n_atoms + 80 bytes/frame.
_NAMD_DCD_FRAME_OVERHEAD = 80
# Per segment NAMD persists a binary restart set (.coor + .vel), each n_atoms*3
# doubles ≈ 24*n_atoms bytes.
_NAMD_RESTART_BYTES_PER_ATOM = 48
# A safety factor covering logs, .xst, colvars and estimation slop.
_SAFETY = 1.15


def namd_run_output_bytes(segments, n_atoms: int) -> int:
    """Estimated bytes a NAMD run writes, given its ``segments`` and atom count.

    ``segments`` is an iterable of objects (or (steps, dcd_freq) tuples) exposing
    ``steps`` and ``dcd_freq``.  Sums each segment's DCD trajectory plus one
    persisted restart set; applies a modest safety factor.
    """
    if n_atoms <= 0:
        return 0
    frame_bytes = 12 * n_atoms + _NAMD_DCD_FRAME_OVERHEAD
    total = 0
    for seg in segments:
        steps, dcd_freq = _steps_and_freq(seg)
        frames = steps // max(1, dcd_freq)
        total += frames * frame_bytes
        total += _NAMD_RESTART_BYTES_PER_ATOM * n_atoms
    return int(total * _SAFETY)


# oxDNA trajectory.dat: one text line per particle per config (~15 floats),
# ≈130 bytes/particle, plus a 3-line config header.
_OXDNA_CONF_BYTES_PER_NT = 130
_OXDNA_CONF_HEADER_BYTES = 80


def oxdna_run_output_bytes(stages, n_nucleotides: int) -> int:
    """Estimated bytes an oxDNA run writes, given its ``stages`` and particle count.

    ``stages`` is an iterable of (steps, print_conf_interval) tuples.  oxDNA prints
    ~100 configs/stage regardless of length, so this stays small; the estimate
    still matters when the disk is already near-full from other data.
    """
    if n_nucleotides <= 0:
        return 0
    per_frame = n_nucleotides * _OXDNA_CONF_BYTES_PER_NT + _OXDNA_CONF_HEADER_BYTES
    total = 0
    for steps, interval in stages:
        frames = int(steps) // max(1, int(interval))
        total += frames * per_frame
        total += per_frame  # last_conf.dat
    return int(total * _SAFETY)


def _steps_and_freq(seg) -> tuple[int, int]:
    if isinstance(seg, (tuple, list)):
        return int(seg[0]), int(seg[1])
    return int(seg.steps), int(getattr(seg, "dcd_freq", 0) or 1)


# ── Forecast (before a run) ──────────────────────────────────────────────────────

def forecast(target_dir: Path, predicted_bytes: int) -> dict:
    """Compare a run's predicted output against free space on its target volume.

    Returns a JSON-ready dict the frontend renders into a Continue/Cancel popup.
    ``warn`` is true when finishing the run would leave the disk below the 10 GB
    warn threshold.
    """
    fb = free_bytes(target_dir)
    predicted = max(0, int(predicted_bytes))
    after = fb - predicted
    return {
        "free_bytes": fb,
        "predicted_bytes": predicted,
        "free_after_bytes": after,
        "warn": after < WARN_MIN_FREE_BYTES,
        "warn_threshold_bytes": WARN_MIN_FREE_BYTES,
        "abort_threshold_bytes": ABORT_MIN_FREE_BYTES,
        # When the run won't comfortably fit, point the user at a roomier volume so the UI
        # can offer "archive & run there" instead of just Continue/Cancel.
        "suggested_archive": (suggest_archive_dir(target_dir, predicted)
                              if after < WARN_MIN_FREE_BYTES else None),
    }


def _safe_iterdir(p: Path) -> list[Path]:
    try:
        return list(p.iterdir())
    except OSError:
        return []


def _candidate_volumes() -> list[Path]:
    """Mounted volumes a big run could be redirected to: external/removable drives under
    /media/<user>/<drive> and /mnt/<drive>, plus the home directory."""
    out: list[Path] = []
    for base in ("/media", "/mnt"):
        b = Path(base)
        if not b.is_dir():
            continue
        for lvl1 in _safe_iterdir(b):        # /media/<user>  or  /mnt/<drive>
            if lvl1.is_dir():
                out.append(lvl1)
                for lvl2 in _safe_iterdir(lvl1):   # /media/<user>/<drive>
                    if lvl2.is_dir():
                        out.append(lvl2)
    out.append(Path.home())
    return out


def suggest_archive_dir(target_dir: Path, predicted_bytes: int) -> "dict | None":
    """A roomier, writable volume on a DIFFERENT filesystem than ``target_dir`` that has room
    for the run — for the low-disk popup's "archive to a larger drive and run there" prompt.
    Returns ``{path, free_bytes}`` of the emptiest qualifying volume, or ``None`` if none is
    clearly better (so the popup falls back to plain Continue/Cancel)."""
    try:
        tp = Path(target_dir)
        while not tp.exists() and tp.parent != tp:
            tp = tp.parent
        target_dev = os.stat(tp).st_dev
    except OSError:
        target_dev = None
    need = max(0, int(predicted_bytes)) + WARN_MIN_FREE_BYTES
    best: "dict | None" = None
    for r in _candidate_volumes():
        try:
            if not r.is_dir() or not os.access(r, os.W_OK):
                continue
            if target_dev is not None and os.stat(r).st_dev == target_dev:
                continue                     # same disk → no help
            fb = shutil.disk_usage(r).free
            if fb >= need and (best is None or fb > best["free_bytes"]):
                best = {"path": str(r), "free_bytes": fb}
        except OSError:
            continue
    return best


# ── Guard (during a run) ─────────────────────────────────────────────────────────

async def wait_proc_with_disk_guard(
    proc,
    guard_dir: Path,
    *,
    kill,
    poll_s: float = GUARD_POLL_S,
    min_free_bytes: int = ABORT_MIN_FREE_BYTES,
) -> int:
    """``await proc.wait()`` while polling free disk every ``poll_s`` seconds.

    If free space on ``guard_dir``'s volume drops below ``min_free_bytes``, call
    ``kill(proc.pid)`` (the runner's process-group killer) and return
    :data:`DISK_ABORT_RC`.  Otherwise returns the process's real returncode.
    ``asyncio.CancelledError`` (a user stop / server shutdown) propagates so the
    caller's existing cancellation cleanup runs unchanged.
    """
    while True:
        try:
            # Cancelling this wait on timeout does not signal the OS process — it
            # keeps running; the next loop simply re-awaits it.
            return await asyncio.wait_for(proc.wait(), timeout=poll_s)
        except asyncio.TimeoutError:
            if free_bytes(guard_dir) < min_free_bytes:
                kill(proc.pid)
                try:
                    await proc.wait()
                except Exception:  # noqa: BLE001 — process already reaped is fine
                    pass
                return DISK_ABORT_RC
