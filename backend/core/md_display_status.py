"""Why the MD live display has nothing to show.

``GET /md/jobs/{id}/display`` reported a bare ``ready: false`` and nothing else, so the
panel's readiness dot collapsed to "off" — i.e. it HID ITSELF — for every job that was not
yet displayable. A run going on a rented GPU therefore looked identical to no job at all:
toggle Display MD, get nothing, no explanation anywhere.

The four not-ready cases are genuinely different and only one of them is a problem:

  ``no_package``  the package was never built — nothing exists to display
  ``pending``     built, running here, no frames written yet — this resolves on its own
  ``remote``      built and running on a pod/cluster; the trajectory is THERE, not here.
                  Waiting will not help: it needs a fetch (or the one-frame live fetch)
  ``empty``       the run reached a terminal state having written no trajectory at all —
                  the only case that means something went wrong

Pure and separately tested; the route supplies the facts, the panel picks the wording.
"""

from __future__ import annotations

from typing import Optional

# Statuses in which more frames may still appear.
_IN_FLIGHT = {"running", "preparing", "queued"}


def display_not_ready(
    *,
    has_manifest: bool,
    has_trajectory: bool,
    status: str,
    execution_target: str = "local",
    has_live_frame: bool = False,
) -> Optional[dict]:
    """``{"code", "reason"}`` explaining an un-displayable job, or ``None`` when it is fine.

    ``has_live_frame`` matters because a single fetched frame from a remote run IS
    displayable — it is just not a trajectory, and it does not advance on its own.
    """
    if has_manifest and (has_trajectory or has_live_frame):
        return None
    if not has_manifest:
        return {
            "code": "no_package",
            "reason": "No package built for this job yet — nothing to display.",
        }
    remote = execution_target in ("alpine", "runpod")
    in_flight = status in _IN_FLIGHT
    if remote and in_flight:
        # RunPod auth is key-based, so NADOC can reach the pod whenever it likes and the
        # panel pulls a snapshot by itself on a timer. Alpine is Duo-gated — there is no
        # background session, so a frame only arrives when the user is signed in and asks.
        # Saying "fetch a live frame" at a RunPod user described work already in progress.
        if execution_target == "runpod":
            return {
                "code": "remote",
                "reason": "Fetching the latest frame from the pod…",
            }
        return {
            "code": "remote",
            "reason": (
                "This run's trajectory is on the cluster, not on this computer. Fetch a "
                "live frame to see where it has got to, or fetch the results when it "
                "finishes."
            ),
        }
    if in_flight:
        return {
            "code": "pending",
            "reason": "Running — no frames written yet. The display starts once the first "
            "trajectory frame lands.",
        }
    if remote:
        return {
            "code": "remote",
            "reason": (
                "Nothing fetched from "
                + ("the pod" if execution_target == "runpod" else "the cluster")
                + " yet. Fetch this run's results to display it."
            ),
        }
    return {
        "code": "empty",
        "reason": "This run wrote no trajectory, so there is nothing to display.",
    }
