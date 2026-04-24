"""
Base-pair C1'–C1' distance analysis for GROMACS GRO files.

B-DNA reference geometry
------------------------
  C1'–C1' = 10.4 Å  (ideal Watson-Crick pair)
  intact:    < 12 Å  — hydrogen bonding geometry maintained
  strained: 12–15 Å  — stretched, still thermally accessible
  disrupted: > 15 Å  — base pair open

Design notes
------------
GROMACS GRO files have no chain IDs.  Strand boundaries are resolved by
supplying the number of nucleotides per strand from the NADOC Design
(``nucleotides_per_strand``).  pdb2gmx preserves the atom ordering of the
input PDB, so C1' atoms in the GRO appear in the same strand order as in
the NADOC design.

This approach assumes every residue in the strand is a STANDARD DNA
nucleotide with a C1' atom.  It holds for single-domain (no-crossover)
strands.  Multi-domain strands may contain extra-base crossover residues
that lack C1'; those strands should be excluded from the pairing or
analysed with a topology-aware method.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ── B-DNA reference constants ─────────────────────────────────────────────────

BP_C1C1_IDEAL_ANG: float = 10.4    # Å  ideal Watson-Crick C1'–C1'
BP_INTACT_ANG:    float = 12.0    # threshold: intact
BP_STRAINED_ANG:  float = 15.0    # threshold: strained / disrupted


# ══════════════════════════════════════════════════════════════════════════════
# §1  GRO PARSER
# ══════════════════════════════════════════════════════════════════════════════

def read_gro_c1prime(gro_path: Path) -> list[np.ndarray]:
    """
    Return all C1' atom positions from a GRO file, in file order (nm).

    GRO atom order matches the PDB chain order (pdb2gmx preserves input
    ordering).  Hydrogen atoms added by pdb2gmx are interleaved with heavy
    atoms, but C1' is always present exactly once per standard nucleotide,
    so the count and relative ordering are stable.
    """
    positions: list[np.ndarray] = []
    with open(gro_path) as fh:
        fh.readline()                        # title
        n_atoms = int(fh.readline().strip())
        for _ in range(n_atoms):
            line = fh.readline()
            if len(line) < 44:
                continue
            if line[10:15].strip() == "C1'":
                positions.append(np.array([
                    float(line[20:28]),
                    float(line[28:36]),
                    float(line[36:44]),
                ]))
    return positions


def split_c1prime_by_strand(
    all_c1prime: list[np.ndarray],
    strand_lengths: list[int],
) -> list[list[np.ndarray]]:
    """
    Partition a flat list of C1' positions into per-strand sublists.

    Uses NADOC strand lengths (nucleotides per strand) rather than GRO chain
    ID heuristics.  Raises ``ValueError`` if the counts do not match — this
    usually means a strand contains extra-base crossover residues (which
    lack C1') and its length needs to be computed differently.
    """
    total = sum(strand_lengths)
    if len(all_c1prime) != total:
        raise ValueError(
            f"C1' count mismatch: GRO has {len(all_c1prime)}, "
            f"design strand_lengths sum to {total}. "
            f"Strands with multi-domain crossovers may contain extra-base "
            f"residues that lack C1' — exclude those strands or count only "
            f"standard nucleotides."
        )
    strands: list[list[np.ndarray]] = []
    offset = 0
    for n in strand_lengths:
        strands.append(all_c1prime[offset: offset + n])
        offset += n
    return strands


# ══════════════════════════════════════════════════════════════════════════════
# §2  BASE PAIR INDEX MAPPING
# ══════════════════════════════════════════════════════════════════════════════

def antiparallel_duplex_pairs(
    n_bp: int,
    fwd_strand_idx: int = 0,
    rev_strand_idx: int = 1,
) -> list[tuple[int, int, int, int]]:
    """
    Return ``(strand_a, c1p_idx_a, strand_b, c1p_idx_b)`` tuples for a
    simple antiparallel duplex with ``n_bp`` base pairs.

    NADOC convention (confirmed from ``_build_gromacs_input_pdb``):
      FORWARD strand 5'→3':  C1'[k] corresponds to bp k   (k = 0 … n_bp-1)
      REVERSE strand 5'→3':  C1'[k] corresponds to bp (n_bp-1-k)

    Base pair k:  fwd C1'[k]  ↔  rev C1'[n_bp-1-k]
    """
    return [
        (fwd_strand_idx, k, rev_strand_idx, n_bp - 1 - k)
        for k in range(n_bp)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# §3  DISTANCE COMPUTATION AND REPORT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BpDistanceReport:
    """Per-snapshot C1'–C1' distance statistics for a DNA duplex."""

    label: str
    distances_ang: np.ndarray   # per-pair, shape (n_bp,)

    # ── derived statistics ────────────────────────────────────────────────────

    @property
    def n(self) -> int:
        return len(self.distances_ang)

    @property
    def mean(self) -> float:
        return float(np.mean(self.distances_ang))

    @property
    def std(self) -> float:
        return float(np.std(self.distances_ang))

    @property
    def min(self) -> float:
        return float(np.min(self.distances_ang))

    @property
    def max(self) -> float:
        return float(np.max(self.distances_ang))

    @property
    def deviation_from_ideal(self) -> float:
        """Mean absolute deviation from the 10.4 Å ideal."""
        return float(np.mean(np.abs(self.distances_ang - BP_C1C1_IDEAL_ANG)))

    @property
    def intact_pct(self) -> float:
        return 100.0 * float(np.sum(self.distances_ang < BP_INTACT_ANG)) / self.n

    @property
    def strained_pct(self) -> float:
        mask = (self.distances_ang >= BP_INTACT_ANG) & (self.distances_ang < BP_STRAINED_ANG)
        return 100.0 * float(np.sum(mask)) / self.n

    @property
    def disrupted_pct(self) -> float:
        return 100.0 * float(np.sum(self.distances_ang >= BP_STRAINED_ANG)) / self.n

    @property
    def verdict(self) -> str:
        if self.disrupted_pct > 0:
            return "FAIL"
        if self.strained_pct > 10.0:
            return "WARN"
        return "PASS"

    # ── formatting ────────────────────────────────────────────────────────────

    def summary_line(self) -> str:
        return (
            f"[{self.label}] "
            f"mean={self.mean:.2f} std={self.std:.2f} "
            f"min={self.min:.2f} max={self.max:.2f} Å  "
            f"Δideal={self.deviation_from_ideal:.2f}  "
            f"intact={self.intact_pct:.0f}% strained={self.strained_pct:.0f}% "
            f"disrupted={self.disrupted_pct:.0f}%  [{self.verdict}]"
        )

    def per_pair_table(self) -> str:
        header = f"  {'bp':>4}  {'C1′–C1′ (Å)':>12}  status"
        sep    = "  " + "─" * 30
        rows = [header, sep]
        for i, d in enumerate(self.distances_ang):
            if d < BP_INTACT_ANG:
                status = "intact"
            elif d < BP_STRAINED_ANG:
                status = "STRAINED"
            else:
                status = "DISRUPTED ◄"
            rows.append(f"  {i:>4}  {d:>12.3f}  {status}")
        rows.append(sep)
        rows.append(
            f"  {'mean':>4}  {self.mean:>12.3f}  "
            f"std={self.std:.3f}  Δideal={self.deviation_from_ideal:.3f}"
        )
        return "\n".join(rows)


def compute_bp_distances(
    c1prime_strands: list[list[np.ndarray]],
    bp_pairs: list[tuple[int, int, int, int]],
    label: str = "",
) -> BpDistanceReport:
    """
    Compute C1'–C1' distance (Å) for each base pair.

    Parameters
    ----------
    c1prime_strands : per-strand lists of C1' positions (nm)
    bp_pairs        : list of (strand_a, idx_a, strand_b, idx_b)
    label           : descriptive name for the snapshot
    """
    dists = np.array([
        np.linalg.norm(
            c1prime_strands[sa][ia] - c1prime_strands[sb][ib]
        ) * 10.0          # nm → Å
        for sa, ia, sb, ib in bp_pairs
    ])
    return BpDistanceReport(label=label, distances_ang=dists)


# ══════════════════════════════════════════════════════════════════════════════
# §4  CONVENIENCE: analyse a GRO snapshot directly
# ══════════════════════════════════════════════════════════════════════════════

def analyse_duplex_gro(
    gro_path: Path,
    n_bp: int,
    strand_lengths: list[int] | None = None,
    label: str = "",
) -> BpDistanceReport:
    """
    One-call helper: read GRO, split by strand, compute C1'–C1' for an
    antiparallel duplex.

    Parameters
    ----------
    gro_path       : path to the GRO file
    n_bp           : number of base pairs
    strand_lengths : nucleotide count per strand (default: [n_bp, n_bp])
    label          : snapshot description for the report
    """
    if strand_lengths is None:
        strand_lengths = [n_bp, n_bp]
    all_c1p = read_gro_c1prime(gro_path)
    strands = split_c1prime_by_strand(all_c1p, strand_lengths)
    pairs   = antiparallel_duplex_pairs(n_bp)
    return compute_bp_distances(strands, pairs, label=label)
