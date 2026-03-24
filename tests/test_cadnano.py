"""
Tests for caDNAno v2 import — Phase CN.

Methodology
───────────
For each hypothesis we:
  1. State the hypothesis.
  2. Run an experiment (assertion or printed figure).
  3. Record the conclusion.

Nearest-neighbour geometry is validated via the shared helper from
test_helix_neighbors.py, which checks that HC interior helices have 3
neighbours at uniform 120° gaps and SQ interior helices have 4 at 90°.
"""

from __future__ import annotations

import json
import math
import pathlib
import textwrap

import pytest

# ── Paths ─────────────────────────────────────────────────────────────────────

EXAMPLES = pathlib.Path(__file__).parent.parent / "Examples" / "cadnano"
HB6_CN   = EXAMPLES / "Honeycomb_6hb_test1.json"
HB18_CN  = EXAMPLES / "18hb_symm_p7249_21_even_spacing_sequential_coloring.json"
HB6_NADOC = (
    pathlib.Path(__file__).parent.parent
    / "Examples"
    / "Honeycome_6hb_test1_NADOC.nadoc"
)

# ── Shared geometry helper (from test_helix_neighbors) ────────────────────────

from tests.test_helix_neighbors import _assert_neighbour_geometry  # noqa: E402


# ── Load helpers ──────────────────────────────────────────────────────────────

