"""Fast (no-GPU) pins for the square-lattice skip-twist self-consistency tuning
building blocks: the parameterized periodic-skip design builder, the simulation-keyed
analytic reference, and the secant period adjuster.  The full closed loop (real oxDNA)
is exercised opt-in in tests/test_skip_twist_tuning_production.py."""

import pytest

from backend.api.skip_twist_tuning import (
    PeriodAdjuster,
    build_sq_skip_design,
    core_reference_geometry,
    square_cells,
)
from backend.core.models import LatticeType
from backend.physics import oxdna_interface as ox

CELLS = square_cells(2, 3)


def _ox_keys(design):
    return {
        (k[0], int(k[1]), getattr(k[2], "value", k[2]))
        for k in ox._strand_nucleotide_order(design)
        if k[0] != ox._XB_SENTINEL
    }


def _ref_keys(ref):
    return {
        (
            g["helix_id"],
            int(g["bp_index"]),
            getattr(g["direction"], "value", g["direction"]),
        )
        for g in ref
    }


# ── build_sq_skip_design ─────────────────────────────────────────────────────────
def test_build_sq_skip_design_is_routed_sequenced_square():
    d = build_sq_skip_design(CELLS, 40, None)
    assert d.lattice_type == LatticeType.SQUARE
    assert len(d.helices) == 6
    assert any(s.strand_type.value == "scaffold" for s in d.strands)
    assert all(s.sequence for s in d.strands)  # fully sequenced (no None)
    assert sum(len(h.loop_skips) for h in d.helices) == 0  # period=None => no skips


def test_build_sq_skip_design_skip_count_scales_inversely_with_period():
    counts = {
        p: sum(len(h.loop_skips) for h in build_sq_skip_design(CELLS, 40, p).helices)
        for p in (48, 24, 16)
    }
    assert counts[48] < counts[24] < counts[16]
    assert counts[48] > 0


def test_build_sq_skip_design_skips_are_all_deletions_in_dsDNA_core():
    d = build_sq_skip_design(CELLS, 40, 24)
    marks = [ls for h in d.helices for ls in h.loop_skips]
    assert marks and all(ls.delta == -1 for ls in marks)  # skips (deletions), not loops


# ── core_reference_geometry ──────────────────────────────────────────────────────
@pytest.mark.parametrize("period", [None, 24])
def test_core_reference_keys_match_oxdna_particles(period):
    """The reference must be keyed like the SIMULATION (strand walk), not the display
    feed — every reference key addresses a real oxDNA particle."""
    d = build_sq_skip_design(CELLS, 40, period)
    ref = core_reference_geometry(d)
    assert ref, "reference must not be empty"
    assert _ref_keys(ref) <= _ox_keys(d)  # subset, no orphan keys


def test_core_reference_is_paired_core_and_straight():
    """The reference is the dsDNA core (both strands per column) and reads ~0 global
    twist — the straight bundle the design depicts (the self-consistency target)."""
    from backend.core.oxdna_health import measure_bundle_twist

    d = build_sq_skip_design(CELLS, 40, None)
    ref = core_reference_geometry(d)
    # every (helix, bp) in the reference carries both strands
    by_pos = {}
    for g in ref:
        by_pos.setdefault((g["helix_id"], g["bp_index"]), set()).add(
            getattr(g["direction"], "value", g["direction"])
        )
    assert all(len(dirs) == 2 for dirs in by_pos.values())
    assert abs(measure_bundle_twist(ref)) < 2.0  # straight depiction


# ── PeriodAdjuster ───────────────────────────────────────────────────────────────
def _verdict(residual):
    return {"steering": {"bundle_twist_residual_deg": residual}}


def test_period_adjuster_secant_converges_on_monotone_residual():
    """A monotone residual(P) (root at P=20) is driven to ~0 by the secant step."""
    adj = PeriodAdjuster(p_min=8, p_max=400)
    P, hit = 48, False
    for _ in range(8):
        r = 0.8 * (P - 20)
        if abs(r) < 2.0:
            hit = True
            break
        P = adj(P, _verdict(r))
    assert hit and abs(P - 20) <= 3


def test_period_adjuster_clamps_and_returns_distinct_int():
    adj = PeriodAdjuster(p_min=10, p_max=60)
    nxt = adj(12, _verdict(100.0))  # huge residual would overshoot bounds
    assert isinstance(nxt, int) and 10 <= nxt <= 60
    # a second call with a flat residual still returns a distinct, in-bounds int
    nxt2 = adj(nxt, _verdict(100.0))
    assert isinstance(nxt2, int) and 10 <= nxt2 <= 60


