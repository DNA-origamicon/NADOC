"""Unit tests for backend/core/remote_live_frame.py — the one-frame cluster fetch.

No network and no giant PSF: a FakeConn stands in for the SSH connection, and the
DCD conversion is exercised once against a tiny synthetic system so the round trip
is really pinned rather than mocked away.

The behaviours worth protecting are the guards, not the happy path.  The stand-in
frame is written to the SAME path the real trajectory will occupy, which is what
lets the whole display stack stay unchanged — so every test here is ultimately
about that file never being mistaken for results.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.core import md_executor as ex
from backend.core import md_import, remote_live_frame as rlf


def _run(coro):
    return asyncio.run(coro)


class _Seg:
    def __init__(self, name):
        self.name = name


class _Job:
    """Minimal stand-in for MdJob — only the fields this module reads."""

    def __init__(self, tmp: Path, *, segments=("seg0", "seg1"), target="alpine"):
        self.job_id = "abc123"
        self.execution_target = target
        self.remote_scratch_dir = "/scratch/alpine/u/nadoc_jobs/abc123"
        self.name_stem = "sys"
        self.segments = [_Seg(s) for s in segments]
        self.current_segment_idx = 0
        self.live_metrics = None
        self.live_frame = None
        self._root = tmp

    def package_dir(self, _workspace):
        return self._root / "package"

    def job_dir(self, _workspace):
        return self._root


class _FakeConn:
    def __init__(
        self, *, coor_bytes: bytes | None = b"x" * 8192, xsc_step: int = 285_000
    ):
        self.coor_bytes = coor_bytes
        self.xsc_step = xsc_step
        self.gets: list[str] = []

    async def sftp_get(self, remote, local, on_progress=None):
        self.gets.append(remote)
        if remote.endswith(".xsc"):
            Path(local).write_text(
                "# NAMD\n%d 100 0 0 0 100 0 0 0 100 50 50 50\n" % self.xsc_step
            )
            return
        if self.coor_bytes is None:
            raise FileNotFoundError(remote)
        Path(local).write_bytes(self.coor_bytes)
        if on_progress:
            on_progress(len(self.coor_bytes), len(self.coor_bytes))


def _package(tmp: Path) -> Path:
    pkg = tmp / "package"
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    (pkg / "sys.psf").write_text("psf")
    (pkg / "nadoc_md_run.json").write_text(json.dumps({"files": {}}))
    return pkg


# ── active_segment_name ───────────────────────────────────────────────────────


def test_node_reported_segment_beats_the_index(tmp_path):
    job = _Job(tmp_path)
    job.live_metrics = {"segment": "from_node"}
    job.current_segment_idx = 0
    # The index lags: it only advances when a segment is seen COMPLETE, which on a
    # short-walltime ladder may never happen inside a block.
    assert rlf.active_segment_name(job) == "from_node"


def test_segment_falls_back_to_the_index_and_clamps(tmp_path):
    job = _Job(tmp_path, segments=("a", "b", "c"))
    job.current_segment_idx = 1
    assert rlf.active_segment_name(job) == "b"
    job.current_segment_idx = 99
    assert rlf.active_segment_name(job) == "c"
    job.current_segment_idx = -5
    assert rlf.active_segment_name(job) == "a"


def test_no_segments_gives_no_name(tmp_path):
    assert rlf.active_segment_name(_Job(tmp_path, segments=())) is None


# ── the stand-in marker ───────────────────────────────────────────────────────


def test_marker_is_per_segment(tmp_path):
    job = _Job(tmp_path)
    job.live_frame = {"segment": "seg1"}
    assert rlf.is_live_stand_in(job, "seg1") is True
    assert rlf.is_live_stand_in(job, "seg0") is False


def test_clear_is_scoped_to_the_named_segment(tmp_path):
    job = _Job(tmp_path)
    job.live_frame = {"segment": "seg1"}
    rlf.clear_live_frame(job, "seg0")
    assert job.live_frame is not None  # different segment — untouched
    rlf.clear_live_frame(job, "seg1")
    assert job.live_frame is None


def test_health_refuses_a_stand_in_segment(tmp_path):
    """A one-frame DCD sails past the size floor; RMSF over it would read as 0.0."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "seg1.dcd").write_bytes(b"x" * 20_000)  # well over the 4096 floor
    job = _Job(tmp_path)
    assert ex._segment_has_trajectory(out, "seg1") is True  # no job → unguarded
    assert ex._segment_has_trajectory(out, "seg1", job) is True  # unmarked
    job.live_frame = {"segment": "seg1"}
    assert ex._segment_has_trajectory(out, "seg1", job) is False  # marked → excluded


