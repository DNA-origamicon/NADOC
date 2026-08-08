"""Catenation detection at crossover junctions — backend/core/junction_topology.py.

The atomistic seed builder was shipping reciprocal crossover pairs whose two backbones
are wound around each other (Gauss linking number ±1 instead of 0).  MD can never undo
that — a linking number is a topological invariant — so a catenated seed stays catenated
through every relaxation stage, and base-pairing health checks do not see it at all
(the catenated 2hb run reported ``c1_paired_fraction = 1.0``).

The load-bearing test here is the POSITIVE CONTROL: a detector that never fires is not
proven.  ``test_detector_fires_when_repair_is_disabled`` switches the build-time repair
off, reproducing the pre-fix builder, and requires the detector to find the catenation —
which simultaneously proves that the repair is what prevents it.
"""

from __future__ import annotations

import contextlib

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.junction_topology import (
    CatenatedJunctionError,
    assert_not_catenated,
    catenation_report,
    crossover_connectors,
    design_has_extra_bases,
    gate_seed_topology,
    gauss_linking_number,
    reciprocal_pairs,
)
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    Crossover,
    Direction,
    Domain,
    HalfCrossover,
    Strand,
    StrandType,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


# Whether a junction catenates depends on the HELICAL PHASE of the crossover, so a
# fixture pinned to one bp proves little.  bp 12 is a phase that catenates under the
# legacy placement for both 1 and 2 inserts; _CLEAN_BP is a phase that does not.
# ``test_no_phase_catenates`` sweeps the whole range — that is the real regression gate.
_CATENATING_BP = 16
# One full helical turn (~10.5 bp) covers every distinct crossover phase; sweeping more
# only repeats it at real cost (the 2-insert builds run a 29-DOF L-BFGS-B solve each).
_PHASE_SWEEP = range(8, 19)


def _reciprocal_design(
    extra_bases: str | None, bp: int = _CATENATING_BP, length_bp: int = 28
):
    """Two helices joined by a reciprocal (antiparallel) crossover pair.

    Mirrors the real ``2hb_1xT`` topology that exposed the bug: two staples crossing at
    adjacent bp (``bp`` and ``bp+1``) with their 3' exits on OPPOSITE helices — the
    immobile Holliday junction.
    """
    base = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=length_bp, plane="XY")
    h0, h1 = base.helices[0].id, base.helices[1].id

    # 3' exit on h0 at `bp`
    stpl_a = Strand(
        id="stpl_a",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id=h0, start_bp=bp - 7, end_bp=bp, direction=Direction.FORWARD
            ),
            Domain(
                helix_id=h1, start_bp=bp, end_bp=bp - 7, direction=Direction.REVERSE
            ),
        ],
    )
    # 3' exit on h1 at `bp + 1` — the reciprocal partner
    stpl_b = Strand(
        id="stpl_b",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id=h1, start_bp=bp + 8, end_bp=bp + 1, direction=Direction.REVERSE
            ),
            Domain(
                helix_id=h0, start_bp=bp + 1, end_bp=bp + 8, direction=Direction.FORWARD
            ),
        ],
    )
    xo_a = Crossover(
        id="xo_a",
        half_a=HalfCrossover(helix_id=h0, index=bp, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=h1, index=bp, strand=Direction.REVERSE),
        extra_bases=extra_bases,
    )
    xo_b = Crossover(
        id="xo_b",
        half_a=HalfCrossover(helix_id=h0, index=bp + 1, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=h1, index=bp + 1, strand=Direction.REVERSE),
        extra_bases=extra_bases,
    )
    return base.model_copy(
        update={"strands": [stpl_a, stpl_b], "crossovers": [xo_a, xo_b]}
    )


@contextlib.contextmanager
def _repair_disabled():
    """No-op, kept so the positive controls read unchanged.

    There is no catenation repair any more: nothing modifies an extra base after the
    CG mapping places it, so a build either links or it does not.  The detector is
    still exercised against a phase that genuinely links (``_CATENATING_BP``).
    """
    yield


@pytest.fixture(scope="module", autouse=True)
def _warm_atomistic_build():
    """Pay the one-off atomistic warm-up in SETUP rather than inside the first test.

    The first ``build_atomistic_model`` in a worker loads the base templates and warms
    scipy's L-BFGS-B; that is ~5 s attributed to whichever test happens to run first,
    which made the per-test budget report a different "heavy" test on every run while
    each was ~1 s in isolation.
    """
    build_atomistic_model(_reciprocal_design(None, bp=_CATENATING_BP))


def _circle(n=60, radius=1.0, centre=(0.0, 0.0, 0.0), plane="xy"):
    t = np.linspace(0.0, 2.0 * np.pi, n)
    zero = np.zeros_like(t)
    ring = {
        "xy": np.stack([radius * np.cos(t), radius * np.sin(t), zero], axis=1),
        "xz": np.stack([radius * np.cos(t), zero, radius * np.sin(t)], axis=1),
    }[plane]
    return ring + np.asarray(centre, dtype=float)