def test_prepare_design_for_autorefine_applies_skips_and_sequences():
    """Autorefine auto-prep: a design without the default skips / sequences is made oxDNA-ready
    (analytical skips applied + fully sequenced); an already-ready design is returned unchanged."""
    from backend.api.skip_twist_tuning import (
        build_sq_skip_design,
        prepare_design_for_autorefine,
    )
    from backend.physics.oxdna_interface import count_undefined_bases

    bare = build_sq_skip_design(CELLS, 40, None)  # routed, no skips
    assert not any(h.loop_skips for h in bare.helices)
    prepared, did = prepare_design_for_autorefine(bare)
    assert did
    assert any(h.loop_skips for h in prepared.helices)  # default skips applied
    assert count_undefined_bases(prepared, exclude_reference=True)[0] == 0  # sequenced

    ready = build_sq_skip_design(CELLS, 40, 24)  # skips + sequenced
    prepared2, did2 = prepare_design_for_autorefine(ready)
    assert did2 is False and prepared2 is ready  # untouched


def test_period_adjuster_step_scales_with_residual_and_is_directed():
    """First step is sign-directed and SIZED to the residual: far-off → big step (square's
    48→~24); near-converged → gentle. Over-twisted (residual>0) → smaller period; under → larger."""
    big = PeriodAdjuster()(48, _verdict(70.0))  # far off, over-twisted → big step down
    assert big <= 26, big  # ~halved toward more skips (square 48→24)
    small = PeriodAdjuster()(48, _verdict(3.0))  # near converged → gentle
    assert 44 <= small < 48, small
    under = PeriodAdjuster()(
        48, _verdict(-70.0)
    )  # far off, under-twisted → big step up
    assert under >= 70, under


def test_period_adjuster_requires_steering_signal():
    adj = PeriodAdjuster()
    with pytest.raises(ValueError, match="signed twist residual"):
        adj(48, {"measured_nm": 1.0})  # no steering block => cannot direct


# ── autorefine (loaded-design refine + route gating) ─────────────────────────────
def test_build_sq_skip_from_design_reapplies_pattern():
    """The autorefine build_fn re-derives the skip pattern on an already-routed design:
    None clears skips, a smaller period adds more — and the design stays square +
    fully sequenced."""
    from backend.api.skip_twist_tuning import (
        build_sq_skip_design,
        build_sq_skip_from_design,
    )

    base = build_sq_skip_design(CELLS, 40, 48)
    n0 = sum(len(h.loop_skips) for h in build_sq_skip_from_design(base, None).helices)
    n48 = sum(len(h.loop_skips) for h in build_sq_skip_from_design(base, 48).helices)
    n16 = sum(len(h.loop_skips) for h in build_sq_skip_from_design(base, 16).helices)
    assert n0 == 0 and 0 < n48 < n16
    refined = build_sq_skip_from_design(base, 16)
    assert refined.lattice_type == LatticeType.SQUARE
    assert all(s.sequence for s in refined.strands)


def test_autorefine_route_rejects_non_square():
    """The autorefine endpoint gates to SQUARE lattice — a honeycomb design is rejected
    with a clear 400 before any simulation is launched."""
    from fastapi import HTTPException
    from backend.api import state as design_state
    from backend.api.routes_autorefine import AutorefineStartRequest, start_autorefine
    from tests.conftest import make_6hb_design  # honeycomb

    design_state.set_design(make_6hb_design())
    with pytest.raises(HTTPException) as ei:
        start_autorefine(AutorefineStartRequest())
    assert ei.value.status_code == 400
    assert "SQUARE" in ei.value.detail


def test_autorefine_route_starts_for_square(monkeypatch):
    """A square-lattice design is accepted: the route returns a run id and a pollable
    registry entry (the heavy loop is stubbed so no real simulation runs)."""
    import backend.api.skip_twist_tuning as stt
    from backend.api import state as design_state
    from backend.api.routes_autorefine import (
        AutorefineStartRequest,
        get_autorefine,
        start_autorefine,
    )
    from backend.api.skip_twist_tuning import build_sq_skip_design

    monkeypatch.setattr(
        stt,
        "autorefine_sq_design",
        lambda design, ws, **k: {
            "status": "met",
            "converged_period": 24,
            "primary_metric": "global_twist_deg",
            "before": {},
            "after": {},
            "iterations": [],
        },
    )
    design_state.set_design(build_sq_skip_design(CELLS, 40, 48))
    r = start_autorefine(AutorefineStartRequest())
    assert r["autorefine_id"] and r["state"] == "running"
    # the background stub completes ~instantly; poll the registry briefly
    import time

    rid = r["autorefine_id"]
    for _ in range(50):
        s = get_autorefine(rid)
        if s["state"] != "running":
            break
        time.sleep(0.02)
    assert get_autorefine(rid)["state"] == "done"