# ── fetch_live_frame guards ───────────────────────────────────────────────────


def test_local_job_is_rejected(tmp_path):
    job = _Job(tmp_path, target="local")
    with pytest.raises(ValueError, match="already on this machine"):
        _run(rlf.fetch_live_frame(job, tmp_path, conn=_FakeConn()))


def test_missing_scratch_dir_is_rejected(tmp_path):
    job = _Job(tmp_path)
    job.remote_scratch_dir = None
    with pytest.raises(ValueError, match="scratch"):
        _run(rlf.fetch_live_frame(job, tmp_path, conn=_FakeConn()))


def test_a_real_trajectory_is_never_overwritten(tmp_path):
    """The whole point of the marker: results outrank anything this module makes."""
    pkg = _package(tmp_path)
    (pkg / "output" / "seg0.dcd").write_bytes(b"REAL" * 4096)
    job = _Job(tmp_path)
    conn = _FakeConn()
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=conn))
    assert res["skipped"] == "real trajectory already local"
    assert conn.gets == []  # nothing pulled
    assert (pkg / "output" / "seg0.dcd").read_bytes().startswith(b"REAL")


def test_recent_frame_is_reused_rather_than_refetched(tmp_path):
    """NAMD rewrites .restart.coor every ~5k steps; the 15 s display tick must not
    drag 32 MB across the wire four times a minute for identical bytes."""
    pkg = _package(tmp_path)
    (pkg / "output" / "seg0.dcd").write_bytes(b"x" * 20_000)
    job = _Job(tmp_path)
    job.live_frame = {"segment": "seg0", "step": 5000, "fetched_at": time.time()}
    conn = _FakeConn()
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=conn))
    assert res["reused"] is True
    assert conn.gets == []


def test_stale_frame_is_refetched(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    (pkg / "output" / "seg0.dcd").write_bytes(b"x" * 20_000)
    job = _Job(tmp_path)
    job.live_frame = {
        "segment": "seg0",
        "fetched_at": time.time() - rlf.MIN_REFETCH_INTERVAL_S - 1,
    }
    monkeypatch.setattr(rlf, "_write_single_frame_dcd", lambda *a: 42)
    conn = _FakeConn()
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=conn))
    assert res["ok"] is True
    assert res["n_atoms"] == 42
    # The .xsc comes too: a NAMD .coor has no unit cell, and a boxless DCD is one the
    # display refuses to load at all (see test_xsc_gives_the_box_the_display_needs).
    assert conn.gets == [
        "/scratch/alpine/u/nadoc_jobs/abc123/output/seg0.restart.xsc",
        "/scratch/alpine/u/nadoc_jobs/abc123/output/seg0.restart.coor",
    ]


def test_force_bypasses_the_reuse_window(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    (pkg / "output" / "seg0.dcd").write_bytes(b"x" * 20_000)
    job = _Job(tmp_path)
    job.live_frame = {"segment": "seg0", "fetched_at": time.time()}
    monkeypatch.setattr(rlf, "_write_single_frame_dcd", lambda *a: 7)
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=_FakeConn(), force=True))
    assert res.get("reused") is not True
    assert res["n_atoms"] == 7


def test_manual_refresh_keeps_cached_frame_when_remote_step_is_not_newer(tmp_path):
    pkg = _package(tmp_path)
    (pkg / "output" / "seg0.dcd").write_bytes(b"x" * 20_000)
    job = _Job(tmp_path)
    job.live_frame = {"segment": "seg0", "step": 285_000, "fetched_at": 1}
    conn = _FakeConn(xsc_step=285_000)
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=conn, force=True))
    assert res["reused"] is True
    assert res["newer"] is False
    assert conn.gets == [
        "/scratch/alpine/u/nadoc_jobs/abc123/output/seg0.restart.xsc"
    ]


def test_no_checkpoint_yet_is_reported_not_raised(tmp_path):
    """A job that has not reached its first restartfreq is normal, not an error."""
    _package(tmp_path)
    job = _Job(tmp_path)
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=_FakeConn(coor_bytes=None)))
    assert res["ok"] is False
    assert "restart checkpoint" in res["reason"]
    assert job.live_frame is None
    # the temp download must not survive a failed pull
    assert list(tmp_path.glob("_live_frame_*")) == []


def test_successful_fetch_records_the_marker(tmp_path, monkeypatch):
    _package(tmp_path)
    job = _Job(tmp_path)
    job.live_metrics = {"segment": "seg0", "step": 285_000}
    monkeypatch.setattr(rlf, "_write_single_frame_dcd", lambda *a: 1320174)
    res = _run(rlf.fetch_live_frame(job, tmp_path, conn=_FakeConn()))
    assert res["ok"] is True
    assert job.live_frame == {
        "segment": "seg0",
        "step": 285_000,
        "n_atoms": 1320174,
        "fetched_at": pytest.approx(time.time(), abs=10),
    }
    assert list(tmp_path.glob("_live_frame_*")) == []