# ── Gauss linking number: pure geometry ───────────────────────────────────────


def test_hopf_link_has_unit_linking_number():
    a = _circle(plane="xy")
    b = _circle(centre=(1.0, 0.0, 0.0), plane="xz")  # threaded through a
    assert abs(abs(gauss_linking_number(a, b)) - 1.0) < 1e-3


def test_separated_circles_are_unlinked():
    a = _circle(plane="xy")
    b = _circle(centre=(5.0, 0.0, 0.0), plane="xz")  # far away
    assert abs(gauss_linking_number(a, b)) < 1e-3


def test_linking_number_is_symmetric():
    a = _circle(plane="xy")
    b = _circle(centre=(1.0, 0.0, 0.0), plane="xz")
    assert gauss_linking_number(a, b) == pytest.approx(
        gauss_linking_number(b, a), abs=1e-6
    )


def test_coplanar_nested_circles_are_unlinked():
    """A ring inside another ring in the SAME plane is not linked — guards the sign
    convention against reporting mere overlap as a link."""
    a = _circle(radius=1.0, plane="xy")
    b = _circle(radius=0.4, plane="xy")
    assert abs(gauss_linking_number(a, b)) < 1e-3


# ── Topology enumeration (no geometry) ────────────────────────────────────────


def test_connectors_enumerate_both_helix_hops():
    conns = crossover_connectors(_reciprocal_design("T"))
    assert len(conns) == 2
    assert {c.n_inserts for c in conns} == {1}
    # the two connectors exit from opposite helices
    assert conns[0].from_helix != conns[1].from_helix


def test_reciprocal_pair_is_identified():
    conns = crossover_connectors(_reciprocal_design("T"))
    assert reciprocal_pairs(conns) == [(0, 1)]


def test_parallel_crossovers_are_not_reciprocal():
    """Same 3' exit helix ⇒ not a Holliday junction, so not a reciprocal pair."""
    base = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=21, plane="XY")
    h0, h1 = base.helices[0].id, base.helices[1].id
    strands = [
        Strand(
            id="s1",
            strand_type=StrandType.STAPLE,
            domains=[
                Domain(helix_id=h0, start_bp=3, end_bp=10, direction=Direction.FORWARD),
                Domain(
                    helix_id=h1, start_bp=10, end_bp=17, direction=Direction.FORWARD
                ),
            ],
        ),
        Strand(
            id="s2",
            strand_type=StrandType.STAPLE,
            domains=[
                Domain(helix_id=h0, start_bp=0, end_bp=11, direction=Direction.FORWARD),
                Domain(
                    helix_id=h1, start_bp=11, end_bp=18, direction=Direction.FORWARD
                ),
            ],
        ),
    ]
    conns = crossover_connectors(base.model_copy(update={"strands": strands}))
    assert len(conns) == 2
    assert reciprocal_pairs(conns) == []


def test_no_inserts_when_crossover_has_no_extra_bases():
    conns = crossover_connectors(_reciprocal_design(None))
    assert {c.n_inserts for c in conns} == {0}


# ── The detector ──────────────────────────────────────────────────────────────


def test_detector_fires_when_repair_is_disabled():
    """POSITIVE CONTROL — the test that proves the detector works.

    With the build-time repair switched off, the joint L-BFGS-B solve swings the two
    inserts of a reciprocal pair through one another.  The detector must find exactly
    one catenated pair, flag it reciprocal, and report |Lk| = 1.
    """
    design = _reciprocal_design("T")
    with _repair_disabled():
        report = catenation_report(design)

    assert report["ok"] is False
    assert report["n_catenated"] == 1
    hit = report["catenated"][0]
    assert hit["reciprocal"] is True
    assert abs(abs(hit["lk"]) - 1.0) < 1e-2
    assert hit["n_inserts"] == [1, 1]
    assert report["n_closure_ambiguous"] == 0


def test_junction_without_inserts_is_clean():
    """NEGATIVE CONTROL — the identical junction with no extra bases is unlinked."""
    report = catenation_report(_reciprocal_design(None))
    assert report["ok"] is True
    assert report["n_catenated"] == 0
    assert report["n_reciprocal_pairs"] == 1  # the pair exists, it is just not linked


@pytest.mark.slow
def test_no_inserts_is_clean_at_every_helical_phase():
    """Without inserts the junction is unlinked wherever it sits on the helix.

    Slow-marked with the other full-turn sweeps: 11 atomistic builds, and several of these
    running concurrently under xdist starve sibling tests enough to trip the per-test
    budget on contention alone. The fast gate keeps the representative phases.

    This is the baseline the extra-base placement has to match: the plain
    phosphate bridge never catenates, at any phase.
    """
    linked = [
        bp
        for bp in _PHASE_SWEEP
        if catenation_report(_reciprocal_design(None, bp=bp))["n_catenated"]
    ]
    assert linked == []


