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
import math
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


# ── The stand-in marker ───────────────────────────────────────────────────────
# The marker lives BESIDE the file it describes, not only in ``job.live_frame``.
#
# ⚠️ Why: ``job.json`` has two writers. The supervisor loop (``runpod_executor
# ._supervise_run`` / ``md_executor``) holds its own in-memory ``MdJob`` and re-saves the
# WHOLE record every poll, so a field written out-of-band by a route is silently reverted
# within ~30 s. That is exactly what happened: the fetch route set ``job.live_frame``, the
# supervisor's next save wiped it, and the following fetch then saw a DCD it no longer
# recognised as a stand-in and refused to refresh it —
# ``{"ok": true, "skipped": "real trajectory already local"}`` forever. The display froze
# on its first snapshot and reported success the whole time.
#
# A sidecar has one writer and describes the one thing that matters (this FILE is a single
# fetched frame), so it cannot drift from it. ``job.live_frame`` is still written, because
# it is the display payload the panel reads; the sidecar is the AUTHORITY.
_MARKER_SUFFIX = ".live.json"


def marker_path(package_dir: Path, segment_name: str) -> Path:
    return package_dir / "output" / f"{segment_name}.dcd{_MARKER_SUFFIX}"


def read_marker(package_dir: Path, segment_name: str) -> dict | None:
    """The stand-in record for this segment, or ``None``. Never raises."""
    path = marker_path(package_dir, segment_name)
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def is_live_stand_in(job, segment_name: str, package_dir: Path | None = None) -> bool:
    """True if this segment's local DCD is a fetched single frame, not real results.

    Checks the sidecar FIRST when the caller can name the package; ``job.live_frame`` is
    the fallback for callers that cannot, and for records written before the sidecar
    existed.
    """
    if package_dir is not None and read_marker(package_dir, segment_name) is not None:
        return True
    live = getattr(job, "live_frame", None) or {}
    return live.get("segment") == segment_name


def clear_live_frame(
    job, segment_name: str | None = None, package_dir: Path | None = None
) -> None:
    """Drop the stand-in marker once real outputs land (``fetch_outputs``).

    Without this the marker would outlive the file it describes, and the next call
    here would happily overwrite a real fetched trajectory with a single frame.
    """
    live = getattr(job, "live_frame", None) or {}
    if live and (segment_name is None or live.get("segment") == segment_name):
        job.live_frame = None
    if package_dir is None:
        return
    names = [segment_name] if segment_name else [s.name for s in (job.segments or [])]
    for name in names:
        marker_path(package_dir, name).unlink(missing_ok=True)


def parse_xsc_dimensions(text: str) -> list[float] | None:
    """MDAnalysis ``dimensions`` — ``[lx, ly, lz, alpha, beta, gamma]`` — from a NAMD
    ``.xsc``, or ``None`` if it cannot be read.

    ⚠️ **Without this the snapshot is unusable.** A NAMD ``.coor`` (NAMDBIN) is
    coordinates and nothing else, so the DCD written from one carries a ZEROED unit
    cell. ``ws._try_unwrap`` registers MDAnalysis' ``unwrap`` transformation for any
    system under 200k atoms, and that transformation raises *"No box information
    available"* on the first frame access — which happens inside the load, so the whole
    load fails and every later poll answers *"No trajectory loaded."* A real NAMD DCD has
    the box, which is why only the live-snapshot path was affected.

    The ``.xsc`` sits beside the ``.restart.coor`` and is rewritten with it, so it is the
    box AT THAT STEP — which matters under NPT, where the cell is still breathing.

    Columns are ``step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z``; the last
    non-comment line is the current one.
    """
    row = None
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            row = line.split()
    if not row or len(row) < 10:
        return None
    try:
        a = [float(v) for v in row[1:4]]
        b = [float(v) for v in row[4:7]]
        c = [float(v) for v in row[7:10]]
    except ValueError:
        return None

    def _norm(v):
        return math.sqrt(sum(x * x for x in v))

    def _angle(u, v):
        nu, nv = _norm(u), _norm(v)
        if nu == 0 or nv == 0:
            return 90.0
        cos = sum(x * y for x, y in zip(u, v)) / (nu * nv)
        return math.degrees(math.acos(max(-1.0, min(1.0, cos))))

    la, lb, lc = _norm(a), _norm(b), _norm(c)
    if min(la, lb, lc) <= 0:
        return None
    return [la, lb, lc, _angle(b, c), _angle(a, c), _angle(a, b)]


