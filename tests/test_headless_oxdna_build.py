"""AF-13 Phase 1 — headless oxDNA relaxation wrapper + physical-layer oracle.

Drives the REAL oxDNA job routes (``create_oxdna_job`` → ``start_oxdna_job`` →
poll → ``get_oxdna_display``) from a scratch session, against the MOCK oxDNA binary
(``$OXDNA_BIN``), and proves the foundational Tier-5 property: a headless relaxation
reaches ``completed`` and its relaxed last frame reads back into a full
per-nucleotide position map (``assert_relaxed_geometry_recovered``).

The mock copies the input conf → ``last_conf`` (it does not actually relax), so
``min_bp_retained=0.0`` disables the base-pair-retention gate — this pins the
ORCHESTRATION + geometry recovery, not relaxation quality (covered separately in
``test_oxdna_relaxation.py``).  Real-binary paths stay gated by ``find_oxdna()``.
"""

from __future__ import annotations

import dataclasses
import stat

import pytest

from backend.api import headless_oxdna_build as hox
from backend.core.oxdna_job import OxdnaStatus
from tests.automation_harness import (
    assert_relaxed_geometry_recovered,
    oxdna_coverage_report,
)
from tests.conftest import make_6hb_design

# Reuse the mock-binary source + the M13+WC sequencing helper from the oxDNA runner
# tests (a local fixture wraps the mock so pytest discovers it without a
# cross-module fixture import).
from tests.test_oxdna_relaxation import _MOCK_OXDNA, _sequence_for_oxdna


@pytest.fixture
def mock_oxdna(tmp_path, monkeypatch):
    """A fake oxDNA binary (copies the input conf → last_conf, writes energy) bound
    via ``$OXDNA_BIN`` — drives the whole job lifecycle deterministically, no GPU."""
    p = tmp_path / "mock_oxdna.py"
    p.write_text(_MOCK_OXDNA)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


@pytest.fixture
def sequenced_6hb():
    """A fully-sequenced 6hb (M13 scaffold + WC-complement staples) — oxDNA rejects
    any undefined base, so the design must carry a definite A/C/G/T everywhere."""
    return _sequence_for_oxdna(make_6hb_design())


# ── The wrapper drives a real relaxation + the oracle recovers the geometry ────

def test_run_relaxation_completes_and_recovers_geometry(sequenced_6hb, tmp_path, mock_oxdna):
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error
    # All three relaxation stages ran.
    assert all(s.status == "done" for s in job.stages)

    display = assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path)
    # The recovered map is the full design (the geometry kernel's nucleotide count).
    from backend.core.design_geometry import _geometry_for_design
    assert display["n_positions"] == len(_geometry_for_design(sequenced_6hb))


def test_create_then_start_two_step(sequenced_6hb, tmp_path, mock_oxdna):
    """The lower-level wrappers compose: create (queued, no autostart) → start →
    poll to completed."""
    info = hox.create_job(sequenced_6hb, tmp_path, autostart=False, min_bp_retained=0.0)
    assert info["status"] == "queued"
    hox.start_relaxation(info["job_id"], tmp_path)
    job = hox.wait_for_terminal(info["job_id"], tmp_path)
    assert job.status is OxdnaStatus.completed, job.error
    assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path)


def test_append_production_after_completion(sequenced_6hb, tmp_path, mock_oxdna):
    """A completed relaxation can be extended with an unbiased production stage —
    it reaches completed again and the relaxed geometry still reads back."""
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed

    n_stages_before = len(job.stages)
    hox.append_production(job.job_id, tmp_path, steps=1000)
    job = hox.wait_for_terminal(job.job_id, tmp_path)
    assert job.status is OxdnaStatus.completed, job.error
    assert len(job.stages) == n_stages_before + 1
    assert any(s.kind == "production" for s in job.stages)
    assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path)


# ── Red-tests: the oracle CAN go red ──────────────────────────────────────────

def test_oracle_fires_on_non_completed_job(sequenced_6hb, tmp_path, mock_oxdna):
    """A job that did not reach completed raises the status guard."""
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    not_done = dataclasses.replace(job, status=OxdnaStatus.failed, error="boom")
    with pytest.raises(AssertionError, match="did not reach completed"):
        assert_relaxed_geometry_recovered(not_done, sequenced_6hb, tmp_path)


def test_oracle_fires_on_wrong_count(sequenced_6hb, tmp_path, mock_oxdna):
    """If fewer/more positions come back than design nucleotides, the count check
    raises (a truncated / dropped conf would trip this)."""
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    from backend.core.design_geometry import _geometry_for_design
    inflated = len(_geometry_for_design(sequenced_6hb)) + 5
    with pytest.raises(AssertionError, match="expected"):
        assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path,
                                          expected_count=inflated)


# ── Function-identity coverage: the wrappers drive the real route handlers ─────

def test_oxdna_coverage_report_marks_af13_routes_covered():
    """The wrappers register their /oxdna routes as covered (function-identity)."""
    report = oxdna_coverage_report()
    assert report["total"] == report["covered"] + report["uncovered"]
    covered = {r["endpoint"] for r in report["covered_routes"]}
    # The three /oxdna MUTATION routes the wrappers drive (get_oxdna_display is a
    # read-only GET, excluded from a mutation audit — pinned by the import test).
    assert {"create_oxdna_job", "start_oxdna_job",
            "append_oxdna_production"} <= covered


def test_wrappers_import_exact_route_handlers():
    """Anti-passthrough: the wrappers reference the actual route handler objects,
    not re-implementations."""
    from backend.api import routes_oxdna

    assert hox._route_create_oxdna_job is routes_oxdna.create_oxdna_job
    assert hox._route_start_job is routes_oxdna.start_oxdna_job
    assert hox._route_append_production is routes_oxdna.append_oxdna_production
    assert hox._route_get_display is routes_oxdna.get_oxdna_display
