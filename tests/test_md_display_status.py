"""Why the MD live display has nothing to show (backend/core/md_display_status).

The bug this closes: ``GET /md/jobs/{id}/display`` returned a bare ``ready: false``, the
panel collapsed that to "off", and "off" HIDES the readiness dot — so a run going on a
rented GPU looked exactly like no job at all. Only one of the four not-ready cases is
actually a problem, and they need different words.
"""

from __future__ import annotations

from backend.core.md_display_status import display_not_ready


def _r(**kw):
    base = dict(has_manifest=True, has_trajectory=False, status="running")
    base.update(kw)
    return display_not_ready(**base)


def test_a_displayable_job_has_no_complaint():
    assert (
        display_not_ready(has_manifest=True, has_trajectory=True, status="completed")
        is None
    )


def test_a_single_fetched_frame_counts_as_displayable():
    """One frame off a running remote job IS something to draw — it just does not
    advance on its own."""
    assert _r(has_trajectory=False, has_live_frame=True) is None


def test_no_package_is_not_an_error_it_is_an_absence():
    v = _r(has_manifest=False)
    assert v["code"] == "no_package"
    assert "nothing to display" in v["reason"].lower()


def test_a_local_run_with_no_frames_yet_resolves_itself():
    v = _r(execution_target="local")
    assert v["code"] == "pending"
    assert "no frames" in v["reason"].lower()


def test_a_running_runpod_job_offers_manual_refresh():
    v = _r(execution_target="runpod")
    assert v["code"] == "remote"
    assert "pod" in v["reason"].lower()
    assert "refresh" in v["reason"].lower()
    assert "not on this computer" not in v["reason"].lower()


def test_an_alpine_run_says_cluster_not_pod():
    v = _r(execution_target="alpine")
    assert v["code"] == "remote"
    assert "alpine" in v["reason"].lower()
    assert "refresh" in v["reason"].lower()
    assert "pod" not in v["reason"].lower()


def test_a_finished_remote_run_asks_for_a_fetch():
    v = _r(execution_target="runpod", status="completed")
    assert v["code"] == "remote"
    assert "fetch" in v["reason"].lower()


def test_a_finished_local_run_with_no_trajectory_is_an_error():
    """The one case that means something went wrong: it will never have frames."""
    v = _r(execution_target="local", status="failed")
    assert v["code"] == "empty"
    assert "no trajectory" in v["reason"].lower()


def test_every_in_flight_status_counts_as_in_flight():
    for status in ("queued", "preparing", "running"):
        assert _r(execution_target="local", status=status)["code"] == "pending"


def test_every_case_carries_a_human_reason():
    """The code drives the dot; the reason is the only thing that explains it."""
    for kw in (
        {"has_manifest": False},
        {"execution_target": "local"},
        {"execution_target": "runpod"},
        {"execution_target": "local", "status": "failed"},
    ):
        v = _r(**kw)
        # A finished sentence, not a fragment. "…" counts: the RunPod case describes work
        # already under way ("Fetching the latest frame from the pod…"), which is an
        # ongoing action and takes an ellipsis like every other in-progress string in the
        # app — not a full stop.
        assert v["reason"].strip() and v["reason"].rstrip().endswith((".", "…"))
