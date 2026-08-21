"""Unit tests for backend/core/resume_transfer.py — may this ``.part`` be appended to?

The bug these exist to prevent: the live-frame writer shared the downloader's ``.part``
path, so a refresh truncated a multi-gigabyte partial to a one-frame stand-in DCD and the
next fetch appended real remote bytes onto that foreign head.  The result matched the
expected byte count exactly, so every size-based check passed it as complete.  Only a
structural walk can see it, which is why ``dcd_prefix_is_valid`` exists.
"""

from __future__ import annotations

import struct

from backend.core import resume_transfer as rt


# ── synthetic DCD builder (mirrors NAMD's layout; tiny n_atoms) ───────────────


def _fortran(payload: bytes) -> bytes:
    return struct.pack("<i", len(payload)) + payload + struct.pack("<i", len(payload))


def build_dcd(n_atoms: int, n_frames: int, *, n_titles: int = 2, fill: int = 0) -> bytes:
    ints = [0] * 20
    ints[0] = n_frames  # NSET
    ints[10] = 1  # unit cell present
    ints[19] = 24  # CHARMM/NAMD version
    head = _fortran(b"CORD" + struct.pack("<20i", *ints))
    titles = _fortran(struct.pack("<i", n_titles) + b"T" * (80 * n_titles))
    natom = _fortran(struct.pack("<i", n_atoms))
    out = head + titles + natom
    for f in range(n_frames):
        out += _fortran(struct.pack("<6d", *([100.0 + f + fill] * 6)))
        for axis in range(3):
            out += _fortran(
                struct.pack(f"<{n_atoms}f", *[float(f * 10 + axis + fill)] * n_atoms)
            )
    return out


def frame_size(n_atoms: int) -> int:
    return 56 + 3 * (8 + 4 * n_atoms)


def header_size(n_titles: int = 2) -> int:
    return 92 + (8 + 4 + 80 * n_titles) + 12


# ── plan_resume ───────────────────────────────────────────────────────────────


def test_no_partial_starts_from_zero():
    plan = rt.plan_resume(
        part_size=0, remote_path="/r/a.dcd", remote_size=1000,
        remote_mtime=1.0, sidecar=None,
    )
    assert plan.offset == 0 and plan.restarts


def test_partial_resumes_and_asks_for_a_tail_check():
    plan = rt.plan_resume(
        part_size=5_000_000, remote_path="/r/a.dcd", remote_size=9_000_000,
        remote_mtime=1.0, sidecar=None,
    )
    assert plan.offset == 5_000_000
    assert plan.verify_from == 5_000_000 - rt.TAIL_VERIFY_BYTES


def test_tail_check_window_is_clamped_to_the_file():
    plan = rt.plan_resume(
        part_size=100, remote_path="/r/a.dcd", remote_size=9_000,
        remote_mtime=1.0, sidecar=None,
    )
    assert plan.verify_from == 0


def test_partial_longer_than_remote_is_refused():
    plan = rt.plan_resume(
        part_size=2000, remote_path="/r/a.dcd", remote_size=1000,
        remote_mtime=1.0, sidecar=None,
    )
    assert plan.restarts and "exceeds remote" in plan.reason


def test_sidecar_from_a_different_remote_path_is_refused():
    plan = rt.plan_resume(
        part_size=500, remote_path="/r/a.dcd", remote_size=1000, remote_mtime=1.0,
        sidecar={"remote_path": "/r/b.dcd", "remote_size": 1000},
    )
    assert plan.restarts and "different remote path" in plan.reason


def test_remote_that_changed_size_invalidates_the_partial():
    plan = rt.plan_resume(
        part_size=500, remote_path="/r/a.dcd", remote_size=2000, remote_mtime=1.0,
        sidecar={"remote_path": "/r/a.dcd", "remote_size": 1000},
    )
    assert plan.restarts and "grew/shrank" in plan.reason


def test_rewritten_remote_invalidates_the_partial():
    plan = rt.plan_resume(
        part_size=500, remote_path="/r/a.dcd", remote_size=1000, remote_mtime=9_000.0,
        sidecar={"remote_path": "/r/a.dcd", "remote_size": 1000, "remote_mtime": 1.0},
    )
    assert plan.restarts and "rewritten" in plan.reason


def test_matching_sidecar_resumes():
    plan = rt.plan_resume(
        part_size=500, remote_path="/r/a.dcd", remote_size=1000, remote_mtime=1.4,
        sidecar={"remote_path": "/r/a.dcd", "remote_size": 1000, "remote_mtime": 1.0},
    )
    assert plan.offset == 500 and not plan.restarts


# ── sidecar IO ────────────────────────────────────────────────────────────────


