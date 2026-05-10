"""
Sequence assignment for scaffold and staple strands.

Supports:
- M13mp18 scaffold assignment (7249 nt, standard caDNAno ordering).
- p7560 scaffold assignment (7560 nt, M13-derived, caDNAno ordering).
- p8064 scaffold assignment (8064 nt, M13-derived, caDNAno ordering).
- Custom sequence assignment (arbitrary ATGCN string).
- Complementary staple sequence derivation from scaffold sequence.

Conventions
-----------
- Scaffold sequence is assigned 5' to 3' along the scaffold strand's domain list.
- Each domain contributes bases in its natural traversal order
  (FORWARD: start_bp to end_bp inclusive; REVERSE: start_bp to end_bp inclusive,
  remembering that for REVERSE start_bp > end_bp and traversal is high to low).
- Staple complement is Watson-Crick: A<->T, G<->C, upper-case throughout.
  Positions not covered by the scaffold receive 'N'.
- When a scaffold is longer than the chosen sequence, remaining positions are
  filled with 'N' rather than raising an error.
"""

from __future__ import annotations

import pathlib
from collections import Counter, defaultdict

from backend.core.models import Design, Direction, Strand, StrandType

_CORE = pathlib.Path(__file__).parent


def _load_seq(filename: str) -> str:
    path = _CORE / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Scaffold sequence file not found: {path}."
        )
    return path.read_text().strip().upper()


# ── Available scaffold sequences ──────────────────────────────────────────────

M13MP18_SEQUENCE: str = _load_seq("m13mp18.txt")   # 7249 nt
P7560_SEQUENCE:   str = _load_seq("p7560.txt")      # 7560 nt
P8064_SEQUENCE:   str = _load_seq("p8064.txt")      # 8064 nt

# Ordered list of (display_name, length, sequence) for the UI
SCAFFOLD_LIBRARY: list[tuple[str, int, str]] = [
    ("M13mp18", len(M13MP18_SEQUENCE), M13MP18_SEQUENCE),
    ("p7560",   len(P7560_SEQUENCE),   P7560_SEQUENCE),
    ("p8064",   len(P8064_SEQUENCE),   P8064_SEQUENCE),
]

_SCAFFOLD_BY_NAME: dict[str, str] = {
    "M13mp18": M13MP18_SEQUENCE,
    "p7560":   P7560_SEQUENCE,
    "p8064":   P8064_SEQUENCE,
}

# Watson-Crick complement map
_COMPLEMENT: dict[str, str] = {"A": "T", "T": "A", "G": "C", "C": "G", "N": "N"}

# Valid bases for custom sequence input
_VALID_BASES: frozenset[str] = frozenset("ATGCN")


def complement_base(base: str) -> str:
    """Return the Watson-Crick complement of a single base (uppercase)."""
    return _COMPLEMENT.get(base.upper(), "N")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_loop_skip_map(design: Design) -> dict[tuple[str, int], int]:
    """Return {(helix_id, global_bp_index): delta} for every loop/skip in design."""
    ls_map: dict[tuple[str, int], int] = {}
    for helix in design.helices:
        for ls in helix.loop_skips:
            ls_map[(helix.id, ls.bp_index)] = ls.delta
    return ls_map


def domain_bp_range(domain):
    """Yield bp indices in 5' to 3' traversal order for the domain."""
    if domain.direction == Direction.FORWARD:
        yield from range(domain.start_bp, domain.end_bp + 1)
    else:
        yield from range(domain.start_bp, domain.end_bp - 1, -1)


def _strand_nt_with_skips(strand: Strand, ls_map: dict[tuple[str, int], int]) -> int:
    """Count nucleotides for a strand, accounting for loop/skip modifications.

    Skips (delta=-1) contribute 0 nt; loops (delta=+1) contribute 2 nt.
    """
    total = 0
    for domain in strand.domains:
        for bp in domain_bp_range(domain):
            delta = ls_map.get((domain.helix_id, bp), 0)
            if delta <= -1:
                continue       # skip -- no nucleotide at this position
            total += delta + 1  # 1 for normal bp, 2 for a loop (+1), etc.
    return total


# ── Scaffold sequence assignment ───────────────────────────────────────────────