def test_missing_psf_is_rejected(tmp_path):
    pkg = tmp_path / "package"
    (pkg / "output").mkdir(parents=True)
    (pkg / "nadoc_md_run.json").write_text("{}")
    with pytest.raises(ValueError, match="No PSF"):
        _run(rlf.fetch_live_frame(_Job(tmp_path), tmp_path, conn=_FakeConn()))


# ── the conversion itself, against a real (tiny) system ───────────────────────


def test_coor_to_single_frame_dcd_round_trip(tmp_path):
    """NAMDBIN is converted directly; the huge topology is deliberately not parsed."""
    mda = pytest.importorskip("MDAnalysis")
    import numpy as np

    n = 12
    universe = mda.Universe.empty(n, trajectory=True)
    universe.atoms.positions = np.arange(n * 3, dtype=np.float32).reshape(n, 3)
    pdb, coor = tmp_path / "tiny.pdb", tmp_path / "tiny.coor"
    universe.atoms.write(str(pdb))
    with mda.Writer(str(coor), n_atoms=n, format="NAMDBIN") as writer:
        writer.write(universe.atoms)

    dest = tmp_path / "out" / "seg0.dcd"
    # The converter only validates topology at the outer fetch boundary. Supplying a
    # nonexistent path here proves this hot conversion path does not parse it.
    assert rlf._write_single_frame_dcd(tmp_path / "must-not-be-read.psf", coor, dest) == n

    reread = mda.Universe(str(pdb), str(dest))
    assert len(reread.trajectory) == 1
    assert reread.atoms.positions == pytest.approx(universe.atoms.positions, abs=1e-3)
    assert list(dest.parent.glob("*.part")) == []  # temp cleaned up by rename


