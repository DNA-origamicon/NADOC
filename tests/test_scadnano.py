"""
Tests for scadnano import — Phase SC.

Methodology
───────────
For each hypothesis we:
  1. State the hypothesis.
  2. Run an experiment (assertion or printed figure).
  3. Record the conclusion.

All fixtures are inline JSON dicts to avoid external file dependencies.
"""

from __future__ import annotations

import pytest

from backend.core.models import Direction, LatticeType, StrandType
from backend.core.scadnano import import_scadnano

# ── Shared fixture builder helpers ────────────────────────────────────────────

def _sq_design(**kwargs) -> dict:
    """Minimal valid 2-helix square-lattice design."""
    base = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [
            {"grid_position": [0, 0], "max_offset": 16},
            {"grid_position": [1, 0], "max_offset": 16},
        ],
        "strands": [
            {
                "is_scaffold": True,
                "domains": [
                    {"helix": 0, "forward": True,  "start": 0, "end": 8},
                    {"helix": 1, "forward": False, "start": 0, "end": 8},
                ],
            },
            {
                "color": "#ff0000",
                "domains": [
                    {"helix": 0, "forward": False, "start": 0, "end": 8},
                    {"helix": 1, "forward": True,  "start": 0, "end": 8},
                ],
            },
        ],
    }
    base.update(kwargs)
    return base


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 1 — Basic square-lattice import
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: A 2-helix square-lattice design imports to exactly 2 helices,
# SQUARE lattice type, 1 scaffold and 1 staple strand with intra-strand
# crossovers connecting their domains.

def test_simple_square():
    design, warns = import_scadnano(_sq_design())
    assert len(design.helices) == 2
    assert design.lattice_type == LatticeType.SQUARE
    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    staples   = [s for s in design.strands if s.strand_type == StrandType.STAPLE]
    assert len(scaffolds) == 1
    assert len(staples)   == 1
    assert not warns


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 2 — Honeycomb lattice detection
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: A design with "grid": "honeycomb" produces LatticeType.HONEYCOMB.

def test_honeycomb_lattice():
    data = {
        "version": "0.19.0",
        "grid": "honeycomb",
        "helices": [
            {"grid_position": [0, 0], "max_offset": 21},
            {"grid_position": [0, 1], "max_offset": 21},
        ],
        "strands": [
            {
                "is_scaffold": True,
                "domains": [
                    {"helix": 0, "forward": True,  "start": 0, "end": 21},
                    {"helix": 1, "forward": False, "start": 0, "end": 21},
                ],
            },
        ],
    }
    design, _ = import_scadnano(data)
    assert design.lattice_type == LatticeType.HONEYCOMB


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 3 — None-grid raises ValueError
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: A "grid": "none" design raises ValueError with an informative message.

def test_none_grid_raises():
    data = {
        "version": "0.19.0",
        "grid": "none",
        "helices": [{"max_offset": 16, "position": {"x": 0, "y": 0, "z": 0}}],
        "strands": [],
    }
    with pytest.raises(ValueError, match="none"):
        import_scadnano(data)


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 4 — Circular strand handling
# ═════════════════════════════════════════════════════════════════════════════
#
# Non-scaffold circular strands are skipped with a warning.
# Circular scaffold strands are imported as linear (nick before first domain).

def test_circular_non_scaffold_skipped():
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 16}],
        "strands": [
            {
                "circular": True,
                "domains": [{"helix": 0, "forward": True, "start": 0, "end": 16}],
            }
        ],
    }
    design, warns = import_scadnano(data)
    assert len(design.strands) == 0
    assert any("circular" in w for w in warns)


def test_circular_scaffold_imported_as_linear():
    """A circular scaffold strand is accepted and imported as a linear strand."""
    from backend.core.models import StrandType
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [
            {"grid_position": [0, 0], "max_offset": 32},
            {"grid_position": [1, 0], "max_offset": 32},
        ],
        "strands": [
            {
                "is_scaffold": True,
                "circular": True,
                "sequence": "A" * 64,
                "domains": [
                    {"helix": 0, "forward": True,  "start": 0, "end": 32},
                    {"helix": 1, "forward": False, "start": 0, "end": 32},
                ],
            }
        ],
    }
    design, warns = import_scadnano(data)
    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1, "Circular scaffold must be imported as one linear strand"
    assert scaffolds[0].sequence is not None
    assert any("circular" in w and "linear" in w for w in warns)