def _resolve_scaffold_strand(design: Design, strand_id: str | None) -> Strand:
    """Return the scaffold strand to assign a sequence to.

    If *strand_id* is given, find that strand and verify it is a scaffold.
    Otherwise fall back to the first scaffold strand in the design.
    """
    if strand_id is not None:
        strand = next((s for s in design.strands if s.id == strand_id), None)
        if strand is None:
            raise ValueError(f"Strand {strand_id!r} not found in the design.")
        if strand.strand_type != StrandType.SCAFFOLD:
            raise ValueError(
                f"Strand {strand_id!r} is not a scaffold strand "
                f"(strand_type={strand.strand_type!r})."
            )
        return strand
    scaffold = design.scaffold()
    if scaffold is None:
        raise ValueError("No scaffold strand found in the design.")
    return scaffold


def _do_assign_sequence(
    design: Design,
    scaffold_strand: Strand,
    chosen_seq: str,
) -> tuple[Design, int, int]:
    """Walk *scaffold_strand*'s domains 5' to 3' and assign bases from *chosen_seq*.

    Excess positions (scaffold longer than sequence) are filled with 'N'.

    Returns
    -------
    (updated_design, total_nt, padded_nt)
    """
    ls_map    = _build_loop_skip_map(design)
    seq_len   = len(chosen_seq)
    total_nt  = _strand_nt_with_skips(scaffold_strand, ls_map)
    padded_nt = max(0, total_nt - seq_len)

    bases: list[str] = []
    seq_idx = 0
    for domain in scaffold_strand.domains:
        for bp in domain_bp_range(domain):
            delta = ls_map.get((domain.helix_id, bp), 0)
            if delta <= -1:
                continue  # skip -- no nucleotide emitted
            n_copies = delta + 1  # 1 for normal, 2 for a loop (+1), etc.
            for _ in range(n_copies):
                bases.append(chosen_seq[seq_idx] if seq_idx < seq_len else "N")
                seq_idx += 1

    new_scaffold = scaffold_strand.model_copy(update={"sequence": "".join(bases)})
    new_strands  = [
        new_scaffold if s.id == scaffold_strand.id else s
        for s in design.strands
    ]
    return design.model_copy(update={"strands": new_strands}), total_nt, padded_nt


def assign_scaffold_sequence(
    design: Design,
    scaffold_name: str = "M13mp18",
    strand_id: str | None = None,
) -> tuple[Design, int, int]:
    """Assign a preset scaffold sequence to a scaffold strand.

    Bases are assigned consecutively 5' to 3' starting from the scaffold's
    5' terminus (sequence[0] maps to the first base of the scaffold strand).

    If the scaffold strand is longer than the chosen sequence, the excess
    positions are filled with 'N' rather than raising an error.

    Parameters
    ----------
    design:
        Active design with a scaffold strand.
    scaffold_name:
        One of "M13mp18", "p7560", "p8064".
    strand_id:
        If given, target this specific scaffold strand instead of the first one.

    Returns
    -------
    (updated_design, total_nt, padded_nt)
        updated_design -- new Design with scaffold sequence applied.
        total_nt       -- number of scaffold nucleotides in the design.
        padded_nt      -- number of positions filled with 'N' (0 if scaffold fits).

    Raises
    ------
    ValueError
        If no scaffold strand is found or scaffold_name is unrecognised.
    """
    if scaffold_name not in _SCAFFOLD_BY_NAME:
        known = ", ".join(_SCAFFOLD_BY_NAME)
        raise ValueError(
            f"Unknown scaffold '{scaffold_name}'. Choose one of: {known}."
        )
    scaffold   = _resolve_scaffold_strand(design, strand_id)
    chosen_seq = _SCAFFOLD_BY_NAME[scaffold_name]
    return _do_assign_sequence(design, scaffold, chosen_seq)


def assign_custom_scaffold_sequence(
    design: Design,
    raw_sequence: str,
    strand_id: str | None = None,
) -> tuple[Design, int, int]:
    """Assign a user-supplied raw DNA sequence to a scaffold strand.

    Parameters
    ----------
    design:
        Active design with a scaffold strand.
    raw_sequence:
        Arbitrary DNA string.  Only A, T, G, C, N characters are accepted
        (case-insensitive).  Whitespace is stripped.
    strand_id:
        If given, target this specific scaffold strand instead of the first one.

    Returns
    -------
    (updated_design, total_nt, padded_nt)

    Raises
    ------
    ValueError
        On invalid characters, empty sequence, or missing scaffold strand.
    """
    cleaned = raw_sequence.strip().upper().replace(" ", "").replace("\n", "").replace("\r", "")
    if not cleaned:
        raise ValueError("Custom sequence is empty after stripping whitespace.")
    bad = sorted({c for c in cleaned if c not in _VALID_BASES})
    if bad:
        raise ValueError(
            f"Invalid characters in custom sequence: {bad!r}. "
            "Only A, T, G, C, N are allowed."
        )
    scaffold = _resolve_scaffold_strand(design, strand_id)
    return _do_assign_sequence(design, scaffold, cleaned)


