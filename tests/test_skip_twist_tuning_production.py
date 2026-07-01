"""Real-engine validation of the square-lattice skip-twist self-consistency loop.

Drives the FULL closed loop on the real CUDA oxDNA engine: build a seamless, routed,
sequenced square-lattice bundle with a periodic skip pattern -> relax -> production ->
measure the simulated mean structure against the design's straight ANALYTIC geometry
(geometry_match RMSD) -> adjust the skip period on the SIGNED twist residual -> repeat.

Two tiers:
  * proxy 2x3x40  — the loop MECHANICS (build/relax/measure/adjust/repeat all fire and
    a well-formed verdict comes back).  Minutes.
  * full 3x6x400  — CONVERGENCE + non-vacuity (the skip pattern measurably straightens
    the bundle vs the period-48 seed).  ~hours; the full-scale validation.

Opt-in (real relax + production is expensive):
    NADOC_RUN_OXDNA_SLOW=1 just test-file tests/test_skip_twist_tuning_production.py
Needs a real oxDNA binary (``find_oxdna``) + a CUDA GPU.  Skipped otherwise.
"""
import glob
import os
from pathlib import Path

import pytest

from backend.api import headless_oxdna_build as hox
from backend.api.skip_twist_tuning import (
    build_sq_skip_design, iterate_sq_skips, square_cells,
)
from backend.core.oxdna_job import OxdnaStatus
from backend.core.oxdna_runner import _conf_max_extent, find_oxdna

pytestmark = pytest.mark.slow


def _skip_if_no_engine():
    if not os.environ.get("NADOC_RUN_OXDNA_SLOW"):
        pytest.skip("opt-in: set NADOC_RUN_OXDNA_SLOW=1 (real relax + production is expensive)")
    if find_oxdna() is None:
        pytest.skip("no real oxDNA binary on PATH/$OXDNA_BIN")


def test_skipped_square_design_relaxes_and_produces_intact(tmp_path):
    """SKIPS through the real engine (the coverage missing before autorefine surfaced
    it): a skipped, CROSSOVERED square-lattice design relaxes AND produces without the
    structure blowing up.  Before this, only EXTRA BASES (loops) had a real-engine
    production test, and the one skip test was geometry-only on a crossover-free bundle.
    Also exercises the non-aborting blow-up recovery: if production goes unstable the
    runner halves dt + retries, so a passing run ends with an INTACT structure (extent
    not far beyond the relaxed seed) — never a silently-exploded one."""
    _skip_if_no_engine()
    design = build_sq_skip_design(square_cells(2, 3), 120, 48)   # SQ + crossovers + skips
    assert sum(len(h.loop_skips) for h in design.helices) > 0

    job = hox.run_relaxation(design, tmp_path, backend="CUDA", timeout=3600.0,
                             **hox.STANDARD_RELAX_PARAMS)
    assert job.status is OxdnaStatus.completed, f"relaxation failed: {job.error}"
    hox.append_production(job.job_id, tmp_path, steps=2_000_000)
    job = hox.wait_for_terminal(job.job_id, tmp_path, timeout=7200.0)
    assert job.status is OxdnaStatus.completed, f"production failed/blew up: {job.error}"

    jd = job.job_dir(tmp_path)
    prod = sorted(glob.glob(f"{jd}/*production*/last_conf.dat"))
    relax = sorted(glob.glob(f"{jd}/*equil*/last_conf.dat")
                   + glob.glob(f"{jd}/*md_relax*/last_conf.dat"))
    assert prod, "no production conf written"
    ext_prod = _conf_max_extent(Path(prod[-1]))
    ext_relax = _conf_max_extent(Path(relax[-1])) if relax else ext_prod
    assert ext_prod < 2.0 * ext_relax, (
        f"structure expanded {ext_prod / ext_relax:.1f}x its relaxed size — blew up "
        "(the dt-halving recovery should have kept it intact or failed the job)")


def _assert_wellformed_verdict(v):
    """A self-consistency verdict carries the gated metric AND both companions in
    steering (RMSD-to-design + signed twist residual)."""
    assert v is not None, "iteration produced no verdict — relax/production failed"
    assert isinstance(v["measured_nm"], float)        # signed for the twist gate
    assert v["status"] in {"met", "unmet", "inconclusive"}
    steer = v.get("steering") or {}
    assert isinstance(steer.get("bundle_twist_residual_deg"), float)
    assert isinstance(steer.get("geometry_rmsd_nm"), float)


def test_proxy_loop_mechanics_2x3x40(tmp_path):
    """The full loop runs end-to-end on the small proxy and returns a well-formed
    result: every build is relaxed + produced, the mean structure is measured against
    the analytic depiction, and a verdict (RMSD + signed twist) comes back."""
    _skip_if_no_engine()
    result = iterate_sq_skips(
        square_cells(2, 3), 40, tmp_path,
        tol_twist_deg=8.0, min_confidence=15, initial_period=48,
        max_iterations=3, production_steps=300_000, screen_steps=100_000,
        max_production_rounds=3, timeout=1800.0, backend="CUDA",
        **hox.STANDARD_RELAX_PARAMS,
    )
    assert result["status"] in {"met", "exhausted"}
    assert result["iterations"], "loop produced no iterations"
    # The first iteration must have completed relax+production (a real verdict).
    _assert_wellformed_verdict(result["iterations"][0]["verdict"])
    assert isinstance(result["knob"], int)          # a concrete converged skip period


def test_full_scale_converges_3x6x400(tmp_path):
    """Full-scale: the loop drives the 3x6x400 bundle toward its straight analytic
    depiction, gating on the SIGNED global twist (the metric RMSD was too insensitive
    to — the period-48 vacuous-convergence post-mortem).  Convergence + non-vacuity:
    it reaches 'met', OR the final |twist residual| is meaningfully smaller than the
    period-48 seed's (the skips measurably straightened the bundle)."""
    _skip_if_no_engine()
    result = iterate_sq_skips(
        square_cells(3, 6), 400, tmp_path,
        tol_twist_deg=5.0, min_confidence=400, initial_period=48,
        max_iterations=5, production_steps=8_000_000, screen_steps=2_000_000,
        max_production_rounds=6, timeout=36000.0, backend="CUDA",
        **hox.STANDARD_RELAX_PARAMS,
    )
    verdicts = [it["verdict"] for it in result["iterations"] if it.get("verdict")]
    assert verdicts, "loop produced no verdicts"
    for v in verdicts:
        _assert_wellformed_verdict(v)

    if result["status"] == "met":
        return                                       # converged within tolerance
    # Otherwise require the global twist to have measurably shrunk (non-vacuity).
    twist = lambda v: abs(v["steering"]["bundle_twist_residual_deg"])
    assert twist(verdicts[-1]) < twist(verdicts[0]), "global twist did not shrink"
