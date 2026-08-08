"""The full representation draws both arcs of a DX junction equally — and only it does.

A DX junction is two staple crossovers between the same helix pair at bp i and bp i+1.
The full (coarse-grained) rep draws each as a backbone bead-to-bead arc, and a Holliday
junction is symmetric, so the two arcs must be equal.

Honeycomb already was.  Square drew 1.126 nm against 0.286 nm until the display-only
``junction_balance`` roll landed (``constants.FULL_REP_BALANCE_ROLL_*``).

These tests assert the PROPERTY (equal arcs), not the constant.  If the shared lattice
phase ever moves, the balance point moves with it and this fails rather than drifting
silently — the roll must then be re-measured.

The other two tests are the firewall: the roll is display-only, so the geometric layer,
every seed writer, every exporter and every pose fitter must see byte-identical geometry
with it absent.
"""

from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import (
    _geometry_for_design,
    _positions_for_design,
    full_rep_balance_roll_rad,
)
from backend.core.models import Design, LatticeType, StrandType

SQUARE_FIXTURE = Path("workspace/2x3x100_Sq_test.nadoc")
HONEYCOMB_FIXTURE = Path("workspace/6hb_e_test.nadoc")

# Both arcs of every junction must agree to this, in nm.  The measured residual is
# 0.000000 on square and 0.0005 on honeycomb (the latter is the shipped lattice phase,
# not this roll).
ARC_TOL_NM = 0.001


def _load(path: Path) -> Design:
    if not path.exists():
        pytest.skip(f"fixture {path} not present on this machine")
    return Design.model_validate_json(path.read_text())


def _staple_slots(design: Design) -> set:
    out = set()
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE:
            continue
        for dom in s.domains:
            lo, hi = min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)
            for bp in range(lo, hi + 1):
                out.add((dom.helix_id, bp, dom.direction))
    return out


def _junction_arc_deltas(
    design: Design, *, junction_balance: bool, measured_positioning: bool = False
) -> list[float]:
    """Signed (arc at i+1) − (arc at i) for every DX junction, in nm."""
    nucs = _geometry_for_design(
        design,
        compact_skips=True,
        measured_positioning=measured_positioning,
        junction_balance=junction_balance,
    )
    gm = {(n["helix_id"], n["bp_index"], str(n["direction"])): n for n in nucs}
    staple = _staple_slots(design)

    arcs: dict = {}
    for x in design.crossovers:
        a, b = x.half_a, x.half_b
        if (a.helix_id, a.index, a.strand) not in staple:
            continue
        na = gm.get((a.helix_id, a.index, str(a.strand.value)))
        nb = gm.get((b.helix_id, b.index, str(b.strand.value)))
        if na is None or nb is None:
            continue
        d = np.linalg.norm(
            np.asarray(nb["backbone_position"], float)
            - np.asarray(na["backbone_position"], float)
        )
        arcs[(frozenset((a.helix_id, b.helix_id)), a.index)] = float(d)

    by_pair = defaultdict(dict)
    for (pair, idx), v in arcs.items():
        by_pair[pair][idx] = v
    return [
        by_pair[pair][i + 1] - v
        for pair, items in by_pair.items()
        for i, v in items.items()
        if i + 1 in items
    ]


def test_the_square_full_rep_draws_both_arcs_of_a_dx_junction_equally():
    design = _load(SQUARE_FIXTURE)
    assert design.lattice_type == LatticeType.SQUARE
    deltas = _junction_arc_deltas(design, junction_balance=True)
    assert len(deltas) >= 20, "fixture lost its DX junctions"
    assert max(abs(d) for d in deltas) < ARC_TOL_NM


def test_the_roll_survives_help_new_positioning():
    """The measured re-placement runs AFTER the roll in the same serialiser.

    The cell-independent O5' projection must preserve that roll. Detailed DX geometry is
    intentionally reviewed separately from the basic nucleotide landmark correction.
    """
    deltas = _junction_arc_deltas(
        _load(SQUARE_FIXTURE), junction_balance=True, measured_positioning=True
    )
    assert max(abs(d) for d in deltas) < 1.1e-3


def test_the_square_full_rep_is_grossly_asymmetric_without_the_roll():
    """The bug this fixes — pinned so a silent revert cannot pass as 'no change'."""
    deltas = _junction_arc_deltas(_load(SQUARE_FIXTURE), junction_balance=False)
    assert min(deltas) < -0.8, "square without the roll should be ~0.84 nm out"


