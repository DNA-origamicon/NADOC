"""Storage forecast for a RunPod NAMD run — what it writes, where it lands, what it costs.

Three distinct storage facts matter before renting, and none of them were visible anywhere:

1. **What the run writes.** DCD trajectories plus one restart set per segment. This is the same
   arithmetic the local runner already forecasts against a local disk, so it is reused verbatim
   from :func:`backend.core.disk_guard.namd_run_output_bytes` rather than re-derived — one
   formula, one place to fix.

2. **Where it lands.** ``REMOTE_ROOT=/workspace/nadoc_jobs`` is on the NETWORK VOLUME, not the
   pod's container disk, which is why staged inputs and outputs survive the pod dying. The
   volume is a fixed-size rental (50 GB in the current setup), so a long production run can
   fill it — and NAMD dies mid-run when it does.

   ⚠️ **The RunPod REST API reports a volume's SIZE but not its USAGE**
   (``parse_network_volume`` → ``size_gb`` only). Measuring free space needs a live pod, which
   costs money. So ``used_gb`` is an OPTIONAL input, and when it is absent this module says
   ``used_known: False`` rather than quietly assuming an empty volume — a forecast that assumes
   50 GB free on a volume already holding three checkpoint sets is exactly the kind of
   confident-wrong number that gets a run killed at hour six.

3. **Staging is billable.** The package uploads over SFTP at domestic upstream speed while the
   GPU sits idle and billing. On the 1.94M-atom run that was 1.21 GB ≈ 15 min ≈ $0.20 before
   NAMD ran a single step (RUNBOOK §6). Small in absolute terms, but it is the one cost that is
   pure waste, and seeing it is what motivates re-using an already-staged job_id.

Everything here is pure — the route supplies the volume list and the stage table.
"""

from __future__ import annotations

from typing import Iterable, Optional

from backend.core.disk_guard import namd_run_output_bytes

GB = 1024**3

# Measured, not guessed: 1.21 GB of package took ~15 min of pod time on the 3x6x400 run
# (RUNBOOK §6) => ~10.8 Mbps sustained. Rounded to 11 and kept overridable, because the
# figure is a property of the user's uplink, not of RunPod.
DEFAULT_UPLOAD_MBPS = 11.0

# Leave the volume some slack. NAMD does not fail gracefully on a full filesystem — it dies
# mid-segment, and on a rented pod that means paying for the restart too.
VOLUME_HEADROOM_GB = 2.0


def staging_estimate(
    package_bytes: int,
    *,
    usd_per_hour: Optional[float] = None,
    upload_mbps: float = DEFAULT_UPLOAD_MBPS,
) -> dict:
    """Upload time and billed cost for staging a package onto the network volume.

    ``usd_per_hour`` is the rate of the card the user is looking at, so the dollar figure moves
    with the selection. ``None`` (unknown rate) gives minutes without a cost rather than a
    made-up one.
    """
    if package_bytes <= 0 or upload_mbps <= 0:
        return {
            "bytes": max(0, int(package_bytes)),
            "minutes": None,
            "usd": None,
            "upload_mbps": upload_mbps,
        }
    minutes = (package_bytes * 8.0) / (upload_mbps * 1e6) / 60.0
    usd = (minutes / 60.0) * usd_per_hour if usd_per_hour else None
    return {
        "bytes": int(package_bytes),
        "minutes": round(minutes, 1),
        "usd": round(usd, 2) if usd is not None else None,
        "upload_mbps": upload_mbps,
    }


def storage_estimate(
    *,
    stages: Iterable,
    n_atoms: int,
    package_bytes: int = 0,
    volume_size_gb: Optional[int] = None,
    volume_used_gb: Optional[float] = None,
    usd_per_hour: Optional[float] = None,
    upload_mbps: float = DEFAULT_UPLOAD_MBPS,
) -> dict:
    """What this run needs on the network volume, and whether it fits.

    ``stages`` is anything :func:`namd_run_output_bytes` accepts — objects with ``.steps`` /
    ``.dcd_freq``, or ``(steps, dcd_freq)`` tuples, which is the shape the wizard's plan table
    hands over directly.

    ``warn`` is true only when we can actually SHOW a problem: a volume too small for the run
    plus its headroom. When usage is unknown the check is against total size, and
    ``used_known`` is false so the UI can say so instead of implying a measurement.
    """
    output_bytes = namd_run_output_bytes(stages, n_atoms) if n_atoms > 0 else 0
    staging = staging_estimate(
        package_bytes, usd_per_hour=usd_per_hour, upload_mbps=upload_mbps
    )
    needed_bytes = output_bytes + max(0, int(package_bytes))

    size_bytes = int(volume_size_gb) * GB if volume_size_gb else None
    used_bytes = int(volume_used_gb * GB) if volume_used_gb is not None else None
    free_bytes = (
        (size_bytes - used_bytes)
        if (size_bytes is not None and used_bytes is not None)
        else size_bytes
    )
    free_after = (free_bytes - needed_bytes) if free_bytes is not None else None

    warn = False
    reason = ""
    if free_after is not None and free_after < VOLUME_HEADROOM_GB * GB:
        warn = True
        reason = (
            f"This run needs about {needed_bytes / GB:.1f} GB but the volume has "
            f"{max(0.0, (free_bytes or 0) / GB):.1f} GB"
            + ("" if used_bytes is not None else " in total")
            + ". NAMD dies mid-segment on a full volume."
        )

    return {
        "output_bytes": int(output_bytes),
        "package_bytes": max(0, int(package_bytes)),
        "needed_bytes": int(needed_bytes),
        "volume_size_gb": volume_size_gb,
        "volume_used_gb": volume_used_gb,
        "used_known": used_bytes is not None,
        "free_bytes": free_bytes,
        "free_after_bytes": free_after,
        "headroom_gb": VOLUME_HEADROOM_GB,
        "staging": staging,
        "warn": warn,
        "reason": reason,
    }