def _write_single_frame_dcd(
    topology: Path, coor: Path, dest: Path, dimensions: list[float] | None = None
) -> int:
    """NAMD binary ``.coor`` + PSF -> a one-frame DCD at ``dest``.  Returns atom count.

    Blocking and slow (a 180 MB solvated PSF parses in ~5 s), so callers run it off
    the event loop.
    """
    import MDAnalysis as mda  # noqa: PLC0415 — heavy import, deferred

    universe = mda.Universe(str(topology), str(coor), format="NAMDBIN")
    if dimensions is not None:
        # See parse_xsc_dimensions: a boxless frame fails the display load outright.
        universe.dimensions = dimensions
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target and rename: the display polls every 15 s and must
    # never open a half-written DCD.  `format` is explicit because MDAnalysis infers
    # it from the extension, and the temp name's is ".part".
    tmp = dest.with_name(dest.name + ".part")
    with mda.Writer(str(tmp), n_atoms=universe.atoms.n_atoms, format="DCD") as writer:
        writer.write(universe.atoms)
    tmp.replace(dest)
    return int(universe.atoms.n_atoms)


async def fetch_live_frame(
    job, workspace_dir: Path, *, conn=None, force: bool = False
) -> dict:
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
    if dest.is_file() and not is_live_stand_in(job, segment, package_dir):
        return {
            "ok": True,
            "segment": segment,
            "skipped": "real trajectory already local",
        }

    # The sidecar, not job.live_frame: the supervisor's whole-record save reverts the
    # latter within a poll, and pacing off a reverted timestamp means re-fetching ~32 MB
    # on every single tick.
    previous = (
        read_marker(package_dir, segment) or getattr(job, "live_frame", None) or {}
    )
    if (
        not force
        and dest.is_file()
        and previous.get("segment") == segment
        and time.time() - float(previous.get("fetched_at") or 0)
        < MIN_REFETCH_INTERVAL_S
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
        return {
            "ok": False,
            "segment": segment,
            "reason": "no restart checkpoint on the node yet",
        }

    # The box, from the .xsc written alongside the .coor. Best-effort: a snapshot with a
    # stale box beats no snapshot, and an older run may not have one. But see
    # parse_xsc_dimensions — without it the display cannot load the frame at all, so a
    # miss is worth a warning.
    tmp_xsc = job.job_dir(workspace_dir) / f"_live_frame_{segment}.xsc"
    dimensions = None
    try:
        await conn.sftp_get(f"{scratch}/output/{segment}.restart.xsc", str(tmp_xsc))
        dimensions = parse_xsc_dimensions(tmp_xsc.read_text(errors="replace"))
    except Exception as exc:  # noqa: BLE001 — a missing .xsc must not lose the frame
        logger.warning("[%s] no .xsc for %s: %s", job.job_id, segment, exc)
    finally:
        tmp_xsc.unlink(missing_ok=True)
    if dimensions is None:
        logger.warning(
            "[%s] live frame for %s has NO unit cell — the display will refuse it",
            job.job_id,
            segment,
        )

    try:
        n_atoms = await asyncio.to_thread(
            _write_single_frame_dcd, topology, tmp_coor, dest, dimensions
        )
    finally:
        tmp_coor.unlink(missing_ok=True)

    job.live_frame = {
        "segment": segment,
        "step": (job.live_metrics or {}).get("step"),
        "n_atoms": n_atoms,
        "fetched_at": time.time(),
    }
    # Write the sidecar BEFORE returning: it, not the job record, is what the next call
    # consults to decide whether this DCD may be overwritten.
    try:
        marker_path(package_dir, segment).write_text(json.dumps(job.live_frame))
    except OSError as exc:  # noqa: BLE001 — a frame we cannot mark is still a frame
        logger.warning("[%s] could not write live-frame marker: %s", job.job_id, exc)
    logger.info(
        "[%s] live frame: %s step %s (%d atoms)",
        job.job_id,
        segment,
        job.live_frame["step"],
        n_atoms,
    )
    return {"ok": True, **job.live_frame}