def test_autorefine_stop_route_cancels_run(monkeypatch):
    """Stopping a run sets the cooperative cancel flag the loop honors: a stubbed runner
    that blocks until should_stop() exits, and the run transitions to 'stopped'."""
    import time

    import backend.api.skip_twist_tuning as stt
    from backend.api import state as design_state
    from backend.api.routes_autorefine import (
        AutorefineStartRequest,
        get_autorefine,
        start_autorefine,
        stop_autorefine,
    )
    from backend.api.skip_twist_tuning import build_sq_skip_design

    def _blocking(design, ws, *, should_stop=None, on_job=None, on_progress=None, **k):
        while not (should_stop and should_stop()):
            time.sleep(0.01)
        return {
            "status": "stopped",
            "converged_period": None,
            "primary_metric": "global_twist_deg",
            "before": {},
            "after": {},
            "iterations": [],
        }

    monkeypatch.setattr(stt, "autorefine_sq_design", _blocking)
    design_state.set_design(build_sq_skip_design(CELLS, 40, 48))
    rid = start_autorefine(AutorefineStartRequest())["autorefine_id"]
    assert stop_autorefine(rid)["stopping"] is True
    for _ in range(100):
        if get_autorefine(rid)["state"] != "running":
            break
        time.sleep(0.02)
    assert get_autorefine(rid)["state"] == "stopped"


def test_seed_skip_period_standard_when_no_skips_else_from_density():
    """First-iteration seed: the literature-standard 48 bp when the design has no marks
    (so iteration 0 = the 'add loops/skips' routine), else derived from the existing
    skip density (refine in place — denser marks => smaller period)."""
    from backend.api.skip_twist_tuning import (
        build_sq_skip_design,
        build_sq_skip_from_design,
        seed_skip_period,
    )

    bare = build_sq_skip_design(CELLS, 40, None)
    assert sum(len(h.loop_skips) for h in bare.helices) == 0
    assert seed_skip_period(bare) == 48  # no skips → standard

    dense = build_sq_skip_from_design(bare, 16)  # ~3x the standard density
    p_dense = seed_skip_period(dense)
    assert 8 <= p_dense < 48  # denser → shorter period
    std = build_sq_skip_from_design(bare, 48)
    assert abs(seed_skip_period(std) - 48) <= 24  # ballpark recovery of 48


def test_autorefine_apply_adds_skips_and_feature_log_entry():
    """Applying a completed run lays the converged skip pattern on the ACTIVE design and
    records an 'autorefine-skips' feature-log entry (so it is seekable/revertable/
    deletable by the generic machinery)."""
    from backend.api import state as design_state
    from backend.api.routes_autorefine import _RUNS, apply_autorefine_skips
    from backend.api.skip_twist_tuning import build_sq_skip_design

    design_state.set_design(build_sq_skip_design(CELLS, 40, None))  # square, no skips
    assert sum(len(h.loop_skips) for h in design_state.get_or_404().helices) == 0
    _RUNS["rApply"] = {"state": "done", "result": {"converged_period": 24}}

    apply_autorefine_skips("rApply")
    cur = design_state.get_or_404()
    assert sum(len(h.loop_skips) for h in cur.helices) > 0  # skips landed
    entry = cur.feature_log[-1]
    assert entry.op_kind == "autorefine-skips"
    assert "period 24" in entry.label
    assert entry.feature_type == "snapshot"  # => revert/seek/delete work


def test_autorefine_apply_regional_lands_explicit_pattern():
    """A REGIONAL run's completion-apply lays the EXACT converged non-uniform deletion set
    (from result.converged_skips), not a re-derived uniform period."""
    from backend.api import state as design_state
    from backend.api.routes_autorefine import _RUNS, apply_autorefine_skips
    from backend.api.skip_twist_tuning import build_sq_skip_design
    from backend.core.regional_skip_placer import core_candidates

    base = build_sq_skip_design(CELLS, 40, None)
    design_state.set_design(base)
    h = next(hh for hh in base.helices if len(core_candidates(base, hh)) >= 3)
    want = sorted(core_candidates(base, h)[1:4])
    _RUNS["rRegional"] = {
        "state": "done",
        "result": {
            "converged_period": 24,
            "placement": "regional",
            "converged_skips": {h.id: want},
        },
    }

    apply_autorefine_skips("rRegional")  # period None => apply the regional pattern
    cur = design_state.get_or_404()
    bh = next(hh for hh in cur.helices if hh.id == h.id)
    assert sorted(ls.bp_index for ls in bh.loop_skips) == want  # EXACT pattern landed
    entry = cur.feature_log[-1]
    assert entry.op_kind == "autorefine-skips"
    assert entry.params.get("placement") == "regional"
    assert entry.feature_type == "snapshot"