def test_sidecar_round_trip(tmp_path):
    part = tmp_path / "a.dcd.part"
    rt.write_sidecar(
        part, remote_path="/r/a.dcd", remote_size=99, remote_mtime=5.0, offset=42
    )
    data = rt.read_sidecar(part)
    assert data["remote_path"] == "/r/a.dcd"
    assert data["remote_size"] == 99 and data["offset"] == 42
    rt.clear_sidecar(part)
    assert rt.read_sidecar(part) is None


def test_unreadable_sidecar_is_treated_as_absent(tmp_path):
    part = tmp_path / "a.dcd.part"
    rt.sidecar_path(part).write_text("{not json")
    assert rt.read_sidecar(part) is None


# ── DCD structure ─────────────────────────────────────────────────────────────


def test_layout_of_a_synthetic_dcd(tmp_path):
    p = tmp_path / "t.dcd"
    p.write_bytes(build_dcd(7, 3))
    layout = rt.dcd_layout(p)
    assert layout.n_atoms == 7 and layout.has_cell
    assert layout.header_size == header_size() and layout.frame_size == frame_size(7)


def test_layout_rejects_a_non_dcd(tmp_path):
    p = tmp_path / "t.dcd"
    p.write_bytes(b"not a dcd at all" * 40)
    assert rt.dcd_layout(p) is None


def test_complete_dcd_validates(tmp_path):
    p = tmp_path / "t.dcd"
    p.write_bytes(build_dcd(9, 5))
    ok, _ = rt.dcd_prefix_is_valid(p)
    assert ok


def test_truncated_mid_frame_is_still_a_valid_prefix(tmp_path):
    """A download in flight always ends mid-frame; that must not read as corrupt."""
    p = tmp_path / "t.dcd"
    whole = build_dcd(9, 5)
    p.write_bytes(whole[: header_size() + 3 * frame_size(9) + 17])
    ok, detail = rt.dcd_prefix_is_valid(p)
    assert ok, detail


def test_stand_in_head_spliced_onto_real_frames_is_caught(tmp_path):
    """The exact production failure: a foreign one-frame DCD, then real bytes.

    Both files describe the same system, so the splice is byte-aligned and the total
    size can still be exactly right — only the frame boundaries give it away.
    """
    n = 9
    stand_in = build_dcd(n, 1, n_titles=3, fill=500)  # MDAnalysis writes 3 titles
    real = build_dcd(n, 6)
    poisoned = stand_in + real[len(stand_in) :]
    assert len(poisoned) == len(real)  # size check alone cannot see this
    p = tmp_path / "t.dcd"
    p.write_bytes(poisoned)
    ok, detail = rt.dcd_prefix_is_valid(p)
    assert not ok
    assert "frame 1" in detail


def test_garbage_appended_at_a_frame_boundary_is_caught(tmp_path):
    p = tmp_path / "t.dcd"
    p.write_bytes(build_dcd(9, 4) + b"\xff" * frame_size(9))
    ok, _ = rt.dcd_prefix_is_valid(p)
    assert not ok


def test_validate_partial_skips_formats_it_cannot_read(tmp_path):
    p = tmp_path / "results.tar.gz.part"
    p.write_bytes(b"\x1f\x8b nonsense")
    ok, detail = rt.validate_partial(p)
    assert ok and "no structural validator" in detail


def test_validate_partial_reads_a_dot_part_dcd(tmp_path):
    p = tmp_path / "t.dcd.part"
    p.write_bytes(build_dcd(9, 3))
    assert rt.validate_partial(p)[0]


# ── transfer-artifact recognition ─────────────────────────────────────────────


def test_transfer_artifacts_are_recognised():
    for name in (
        "seg.dcd.part",
        "seg.dcd.part.rejected",
        "seg.dcd.part.resume.json",
        "seg.dcd.part.resume.tmp",
    ):
        assert rt.is_transfer_artifact(name), name


def test_real_results_are_not_transfer_artifacts():
    for name in ("seg.dcd", "run.log", "seg.restart.coor", "seg.dcd.live.json"):
        assert not rt.is_transfer_artifact(name), name


# ── files too small to judge ──────────────────────────────────────────────────


def test_an_empty_dcd_is_not_called_corrupt(tmp_path):
    """NAMD creates the DCD before the first dcdfreq step; a run killed early leaves a
    zero-byte file that is legitimately what the remote holds."""
    p = tmp_path / "empty.dcd"
    p.write_bytes(b"")
    ok, detail = rt.dcd_prefix_is_valid(p)
    assert ok and "too short" in detail


def test_a_sub_header_dcd_is_not_called_corrupt(tmp_path):
    p = tmp_path / "stub.dcd"
    p.write_bytes(b"\x54\x00\x00\x00CORD")
    assert rt.dcd_prefix_is_valid(p)[0]


def test_a_full_length_non_dcd_is_still_rejected(tmp_path):
    p = tmp_path / "junk.dcd"
    p.write_bytes(b"J" * 4096)
    ok, detail = rt.dcd_prefix_is_valid(p)
    assert not ok and "did not parse" in detail