def test_resolve_topology_prefers_the_manifest_entry(tmp_path):
    """The frame must be written against the PSF the DISPLAY will open, and a
    package routinely ships two (``X.psf`` and ``X_hmr.psf``)."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a_hmr.psf").write_text("hmr")
    (pkg / "sys.psf").write_text("plain")
    assert (
        md_import.resolve_topology(pkg, {"topology": "sys.psf"}, None).name == "sys.psf"
    )
    assert md_import.resolve_topology(pkg, {}, "sys").name == "sys.psf"
    assert md_import.resolve_topology(pkg, {}, None).name == "a_hmr.psf"  # first glob
    assert md_import.resolve_topology(tmp_path / "empty", {}, None) is None


# ── progress carried forward between sign-ins ────────────────────────────────


def test_projected_step_carries_forward_at_the_measured_rate():
    from backend.core.namd_metrics import projected_step

    # 0.009 s/step for 90 s = 10 000 steps past the last reading.
    assert projected_step(285_000, 0.009, 90.0) == 285_000 + 10_000


def test_projected_step_refuses_to_invent_a_rate():
    """No rate, no extrapolation — a frozen bar beats a fabricated one."""
    from backend.core.namd_metrics import projected_step

    assert projected_step(285_000, None, 90.0) == 285_000
    assert projected_step(285_000, 0.0, 90.0) == 285_000
    assert projected_step(285_000, 0.009, None) == 285_000
    assert projected_step(285_000, 0.009, -5.0) == 285_000  # clock went backwards


def test_projection_never_claims_the_last_one_percent():
    """Reaching 100% would assert a completion nobody observed — the run may have
    crashed or hit its walltime a second after the last report we saw."""
    from backend.core.namd_metrics import projected_step

    # Signed out for a week: the raw projection lands far past the end.
    assert projected_step(285_000, 0.009, 7 * 86_400, cap_steps=500_000) == 495_000
    # A real observation past the ceiling still wins — it was measured, not guessed.
    assert projected_step(499_000, 0.009, 3600, cap_steps=500_000) == 499_000


def test_live_metrics_anchor_uses_nadoc_clock_and_only_moves_on_new_data(monkeypatch):
    """The blob's `collected_at` is the NODE's clock; extrapolation needs ours.
    And an unchanged blob must NOT re-anchor — the run advanced in the meantime."""
    import json as _json
    from backend.core import md_executor as mex

    class _J:
        live_metrics = None

    job = _J()
    monkeypatch.setattr(mex.time, "time", lambda: 1000.0)
    blob = _json.dumps({"step": 285_000, "s_per_step": 0.009, "collected_at": 5.0})
    assert mex.apply_live_metrics(job, blob) is True
    assert job.live_metrics["retrieved_at"] == 1000.0

    monkeypatch.setattr(mex.time, "time", lambda: 2000.0)
    assert mex.apply_live_metrics(job, blob) is False  # identical → no change
    assert job.live_metrics["retrieved_at"] == 1000.0  # anchor NOT moved

    newer = _json.dumps({"step": 295_000, "s_per_step": 0.009, "collected_at": 95.0})
    assert mex.apply_live_metrics(job, newer) is True
    assert job.live_metrics["retrieved_at"] == 2000.0  # re-anchored on real data


def test_remote_projected_step_needs_both_an_anchor_and_a_rate(tmp_path):
    from backend.api.routes_md import _remote_projected_step

    class _J:
        live_metrics = None

    job = _J()
    assert _remote_projected_step(job, 500_000) == (None, False)

    job.live_metrics = {"step": 285_000}  # observed, not extrapolatable
    assert _remote_projected_step(job, 500_000) == (285_000, False)

    job.live_metrics = {
        "step": 285_000,
        "s_per_step": 0.009,
        "retrieved_at": time.time() - 90,
    }
    step, estimated = _remote_projected_step(job, 500_000)
    assert estimated is True
    assert step == pytest.approx(295_000, abs=200)


# ── the unit cell (the reason a snapshot was unusable) ────────────────────────


XSC = """# NAMD extended system configuration output file
#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z
370000 92.5 0 0 0 104.25 0 0 0 130.75 0 0 0
"""


def test_xsc_gives_the_box_the_display_needs():
    """A NAMD .coor is coordinates only, so the DCD written from one has a ZEROED cell.
    ws._try_unwrap then raises "No box information available" on the first frame access,
    the whole load fails, and every poll answers "No trajectory loaded." forever."""
    dims = rlf.parse_xsc_dimensions(XSC)
    assert dims == pytest.approx([92.5, 104.25, 130.75, 90.0, 90.0, 90.0])


def test_xsc_reads_the_LAST_step_not_the_first():
    """Under NPT the cell is still breathing — a stale box is the wrong box."""
    two = XSC + "375000 91.0 0 0 0 103.0 0 0 0 129.0 0 0 0\n"
    assert rlf.parse_xsc_dimensions(two)[0] == pytest.approx(91.0)


def test_a_triclinic_cell_becomes_real_angles():
    tri = "#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z\n100 10 0 0 0 10 0 0 5 5\n"
    lx, ly, lz, alpha, beta, gamma = rlf.parse_xsc_dimensions(tri)
    assert (lx, ly) == pytest.approx((10.0, 10.0))
    assert lz == pytest.approx(7.0710678)
    assert alpha == pytest.approx(45.0)  # b·c at 45°
    assert (beta, gamma) == pytest.approx((90.0, 90.0))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# only comments\n",
        "370000 92.5 0 0\n",  # truncated row
        "370000 a b c d e f g h i\n",  # non-numeric
        "370000 0 0 0 0 0 0 0 0 0\n",  # a zero cell is not a cell
    ],
)
def test_an_unusable_xsc_is_none_not_a_crash(text):
    """Fail toward "no box" (logged, frame still written) rather than raising: a
    snapshot with a stale box beats no snapshot at all."""
    assert rlf.parse_xsc_dimensions(text) is None


def test_the_written_dcd_carries_the_box(tmp_path):
    """The round trip that actually matters — the display reads dimensions off the DCD.

    Verified against the live 2hb_1xT RunPod run: without the cell the display logged
    "No box information available", the load aborted, and the panel showed
    "Display failed: No trajectory loaded." for the whole session.
    """
    mda = pytest.importorskip("MDAnalysis")
    import numpy as np

    n = 12
    universe = mda.Universe.empty(n, trajectory=True)
    universe.atoms.positions = np.arange(n * 3, dtype=np.float32).reshape(n, 3)
    pdb, coor = tmp_path / "tiny.pdb", tmp_path / "tiny.coor"
    universe.atoms.write(str(pdb))
    with mda.Writer(str(coor), n_atoms=n, format="NAMDBIN") as writer:
        writer.write(universe.atoms)

    dest = tmp_path / "out" / "seg0.dcd"
    rlf._write_single_frame_dcd(
        pdb, coor, dest, [92.5, 104.25, 130.75, 90.0, 90.0, 90.0]
    )

    reread = mda.Universe(str(pdb), str(dest))
    assert reread.dimensions[:3] == pytest.approx([92.5, 104.25, 130.75], abs=1e-2)
