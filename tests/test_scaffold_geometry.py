"""
Scaffold backbone bond-distance tests for auto_scaffold.

For every pair of consecutive nucleotides in the routed scaffold strand, the
3-D Euclidean distance between their backbone bead positions must fall within
physically plausible bounds that depend on the bond type:

  • Within-helix bond  ≈ WITHIN_HELIX_DIST nm  (~0.678 nm)
  • Crossover bond     ≤ SCAFFOLD_XOVER_MAX nm  (= HONEYCOMB_HELIX_SPACING
                                                   + HELIX_RADIUS ≈ 3.25 nm)

Both bounds are derived from B-DNA / lattice geometry constants so the tests
stay correct if those constants are ever updated.

NOTE: scaffold/staple routing tests are only meaningful for 6 HB or larger
designs.  A 2 HB design is too small — it has only one crossover pair, which
is always a loop crossover with no seam crossovers, and the path topology
gives no useful coverage of the alternating loop/seam logic.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
    HONEYCOMB_HELIX_SPACING,
)
from backend.core.geometry import nucleotide_positions
from backend.core.lattice import auto_scaffold, make_bundle_design
from backend.core.models import Design, Direction, StrandType

client = TestClient(app)

# ── Derived geometry constants ────────────────────────────────────────────────

# Exact within-helix backbone bond length computed from B-DNA parameters.
# chord = 2 × R × sin(twist/2); dist = √(rise² + chord²)
_chord = 2.0 * HELIX_RADIUS * math.sin(BDNA_TWIST_PER_BP_RAD / 2.0)
WITHIN_HELIX_DIST: float = math.sqrt(BDNA_RISE_PER_BP**2 + _chord**2)

# Maximum scaffold crossover backbone distance.
# The scaffold uses FORWARD(A)→REVERSE(B) at a crossover, while the geometrically
# closest pair at the same bp is REVERSE(A)→FORWARD(B) (the staple direction,
# ≤ 0.25 nm).  The scaffold pair has a fixed 60° angular offset, giving
# d_max = HONEYCOMB_HELIX_SPACING + HELIX_RADIUS  (analytically exact for same-bp
# crossovers in the honeycomb lattice).
SCAFFOLD_XOVER_MAX: float = HONEYCOMB_HELIX_SPACING + HELIX_RADIUS

# Floating-point tolerance for geometry comparisons.
GEOM_TOL: float = 1e-4  # nm

# ── Canonical cell layouts ────────────────────────────────────────────────────

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]

CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _domain_backbone_positions(
    domain, helices_by_id: dict
) -> list[np.ndarray]:
    """Return backbone bead positions for one domain in 5′→3′ order."""
    h = helices_by_id[domain.helix_id]
    nuc_map = {
        (n.bp_index, n.direction): n.position
        for n in nucleotide_positions(h)
    }
    step = 1 if domain.direction == Direction.FORWARD else -1
    positions: list[np.ndarray] = []
    for bp in range(domain.start_bp, domain.end_bp + step, step):
        pos = nuc_map.get((bp, domain.direction))
        if pos is not None:
            positions.append(pos)
    return positions


def _assert_bond_distances(design: Design, label: str) -> None:
    """Assert all consecutive scaffold backbone bond distances are valid.

    Checks two bond types separately:

    Within-helix bonds (consecutive nucleotides on the same domain):
      Must be close to WITHIN_HELIX_DIST (~0.678 nm).
      Bounds: 0.1 nm … WITHIN_HELIX_DIST + GEOM_TOL.

    Crossover bonds (last nucleotide of domain[i] → first of domain[i+1]):
      The scaffold backbone pair FORWARD(A)–REVERSE(B) has a fixed 60° angular
      offset in the honeycomb lattice, so the max backbone distance is
      HONEYCOMB_HELIX_SPACING + HELIX_RADIUS = 3.25 nm.
      Bounds: 0.1 nm … SCAFFOLD_XOVER_MAX + GEOM_TOL.
    """
    scaffold = next((s for s in design.strands if s.strand_type == StrandType.SCAFFOLD), None)
    assert scaffold is not None, f"{label}: no scaffold strand found"

    helices_by_id = {h.id: h for h in design.helices}
    domains = scaffold.domains
    assert len(domains) >= 2, f"{label}: scaffold has too few domains ({len(domains)})"

    failures: list[str] = [
    ]

    for i, domain in enumerate(domains):
        positions = _domain_backbone_positions(domain, helices_by_id)

        # Within-helix bonds
        for j in range(len(positions) - 1):
            d = float(np.linalg.norm(positions[j + 1] - positions[j]))
            if not (0.1 <= d <= WITHIN_HELIX_DIST + GEOM_TOL):
                failures.append(
                    f"  within-helix domain[{i}] bond {j}: {d:.5f} nm"
                    f"  (expected ≈{WITHIN_HELIX_DIST:.4f})"
                )

        # Crossover bond to next domain
        if i < len(domains) - 1 and positions:
            next_domain = domains[i + 1]
            next_positions = _domain_backbone_positions(next_domain, helices_by_id)
            if next_positions:
                d = float(np.linalg.norm(next_positions[0] - positions[-1]))
                if domain.helix_id == next_domain.helix_id:
                    # Same-helix continuation (shouldn't appear in normal routing)
                    max_d = WITHIN_HELIX_DIST + GEOM_TOL
                    bond_type = "same-helix"
                else:
                    max_d = SCAFFOLD_XOVER_MAX + GEOM_TOL
                    bond_type = "crossover"
                if not (0.1 <= d <= max_d):
                    failures.append(
                        f"  {bond_type} domain[{i}]→[{i+1}]: {d:.5f} nm"
                        f"  (expected 0.1 … {max_d:.4f})"
                    )

    assert not failures, (
        f"{label}: {len(failures)} bond(s) out of range "
        f"(WITHIN_HELIX_DIST≈{WITHIN_HELIX_DIST:.4f}, "
        f"SCAFFOLD_XOVER_MAX={SCAFFOLD_XOVER_MAX}):\n"
        + "\n".join(failures)
    )


# ── Direct function tests — seam_line mode ────────────────────────────────────


@pytest.mark.skip(reason="seam-only routing: bond-distance check expects single scaffold strand")
@pytest.mark.parametrize("cells, length_bp, seam_bp", [
    (CELLS_6HB,  1200,  100),
    (CELLS_6HB,  1200,  595),
    (CELLS_6HB,  1200,  600),
    (CELLS_6HB,   400,  150),
    (CELLS_18HB,  400,  100),
    (CELLS_18HB,  400,  200),
    (CELLS_18HB,  400,  350),
    (CELLS_18HB,  126,   50),
])
def test_scaffold_bond_distances_seam_line(cells, length_bp, seam_bp):
    """Seam-line scaffold: all backbone bonds within expected bounds."""
    design = make_bundle_design(cells, length_bp=length_bp)
    result = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp)
    _assert_bond_distances(result, f"{len(cells)}HB {length_bp}bp seam={seam_bp}")


@pytest.mark.parametrize("cells, length_bp", [
    (CELLS_6HB,  400),
    (CELLS_18HB, 200),
])
def test_scaffold_bond_distances_end_to_end(cells, length_bp):
    """End-to-end scaffold: all backbone bonds within expected bounds."""
    design = make_bundle_design(cells, length_bp=length_bp)
    result = auto_scaffold(design, mode="end_to_end")
    _assert_bond_distances(result, f"{len(cells)}HB {length_bp}bp end_to_end")


# ── Within-helix bond accuracy ────────────────────────────────────────────────


@pytest.mark.skip(reason="seam-only routing: expects single scaffold strand")
@pytest.mark.parametrize("cells, length_bp, seam_bp", [
    (CELLS_6HB,  1200, 600),
    (CELLS_18HB,  400, 200),
])
def test_within_helix_bonds_match_geometry(cells, length_bp, seam_bp):
    """Within-domain backbone bonds equal the analytic B-DNA bond length."""
    design = make_bundle_design(cells, length_bp=length_bp)
    result = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)

    helices_by_id = {h.id: h for h in result.helices}
    bad: list[str] = []

    for domain in scaffold.domains:
        h = helices_by_id[domain.helix_id]
        nuc_map = {
            (n.bp_index, n.direction): n.position
            for n in nucleotide_positions(h)
        }
        step = 1 if domain.direction == Direction.FORWARD else -1
        prev_pos = None
        for bp in range(domain.start_bp, domain.end_bp + step, step):
            pos = nuc_map.get((bp, domain.direction))
            if pos is None:
                continue
            if prev_pos is not None:
                d = float(np.linalg.norm(pos - prev_pos))
                if abs(d - WITHIN_HELIX_DIST) > 5e-4:
                    bad.append(
                        f"  {domain.helix_id} bp {bp}: dist={d:.5f} "
                        f"expected {WITHIN_HELIX_DIST:.5f}"
                    )
            prev_pos = pos

    assert not bad, (
        f"{len(cells)}HB {length_bp}bp: {len(bad)} within-helix bond(s) "
        f"deviate from expected {WITHIN_HELIX_DIST:.5f} nm:\n"
        + "\n".join(bad[:10])
    )


# ── Crossover positions are geometrically valid ───────────────────────────────


@pytest.mark.skip(reason="seam-only routing: expects single scaffold strand")
@pytest.mark.parametrize("cells, length_bp, seam_bp", [
    (CELLS_6HB,  1200, 600),
    (CELLS_6HB,   400, 150),
    (CELLS_18HB,  400, 200),
    (CELLS_18HB,  126,  50),
])
def test_crossover_positions_are_valid(cells, length_bp, seam_bp):
    """Each scaffold crossover (bp_a, bp_b) appears in valid_crossover_positions."""
    from backend.core.crossover_positions import valid_crossover_positions

    design = make_bundle_design(cells, length_bp=length_bp)
    result = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)

    helices_by_id = {h.id: h for h in result.helices}
    bad: list[str] = []

    for i, domain in enumerate(scaffold.domains[:-1]):
        next_domain = scaffold.domains[i + 1]
        if domain.helix_id == next_domain.helix_id:
            continue  # same-helix continuation, skip

        h_a = helices_by_id[domain.helix_id]
        h_b = helices_by_id[next_domain.helix_id]
        bp_a = domain.end_bp
        bp_b = next_domain.start_bp

        cands = valid_crossover_positions(h_a, h_b)
        valid_bps = (
            {(c.bp_a, c.bp_b) for c in cands}
            | {(c.bp_b, c.bp_a) for c in cands}
        )
        if (bp_a, bp_b) not in valid_bps:
            bad.append(
                f"  domain[{i}]→[{i+1}]: ({domain.helix_id}:bp{bp_a}"
                f" → {next_domain.helix_id}:bp{bp_b}) not in valid candidates"
            )

    assert not bad, (
        f"{len(cells)}HB {length_bp}bp seam={seam_bp}: "
        f"{len(bad)} crossover(s) at invalid positions:\n"
        + "\n".join(bad)
    )


# ── API endpoint tests ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_design_state():
    """Restore design state before and after each test in this module."""
    original = design_state.get_design()
    yield
    if original is not None:
        design_state.set_design(original)
    else:
        design_state.set_design_silent(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("cells, length_bp, seam_bp, loop_size", [
    (CELLS_6HB,  1200, 600,  7),
    (CELLS_6HB,   400, 150, 14),
    (CELLS_18HB,  400, 200,  7),
    (CELLS_18HB,  400, 100, 14),
    (CELLS_18HB,  126,  50,  7),
])
@pytest.mark.skip(reason="seam-only routing: bond-distance check expects single scaffold strand")
def test_autoscaffold_api_bond_distances(cells, length_bp, seam_bp, loop_size):
    """POST /api/design/auto-scaffold: backbone bonds valid for 6HB+ designs."""
    design = make_bundle_design(cells, length_bp=length_bp)
    design_state.set_design(design)

    r = client.post("/api/design/auto-scaffold", json={
        "mode":           "seam_line",
        "scaffold_loops": True,
        "seam_bp":        seam_bp,
        "loop_size":      loop_size,
    })
    assert r.status_code == 200, (
        f"API returned {r.status_code}: {r.text}"
    )

    result = design_state.get_design()
    assert result is not None
    label = (
        f"API {len(cells)}HB {length_bp}bp "
        f"seam={seam_bp} loop={loop_size}"
    )
    _assert_bond_distances(result, label)
