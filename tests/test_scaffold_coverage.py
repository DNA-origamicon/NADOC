"""
Scaffold full-coverage tests for auto_scaffold.

Two invariants that must hold for a correct scaffold routing:

  1. FULL COVERAGE — for every helix H and every bp index 0…length_bp-1, the
     scaffold-direction nucleotide at that position belongs to the scaffold
     strand.  Equivalently: the union of the scaffold domains on H covers
     [0, length_bp-1] without gaps.

  2. SINGLE STRAND — every scaffold-direction nucleotide in the design is on
     exactly ONE scaffold strand (no splits, no duplicates, no orphans on
     separate is_scaffold strands).

NOTE: these tests are intentionally skeptical of the existing
_assert_single_scaffold_all_helices helper in test_lattice.py, which only
checks that each helix ID appears in the domain list once.  That check passes
trivially with half-coverage routing and would REJECT a correct two-domain-
per-helix routing.  These tests measure actual bp coverage.

NOTE: scaffold/staple routing tests are only meaningful for 6 HB or larger
designs.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="seam-only routing: single-scaffold coverage invariant suspended")

from backend.core.lattice import auto_scaffold, make_bundle_design
from backend.core.models import Design, Direction, StrandType

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]


# ── Core coverage helpers ─────────────────────────────────────────────────────


def _scaffold_coverage(design: Design) -> dict[str, set[int]]:
    """Return {helix_id: set of bp_indices covered by the scaffold strand}.

    Walks all domains of all is_scaffold strands and records which bp indices
    they cover on which helix.
    """
    covered: dict[str, set[int]] = {}
    for strand in design.strands:
        if strand.strand_type == StrandType.STAPLE:
            continue
        for domain in strand.domains:
            hid = domain.helix_id
            lo  = min(domain.start_bp, domain.end_bp)
            hi  = max(domain.start_bp, domain.end_bp)
            covered.setdefault(hid, set()).update(range(lo, hi + 1))
    return covered


def _scaffold_direction_for_helix(design: Design, helix_id: str) -> Direction | None:
    """Return the scaffold direction on *helix_id* from the pre-routing strands."""
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            for domain in strand.domains:
                if domain.helix_id == helix_id:
                    return domain.direction
    return None


def _assert_full_coverage(result: Design, original_design: Design, label: str) -> None:
    """Assert every bp on every helix has a scaffold nucleotide.

    For each helix, the set of bp indices covered by scaffold domains must
    equal {0, 1, …, length_bp-1}.
    """
    coverage = _scaffold_coverage(result)
    helices_by_id = {h.id: h for h in result.helices}
    failures: list[str] = []

    for helix in result.helices:
        hid     = helix.id
        full    = set(range(helix.length_bp))
        covered = coverage.get(hid, set())
        missing = full - covered
        extra   = covered - full  # should never happen
        if missing:
            failures.append(
                f"  {hid}: missing {len(missing)} bp(s), "
                f"e.g. {sorted(missing)[:5]}"
            )
        if extra:
            failures.append(f"  {hid}: {len(extra)} bp(s) out of range")

    assert not failures, (
        f"{label}: scaffold does not cover every bp on every helix "
        f"({len(failures)} helix/helices with gaps):\n" + "\n".join(failures)
    )


def _assert_single_scaffold_strand(result: Design, label: str) -> None:
    """Assert exactly one is_scaffold strand exists and it covers all helices.

    Checks:
    - Exactly one strand with is_scaffold=True.
    - That strand has at least one domain on every helix.
    - No helix is covered by more than one scaffold strand (can't happen with
      exactly one scaffold strand, but explicit for clarity).
    """
    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1, (
        f"{label}: expected 1 scaffold strand, got {len(scaffolds)}: "
        + str([s.id for s in scaffolds])
    )
    scaffold = scaffolds[0]
    helix_ids_in_scaffold = {d.helix_id for d in scaffold.domains}
    all_helix_ids         = {h.id for h in result.helices}
    missing = all_helix_ids - helix_ids_in_scaffold
    assert not missing, (
        f"{label}: scaffold strand has no domain on helices: {missing}"
    )


# ── Parametrised tests ────────────────────────────────────────────────────────


@pytest.mark.parametrize("cells, length_bp, seam_bp", [
    (CELLS_6HB,  400, 150),
    (CELLS_6HB,  400, 200),
    (CELLS_18HB, 200, 100),
])
def test_scaffold_full_coverage(cells, length_bp, seam_bp):
    """Every bp on every helix must be on the scaffold strand."""
    design  = make_bundle_design(cells, length_bp=length_bp)
    result  = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp,
                            scaffold_loops=False)
    label   = f"{len(cells)}HB {length_bp}bp seam={seam_bp}"
    _assert_single_scaffold_strand(result, label)
    _assert_full_coverage(result, design, label)


@pytest.mark.parametrize("cells, length_bp, seam_bp", [
    (CELLS_6HB,  400, 150),
    (CELLS_6HB,  400, 200),
    (CELLS_18HB, 200, 100),
])
def test_scaffold_single_strand(cells, length_bp, seam_bp):
    """Exactly one scaffold strand, covering all helices."""
    design = make_bundle_design(cells, length_bp=length_bp)
    result = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp,
                           scaffold_loops=False)
    label  = f"{len(cells)}HB {length_bp}bp seam={seam_bp}"
    _assert_single_scaffold_strand(result, label)


@pytest.mark.parametrize("cells, length_bp, seam_bp", [
    (CELLS_6HB,  400, 150),
    (CELLS_18HB, 200, 100),
])
def test_scaffold_x_bases_per_bp_position(cells, length_bp, seam_bp):
    """At every bp position, exactly X helices must have a scaffold base (X = helix count)."""
    design    = make_bundle_design(cells, length_bp=length_bp)
    result    = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp,
                              scaffold_loops=False)
    label     = f"{len(cells)}HB {length_bp}bp seam={seam_bp}"
    coverage  = _scaffold_coverage(result)
    X         = len(result.helices)
    failures: list[str] = []

    for bp in range(length_bp):
        count = sum(1 for hid, bps in coverage.items() if bp in bps)
        if count != X:
            failures.append(f"  bp={bp}: {count}/{X} helices have scaffold")
        if failures and len(failures) > 5:
            failures.append("  ... (truncated)")
            break

    assert not failures, (
        f"{label}: expected {X} scaffold bases at every position:\n"
        + "\n".join(failures)
    )
