"""
Sequence assignment for scaffold and staple strands.

Supports:
- M13MP18 scaffold assignment (7249 nt, standard caDNAno ordering).
- Complementary staple sequence derivation from scaffold sequence.

Conventions
-----------
- Scaffold sequence is assigned 5′→3′ along the scaffold strand's domain list.
- Each domain contributes bases in its natural traversal order
  (FORWARD: start_bp → end_bp inclusive; REVERSE: start_bp → end_bp inclusive,
  remembering that for REVERSE start_bp > end_bp and traversal is high→low).
- Staple complement is Watson-Crick: A↔T, G↔C, upper-case throughout.
  Positions not covered by the scaffold receive 'N'.
"""

from __future__ import annotations

import pathlib

from backend.core.models import Design, Direction, Strand, StrandType

# ── Load M13MP18 sequence ──────────────────────────────────────────────────────

_SEQ_FILE = pathlib.Path(__file__).parent / "m13mp18.txt"

if _SEQ_FILE.exists():
    M13MP18_SEQUENCE: str = _SEQ_FILE.read_text().strip().upper()
else:
    raise FileNotFoundError(
        f"M13MP18 sequence file not found: {_SEQ_FILE}. "
        "Place the 7249-nt M13MP18 sequence in backend/core/m13mp18.txt."
    )

# Watson-Crick complement map
_COMPLEMENT: dict[str, str] = {"A": "T", "T": "A", "G": "C", "C": "G", "N": "N"}


def complement_base(base: str) -> str:
    """Return the Watson-Crick complement of a single base (uppercase)."""
    return _COMPLEMENT.get(base.upper(), "N")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _strand_total_nt(strand: Strand) -> int:
    """Count total nucleotides in a strand's domains."""
    return sum(abs(d.end_bp - d.start_bp) + 1 for d in strand.domains)


def _domain_bp_range(domain):
    """Yield bp indices in 5′→3′ traversal order for the domain."""
    if domain.direction == Direction.FORWARD:
        yield from range(domain.start_bp, domain.end_bp + 1)
    else:
        yield from range(domain.start_bp, domain.end_bp - 1, -1)


# ── Scaffold sequence assignment ───────────────────────────────────────────────


def assign_scaffold_sequence(design: Design, start_offset: int = 0) -> Design:
    """Assign the M13MP18 sequence to the scaffold strand.

    Bases are assigned consecutively 5′→3′ along the scaffold strand's domain
    list.  The M13MP18 sequence is treated as circular (wraps at 7249 nt).

    Parameters
    ----------
    design:
        Active design with a scaffold strand.
    start_offset:
        0-based index into M13MP18_SEQUENCE where assignment begins (default 0).

    Returns
    -------
    Updated Design with the scaffold strand's ``sequence`` field populated.

    Raises
    ------
    ValueError
        If no scaffold strand is found.
    """
    scaffold = design.scaffold()
    if scaffold is None:
        raise ValueError("No scaffold strand found in the design.")

    seq_len = len(M13MP18_SEQUENCE)
    total_nt = _strand_total_nt(scaffold)
    if total_nt > seq_len:
        raise ValueError(
            f"Scaffold is {total_nt} nt but M13MP18 is only {seq_len} nt. "
            "Use a shorter structure or a different/longer sequence."
        )

    idx = start_offset % seq_len
    bases: list[str] = []
    for _ in range(total_nt):
        bases.append(M13MP18_SEQUENCE[idx])
        idx = (idx + 1) % seq_len

    new_scaffold = scaffold.model_copy(update={"sequence": "".join(bases)})
    new_strands = [new_scaffold if s.id == scaffold.id else s for s in design.strands]
    return design.model_copy(update={"strands": new_strands})


# ── Scaffold position lookup ───────────────────────────────────────────────────


def build_scaffold_base_map(design: Design) -> dict[tuple[str, int, str], str]:
    """Build a mapping from (helix_id, bp_index, direction_value) → base letter.

    Traverses the scaffold strand 5′→3′ and records the base at each position.
    """
    scaffold = design.scaffold()
    if scaffold is None or scaffold.sequence is None:
        return {}

    base_map: dict[tuple[str, int, str], str] = {}
    seq_iter = iter(scaffold.sequence)

    for domain in scaffold.domains:
        h = domain.helix_id
        d_val = domain.direction.value
        for bp in _domain_bp_range(domain):
            base = next(seq_iter, "N")
            base_map[(h, bp, d_val)] = base

    return base_map


# ── Staple sequence assignment ─────────────────────────────────────────────────


def assign_staple_sequences(design: Design) -> Design:
    """Assign complementary sequences to all staple strands.

    Each staple base is the Watson-Crick complement of the scaffold base at
    the antiparallel position on the same helix.  If the staple domain is
    FORWARD at (helix_id, bp), the scaffold must be REVERSE at that (helix_id, bp)
    and vice versa.  Unmatched positions receive 'N'.

    Parameters
    ----------
    design:
        Active design.  Scaffold must have ``sequence`` assigned first via
        :func:`assign_scaffold_sequence`.

    Returns
    -------
    Updated Design with ``sequence`` fields on all non-scaffold strands.

    Raises
    ------
    ValueError
        If no scaffold strand is found or it has no sequence.
    """
    scaffold = design.scaffold()
    if scaffold is None:
        raise ValueError("No scaffold strand found in the design.")
    if scaffold.sequence is None:
        raise ValueError(
            "Scaffold has no sequence. Call assign_scaffold_sequence() first."
        )

    scaf_map = build_scaffold_base_map(design)

    new_strands: list[Strand] = []
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            new_strands.append(strand)
            continue

        bases: list[str] = []
        for domain in strand.domains:
            h = domain.helix_id
            # Antiparallel: staple FORWARD pairs with scaffold REVERSE, and vice versa
            scaf_dir_val = (
                Direction.REVERSE.value
                if domain.direction == Direction.FORWARD
                else Direction.FORWARD.value
            )
            for bp in _domain_bp_range(domain):
                scaf_base = scaf_map.get((h, bp, scaf_dir_val), "N")
                bases.append(complement_base(scaf_base))

        new_strands.append(strand.model_copy(update={"sequence": "".join(bases)}))

    return design.model_copy(update={"strands": new_strands})
