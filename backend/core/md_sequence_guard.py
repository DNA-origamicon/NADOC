"""Guard against building or launching an all-atom MD job whose SCAFFOLD sequence is
unassigned.

Why this exists: an unassigned base is silently built as thymine — atomistic.py's
``_BASE_CHAR_TO_RESIDUE.get(base_char, "DT")`` turns the ``"N"`` placeholder into ``DT``
— so an unsequenced scaffold ships as **poly-T**, a physically meaningless reference.
This cost a real RunPod run (the ``6hbx100_90deg`` poly-T incident: 656-nt scaffold =
100% THY because ``scaffold.sequence`` was ``None``).

The pre-existing endpoint guard (``routes_md._sequenced_base_count == 0``) is
insufficient: it blocks only a design with ZERO assigned bases across ALL strands, so a
design with sequenced STAPLES but a ``None`` SCAFFOLD passes it. This module checks the
SCAFFOLD specifically and is wired at the shared build choke point AND at RunPod launch.
"""

from __future__ import annotations

from pathlib import Path

_DNA_SELECT = (
    "resname ADE THY GUA CYT DA DT DG DC DA3 DA5 DT3 DT5 DG3 DG5 DC3 DC5 A T G C"
)
_BASE_OF = {
    "ADE": "A",
    "THY": "T",
    "GUA": "G",
    "CYT": "C",
    "DA": "A",
    "DT": "T",
    "DG": "G",
    "DC": "C",
    "A": "A",
    "T": "T",
    "G": "G",
    "C": "C",
}


def _strand_build_nt_count(design, strand) -> int:
    """Nucleotides the all-atom build actually places for this strand (loop/skip-aware).

    Mirrors ``atomistic._build_sequence_map``'s position enumeration exactly, so the
    coverage comparison against the sequence length is apples-to-apples."""
    from backend.core.atomistic import _atomistic_domain_bp_range  # noqa: PLC0415

    ls_lookup: dict = {}
    for h in design.helices:
        for ls in h.loop_skips:
            ls_lookup[(h.id, ls.bp_index)] = (
                ls_lookup.get((h.id, ls.bp_index), 0) + ls.delta
            )
    n = 0
    for domain in strand.domains:
        for bp in _atomistic_domain_bp_range(domain, strand):
            delta = ls_lookup.get((domain.helix_id, bp), 0)
            if delta <= -1:
                continue  # deletion (skip): no nucleotide built
            n += max(1, delta + 1)  # loop copies add nucleotides
    return n


def scaffold_sequence_problems(design) -> list[str]:
    """Human-readable problems if any scaffold strand lacks a full ACGT sequence.

    Empty list == safe to build/run. Uses ``ACGT`` only (an ``N`` counts as unassigned,
    matching how the endpoint guard treats it) and the loop/skip-aware nt count so it does
    NOT false-positive on skip designs (fewer sequence chars than raw domain span)."""
    from backend.core.models import StrandType  # noqa: PLC0415

    problems: list[str] = []
    scaffs = [
        s
        for s in design.strands
        if s.strand_type == StrandType.SCAFFOLD
        and not getattr(s, "is_reference", False)
    ]
    for s in scaffs:
        acgt = sum(1 for c in (s.sequence or "") if c.upper() in "ACGT")
        expected = _strand_build_nt_count(design, s)
        if expected == 0:
            continue
        if acgt == 0:
            problems.append(
                f"scaffold {s.id!r}: NO sequence assigned "
                f"({expected} nt would build as poly-T)"
            )
        elif acgt < expected:
            problems.append(
                f"scaffold {s.id!r}: under-sequenced "
                f"({acgt}/{expected} nt; the remaining {expected - acgt} build as poly-T)"
            )
    return problems


def all_sequence_problems(design) -> list[str]:
    """Problems for any built DNA strand, including staples and overhang bases.

    NAMD does not know that an ``N`` is a placeholder: the atomistic builder turns it
    into thymine.  The Run boundary therefore requires complete A/C/G/T coverage on
    every non-reference strand, not merely a non-empty scaffold.
    """
    problems: list[str] = []
    for strand in design.strands:
        if getattr(strand, "is_reference", False):
            continue
        expected = _strand_build_nt_count(design, strand)
        if expected == 0:
            continue
        acgt = sum(1 for c in (strand.sequence or "") if c.upper() in "ACGT")
        if acgt >= expected:
            continue
        kind = getattr(getattr(strand, "strand_type", None), "value", None) or "strand"
        if acgt == 0:
            problems.append(
                f"{kind} {strand.id!r}: NO sequence assigned "
                f"({expected} nt would build as poly-T)"
            )
        else:
            problems.append(
                f"{kind} {strand.id!r}: under-sequenced "
                f"({acgt}/{expected} nt; the remaining {expected - acgt} build as poly-T)"
            )
    return problems


def require_sequenced_scaffold(design) -> None:
    """Raise ``ValueError`` if the scaffold isn't fully sequenced. Call before any
    all-atom MD build or run."""
    problems = scaffold_sequence_problems(design)
    if problems:
        raise ValueError(
            "Refusing all-atom MD build/run: unassigned scaffold sequence. Every "
            "unassigned base is silently built as thymine (poly-T), making the topology "
            "physically meaningless. Assign the scaffold sequence first. "
            + "; ".join(problems)
        )


def psf_polyt_problems(psf_path, min_nt: int = 20, frac: float = 0.95) -> list[str]:
    """DNA segments in an ALREADY-BUILT PSF that are ~entirely one base (poly-T/A/G/C) —
    the fingerprint of an unsequenced-scaffold box that already shipped.

    A launch backstop for jobs that seed from a PRE-BUILT box (which the design check
    cannot see — the box may have been built from a stale/unsequenced design)."""
    import MDAnalysis as mda  # noqa: PLC0415
    from collections import Counter  # noqa: PLC0415

    u = mda.Universe(str(Path(psf_path)))
    problems: list[str] = []
    for seg in u.segments:
        bases = [
            _BASE_OF.get(r.resname.strip().upper(), r.resname)
            for r in seg.atoms.select_atoms(_DNA_SELECT).residues
        ]
        if len(bases) < min_nt:
            continue
        top, n = Counter(bases).most_common(1)[0]
        if n / len(bases) >= frac:
            problems.append(
                f"segment {seg.segid}: {len(bases)} nt, {n} are '{top}' "
                f"({100 * n / len(bases):.0f}% poly-{top} — unsequenced placeholder?)"
            )
    return problems
