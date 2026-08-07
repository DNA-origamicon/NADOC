"""Pull ONE current frame off a running cluster job so the viewport can show it.

A remote run's trajectory never leaves the cluster while it is in flight, and it
cannot: the DCD grows without bound (2.9 GB after ~90 min on a 1.3M-atom job), so
streaming it is not an option, and ``md_executor.fetch_outputs`` deliberately runs
only at terminal states.  The consequence today is that a running Alpine job shows
"Waiting for trajectory output" in the viewport for its entire duration.

But NAMD also rewrites ``output/<segment>.restart.coor`` every ``restartfreq`` steps
(5_000 — ``md_protocols._RESTART_EVERY_STEPS``, a few minutes apart).  That is a
single frame, int32 count + N x 3 float64 = 24 bytes/atom: ~32 MB for the same job
whose DCD is 2.9 GB, and unlike the DCD it never grows.  Pulling one on demand and
writing it as a one-frame DCD delivers the one thing a user actually wants from a
job still on the cluster — the current shape of the design.

**Why on demand and not on a timer.**  Cluster auth is Duo-gated, so there is no
background session to stream into; NADOC can only talk to Alpine while the user is
signed in.  The natural cadence is therefore "when the user logs in and looks", not
"every N seconds".  Callers fire this on connect and on job selection.

**Why it writes to the real trajectory path.**  ``output/<segment>.dcd`` is exactly
where ``fetch_outputs`` will later put the real thing, and writing there is what
lets ``_latest_display_segment`` / ``resolve_md_config`` / ``ws.py`` / ``md_panel``
work completely unchanged — no display code knows this feature exists.  The price is
that a one-frame stand-in would otherwise be indistinguishable from real results, so
every write is recorded in ``job.live_frame`` and guarded two ways:
``_segment_has_trajectory`` refuses to compute health off a marked segment, and this
module refuses to overwrite a real trajectory with a stand-in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# NAMD only rewrites .restart.coor every restartfreq steps, so re-pulling faster
# than that just moves identical bytes across the wire.  The display's 15 s tick
# would otherwise re-fetch ~32 MB four times a minute for nothing.
MIN_REFETCH_INTERVAL_S = 60.0


def _manifest(package_dir: Path) -> dict:
    """The package manifest, or ``{}`` — mirrors the lookup order in routes_md."""
    for name in ("nadoc_md_run.json", "manifest.json"):
        path = package_dir / name
        if path.is_file():
            try:
                return json.loads(path.read_text(errors="replace"))
            except (OSError, ValueError):
                return {}
    return {}


def active_segment_name(job) -> str | None:
    """Which segment is on the node *right now*.

    The node-side collector reports this (basename of the newest ``*.log``) and it is
    the authoritative answer.  ``current_segment_idx`` lags: it only advances when a
    segment is observed COMPLETE, which on a short-walltime ladder may not happen
    inside a block at all — the exact case this feature exists for.
    """
    seg = (job.live_metrics or {}).get("segment")
    if seg:
        return str(seg)
    segments = job.segments or []
    if not segments:
        return None
    idx = min(max(int(job.current_segment_idx or 0), 0), len(segments) - 1)
    return segments[idx].name


def is_live_stand_in(job, segment_name: str) -> bool:
    """True if this segment's local DCD is a fetched single frame, not real results."""
    live = getattr(job, "live_frame", None) or {}
    return live.get("segment") == segment_name


def clear_live_frame(job, segment_name: str | None = None) -> None:
    """Drop the stand-in marker once real outputs land (``fetch_outputs``).

    Without this the marker would outlive the file it describes, and the next call
    here would happily overwrite a real fetched trajectory with a single frame.
    """
    live = getattr(job, "live_frame", None) or {}
    if live and (segment_name is None or live.get("segment") == segment_name):
        job.live_frame = None


def _write_single_frame_dcd(topology: Path, coor: Path, dest: Path) -> int:
    """NAMD binary ``.coor`` + PSF -> a one-frame DCD at ``dest``.  Returns atom count.

    Blocking and slow (a 180 MB solvated PSF parses in ~5 s), so callers run it off
    the event loop.
    """
    import MDAnalysis as mda  # noqa: PLC0415 — heavy import, deferred

    universe = mda.Universe(str(topology), str(coor), format="NAMDBIN")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target and rename: the display polls every 15 s and must
    # never open a half-written DCD.  `format` is explicit because MDAnalysis infers
    # it from the extension, and the temp name's is ".part".
    tmp = dest.with_name(dest.name + ".part")
    with mda.Writer(str(tmp), n_atoms=universe.atoms.n_atoms, format="DCD") as writer:
        writer.write(universe.atoms)
    tmp.replace(dest)
    return int(universe.atoms.n_atoms)


async def fetch_live_frame(job, workspace_dir: Path, *, conn=None, force: bool = False) -> dict:
    """Fetch the running segment's current frame and materialise it for display.

    Returns a small status dict; raises ``ValueError`` for a job this cannot apply to
    and lets ``ClusterSSHError`` propagate so the route can map it to a 502.
    """
    from backend.core import md_executor, md_import  # noqa: PLC0415 — cycle

    if job.execution_target == "local":
        raise ValueError("Local job — its trajectory is already on this machine.")
    scratch = job.remote_scratch_dir
    if not scratch:
        raise ValueError("Job has no remote scratch directory.")
    segment = active_segment_name(job)
    if not segment:
        raise ValueError("Job has no segments to fetch a frame from.")

    package_dir = job.package_dir(workspace_dir)
    dest = package_dir / "output" / f"{segment}.dcd"

    # A real fetched trajectory outranks anything this module can produce.
    if dest.is_file() and not is_live_stand_in(job, segment):
        return {"ok": True, "segment": segment, "skipped": "real trajectory already local"}

    previous = getattr(job, "live_frame", None) or {}
    if (
        not force
        and dest.is_file()
        and previous.get("segment") == segment
        and time.time() - float(previous.get("fetched_at") or 0) < MIN_REFETCH_INTERVAL_S
    ):
        return {"ok": True, "reused": True, **previous}

    topology = md_import.resolve_topology(
        package_dir, _manifest(package_dir).get("files"), job.name_stem
    )
    if not topology:
        raise ValueError(f"No PSF in {package_dir} to pair the frame with.")

    conn = conn or md_executor._default_conn()
    tmp_coor = job.job_dir(workspace_dir) / f"_live_frame_{segment}.coor"
    tmp_coor.parent.mkdir(parents=True, exist_ok=True)
    try:
        await conn.sftp_get(f"{scratch}/output/{segment}.restart.coor", str(tmp_coor))
    except Exception as exc:  # noqa: BLE001 — no checkpoint written yet is normal
        logger.info("[%s] no live frame for %s: %s", job.job_id, segment, exc)
        tmp_coor.unlink(missing_ok=True)
        return {"ok": False, "segment": segment, "reason": "no restart checkpoint on the node yet"}

    try:
        n_atoms = await asyncio.to_thread(_write_single_frame_dcd, topology, tmp_coor, dest)
    finally:
        tmp_coor.unlink(missing_ok=True)

    job.live_frame = {
        "segment": segment,
        "step": (job.live_metrics or {}).get("step"),
        "n_atoms": n_atoms,
        "fetched_at": time.time(),
    }
    logger.info("[%s] live frame: %s step %s (%d atoms)",
                job.job_id, segment, job.live_frame["step"], n_atoms)
    return {"ok": True, **job.live_frame}