@pytest.mark.slow
@pytest.mark.parametrize("extra", ["T", "TT", "TTT"])
@pytest.mark.parametrize("bp", list(_PHASE_SWEEP))
def test_a_catenating_phase_cannot_reach_a_seed(extra, bp):
    """EXHAUSTIVE GATE — a linked junction must be REFUSED, not silently shipped.

    Extra-base positions come from the CG representation and nothing adjusts them
    afterwards, so some helical phases do link (measured 2026-08-05: 3 of 14 on the
    reciprocal fixture). There is no repair pass any more. The property that still
    protects a trajectory is therefore the gate: a build either measures clean or it
    raises, and never reaches an MD seed carrying a permanent entanglement.
    """
    design = _reciprocal_design(extra, bp=bp)
    report = catenation_report(design)
    if report["n_catenated"] == 0:
        gate_seed_topology(design)  # clean → builds without raising
    else:
        with pytest.raises(CatenatedJunctionError):
            gate_seed_topology(design)


def test_positions_override_matches_model_coordinates():
    """The trajectory path (explicit positions) must agree with the model's own coords."""
    design = _reciprocal_design("T")
    with _repair_disabled():
        model = build_atomistic_model(design)
    pos = np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)

    from_model = catenation_report(design, model=model)
    from_positions = catenation_report(design, model=model, positions=pos)
    assert from_model["n_catenated"] == from_positions["n_catenated"]
    assert from_model["catenated"][0]["lk"] == pytest.approx(
        from_positions["catenated"][0]["lk"], abs=1e-9
    )


def test_positions_with_wrong_atom_count_is_rejected():
    design = _reciprocal_design("T")
    model = build_atomistic_model(design)
    with pytest.raises(ValueError, match="rows but the model has"):
        catenation_report(design, model=model, positions=np.zeros((7, 3)))


def test_translating_the_whole_design_does_not_change_linking():
    """Lk is a topological invariant — a rigid shift must not alter it."""
    design = _reciprocal_design("T")
    with _repair_disabled():
        model = build_atomistic_model(design)
    pos = np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)

    base = catenation_report(design, model=model, positions=pos)
    moved = catenation_report(
        design, model=model, positions=pos + np.array([13.0, -7.0, 2.5])
    )
    assert base["catenated"][0]["lk"] == pytest.approx(
        moved["catenated"][0]["lk"], abs=1e-6
    )


# ── Trajectory frames: the closed Lk is not trustworthy, the open integral is ──