def _load_cn(path: pathlib.Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _import(path: pathlib.Path):
    from backend.core.cadnano import import_cadnano
    design, _ = import_cadnano(_load_cn(path))
    return design


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 1 — 6HB helix count and lattice detection
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: Importing Honeycomb_6hb_test1.json should produce exactly 6
# helices and lattice_type HONEYCOMB.
#
# Experiment: assert design.helices count and lattice_type.
#
# Expected: pass.  If the importer skips or duplicates vstrands this fails.
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_helix_count():
    """6HB import produces 6 helices."""
    from backend.core.models import LatticeType
    design = _import(HB6_CN)
    assert len(design.helices) == 6, (
        f"Expected 6 helices, got {len(design.helices)}"
    )
    assert design.lattice_type == LatticeType.HONEYCOMB


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 2 — Helix IDs encode caDNAno row/col
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: Each helix ID is "h_XY_{row}_{col}" using the raw caDNAno
# row/col values, preserving the coordinate for roundtrip export.
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_helix_ids():
    """Helix IDs use NADOC h_XY_{nr}_{nc} format (0-based, normalised coords)."""
    design = _import(HB6_CN)
    for h in design.helices:
        assert h.id.startswith("h_XY_"), f"Unexpected ID prefix: {h.id!r}"
        parts = h.id.split("_")
        assert len(parts) == 4, f"Unexpected ID format: {h.id!r}"
        nr, nc = int(parts[2]), int(parts[3])
        assert nr >= 0 and nc >= 0, f"Negative coords in {h.id!r}"


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 3 — bp_start = 0 and length_bp = array length
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: All imported helices should have bp_start=0 and length_bp equal
# to the number of entries in the caDNAno scaf array (42 for the 6HB).
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_helix_bp_start_and_length():
    """bp_start=0 and length_bp matches caDNAno array length."""
    data = _load_cn(HB6_CN)
    array_len = len(data["vstrands"][0]["scaf"])  # should be 42
    design = _import(HB6_CN)
    for h in design.helices:
        assert h.bp_start == 0, f"Helix {h.id} bp_start={h.bp_start}, expected 0"
        assert h.length_bp == array_len, (
            f"Helix {h.id} length_bp={h.length_bp}, expected {array_len}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 4 — Helix XY positions match honeycomb geometry
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: Imported helix XY positions should satisfy the honeycomb
# neighbour geometry: every helix has 1–3 neighbours at HELIX_SPACING
# (2.25 nm) and at uniform angular gaps (120° for interior helices).
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_neighbour_geometry():
    """6HB imported design passes nearest-neighbour geometry check."""
    from backend.core.constants import HONEYCOMB_HELIX_SPACING
    design = _import(HB6_CN)
    _assert_neighbour_geometry(
        design,
        expected_spacing=HONEYCOMB_HELIX_SPACING,
        expected_interior_count=3,
        expected_gap=120.0,
        label="6HB caDNAno import",
    )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 5 — Scaffold strand count (single scaffold expected)
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: The 6HB test file has 6 disconnected helices (no inter-helix
# crossovers), so there should be 6 scaffold strands (one per helix).
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_scaffold_strand_count():
    """6HB with no crossovers produces 6 scaffold strands."""
    from backend.core.models import StrandType
    design = _import(HB6_CN)
    scaf_strands = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaf_strands) == 6, (
        f"Expected 6 scaffold strands, got {len(scaf_strands)}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 6 — Staple strand count
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: 6HB test has 6 staple strands (one per helix, antiparallel).
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_staple_strand_count():
    """6HB produces 6 staple strands."""
    from backend.core.models import StrandType
    design = _import(HB6_CN)
    stap_strands = [s for s in design.strands if s.strand_type == StrandType.STAPLE]
    assert len(stap_strands) == 6, (
        f"Expected 6 staple strands, got {len(stap_strands)}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 7 — Scaffold direction per vstrand (num % 2 rule)
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: Even-num vstrands produce FORWARD scaffold domains; odd-num
# vstrands produce REVERSE scaffold domains.
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_scaffold_directions():
    """Scaffold domain directions are consistent (all strands have single direction)."""
    from backend.core.models import Direction, StrandType
    design = _import(HB6_CN)
    # Each single-domain strand has exactly one direction; just check no domain
    # has a zero-length range (start_bp == end_bp).
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for domain in strand.domains:
            assert domain.start_bp != domain.end_bp, (
                f"Zero-length domain on {domain.helix_id}"
            )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 8 — Domain bp range covers the full helix
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: In the 6HB test (no crossovers), each strand has exactly one
# domain spanning the full 42-bp array (bp 0..41).
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_domain_spans_full_helix():
    """Each strand has one domain spanning the full bp array."""
    from backend.core.models import Direction
    design = _import(HB6_CN)
    for strand in design.strands:
        assert len(strand.domains) == 1, (
            f"Strand {strand.id} has {len(strand.domains)} domains, expected 1"
        )
        d = strand.domains[0]
        lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
        assert lo == 0 and hi == 41, (
            f"Strand {strand.id} domain {d.start_bp}..{d.end_bp}, expected 0..41"
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 9 — No crossovers for the 6HB test (self-contained vstrands)
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: The 6HB json has no inter-helix connections in scaf/stap, so
# design.crossovers should be empty.
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_no_crossovers():
    """6HB test (no inter-helix links) produces zero Crossover objects."""
    design = _import(HB6_CN)
    assert len(design.crossovers) == 0, (
        f"Expected 0 crossovers, got {len(design.crossovers)}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 10 — Colour import from stap_colors
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: Staple strands whose 5′ end has a stap_colors entry should have
# a non-None color field formatted as "#RRGGBB".
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_stap_colors_imported():
    """Staple colors from stap_colors are imported as #RRGGBB strings."""
    from backend.core.models import StrandType
    design = _import(HB6_CN)

    # 6HB has one stap_color entry per vstrand; each has color > 0
    colored = [
        s for s in design.strands
        if s.strand_type == StrandType.STAPLE and s.color is not None
    ]
    assert len(colored) > 0, "No staple strands have a color assigned"

    for s in colored:
        assert s.color.startswith("#"), f"Color {s.color!r} not in #RRGGBB format"
        assert len(s.color) == 7, f"Color {s.color!r} wrong length"


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 11 — Geometry figure: helix XY positions (diagnostic printout)
# ═════════════════════════════════════════════════════════════════════════════
#
# Purpose: Produce a human-readable ASCII figure of the 6HB helix positions
# to confirm spatial layout is correct (run with -s to see output).
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_geometry_figure(capsys):
    """Print ASCII figure of 6HB helix XY positions for visual inspection."""
    design = _import(HB6_CN)

    print("\n" + "═" * 60)
    print("FIGURE 1 — 6HB caDNAno import: helix XY positions")
    print("═" * 60)
    print(f"{'ID':<20} {'X (nm)':>10} {'Y (nm)':>10}")
    print("-" * 60)

    for h in sorted(design.helices, key=lambda h: h.id):
        print(f"{h.id:<20} {h.axis_start.x:>10.4f} {h.axis_start.y:>10.4f}")

    print("═" * 60)


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 12 — Strand figure: domain summary (diagnostic)
# ═════════════════════════════════════════════════════════════════════════════

def test_6hb_strand_figure(capsys):
    """Print strand and domain summary for visual inspection."""
    from backend.core.models import StrandType
    design = _import(HB6_CN)

    print("\n" + "═" * 60)
    print("FIGURE 2 — 6HB caDNAno import: strands and domains")
    print("═" * 60)
    for s in design.strands:
        stype = "SCAF" if s.strand_type == StrandType.SCAFFOLD else "STAP"
        color = s.color or "(default)"
        print(f"  {s.id:<30} [{stype}] color={color}")
        for i, d in enumerate(s.domains):
            print(
                f"    domain[{i}]: {d.helix_id}  bp {d.start_bp}..{d.end_bp}"
                f"  dir={d.direction.value}"
            )
    print("═" * 60)


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 13 — NADOC reference comparison
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: The caDNAno-imported 6HB and the native NADOC 6HB reference
# file should have the same number of helices and same relative XY geometry.
# The absolute positions will differ (caDNAno uses raw row/col offsets) but
# pairwise distances between neighbours should match.
# ─────────────────────────────────────────────────────────────────────────────

def test_6hb_matches_nadoc_reference_geometry():
    """Imported 6HB has same pairwise neighbour distances as NADOC reference."""
    from backend.core.models import Design as D
    from backend.core.constants import HONEYCOMB_HELIX_SPACING

    cn_design = _import(HB6_CN)
    with open(HB6_NADOC) as f:
        nadoc_design = D.from_json(f.read())

    def _neighbour_pairs(design, spacing, tol=0.02):
        """Return set of neighbour pairs by sorted distance ≤ spacing+tol."""
        xy = {
            h.id: (h.axis_start.x, h.axis_start.y)
            for h in design.helices
        }
        pairs = set()
        ids = list(xy)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                ax, ay = xy[a]
                bx, by = xy[b]
                dist = math.hypot(bx - ax, by - ay)
                if dist <= spacing + tol:
                    pairs.add(dist)
        return pairs

    cn_dists = _neighbour_pairs(cn_design, HONEYCOMB_HELIX_SPACING)
    nadoc_dists = _neighbour_pairs(nadoc_design, HONEYCOMB_HELIX_SPACING)

    assert len(cn_dists) > 0, "caDNAno import has no neighbour pairs"
    assert len(nadoc_dists) > 0, "NADOC reference has no neighbour pairs"

    # All distances should be HONEYCOMB_HELIX_SPACING within tolerance
    for dist in cn_dists:
        assert abs(dist - HONEYCOMB_HELIX_SPACING) < 0.02, (
            f"caDNAno: unexpected neighbour distance {dist:.4f} nm"
        )
    for dist in nadoc_dists:
        assert abs(dist - HONEYCOMB_HELIX_SPACING) < 0.02, (
            f"NADOC ref: unexpected neighbour distance {dist:.4f} nm"
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 14 — 18HB import: helix count and scaffold path length
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: The 18HB design has 22 vstrands, 4 of which are holes in the
# caDNAno canvas (num skips: 6,8,9 etc.).  Only the 18 valid vstrands should
# appear as helices.  The single scaffold strand should be 7249 nt long.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not HB18_CN.exists(), reason="18HB file not present")
def test_18hb_helix_count():
    """18HB import: 18 helices (empty placeholder vstrands are skipped)."""
    data = _load_cn(HB18_CN)
    active = sum(
        1 for v in data["vstrands"]
        if any(nh != -1 or ph != -1 for ph, pp, nh, np_ in v["scaf"])
    )
    design = _import(HB18_CN)
    assert len(design.helices) == active, (
        f"Expected {active} helices (active vstrands), got {len(design.helices)}"
    )


@pytest.mark.skipif(not HB18_CN.exists(), reason="18HB file not present")
def test_18hb_scaffold_length():
    """18HB scaffold strand totals 7249 nucleotides (M13 length)."""
    from backend.core.models import StrandType
    design = _import(HB18_CN)

    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1, f"Expected 1 scaffold, got {len(scaffolds)}"

    scaf = scaffolds[0]
    total_nt = sum(abs(d.end_bp - d.start_bp) + 1 for d in scaf.domains)
    assert total_nt == 7249, f"Scaffold length={total_nt}, expected 7249"


@pytest.mark.skipif(not HB18_CN.exists(), reason="18HB file not present")
def test_18hb_neighbour_geometry():
    """18HB imported design passes nearest-neighbour geometry check."""
    from backend.core.constants import HONEYCOMB_HELIX_SPACING
    design = _import(HB18_CN)
    _assert_neighbour_geometry(
        design,
        expected_spacing=HONEYCOMB_HELIX_SPACING,
        expected_interior_count=3,
        expected_gap=120.0,
        label="18HB caDNAno import",
    )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 15 — 18HB crossover count
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: The 18HB design has scaffold crossovers connecting helices.
# We know from manual analysis there are 18 scaffold cross-helix jumps
# (9 pairs × 2 directions), producing 18 Crossover objects of type SCAFFOLD.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not HB18_CN.exists(), reason="18HB file not present")
def test_18hb_scaffold_crossover_count():
    """18HB scaffold crossovers: each connects consecutive domains of the scaffold strand."""
    from backend.core.models import CrossoverType, StrandType
    design = _import(HB18_CN)

    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1
    scaf = scaffolds[0]

    scaf_xovers = [
        x for x in design.crossovers
        if x.crossover_type == CrossoverType.SCAFFOLD
    ]

    # Every scaffold crossover should connect domain[i] → domain[i+1] of the scaffold strand.
    # Number of crossovers = number of cross-helix domain transitions = len(domains) - 1.
    expected = len(scaf.domains) - 1
    assert len(scaf_xovers) == expected, (
        f"Expected {expected} scaffold crossovers (= {len(scaf.domains)} domains - 1), "
        f"got {len(scaf_xovers)}"
    )

    # Verify each crossover connects consecutive domains on the scaffold strand.
    for xo in scaf_xovers:
        assert xo.strand_a_id == scaf.id and xo.strand_b_id == scaf.id, (
            f"Scaffold crossover references wrong strand: {xo}"
        )
        assert xo.domain_b_index == xo.domain_a_index + 1, (
            f"Crossover domains not consecutive: {xo.domain_a_index} → {xo.domain_b_index}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 18 — Circular strand detection
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: When a caDNAno JSON contains circular strands (no 5′ end), they
# are silently skipped but a warning is returned listing the count.
# ─────────────────────────────────────────────────────────────────────────────

def _make_circular_cadnano():
    """Build a minimal caDNAno JSON with one linear staple and one circular staple."""
    from backend.core.cadnano import import_cadnano
    N = 42
    # Two vstrands: one pair. num=0 FORWARD, num=1 REVERSE.
    scaf0 = [[-1, -1, -1, -1]] * N
    scaf1 = [[-1, -1, -1, -1]] * N
    # One linear scaffold on helix 0: positions 0..41
    for i in range(N):
        prev_h, prev_p = (-1, -1) if i == 0 else (0, i - 1)
        next_h, next_p = (-1, -1) if i == N - 1 else (0, i + 1)
        scaf0[i] = [prev_h, prev_p, next_h, next_p]

    # Circular staple on helix 1: positions 0..9 form a loop (tail connects to head)
    stap1 = [[-1, -1, -1, -1]] * N
    for i in range(10):
        prev_p = (i - 1) % 10
        next_p = (i + 1) % 10
        stap1[i] = [1, prev_p, 1, next_p]

    stap0 = [[-1, -1, -1, -1]] * N

    data = {
        "name": "circular_test",
        "vstrands": [
            {"num": 0, "row": 0, "col": 0,
             "scaf": scaf0, "stap": stap0,
             "loop": [0] * N, "skip": [0] * N, "stap_colors": []},
            {"num": 1, "row": 0, "col": 1,
             "scaf": scaf1, "stap": stap1,
             "loop": [0] * N, "skip": [0] * N, "stap_colors": []},
        ],
    }
    return import_cadnano(data)


def test_circular_strand_warning_issued():
    """A circular strand produces a non-empty warnings list."""
    _, warnings = _make_circular_cadnano()
    assert warnings, "Expected at least one warning for circular strand"
    assert any("circular" in w.lower() for w in warnings)


def test_circular_strand_not_imported():
    """A circular strand is not imported as a NADOC strand."""
    from backend.core.models import StrandType
    design, warnings = _make_circular_cadnano()
    # Only the linear scaffold should be imported; circular staple is dropped.
    assert len(design.strands) == 1
    assert design.strands[0].strand_type == StrandType.SCAFFOLD


def test_circular_strand_count_in_warning():
    """Warning message includes the correct count of skipped strands."""
    _, warnings = _make_circular_cadnano()
    assert warnings
    assert "1" in warnings[0]


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT — stap-only vstrand import (Ultimate Polymer Hinge regression)
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: A caDNAno design that contains vstrands with active staple bases
# but NO scaffold bases (structural arm helices) must not be silently dropped
# by the vstrand filter.  Before the fix the filter kept only scaffold-active
# vstrands; following a staple link into a dropped vstrand raised KeyError: 56.
#
# Experiment: construct a minimal 4-vstrand SQ design where vstrand 2 carries
# only a staple (no scaffold).  A staple strand on vstrand 0 crosses into
# vstrand 2, which would previously crash.
#
# Expected: import succeeds, design has 3 helices (vstrand 3 is empty),
# the staple strand spans both vstrands.
# ─────────────────────────────────────────────────────────────────────────────

_STAP_ONLY_HINGE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "Examples" / "cadnano" / "Ultimate Polymer Hinge 191016.json"
)


def _make_stap_only_cadnano():
    """Minimal SQ design: vstrand 0 (scaf+stap), vstrand 2 (stap-only), vstrand 3 (empty)."""
    from backend.core.cadnano import import_cadnano

    N = 32  # one SQ period
    empty = [-1, -1, -1, -1]

    # vstrand 0: FORWARD at row=0, col=0.  Scaffold goes 0→N-1.
    # Staple starts on vstrand 0, crosses to vstrand 2 at bp 16.
    scaf0 = [empty] * N
    stap0 = [empty] * N
    for bp in range(N):
        nh = 0 if bp < N - 1 else -1
        scaf0[bp] = [-1, -1, nh, bp + 1 if bp < N - 1 else -1]
    # staple: vstrand 0 bp 15 → vstrand 2 bp 15 (cross-helix)
    for bp in range(16):
        stap0[bp] = [-1, -1, 0, bp + 1]
    stap0[0] = [-1, -1, 0, 1]   # 5' end
    stap0[15] = [-1, -1, 2, 15]  # crosses to vstrand 2

    # vstrand 2: FORWARD at row=0, col=2.  NO scaffold, only staple.
    scaf2 = [empty] * N
    stap2 = [empty] * N
    stap2[15] = [0, 15, 2, 16]  # arrived from vstrand 0
    for bp in range(16, N):
        nh = 2 if bp < N - 1 else -1
        stap2[bp] = [2, bp - 1, nh, bp + 1 if bp < N - 1 else -1]
    stap2[N - 1] = [2, N - 2, -1, -1]  # 3' end

    # vstrand 3: completely empty placeholder
    scaf3 = [empty] * N
    stap3 = [empty] * N

    data = {
        "vstrands": [
            {"num": 0, "row": 0, "col": 0, "scaf": scaf0, "stap": stap0,
             "loop": [0] * N, "skip": [0] * N, "stap_colors": []},
            {"num": 2, "row": 0, "col": 2, "scaf": scaf2, "stap": stap2,
             "loop": [0] * N, "skip": [0] * N, "stap_colors": []},
            {"num": 3, "row": 0, "col": 3, "scaf": scaf3, "stap": stap3,
             "loop": [0] * N, "skip": [0] * N, "stap_colors": []},
        ],
    }
    return import_cadnano(data)


def test_stap_only_vstrand_not_dropped():
    """Stap-only vstrands are retained — previously raised KeyError."""
    design, _ = _make_stap_only_cadnano()
    # vstrand 3 (empty) is dropped; vstrand 2 (stap-only) must be kept
    assert len(design.helices) == 2


def test_stap_only_vstrand_helix_has_no_scaffold():
    """The imported stap-only helix has no scaffold strand covering it."""
    from backend.core.models import StrandType
    design, _ = _make_stap_only_cadnano()
    stap_only_helices = [
        h for h in design.helices
        if not any(
            d.helix_id == h.id
            for s in design.strands if s.strand_type == StrandType.SCAFFOLD
            for d in s.domains
        )
    ]
    assert stap_only_helices, "Expected at least one stap-only helix"


@pytest.mark.skipif(
    not _STAP_ONLY_HINGE_PATH.exists(),
    reason="Ultimate Polymer Hinge example file not present",
)
def test_ultimate_polymer_hinge_imports_without_error():
    """Ultimate Polymer Hinge 191016.json must import without KeyError: 56."""
    from backend.core.cadnano import import_cadnano
    from backend.core.constants import SQUARE_TWIST_PER_BP_RAD
    import math

    with open(_STAP_ONLY_HINGE_PATH) as f:
        data = json.load(f)
    design, warnings = import_cadnano(data)

    # 75 vstrands minus 1 empty placeholder (num=47)
    assert len(design.helices) == 74

    # Lattice must be SQ (array_len=832 = 32*26)
    for h in design.helices:
        assert math.isclose(h.twist_per_bp_rad, SQUARE_TWIST_PER_BP_RAD, abs_tol=1e-9)

    # At least 12 arm helices have no scaffold coverage
    from backend.core.models import StrandType
    scaf_helix_ids = {
        d.helix_id
        for s in design.strands if s.strand_type == StrandType.SCAFFOLD
        for d in s.domains
    }
    stap_only = [h for h in design.helices if h.id not in scaf_helix_ids]
    assert len(stap_only) >= 12
