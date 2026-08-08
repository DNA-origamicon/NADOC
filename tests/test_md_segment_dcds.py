"""Which DCDs a job's segments actually contribute — backend/api/routes_md._md_segment_dcds.

A resumed segment writes ``<seg>.cont1.dcd``, ``cont2``, … and each covers only the steps
AFTER its restart checkpoint (``md_protocols`` re-emits the conf with ``firsttimestep``
and the remaining steps). They are sequential PIECES of one trajectory, not alternatives.

This used to return one file per segment — the newest by mtime — so every consumer (RMSF,
the metrics card, the trajectory scrub view, the CPD weld trace) silently analysed only
the tail of a resumed run. On a real 2hb_1xT run the base covered 0.10–104.30 ns and
cont1 covered 104.40–161.90 ns: the newest-only rule saw 36% of it and reported no error.

Fast: writes tiny real DCDs with MDAnalysis, no simulation.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest


def _write_dcd(path, n_frames, start_time, dt=100.0, n_atoms=4):
    """A minimal real DCD whose frames carry the given times."""
    mda = pytest.importorskip("MDAnalysis")
    from MDAnalysis.coordinates.DCD import DCDWriter

    u = mda.Universe.empty(n_atoms, trajectory=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # istart is what carries the start into the HEADER — a per-frame ts.time is not
    # written through, which is exactly how a real NAMD continuation differs from its
    # base (firsttimestep).
    with DCDWriter(
        str(path), n_atoms=n_atoms, dt=dt, nsavc=1, istart=int(start_time / dt)
    ) as w:
        for i in range(n_frames):
            u.atoms.positions = np.zeros((n_atoms, 3), dtype=np.float32) + i
            w.write(u.atoms)
    return path


@pytest.fixture
def job(tmp_path, monkeypatch):
    """A one-segment job whose package dir is a tmp dir."""
    from backend.api import routes_md

    pkg = tmp_path / "pkg"
    (pkg / "output").mkdir(parents=True)
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    return SimpleNamespace(
        segments=[SimpleNamespace(name="prod", stage="md")],
        package_dir=lambda _ws: pkg,
    ), pkg


def test_a_resumed_segment_contributes_every_piece_not_just_the_newest(job):
    """The regression. Base + cont1 are sequential; taking only cont1 drops the base."""
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    base = _write_dcd(pkg / "output" / "prod.dcd", 6, start_time=0.0)
    cont = _write_dcd(pkg / "output" / "prod.cont1.dcd", 4, start_time=600.0)

    segs = _md_segment_dcds(j)

    assert [s[2] for s in segs] == [base, cont], "both pieces, base first"


def test_pieces_come_back_in_trajectory_time_order(job):
    """Ordered by the trajectory's own clock. mtime reorders when a file is archived or
    re-touched; name sorting puts cont10 before cont2."""
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    # write the LATER piece first so mtime order is the reverse of time order
    later = _write_dcd(pkg / "output" / "prod.cont1.dcd", 3, start_time=900.0)
    earlier = _write_dcd(pkg / "output" / "prod.dcd", 9, start_time=0.0)

    segs = _md_segment_dcds(j)

    assert [s[2] for s in segs] == [earlier, later]


def test_cont10_sorts_after_cont2(job):
    """Name sorting would put cont10 second; the trajectory clock puts it last."""
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    _write_dcd(pkg / "output" / "prod.dcd", 2, start_time=0.0)
    _write_dcd(pkg / "output" / "prod.cont2.dcd", 2, start_time=200.0)
    _write_dcd(pkg / "output" / "prod.cont10.dcd", 2, start_time=400.0)

    names = [s[2].name for s in _md_segment_dcds(j)]

    assert names == ["prod.dcd", "prod.cont2.dcd", "prod.cont10.dcd"]


def test_an_unresumed_segment_is_unchanged(job):
    """The common case must not gain a duplicate entry."""
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    _write_dcd(pkg / "output" / "prod.dcd", 5, start_time=0.0)

    segs = _md_segment_dcds(j)

    assert len(segs) == 1
    assert segs[0][0] == "prod"


def test_continuation_entries_are_labelled_distinctly(job):
    """Consumers that show segment names would otherwise print the same label twice."""
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    _write_dcd(pkg / "output" / "prod.dcd", 2, start_time=0.0)
    _write_dcd(pkg / "output" / "prod.cont1.dcd", 2, start_time=200.0)

    labels = [s[0] for s in _md_segment_dcds(j)]

    assert labels[0] == "prod"
    assert labels[1] != labels[0]
    assert "cont1" in labels[1]


def test_stage_rides_along_on_every_piece(job):
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    _write_dcd(pkg / "output" / "prod.dcd", 2, start_time=0.0)
    _write_dcd(pkg / "output" / "prod.cont1.dcd", 2, start_time=200.0)

    assert {s[1] for s in _md_segment_dcds(j)} == {"md"}


def test_empty_and_missing_files_are_skipped(job):
    from backend.api.routes_md import _md_segment_dcds

    j, pkg = job
    (pkg / "output" / "prod.dcd").write_bytes(b"")  # zero-length
    _write_dcd(pkg / "output" / "prod.cont1.dcd", 3, start_time=100.0)

    segs = _md_segment_dcds(j)

    assert [s[2].name for s in segs] == ["prod.cont1.dcd"]


def test_a_segment_with_no_dcd_contributes_nothing(job):
    from backend.api.routes_md import _md_segment_dcds

    j, _pkg = job

    assert _md_segment_dcds(j) == []


def test_first_step_falls_back_to_mtime_on_an_unreadable_dcd(tmp_path):
    """A corrupt or partially-written DCD must not drop the file from the list — the
    ordering degrades to mtime rather than the piece vanishing."""
    from backend.api.routes_md import _dcd_first_step

    bad = tmp_path / "broken.dcd"
    bad.write_bytes(b"not a dcd")

    assert _dcd_first_step(bad) > 0