def test_multi_scaffold_import(tmp_path):
    """Design with one linear + one circular scaffold produces two scaffold strands."""
    import json, pathlib
    from backend.core.models import StrandType
    sc_file = pathlib.Path("Examples/cadnano/Voltron_Core_Arm.sc")
    if not sc_file.exists():
        pytest.skip("Voltron_Core_Arm.sc not present")
    data = json.loads(sc_file.read_text())
    design, warns = import_scadnano(data)
    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 2, (
        f"Expected 2 scaffold strands, got {len(scaffolds)}"
    )
    # Both scaffolds must have sequences
    for sc in scaffolds:
        assert sc.sequence is not None, f"Scaffold {sc.id!r} is missing its sequence"


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 7 — Extension at 5′ end
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: A strand whose first subdomain is an extension produces a
# StrandExtension with end="five_prime".

def test_extension_5p():
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 16}],
        "strands": [
            {
                "domains": [
                    {"extension_num_bases": 4},
                    {"helix": 0, "forward": True, "start": 0, "end": 8},
                ],
            }
        ],
    }
    design, warns = import_scadnano(data)
    assert len(design.extensions) == 1
    ext = design.extensions[0]
    assert ext.end == "five_prime"
    assert ext.sequence == "NNNN"
    assert not warns


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 8 — Scaffold strand extension allowed
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: A scaffold strand with a 3′ extension imports without error,
# producing a StrandExtension with strand_id matching the scaffold strand.

def test_scaffold_extension_allowed():
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 16}],
        "strands": [
            {
                "is_scaffold": True,
                "domains": [
                    {"helix": 0, "forward": True, "start": 0, "end": 8},
                    {"extension_num_bases": 2},
                ],
            }
        ],
    }
    design, warns = import_scadnano(data)
    assert len(design.extensions) == 1
    ext = design.extensions[0]
    assert ext.end == "three_prime"
    scaffold_id = next(s.id for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    assert ext.strand_id == scaffold_id
    assert not warns


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 9 — Photoproduct junctions stored on Design
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: photoproduct_junctions in the scadnano JSON are imported as
# PhotoproductJunction objects on the Design.

def test_photoproduct_junctions():
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 16}],
        "strands": [],
        "photoproduct_junctions": [
            {"t1_stable_id": "h0_f_5_t", "t2_stable_id": "h0_f_6_t", "photoproduct_id": "TT-CPD"},
            {"t1_stable_id": "h0_f_7_t", "t2_stable_id": "h0_f_8_t", "photoproduct_id": "TT-CPD"},
        ],
    }
    design, _ = import_scadnano(data)
    assert len(design.photoproduct_junctions) == 2
    assert design.photoproduct_junctions[0].t1_stable_id == "h0_f_5_t"
    assert design.photoproduct_junctions[1].photoproduct_id == "TT-CPD"


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 10 — Domain direction and bp range
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis:
#   forward=True,  start=5, end=10 → start_bp=5, end_bp=9, direction=FORWARD
#   forward=False, start=5, end=10 → start_bp=9, end_bp=5, direction=REVERSE

def test_domain_direction_bp_range():
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 16}],
        "strands": [
            {
                "domains": [{"helix": 0, "forward": True, "start": 5, "end": 10}],
            },
            {
                "domains": [{"helix": 0, "forward": False, "start": 5, "end": 10}],
            },
        ],
    }
    design, _ = import_scadnano(data)
    fwd_strand = design.strands[0]
    rev_strand = design.strands[1]

    d_fwd = fwd_strand.domains[0]
    assert d_fwd.direction == Direction.FORWARD
    assert d_fwd.start_bp  == 5
    assert d_fwd.end_bp    == 9

    d_rev = rev_strand.domains[0]
    assert d_rev.direction == Direction.REVERSE
    assert d_rev.start_bp  == 9
    assert d_rev.end_bp    == 5


# ═════════════════════════════════════════════════════════════════════════════
# EXPERIMENT 11 — length_bp correctness with non-zero min_offset
# ═════════════════════════════════════════════════════════════════════════════
#
# Hypothesis: When a helix has min_offset=10, max_offset=26, the NADOC helix
# must have length_bp=16 (not 26), so that geometry.py's loop over
# range(length_bp) generates exactly the 16 nucleotide positions bp 10–25
# without phantom positions beyond axis_end.

def test_length_bp_with_min_offset():
    data = {
        "version": "0.19.0",
        "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 26, "min_offset": 10}],
        "strands": [
            {
                "domains": [{"helix": 0, "forward": True, "start": 10, "end": 26}],
            }
        ],
    }
    design, _ = import_scadnano(data)
    helix = design.helices[0]
    assert helix.bp_start  == 10
    assert helix.length_bp == 16          # max_offset - min_offset, NOT max_offset
    # axis_start and axis_end must be consistent with bp_start and length_bp
    from backend.core.constants import BDNA_RISE_PER_BP
    assert abs(helix.axis_start.z - 10 * BDNA_RISE_PER_BP) < 1e-9
    assert abs(helix.axis_end.z   - 25 * BDNA_RISE_PER_BP) < 1e-9  # (max_offset-1)*RISE
