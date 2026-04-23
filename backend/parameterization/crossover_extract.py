"""
Step 1 — Crossover extraction and variant generation.

Loads a 2-crossover reference design (2hb_xover_val.nadoc), assigns sequences,
and produces atomistic PDB files for each T-count variant.

The 2hb design is the minimal unit that locks a single Holliday junction isoform:
two antiparallel crossovers at bp 13-14 and 34-35, with ~20 bp of duplex between
them (the measurement region) and ~6 bp outer stubs on each end.  A single
crossover (dumbbell) cannot be used because it freely interconverts between
junction isoforms; the paired-crossover geometry is required to pin the isoform.

Outer stub handling
-------------------
The ~6 bp outer stubs are too short to be self-consistent as free ends; they are
restrained in MD to mimic origami embedding (see md_setup.py).  What the correct
restraint model for these stubs should be is an open question — the placeholder is
soft position restraints on terminal P atoms, with a sensitivity sweep.

T-count variants
----------------
extra_bases on each crossover in the design controls the number of extra thymines.
T=0 → extra_bases = None (standard crossover)
T=N → extra_bases = "T" * N on all crossover sites

CPD hook
--------
CrossoverVariant.cpd_pairs is a reserved field for future cyclobutane-pyrimidine
dimer crosslinks between adjacent thymines at the junction.  It is not used yet.
Pass non-empty cpd_pairs to export_pdb via non_std_bonds when CPD support arrives.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from backend.core.models import Design
from backend.core.sequences import (
    assign_custom_scaffold_sequence,
    assign_staple_sequences,
)
from backend.core.pdb_export import export_pdb

logger = logging.getLogger(__name__)

# ── Design path ───────────────────────────────────────────────────────────────

_DEFAULT_DESIGN_PATH = (
    Path(__file__).parent.parent.parent / "Examples" / "2hb_xover_val.nadoc"
)

# ── Reproducible sequence generation ─────────────────────────────────────────

_GC_CONTENT = 0.50   # target GC fraction

def _gc_balanced_sequence(length: int, rng: np.random.Generator) -> str:
    """Generate a GC-balanced random DNA sequence with no runs of >3 identical bases."""
    bases = ["A", "T", "G", "C"]
    target_gc = round(length * _GC_CONTENT)
    target_at = length - target_gc
    pool = (
        ["G"] * (target_gc // 2)
        + ["C"] * (target_gc - target_gc // 2)
        + ["A"] * (target_at // 2)
        + ["T"] * (target_at - target_at // 2)
    )
    # Pad or trim to exactly `length`
    while len(pool) < length:
        pool.append(rng.choice(bases))
    pool = pool[:length]
    rng.shuffle(pool)

    # Break any runs of 4+ identical bases by swapping with a distant position
    for i in range(3, len(pool)):
        if pool[i] == pool[i-1] == pool[i-2] == pool[i-3]:
            for j in range(i + 1, len(pool)):
                if pool[j] != pool[i]:
                    pool[i], pool[j] = pool[j], pool[i]
                    break

    return "".join(pool)


def assign_sequences_to_design(design: Design, seed: int = 42) -> Design:
    """
    Assign GC-balanced random sequences to all scaffold strands, then derive
    complementary staple sequences.

    Uses a fixed seed for reproducibility.  Each scaffold strand gets an
    independent sequence.  Staple sequences are derived automatically from the
    scaffold via Watson-Crick complement.

    Parameters
    ----------
    design : Design
        Input design, typically with sequence=None on all strands.
    seed : int
        RNG seed for reproducible sequence generation (default: 42).

    Returns
    -------
    Updated Design with all strand sequences populated.
    """
    from backend.core.models import StrandType
    rng = np.random.default_rng(seed)

    updated = design
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        # Count nucleotides in this scaffold strand
        n_nt = sum(
            abs(dom.end_bp - dom.start_bp) + 1
            for dom in strand.domains
        )
        seq = _gc_balanced_sequence(n_nt, rng)
        updated, _, _ = assign_custom_scaffold_sequence(
            updated, seq, strand_id=strand.id
        )
        logger.info(
            "Assigned %d-nt sequence to scaffold %s (GC=%.0f%%)",
            n_nt, strand.id, 100 * (seq.count("G") + seq.count("C")) / n_nt,
        )

    updated = assign_staple_sequences(updated)
    return updated


# ── Variant definition ────────────────────────────────────────────────────────

@dataclass
class CrossoverVariant:
    """
    Describes one T-count variant of the 2hb crossover system.

    Attributes
    ----------
    label : str
        Short identifier, e.g. "T0", "T1", "T2".
    n_extra_t : int
        Number of extra thymines inserted at each crossover junction.
    cpd_pairs : list[tuple[int, int]]
        Reserved for future CPD crosslinks.  Leave empty until CPD support
        is added.  When non-empty, these (serial_i, serial_j) pairs are
        passed as non_std_bonds to export_pdb so they appear as LINK records.
    restraint_k_kcal_per_mol_per_A2 : list[float]
        Restraint spring constants to simulate for this variant.
        The first value is the "nominal" run; all values feed the
        restraint-sensitivity sweep in md_setup.
    """
    label: str
    n_extra_t: int
    cpd_pairs: list[tuple[int, int]] = field(default_factory=list)
    restraint_k_kcal_per_mol_per_A2: list[float] = field(
        default_factory=lambda: [0.5, 1.0, 2.0]
    )


# Standard first-batch variants
FIRST_BATCH_VARIANTS: list[CrossoverVariant] = [
    CrossoverVariant(label="T0", n_extra_t=0),
    CrossoverVariant(label="T1", n_extra_t=1),
    CrossoverVariant(label="T2", n_extra_t=2),
]


def _apply_extra_t(design: Design, n_extra_t: int) -> Design:
    """
    Return a copy of *design* with extra_bases = "T" * n_extra_t on every
    crossover.  n_extra_t=0 clears extra_bases (standard crossover).

    Extra thymines are in the STAPLE strand at the junction.  The extra_bases
    field on Crossover is written into the PDB by build_atomistic_model as
    single-stranded ssDNA at the crossover site, which is physically correct.
    """
    extra = "T" * n_extra_t if n_extra_t > 0 else None
    new_crossovers = [xo.model_copy(update={"extra_bases": extra})
                      for xo in design.crossovers]
    return design.model_copy(update={"crossovers": new_crossovers})


# ── Main extraction API ───────────────────────────────────────────────────────

def load_reference_design(design_path: str | Path | None = None) -> Design:
    """
    Load the 2hb reference design.  Defaults to Examples/2hb_xover_val.nadoc.

    The returned design has sequence=None on all strands.  Call
    assign_sequences_to_design() before building atomistic models.
    """
    path = Path(design_path) if design_path else _DEFAULT_DESIGN_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Reference design not found: {path}\n"
            "Expected Examples/2hb_xover_val.nadoc relative to repo root."
        )
    raw = json.loads(path.read_text())
    return Design.model_validate(raw)


def generate_variant_pdb(
    variant: CrossoverVariant,
    output_dir: str | Path,
    design_path: str | Path | None = None,
    sequence_seed: int = 42,
    box_margin_nm: float = 2.0,
) -> Path:
    """
    Build an atomistic PDB for one crossover variant.

    Workflow
    --------
    1. Load reference 2hb design
    2. Assign GC-balanced sequences (seed-reproducible)
    3. Apply extra_bases for requested T-count
    4. Build heavy-atom model and export PDB

    Parameters
    ----------
    variant : CrossoverVariant
        T-count variant to export.
    output_dir : path
        Directory in which to write <variant.label>/structure.pdb.
        Created if absent.
    design_path : optional path
        Override the default 2hb reference design.
    sequence_seed : int
        RNG seed for sequence generation (default: 42).
    box_margin_nm : float
        Padding around bounding box for CRYST1 record (default: 2.0 nm).

    Returns
    -------
    Path to the written PDB file.

    Notes
    -----
    CPD crosslinks (variant.cpd_pairs) are passed as LINK records.  The CPD
    bond parameters are not in CHARMM36 by default — this is a reminder that
    parameterization of the CPD-modified forcefield must precede any CPD MD.
    When cpd_pairs is non-empty, a warning is emitted to that effect.
    """
    if variant.cpd_pairs:
        logger.warning(
            "CPD crosslinks requested for variant %s but CPD force-field "
            "parameters are not yet included in CHARMM36.  The LINK records "
            "will be written, but MD will fail without custom CPD parameters.",
            variant.label,
        )

    design = load_reference_design(design_path)
    design = assign_sequences_to_design(design, seed=sequence_seed)
    design = _apply_extra_t(design, variant.n_extra_t)

    out_dir = Path(output_dir) / variant.label
    out_dir.mkdir(parents=True, exist_ok=True)

    pdb_text = export_pdb(
        design,
        non_std_bonds=variant.cpd_pairs if variant.cpd_pairs else None,
        box_margin_nm=box_margin_nm,
    )
    pdb_path = out_dir / "structure.pdb"
    pdb_path.write_text(pdb_text)
    logger.info("Wrote PDB for variant %s → %s", variant.label, pdb_path)

    # Write a metadata sidecar so downstream steps know what they're working with
    meta = {
        "variant_label": variant.label,
        "n_extra_t": variant.n_extra_t,
        "sequence_seed": sequence_seed,
        "restraint_k_values": variant.restraint_k_kcal_per_mol_per_A2,
        "cpd_pairs": variant.cpd_pairs,
        "design_path": str(Path(design_path) if design_path else _DEFAULT_DESIGN_PATH),
        "notes": {
            "outer_stub_length_bp": 6,
            "inter_crossover_arm_bp": 20,
            "measurement_region": "inter-crossover arm (bp 14-33 on each helix)",
            "restraint_model": "soft_position_restraints_on_terminal_P_atoms",
            "restraint_open_question": (
                "What 'origami-embedding' restraints look like is an open "
                "question — pure position, orientational, or Gaussian-chain "
                "end-to-end force are all candidates.  Current default: soft "
                "position restraints (k sweep: 0.5, 1.0, 2.0 kcal/mol/A^2)."
            ),
        },
    }
    (out_dir / "variant_meta.json").write_text(json.dumps(meta, indent=2))
    return pdb_path


def generate_all_variants(
    output_dir: str | Path,
    variants: list[CrossoverVariant] | None = None,
    design_path: str | Path | None = None,
    sequence_seed: int = 42,
) -> dict[str, Path]:
    """
    Generate PDB files for all variants.

    Returns a dict mapping variant.label → PDB path.
    """
    if variants is None:
        variants = FIRST_BATCH_VARIANTS
    return {
        v.label: generate_variant_pdb(
            v, output_dir, design_path=design_path, sequence_seed=sequence_seed
        )
        for v in variants
    }
