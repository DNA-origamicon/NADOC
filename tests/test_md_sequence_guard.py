"""Regression guard for the poly-T-scaffold incident (6hbx100_90deg): an unassigned
scaffold sequence is silently built as thymine, wasting a full MD run on a physically
meaningless reference. See backend/core/md_sequence_guard.py.
"""

from pathlib import Path

import pytest

from backend.core.models import Design, StrandType
from backend.core.md_sequence_guard import (
    all_sequence_problems,
    scaffold_sequence_problems,
    require_sequenced_scaffold,
    _strand_build_nt_count,
)

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
            s.sequence = "A" * _strand_build_nt_count(
                d, s
            )  # assignment (any ACGT) clears it
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


def test_run_guard_requires_staple_sequences_too():
    d = _load("U6hb")
    staple = next(s for s in d.strands if s.strand_type == StrandType.STAPLE)
    staple.sequence = None
    probs = all_sequence_problems(d)
    assert any("staple" in p and "NO sequence assigned" in p for p in probs)


def test_create_allows_unsequenced_but_run_rejects_with_message(monkeypatch, tmp_path):
    """Creation records the plan; Run is the explicit sequence safety boundary."""
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
    monkeypatch.setattr(
        routes_md, "_WORKSPACE_DIR", tmp_path
    )  # a regression must not touch the real workspace

    d = _load("6hb_test")
    for s in d.strands:
        s.sequence = None if s.strand_type == StrandType.SCAFFOLD else "ACGT" * 40
    assert _sequenced_base_count(d) > 0, (
        "staples sequenced → the generic zero-count guard would PASS"
    )
    assert scaffold_sequence_problems(d), "scaffold must still be flagged"

    doc_context.set_current_doc(None)
    try:
        design_state.set_design(d)
        client = TestClient(app)
        r = client.post(
            "/api/md/jobs", json={"protocol": "mgh_slow_release", "autostart": False}
        )
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["status"] == "draft"
        assert job["awaiting_sequence"] is True

        started = client.post(f'/api/md/jobs/{job["job_id"]}/start')
        assert started.status_code == 400, started.text
        assert "scaffold" in started.json()["detail"].lower()

        # Assigning sequence after creation must make Run prepare THIS job from the
        # updated live design.  That preparation boundary is where the exact PSF atom
        # count and every consumer of it are regenerated, before autostart.
        for strand in d.strands:
            if strand.strand_type == StrandType.SCAFFOLD:
                strand.sequence = "A" * _strand_build_nt_count(d, strand)
        design_state.set_design(d)
        captured = {}

        def fake_prepare(body, *, design, existing_job, **kwargs):
            captured.update(
                sequenced_bases=_sequenced_base_count(design),
                autostart=body.autostart,
                same_job=existing_job.job_id == job["job_id"],
            )
            existing_job.status = routes_md.MdStatus.preparing
            return existing_job

        monkeypatch.setattr(routes_md, "_spawn_prep_job", fake_prepare)
        started = client.post(f'/api/md/jobs/{job["job_id"]}/start')
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "preparing"
        assert captured["sequenced_bases"] > 0
        assert captured["autostart"] is True
        assert captured["same_job"] is True
    finally:
        design_state.drop_doc(doc_context.DEFAULT_DOC_ID)