# ── Scaffold position lookup ───────────────────────────────────────────────────


def build_scaffold_base_map(design: Design) -> dict[tuple[str, int, str], list[str]]:
    """Build a mapping from (helix_id, bp_index, direction_value) to list of base letters.

    Traverses the scaffold strand 5' to 3' and records the base(s) at each position,
    honouring loop/skip modifications:
      - Skip (delta<=-1): position omitted from the map (0 nt).
      - Normal (delta=0): one-element list.
      - Loop (delta=+1): two-element list.
    """
    scaffold = design.scaffold()
    if scaffold is None or scaffold.sequence is None:
        return {}

    ls_map   = _build_loop_skip_map(design)
    base_map: dict[tuple[str, int, str], list[str]] = {}
    seq_iter = iter(scaffold.sequence)

    for domain in scaffold.domains:
        h     = domain.helix_id
        d_val = domain.direction.value
        for bp in domain_bp_range(domain):
            delta = ls_map.get((h, bp), 0)
            if delta <= -1:
                continue  # skip -- no nucleotide
            n_copies = delta + 1
            bases_at_bp = [next(seq_iter, "N") for _ in range(n_copies)]
            base_map[(h, bp, d_val)] = bases_at_bp

    return base_map


def build_scaffold_index_map(design: Design) -> list[tuple[str, int, str]]:
    """Return a list mapping scaffold sequence index -> (helix_id, bp_index, direction_value).

    The returned list has length equal to the number of scaffold nucleotides
    (accounting for loop copies) and is ordered 0..N-1 matching the scaffold
    strand.sequence indexing used elsewhere.
    """
    scaffold = design.scaffold()
    if scaffold is None or scaffold.sequence is None:
        return []

    ls_map = _build_loop_skip_map(design)
    index_map: list[tuple[str, int, str]] = []
    for domain in scaffold.domains:
        h = domain.helix_id
        d_val = domain.direction.value
        for bp in domain_bp_range(domain):
            delta = ls_map.get((h, bp), 0)
            if delta <= -1:
                continue
            n_copies = delta + 1
            for _ in range(n_copies):
                index_map.append((h, bp, d_val))
    return index_map


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
        :func:`assign_scaffold_sequence` or :func:`assign_custom_scaffold_sequence`.

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
    ls_map   = _build_loop_skip_map(design)

    # Build lookup: overhang_id -> OverhangSpec (for user-specified sequences)
    overhang_map: dict[str, object] = {o.id: o for o in design.overhangs}

    new_strands: list[Strand] = []
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            new_strands.append(strand)
            continue

        bases: list[str] = []
        for domain in strand.domains:
            domain_len = abs(domain.end_bp - domain.start_bp) + 1

            # Overhang domains are single-stranded -- use user-specified sequence
            # if provided, otherwise fill with 'N' (no scaffold complement).
            if domain.overhang_id is not None:
                spec = overhang_map.get(domain.overhang_id)
                if spec is not None and spec.sequence is not None:
                    # Pad/trim to match domain length
                    seq = spec.sequence.upper()
                    if len(seq) >= domain_len:
                        bases.extend(seq[:domain_len])
                    else:
                        bases.extend(seq + "N" * (domain_len - len(seq)))
                else:
                    bases.extend(["N"] * domain_len)
                continue

            h = domain.helix_id
            # Antiparallel: staple FORWARD pairs with scaffold REVERSE, and vice versa
            scaf_dir_val = (
                Direction.REVERSE.value
                if domain.direction == Direction.FORWARD
                else Direction.FORWARD.value
            )
            for bp in domain_bp_range(domain):
                delta = ls_map.get((h, bp), 0)
                if delta <= -1:
                    continue  # skip -- no nucleotide in staple at this position
                scaf_bases = scaf_map.get((h, bp, scaf_dir_val))
                n_copies   = delta + 1  # 1 for normal, 2 for loop
                if scaf_bases is not None:
                    for scaf_base in scaf_bases:
                        bases.append(complement_base(scaf_base))
                else:
                    bases.extend(["N"] * n_copies)

        new_strands.append(strand.model_copy(update={"sequence": "".join(bases)}))

    return design.model_copy(update={"strands": new_strands})


