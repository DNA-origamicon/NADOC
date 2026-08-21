"""Unit tests for scripts/repair_dcd_partial.py — the stand-in-head partial repair.

This tool rewrites the first megabytes of files that can represent many hours of
transfer, and its promote step *moves* them.  The naming and the refusal conditions are
therefore the parts worth pinning.
"""

from __future__ import annotations

import pytest

from scripts.repair_dcd_partial import (
    diagnose,
    promote,
    strip_partial_suffixes,
)
from tests.test_resume_transfer import build_dcd, frame_size, header_size


def test_strip_partial_suffixes():
    assert strip_partial_suffixes("seg.dcd.part") == "seg.dcd"
    assert strip_partial_suffixes("seg.dcd.part.rejected") == "seg.dcd"
    assert strip_partial_suffixes("seg.dcd") == "seg.dcd"


def test_promote_installs_a_quarantined_partial(tmp_path):
    rejected = tmp_path / "seg.dcd.part.rejected"
    rejected.write_bytes(b"the long repaired partial")
    active = promote(rejected)

    assert active == tmp_path / "seg.dcd.part"
    assert active.read_bytes() == b"the long repaired partial"
    assert not rejected.exists()


def test_promote_moves_an_existing_partial_aside_rather_than_deleting(tmp_path):
    """The shorter partial is redundant, but discarding data is this tool's whole sin."""
    (tmp_path / "seg.dcd.part").write_bytes(b"short fresh partial")
    rejected = tmp_path / "seg.dcd.part.rejected"
    rejected.write_bytes(b"the long repaired partial")

    active = promote(rejected)

    assert active.read_bytes() == b"the long repaired partial"
    assert (tmp_path / "seg.dcd.part.superseded").read_bytes() == b"short fresh partial"


def test_promote_is_a_no_op_for_an_active_partial(tmp_path):
    part = tmp_path / "seg.dcd.part"
    part.write_bytes(b"data")
    assert promote(part) == part
    assert part.exists()


def test_diagnose_finds_the_stand_in_head_length(tmp_path):
    n = 6
    stand_in = build_dcd(n, 1, n_titles=3, fill=500)
    real = build_dcd(n, 5)
    part = tmp_path / "seg.dcd.part"
    part.write_bytes(stand_in + real[len(stand_in) :])

    assert diagnose(part, quiet=True) == header_size(3) + frame_size(n)


def test_diagnose_refuses_a_sound_partial(tmp_path):
    part = tmp_path / "seg.dcd.part"
    part.write_bytes(build_dcd(6, 4))
    with pytest.raises(SystemExit, match="already structurally sound"):
        diagnose(part, quiet=True)


def test_diagnose_refuses_damage_it_does_not_recognise(tmp_path):
    """Corruption somewhere other than the head is not repairable by overwriting it."""
    real = bytearray(build_dcd(6, 5))
    real[header_size() + 3 * frame_size(6) : header_size() + 3 * frame_size(6) + 8] = b"\xff" * 8
    part = tmp_path / "seg.dcd.part"
    part.write_bytes(bytes(real))
    with pytest.raises(SystemExit, match="not with the stand-in-head signature"):
        diagnose(part, quiet=True)


def test_diagnose_refuses_a_file_that_is_not_a_dcd(tmp_path):
    part = tmp_path / "seg.dcd.part"
    part.write_bytes(b"J" * 4096)
    with pytest.raises(SystemExit, match="does not parse as a DCD"):
        diagnose(part, quiet=True)