def test_the_honeycomb_full_rep_stays_balanced_and_unrolled():
    design = _load(HONEYCOMB_FIXTURE)
    assert design.lattice_type == LatticeType.HONEYCOMB
    assert full_rep_balance_roll_rad(design) == 0.0
    deltas = _junction_arc_deltas(design, junction_balance=True)
    assert max(abs(d) for d in deltas) < ARC_TOL_NM


def test_the_roll_is_absent_from_the_geometric_layer_by_default():
    """FIREWALL: every seed, export and pose fitter goes through the default.

    ``_geometry_for_design`` has ~50 consumers and almost all of them are simulation
    or fitting paths.  The default must stay unrolled, and on square the two must
    differ — otherwise this test would pass on a build where the flag does nothing.
    """
    design = _load(SQUARE_FIXTURE)
    default = _geometry_for_design(design, compact_skips=True)
    explicit_off = _geometry_for_design(
        design, compact_skips=True, junction_balance=False
    )
    rolled = _geometry_for_design(design, compact_skips=True, junction_balance=True)

    for a, b in zip(default, explicit_off):
        assert a["backbone_position"] == b["backbone_position"]

    moved = max(
        float(
            np.linalg.norm(
                np.asarray(a["backbone_position"], float)
                - np.asarray(b["backbone_position"], float)
            )
        )
        for a, b in zip(default, rolled)
    )
    assert moved > 0.1, "the flag moved nothing — the firewall test would be vacuous"


def test_the_atomistic_build_never_sees_the_display_roll():
    """The atomistic model is the source of truth; a display tweak may not move an atom.

    (It carries its OWN balance roll — ``atomistic.atomistic_phase_offset_rad`` — which is
    a different constant applied in a different layer.  This asserts the DISPLAY flag has
    no effect on atoms, not that atoms are unrolled.)
    """
    design = _load(SQUARE_FIXTURE)
    before = build_atomistic_model(design, fast_bridges=True)
    _geometry_for_design(design, junction_balance=True)  # the display request
    after = build_atomistic_model(design, fast_bridges=True)
    assert len(before.atoms) == len(after.atoms)
    for a, b in zip(before.atoms, after.atoms):
        assert (a.x, a.y, a.z) == (b.x, b.y, b.z)


def _atomistic_junction_gaps(design: Design) -> list[tuple[float, float]]:
    """(gap at i, gap at i+1) per DX junction — C3'(src)→C5'(dst), in nm.

    The anchor gap, NOT the O3'-P bond: ``_minimize_backbone_bridge`` places O3'/P/O5'
    between these two fixed anchors, so the bond it produces hides the very asymmetry
    this measures (LESSONS H15/H19 — never measure through a minimiser).
    """
    # fast_bridges: the anchors this measures (C3'/C5') are stamp output, which the exact
    # L-BFGS-B bridge solve does not touch — it only places the O3'/P/O5' BETWEEN them.
    # So the cheap linear linker is measurement-identical here and ~6x faster (6.9s -> under
    # the per-test budget on the 234-crossover honeycomb fixture).
    model = build_atomistic_model(design, fast_bridges=True)
    pos: dict = defaultdict(dict)
    for a in model.atoms:
        if a.crossover_id is None and a.extension_id is None:
            pos[(a.helix_id, a.bp_index, a.direction)][a.name] = (a.x, a.y, a.z)

    per_x: dict = {}
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE:
            continue
        for d1, d2 in zip(s.domains, s.domains[1:]):
            if d1.helix_id == d2.helix_id or d1.end_bp != d2.start_bp:
                continue
            donor = pos.get((d1.helix_id, d1.end_bp, d1.direction.value), {})
            acc = pos.get((d2.helix_id, d2.start_bp, d2.direction.value), {})
            if "C3'" in donor and "C5'" in acc:
                per_x[(frozenset((d1.helix_id, d2.helix_id)), d1.end_bp)] = float(
                    np.linalg.norm(np.asarray(acc["C5'"]) - np.asarray(donor["C3'"]))
                )

    by_pair = defaultdict(dict)
    for (pair, idx), v in per_x.items():
        by_pair[pair][idx] = v
    return [
        (v, items[i + 1])
        for pair, items in by_pair.items()
        for i, v in items.items()
        if i + 1 in items
    ]