# ── Periodic-cell consensus sequence assignment ────────────────────────────────


def assign_consensus_sequence(
    full_design: Design,
    sliced_design: Design,
    bp_start: int,
    period: int,
) -> tuple[Design, dict[tuple[str, int, str], str]]:
    """Assign sequences to a period-sliced design from the full design's sequences.

    For each (helix_id, bp_offset, direction) in the sliced window, the base
    is chosen by majority vote across all periods in the full design:

        bp_offset = (bp_index - bp_start) % period

    Because every two complementary strands at a base-pair position must be
    Watson-Crick partners, the FORWARD base is chosen by majority vote and the
    REVERSE base is always its complement.  This guarantees stable A:T and G:C
    pairs regardless of what the independent REVERSE vote would have returned.

    Positions covered by zero sequenced nucleotides in the full design fall back
    to 'A' (FORWARD) / 'T' (REVERSE).

    Parameters
    ----------
    full_design:
        Complete design with sequence fields assigned on all strands.
    sliced_design:
        Period-sliced design (sequence=None on all strands, as produced by
        _slice_to_bp_range).
    bp_start:
        Global bp index of the start of the sliced window (must satisfy
        bp_start % period == 0 for the offset arithmetic to work).
    period:
        Crossover-repeat period in bp (typically 21 for honeycomb lattice).

    Returns
    -------
    (updated_sliced_design, consensus_map)
        updated_sliced_design — sliced_design with sequence fields assigned.
        consensus_map         — {(helix_id, bp_offset, dir_val): base} for inspection.
    """
    ls_map = _build_loop_skip_map(full_design)
    fwd_val = Direction.FORWARD.value
    rev_val = Direction.REVERSE.value

    # Step 1: tally votes from all sequenced strands in the full design.
    # Key: (helix_id, bp_offset, dir_val)  where bp_offset = bp % period.
    votes: dict[tuple[str, int, str], Counter] = defaultdict(Counter)

    for strand in full_design.strands:
        if not strand.sequence:
            continue
        seq_iter = iter(strand.sequence)
        for domain in strand.domains:
            h     = domain.helix_id
            d_val = domain.direction.value
            for bp in domain_bp_range(domain):
                delta = ls_map.get((h, bp), 0)
                if delta <= -1:
                    continue
                n_copies = delta + 1
                for _ in range(n_copies):
                    base = next(seq_iter, "N")
                    if base not in ("N", "n"):
                        offset = bp % period
                        votes[(h, offset, d_val)][base.upper()] += 1

    # Step 2: build consensus.
    # FORWARD base: majority vote; REVERSE base: Watson-Crick complement.
    consensus: dict[tuple[str, int, str], str] = {}
    covered_positions = {(h, off) for h, off, _ in votes}
    for h, offset in covered_positions:
        fwd_counter = votes.get((h, offset, fwd_val), Counter())
        fwd_base    = fwd_counter.most_common(1)[0][0] if fwd_counter else "A"
        rev_base    = _COMPLEMENT.get(fwd_base, "T")
        consensus[(h, offset, fwd_val)] = fwd_base
        consensus[(h, offset, rev_val)] = rev_base

    # Step 3: assign bases to each strand in the sliced design.
    ls_map_sliced = _build_loop_skip_map(sliced_design)
    new_strands: list[Strand] = []

    for strand in sliced_design.strands:
        bases: list[str] = []
        for domain in strand.domains:
            h     = domain.helix_id
            d_val = domain.direction.value
            for bp in domain_bp_range(domain):
                delta = ls_map_sliced.get((h, bp), 0)
                if delta <= -1:
                    continue
                n_copies = delta + 1
                offset   = (bp - bp_start) % period
                base     = consensus.get(
                    (h, offset, d_val),
                    "A" if d_val == fwd_val else "T",
                )
                bases.extend([base] * n_copies)
        new_strands.append(strand.model_copy(update={"sequence": "".join(bases)}))

    updated = sliced_design.model_copy(update={"strands": new_strands})
    return updated, consensus
