"""Regression guard for the poly-T-scaffold incident (6hbx100_90deg): an unassigned
scaffold sequence is silently built as thymine, wasting a full MD run on a physically
meaningless reference. See backend/core/md_sequence_guard.py.
"""
from pathlib import Path

import pytest

from backend.core.models import Design, StrandType
from backend.core.md_sequence_guard import (
    scaffold_sequence_problems, require_sequenced_scaffold, _strand_build_nt_count)

EXAMPLES = Path(__file__).resolve().parent.parent / "Examples"


def _load(stem: str) -> Design:
    return Design.model_validate_json((EXAMPLES / f"{stem}.nadoc").read_text())


def test_unsequenced_scaffold_is_flagged():
    d = _load("6hb_test")  # scaffolds present, no sequence assigned (acgt=0)
    problems = scaffold_sequence_problems(d)
    assert problems, "an unsequenced scaffold MUST be flagged"
    assert all("scaffold" in p for p in problems)
    with pytest.raises(ValueError, match="scaffold"):
        require_sequenced_scaffold(d)


def test_fully_sequenced_scaffold_passes():
    d = _load("U6hb")  # 2588/2588 scaffold bases assigned
    assert scaffold_sequence_problems(d) == []
    require_sequenced_scaffold(d)  # must not raise


def test_assigning_the_sequence_clears_the_flag():
    d = _load("6hb_test")
    assert scaffold_sequence_problems(d)  # flagged beforehand
    for s in d.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            s.sequence = "A" * _strand_build_nt_count(d, s)  # assignment (any ACGT) clears it
    assert scaffold_sequence_problems(d) == []


def test_partial_scaffold_is_flagged():
    # half-assigned scaffold: the remaining nt would still build as poly-T -> must flag.
    d = _load("6hb_test")
    for s in d.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            n = _strand_build_nt_count(d, s)
            s.sequence = "ACGT" * (n // 8)  # ~half coverage
    probs = scaffold_sequence_problems(d)
    assert probs and any("under-sequenced" in p for p in probs)


def test_route_blocks_unsequenced_scaffold_up_front(monkeypatch, tmp_path):
    """POST /md/jobs returns 400 UP FRONT (not a born-then-failed job) when the STAPLES are
    sequenced but the SCAFFOLD is None — the 6hbx100_90deg incident's exact shape, which the
    generic zero-sequence guard misses (sequenced staples make the count > 0).  Locks the
    scaffold-specific block added to create_md_job so the user gets an immediate, actionable
    message instead of a job that spawns 'preparing' then dies in background prep."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state as design_state
    from backend.api import doc_context
    import backend.api.routes_md as routes_md
    from backend.api.routes_md import _sequenced_base_count

    # Engine availability is checked first (fail-fast) — stub it so the test reaches the
    # scaffold guard whether or not NAMD/GROMACS are installed in the environment.
    monkeypatch.setattr(routes_md, "find_namd", lambda: "/usr/bin/namd3")
    monkeypatch.setattr(routes_md, "find_gmx", lambda: "/usr/bin/gmx")
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)  # a regression must not touch the real workspace

    d = _load("6hb_test")
    for s in d.strands:
        s.sequence = None if s.strand_type == StrandType.SCAFFOLD else "ACGT" * 40
    assert _sequenced_base_count(d) > 0, "staples sequenced → the generic zero-count guard would PASS"
    assert scaffold_sequence_problems(d), "scaffold must still be flagged"

    doc_context.set_current_doc(None)
    try:
        design_state.set_design(d)
        r = TestClient(app).post("/api/md/jobs", json={"protocol": "mgh_slow_release", "autostart": False})
        assert r.status_code == 400, r.text
        assert "scaffold" in r.json()["detail"].lower()
    finally:
        design_state.drop_doc(doc_context.DEFAULT_DOC_ID)