@pytest.mark.parametrize("fixture", [HONEYCOMB_FIXTURE, SQUARE_FIXTURE])
def test_the_atomistic_dx_junction_linkers_are_balanced(fixture):
    """The user-visible defect: one linker of every pair was stamped overstretched.

    Honeycomb was the bad case — 0.586 vs 1.086 nm, i.e. one linker 0.48 nm past the
    0.606 nm phosphodiester contour while its partner was comfortably inside it.
    """
    gaps = _atomistic_junction_gaps(_load(fixture))
    assert len(gaps) >= 20
    deltas = [hi - lo for lo, hi in gaps]

    # Mean: this is what the roll is fitted on, and it lands on zero (measured +0.0002 on
    # honeycomb, −0.0057 on square, against +0.500 / +0.485 before).
    assert abs(sum(deltas) / len(deltas)) < 0.01, (
        "the DX pair is not balanced on average"
    )

    # Per junction: a residual 0.060 nm spread survives, and it is NOT the roll — the
    # measured templates are per-residue, so a junction's two linkers see different bases.
    # It was 0.561 / 0.552 before, so the tolerance is set just above the residual to catch
    # a regression rather than to describe one.
    assert max(abs(d) for d in deltas) < 0.08

    # The balance point is also where the WORST linker of any pair is shortest: 1.126 → 0.761.
    assert max(max(g) for g in gaps) < 0.80


def test_the_straight_positions_carry_the_same_roll_as_the_nucleotides():
    """They ship in ONE response, so a mismatch draws unrolled beads beside rolled ones."""
    design = _load(SQUARE_FIXTURE)
    straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
    positions, _ = _positions_for_design(straight, junction_balance=True)
    nucs = _geometry_for_design(straight, junction_balance=True)

    by_key = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in nucs
    }
    checked = 0
    for hid, by_dir in positions.items():
        for dir_name, bucket in by_dir.items():
            for i, bp in enumerate(bucket["bp"]):
                want = by_key.get((hid, bp, dir_name))
                if want is None:
                    continue
                assert np.allclose(bucket["bb"][i], want, atol=1e-12)
                checked += 1
    assert checked > 100


# ── The inversion: the bead is derived, the stamp is not ──────────────────────


@pytest.mark.parametrize("fixture", [HONEYCOMB_FIXTURE, SQUARE_FIXTURE])
def test_the_cg_bead_is_a_projection_of_the_helical_site(fixture):
    """``position == axis_point + HELIX_RADIUS * radial_hat``, exactly, for every nucleotide.

    This is what makes the coarse-grained bead a DERIVED quantity rather than the carrier
    of the helical phase.  The phase is ``radial_hat`` / ``azimuth_rad``; the bead is one
    projection of it and the atomistic stamp is another (at ``_ATOMISTIC_P_RADIUS``).
    """
    from backend.core.constants import HELIX_RADIUS
    from backend.core.deformation import effective_helix_for_geometry
    from backend.core.geometry import nucleotide_positions

    design = _load(fixture)
    checked = 0
    for helix in design.helices:
        for n in nucleotide_positions(effective_helix_for_geometry(helix, design)):
            assert n.radial_hat is not None and n.axis_point is not None
            assert np.array_equal(
                n.position, n.axis_point + HELIX_RADIUS * n.radial_hat
            )
            assert abs(float(np.linalg.norm(n.radial_hat)) - 1.0) < 1e-12
            checked += 1
    assert checked > 100


def test_the_stamp_ignores_the_bead_and_reads_the_phase():
    """Move the bead OFF its cylinder and the atoms must not care.

    The old frame recovered the phase from ``position``, so corrupting the bead moved every
    atom.  The stamp now reads ``radial_hat``, so this is a no-op — that is the inversion,
    asserted rather than described.  (The bead still supplies the AXIAL offset, which is why
    the corruption here is purely radial.)
    """
    import dataclasses as dc

    import backend.core.geometry as geo

    design = _load(SQUARE_FIXTURE)
    before = build_atomistic_model(design, fast_bridges=True)

    orig = geo.nucleotide_positions

    def bead_corrupted(helix, compact_skips=False):
        out = []
        for n in orig(helix, compact_skips=compact_skips):
            radial = n.radial_hat
            out.append(dc.replace(n, position=n.axis_point + 3.7 * radial))
        return out

    geo.nucleotide_positions = bead_corrupted
    try:
        after = build_atomistic_model(design, fast_bridges=True)
    finally:
        geo.nucleotide_positions = orig

    assert len(before.atoms) == len(after.atoms)
    worst = max(
        abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z)
        for a, b in zip(before.atoms, after.atoms)
    )
    assert worst == 0.0, f"the stamp still reads the display bead ({worst:.3e} nm)"