def test_autorefine_apply_resequences_to_keep_complementarity():
    """Applying a skip pattern RE-SEQUENCES the design, not just the marks: a skip
    consumes no sequence character, so changing the skip set on a sequenced design
    de-registers the staples from the scaffold (drops Watson-Crick complementarity to
    ~random).  The apply must re-derive the sequence so the next oxDNA relaxation can
    actually hold the structure — verified on 3x6x400 (apply-without-reseq → 27%)."""
    from backend.api import state as design_state
    from backend.api.routes_autorefine import _RUNS, apply_autorefine_skips
    from backend.api.skip_twist_tuning import build_sq_skip_design
    from backend.physics.oxdna_interface import designed_pair_complementarity

    # Start from a period-48 sequenced design; refine to a DIFFERENT period (24) so the
    # nucleotide register shifts — the case that de-registers stale sequences.
    design_state.set_design(build_sq_skip_design(CELLS, 60, 48))
    _RUNS["rReseq"] = {"state": "done", "result": {"converged_period": 24}}
    apply_autorefine_skips("rReseq")

    cur = design_state.get_or_404()
    assert sum(len(h.loop_skips) for h in cur.helices) > 0
    n_comp, n_pairs = designed_pair_complementarity(cur)
    assert n_pairs > 0
    assert n_comp / n_pairs > 0.95  # re-sequenced → oxDNA-ready, not de-registered


def test_autorefine_apply_with_explicit_period_during_run():
    """An explicit period applies THAT iteration's pattern even while the run is still
    going (the live per-iteration update) — recorded as its own feature-log entry."""
    from backend.api import state as design_state
    from backend.api.routes_autorefine import _RUNS, apply_autorefine_skips
    from backend.api.skip_twist_tuning import build_sq_skip_design

    design_state.set_design(build_sq_skip_design(CELLS, 40, None))
    _RUNS["rLive"] = {"state": "running", "result": None}  # mid-run, no converged yet
    apply_autorefine_skips("rLive", period=48)
    cur = design_state.get_or_404()
    assert sum(len(h.loop_skips) for h in cur.helices) > 0
    assert cur.feature_log[-1].op_kind == "autorefine-skips"
    assert "period 48" in cur.feature_log[-1].label


def test_autorefine_apply_rejects_when_no_period_or_not_complete():
    from fastapi import HTTPException
    from backend.api import state as design_state
    from backend.api.routes_autorefine import _RUNS, apply_autorefine_skips
    from backend.api.skip_twist_tuning import build_sq_skip_design

    design_state.set_design(build_sq_skip_design(CELLS, 40, None))
    _RUNS["rRun"] = {"state": "running", "result": None}
    with pytest.raises(HTTPException) as ei:
        apply_autorefine_skips("rRun")
    assert ei.value.status_code == 409
    _RUNS["rNoP"] = {"state": "done", "result": {"converged_period": None}}
    with pytest.raises(HTTPException) as ej:
        apply_autorefine_skips("rNoP")
    assert ej.value.status_code == 409


def test_autorefine_stop_route_unknown_id():
    from fastapi import HTTPException
    from backend.api.routes_autorefine import stop_autorefine

    with pytest.raises(HTTPException) as ei:
        stop_autorefine("doesnotexist")
    assert ei.value.status_code == 404


def test_autorefine_defaults_long_equilibration_and_override(monkeypatch):
    """exp34 fix: autorefine must equilibrate ~10M (not the stock 100k) before measuring twist,
    so the measured production starts past the bundle's ~5M twist-relaxation transient.  The
    ``equil_steps`` flows through relax_params to the baseline + every iteration; an explicit
    ``equilibration_steps`` (or equil_steps) overrides."""
    from backend.api import skip_twist_tuning as st
    from backend.api.headless_oxdna_build import STANDARD_RELAX_PARAMS

    assert (
        STANDARD_RELAX_PARAMS["equil_steps"] == 100_000
    )  # the too-short stock default

    base = build_sq_skip_design(CELLS, 40, 24)  # prepared (skips + sequenced)
    captured: dict = {}

    class _Stop(Exception):
        pass

    def _fake_measure(design, workspace, **kw):  # capture relax_params, short-circuit
        captured.clear()
        captured.update(kw)
        raise _Stop

    monkeypatch.setattr(st, "measure_design_self_consistency", _fake_measure)

    with pytest.raises(_Stop):
        st.autorefine_sq_design(base, "/tmp/unused")
    assert captured.get("equil_steps") == 10_000_000  # default bumped ~100x

    with pytest.raises(_Stop):
        st.autorefine_sq_design(base, "/tmp/unused", equilibration_steps=6_000_000)
    assert captured.get("equil_steps") == 6_000_000  # knob honored

    with pytest.raises(_Stop):
        st.autorefine_sq_design(base, "/tmp/unused", equil_steps=2_000_000)
    assert captured.get("equil_steps") == 2_000_000  # explicit relax_param still wins
