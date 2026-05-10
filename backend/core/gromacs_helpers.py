"""Pure-text helpers extracted from gromacs_package.py (Refactor 09-B).

These operate on PDB text strings only — no subprocess, no FF-directory
lookup, no GROMACS install required. Testable in isolation.
"""

from __future__ import annotations


# ── Atom-name maps: PDB name → FF name ────────────────────────────────────────
# NADOC exports CHARMM36 naming: OP1/OP2 for phosphate oxygens, C7 for thymine methyl.
#
# charmm27 uses O1P/O2P (same as AMBER) and C5M for thymine methyl.
# charmm36+ uses OP1/OP2 and C7 — matches NADOC directly.
# AMBER FFs use O1P/O2P and C7 (IUPAC).
#
# residue → { nadoc_atom: ff_atom }
_RENAMES_CHARMM27: dict[str, dict[str, str]] = {
    "DA": {"OP1": "O1P", "OP2": "O2P"},
    "DT": {"OP1": "O1P", "OP2": "O2P", "C7": "C5M"},   # C5M = thymine methyl in CHARMM27
    "DG": {"OP1": "O1P", "OP2": "O2P"},
    "DC": {"OP1": "O1P", "OP2": "O2P"},
}
_RENAMES_AMBER: dict[str, dict[str, str]] = {
    # AMBER FFs use O1P/O2P (vs NADOC/CHARMM36 OP1/OP2); C7 is correct for AMBER
    "DA": {"OP1": "O1P", "OP2": "O2P"},
    "DT": {"OP1": "O1P", "OP2": "O2P"},
    "DG": {"OP1": "O1P", "OP2": "O2P"},
    "DC": {"OP1": "O1P", "OP2": "O2P"},
}


# AMBER DNA 5′-terminus entries (DA5, DT5, DG5, DC5) are defined as 5′-OH
# residues without a phosphate group.  The NADOC PDB includes P/OP1/OP2 on
# every residue (CHARMM convention where even the first residue has a
# phosphate).  Strip those three atoms from the first residue of each chain
# so pdb2gmx can match the 5′-terminus RTP entry.
_5P_ATOMS = {"P", "O1P", "O2P", "OP1", "OP2"}   # pre- and post-rename variants


def _rename_atom_in_line(line: str, old: str, new: str) -> str:
    """Replace atom name (cols 12-15) in a PDB ATOM/HETATM line."""
    atom_field = line[12:16]
    if atom_field.strip() != old:
        return line
    elem = line[76:78].strip() if len(line) > 77 else ""
    if len(elem) == 1 and len(new) <= 3:
        new_field = f" {new:<3s}"
    else:
        new_field = f"{new:<4s}"
    return line[:12] + new_field + line[16:]


def adapt_pdb_for_ff(pdb_text: str, ff: str) -> str:
    """
    Rename atom names in a NADOC PDB to match the chosen GROMACS force field.

    NADOC exports CHARMM36 naming (OP1/OP2 for phosphate oxygens, C7 for
    thymine methyl).

    Adjustments per FF:
    - charmm36+: no rename (NADOC naming matches directly)
    - amber*   : OP1→O1P, OP2→O2P  (amber dna.arn also does this, so this is
                 a pre-pass for safety; C7 stays as-is, which is correct for AMBER)

    Note: charmm27 is no longer in _FF_CANDIDATES because it lacks dna.r2b and
    causes pdb2gmx to apply protein termini to DNA chains.
    """
    # charmm36-feb2026_cgenff-5.0 (from charmm2gmx) uses O1P/O2P and C5M —
    # the old-style naming identical to charmm27, despite being a charmm36 release.
    # Earlier charmm36 variants (jul2022, charmm36m) use OP1/OP2 and C7.
    renames_by_res: dict[str, dict[str, str]] = {}
    if ff == "charmm36-feb2026_cgenff-5.0":
        renames_by_res = _RENAMES_CHARMM27
    elif ff.startswith("charmm36") or ff.startswith("charmm36m"):
        return pdb_text   # OP1/OP2 + C7 matches NADOC directly
    elif ff.startswith("amber"):
        renames_by_res = _RENAMES_AMBER

    if not renames_by_res:
        return pdb_text

    out: list[str] = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            res = line[17:20].strip()
            for old, new in renames_by_res.get(res, {}).items():
                line = _rename_atom_in_line(line, old, new)
        out.append(line)
    return "\n".join(out) + "\n"


def strip_5prime_phosphate(pdb_text: str) -> str:
    """
    Remove P, O1P, O2P (and OP1/OP2 pre-rename variants) from the first
    residue of each contiguous chain block in a PDB file.

    Required for AMBER FF pdb2gmx: the 5′-terminus RTP entries (DA5 etc.)
    model a 5′-OH and do not include the phosphate group.

    NADOC reuses chain letters (A–Z) when a design has more than 26 strands.
    pdb2gmx treats each contiguous run of a chain letter as a separate chain,
    so every block-start residue — not just the first occurrence of a letter —
    needs its 5′-phosphate stripped.  A new block is detected whenever the
    chain letter changes between consecutive ATOM lines.
    """
    lines = pdb_text.splitlines()

    # First pass: collect (chain, resnum) pairs that are the first residue of
    # each contiguous block.  A block boundary is detected when the chain ID
    # differs from the previous ATOM/HETATM line.
    block_starts: set[tuple[str, str]] = set()
    prev_chain: str | None = None
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            chain  = line[21]
            resnum = line[22:26].strip()
            if chain != prev_chain:          # start of a new contiguous block
                block_starts.add((chain, resnum))
                prev_chain = chain

    # Second pass: drop 5′-phosphate atoms from every block-start residue.
    result: list[str] = []
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            chain     = line[21]
            resnum    = line[22:26].strip()
            atom_name = line[12:16].strip()
            if (chain, resnum) in block_starts and atom_name in _5P_ATOMS:
                continue   # drop this phosphate atom from the 5′ end
        result.append(line)
    return "\n".join(result) + "\n"