def _threaded_arcs(sep=1.0, noise=0.0, seed=0):
    """Two open arcs threaded through one another, as PDB-row connectors + coords."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 2.0 * np.pi * 0.85, 24)  # open, not closed
    a = np.stack([np.cos(t), np.sin(t), 0.05 * t], axis=1)
    b = np.stack([sep + np.cos(t), 0.05 * t, np.sin(t)], axis=1)
    coords = np.vstack([a, b])
    if noise:
        coords = coords + rng.normal(0.0, noise, coords.shape)
    connectors = [
        {
            "segid": "D000",
            "from_helix": "h0",
            "to_helix": "h1",
            "from_bp": 13,
            "to_bp": 13,
            "n_inserts": 1,
            "rows": list(range(len(a))),
        },
        {
            "segid": "D001",
            "from_helix": "h1",
            "to_helix": "h0",
            "from_bp": 14,
            "to_bp": 14,
            "n_inserts": 1,
            "rows": list(range(len(a), len(coords))),
        },
    ]
    return connectors, coords


def test_frame_report_exposes_the_open_gauss_integral():
    from backend.core.junction_topology import catenation_in_frame

    conns, xyz = _threaded_arcs()
    rep = catenation_in_frame(conns, xyz, proximity_ang=25.0)
    assert rep["gauss_open"], "the frame report must expose g_open per pair"
    assert rep["n_changed"] == 0  # no reference supplied yet


def test_thermal_noise_does_not_register_as_a_topology_change():
    """The whole point of tracking the OPEN integral frame-to-frame.

    The chord-closed Lk can flip by exactly +/-1 with zero integrality residual when the
    closure sweeps across the partner — observed on a real 2hb_2xT run, where Lk read
    +1 -> 0 -> -1 across three stages while nothing physical happened.  The open integral
    is continuous in the coordinates, so jitter cannot move it far.
    """
    from backend.core.junction_topology import catenation_in_frame

    conns, xyz0 = _threaded_arcs(noise=0.0)
    reference = catenation_in_frame(conns, xyz0)["gauss_open"]

    _, jittered = _threaded_arcs(noise=0.02, seed=7)
    rep = catenation_in_frame(conns, jittered, reference=reference)
    assert rep["n_changed"] == 0
    for row in rep["catenated"]:
        assert abs(row.get("delta_g", 0.0)) < 0.5


def test_pulling_the_arcs_apart_does_register_as_a_change():
    """The complement: a genuine topology change must be caught."""
    from backend.core.junction_topology import catenation_in_frame

    conns, linked = _threaded_arcs(sep=1.0)
    reference = catenation_in_frame(conns, linked)["gauss_open"]

    _, unlinked = _threaded_arcs(sep=6.0)  # no longer threaded
    rep = catenation_in_frame(conns, unlinked, reference=reference)
    key = next(iter(reference))
    assert abs(rep["gauss_open"][key] - reference[key]) >= 0.5


# ── The build gate ────────────────────────────────────────────────────────────


def test_assert_not_catenated_raises_on_a_linked_build():
    with _repair_disabled(), pytest.raises(CatenatedJunctionError) as excinfo:
        assert_not_catenated(_reciprocal_design("T"))
    assert excinfo.value.report["n_catenated"] == 1
    assert "linking number" in str(excinfo.value)


def test_assert_not_catenated_passes_a_clean_build():
    report = assert_not_catenated(_reciprocal_design(None))
    assert report["ok"] is True
    assert report["override_used"] is False


def test_override_returns_the_report_instead_of_raising():
    with _repair_disabled():
        report = assert_not_catenated(_reciprocal_design("T"), allow=True)
    assert report["ok"] is False
    assert report["override_used"] is True
    assert report["n_catenated"] == 1


def test_catenated_rows_carry_integer_lk_and_residual():
    with _repair_disabled():
        hit = catenation_report(_reciprocal_design("T"))["catenated"][0]
    assert hit["lk_int"] in (-1, 1)
    assert hit["lk_residual"] < 0.15  # a well-conditioned closure


def test_gate_skips_the_build_for_a_design_with_no_inserts():
    """An ordinary design must not pay for a model build just to be gated."""
    verdict = gate_seed_topology(_reciprocal_design(None))
    assert verdict["gate"] == "skipped_no_extra_bases"
    assert verdict["ok"] is True


def test_gate_raises_on_a_catenated_seed():
    with _repair_disabled(), pytest.raises(CatenatedJunctionError):
        gate_seed_topology(_reciprocal_design("T"))


def test_gate_records_override_in_the_verdict():
    with _repair_disabled():
        verdict = gate_seed_topology(_reciprocal_design("T"), allow=True)
    assert verdict["gate"] == "overridden"
    assert verdict["override_requested"] is True
    assert verdict["n_catenated"] == 1


def test_gate_uses_the_supplied_model_not_a_fresh_build():
    """A seeded run must be gated on ITS OWN seed — that is the whole point of the
    ``model`` argument, since a freshly built model would not be what ships."""
    design = _reciprocal_design("T")
    with _repair_disabled():
        model = build_atomistic_model(design)
    # Collapse the inserts onto a single point: no longer threaded, so no longer linked.
    #
    # The point has to be OUTSIDE the structure.  This used the world origin until
    # 2026-08-07, and `make_bundle_design` puts helix 0's axis start exactly there — so the
    # collapsed inserts sat inside the first base pair's rings and their O3'-P bonds ran out
    # through the middle of the bundle.  Whether one clipped a ring was luck, and it began
    # clipping A1DT when the atomistic junction-balance roll moved every atom ~0.2 nm,
    # failing this test for a reason it never meant to assert.  Collapsing to a corner
    # outside the bounding box keeps the linking trivial (one common point) while the two
    # long bonds leave the structure instead of crossing it.
    import numpy as _np
    _xyz = _np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
    _pt = (float(_xyz[:, 0].min()) - 20.0, float(_xyz[:, 1].min()) - 20.0,
           float(_xyz[:, 2].mean()))
    for atom in model.atoms:
        if atom.crossover_id is not None and atom.extra_base_k is not None:
            atom.x, atom.y, atom.z = _pt
    verdict = gate_seed_topology(design, model=model)
    assert verdict["gate"] == "passed"


def test_design_has_extra_bases_detects_inserts():
    assert design_has_extra_bases(_reciprocal_design("T")) is True
    assert design_has_extra_bases(_reciprocal_design(None)) is False


# ── The repair ────────────────────────────────────────────────────────────────


def _positions(design):
    model = build_atomistic_model(design)
    return np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)


@pytest.mark.parametrize("extra", ["T", "TT"])
def _audit(design):
    """The project's calibrated geometry oracle (excludes bonded pairs)."""
    from backend.core.atomistic_validation import audit_bonds

    return audit_bonds(design)
