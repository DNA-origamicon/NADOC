"""Tests for backend/core/gromacs_helpers.py (Refactor 09-B).

The 3 pure-text helpers extracted from gromacs_package.py operate on PDB
text strings only — no subprocess, no FF-directory lookup, no GROMACS
install required.

Fixture strategy
----------------
All inputs are synthetic PDB ATOM-record strings built inline, mirroring
the inline-writer pattern from tests/test_pdb_import_geometry.py.
The PDB ATOM record column layout (1-indexed):

    cols  1- 6 : record name ("ATOM  " or "HETATM")
    cols  7-11 : atom serial number
    cols 13-16 : atom name (Python slice [12:16])
    col  17    : altLoc
    cols 18-20 : residue name (Python slice [17:20])
    col  22    : chain ID (Python slice [21])
    cols 23-26 : residue sequence number (Python slice [22:26])
    cols 31-54 : x, y, z coordinates (3 × 8 cols)
    cols 77-78 : element symbol (Python slice [76:78])
"""

from __future__ import annotations

import pytest

from backend.core.gromacs_helpers import (
    _rename_atom_in_line,
    adapt_pdb_for_ff,
    strip_5prime_phosphate,
)


# ── PDB-line builder ─────────────────────────────────────────────────────────


def _atom_line(
    *,
    serial: int = 1,
    name: str = " P  ",
    res: str = "DA",
    chain: str = "A",
    resnum: int = 1,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    element: str = " P",
) -> str:
    """Build a single 80-column PDB ATOM record.

    `name` is the raw 4-char atom-name field (as it appears at cols 13-16).
    For 1-letter elements the convention is " X  " or " XX " (leading space).
    """
    assert len(name) == 4, f"atom name field must be 4 chars, got {name!r}"
    assert len(element) == 2, f"element must be 2 chars, got {element!r}"
    return (
        f"ATOM  "                     # 1-6
        f"{serial:5d} "                # 7-11 + col 12 blank
        f"{name}"                      # 13-16
        f" "                           # 17 altLoc
        f"{res:<3s}"                   # 18-20
        f" "                           # 21 blank
        f"{chain}"                     # 22
        f"{resnum:4d}"                 # 23-26
        f"    "                        # 27-30 (insertion + 3 blanks)
        f"{x:8.3f}{y:8.3f}{z:8.3f}"    # 31-54
        f"  1.00  0.00"                # 55-66 occ + B
        f"          "                  # 67-76 blanks
        f"{element}"                   # 77-78
    )


# ── TestRenameAtomInLine ─────────────────────────────────────────────────────


class TestRenameAtomInLine:
    def test_rename_op1_to_o1p(self) -> None:
        """Happy path: rename OP1→O1P; new name appears in cols 13-16."""
        line = _atom_line(name=" OP1", res="DA", element=" O")
        out = _rename_atom_in_line(line, "OP1", "O1P")
        assert out[12:16] == " O1P"
        # Surrounding fields untouched.
        assert out[17:20] == "DA "
        assert out[6:11].strip() == "1"

    def test_no_match_returns_unchanged(self) -> None:
        """Atom name doesn't match → line returned verbatim."""
        line = _atom_line(name=" C7 ", res="DT", element=" C")
        out = _rename_atom_in_line(line, "OP1", "O1P")
        assert out == line

    def test_substring_outside_atom_field_not_replaced(self) -> None:
        """Match is column-anchored: substring in residue/chain field is NOT
        treated as a hit."""
        # Place "OP1" inside the residue-name slot (won't happen in real PDBs
        # but proves we anchor on cols 13-16, not free substring replace).
        line = _atom_line(name=" C5'", res="DA", element=" C")
        # Manually inject "OP1" outside the atom-name field, then verify the
        # function still returns the line unchanged because cols 13-16 are " C5'".
        injected = line[:50] + "OP1" + line[53:]
        out = _rename_atom_in_line(injected, "OP1", "O1P")
        assert out == injected
        # And the atom-name field stayed " C5'".
        assert out[12:16] == " C5'"

    def test_two_letter_new_name_one_letter_element(self) -> None:
        """1-letter element + new ≤3 chars → format as ' XXX' with leading space."""
        line = _atom_line(name=" OP2", res="DA", element=" O")
        out = _rename_atom_in_line(line, "OP2", "O2P")
        assert out[12:16] == " O2P"

    def test_short_line_without_element_field(self) -> None:
        """Lines truncated before col 78 fall through the `len(line) > 77`
        check; element treated as empty, formatter uses the 4-wide branch."""
        # Build a line and truncate it to 60 chars (no element column).
        line = _atom_line(name=" OP1", res="DA", element=" O")[:60]
        out = _rename_atom_in_line(line, "OP1", "O1P")
        # 4-wide format with empty element → "O1P " (no leading space).
        assert out[12:16] == "O1P "


# ── TestAdaptPdbForFf ────────────────────────────────────────────────────────


class TestAdaptPdbForFf:
    def _four_residue_pdb(self) -> str:
        """Synthetic 4-residue PDB: DA/DT/DG/DC each with OP1 + OP2 + (DT) C7."""
        lines = [
            _atom_line(serial=1, name=" OP1", res="DA", chain="A", resnum=1, element=" O"),
            _atom_line(serial=2, name=" OP2", res="DA", chain="A", resnum=1, element=" O"),
            _atom_line(serial=3, name=" OP1", res="DT", chain="A", resnum=2, element=" O"),
            _atom_line(serial=4, name=" OP2", res="DT", chain="A", resnum=2, element=" O"),
            _atom_line(serial=5, name=" C7 ", res="DT", chain="A", resnum=2, element=" C"),
            _atom_line(serial=6, name=" OP1", res="DG", chain="A", resnum=3, element=" O"),
            _atom_line(serial=7, name=" OP2", res="DG", chain="A", resnum=3, element=" O"),
            _atom_line(serial=8, name=" OP1", res="DC", chain="A", resnum=4, element=" O"),
            _atom_line(serial=9, name=" OP2", res="DC", chain="A", resnum=4, element=" O"),
        ]
        return "\n".join(lines) + "\n"

    def test_amber_renames_op_to_op(self) -> None:
        """amber* FF: OP1→O1P, OP2→O2P across all DNA residues; C7 stays."""
        out = adapt_pdb_for_ff(self._four_residue_pdb(), "amber99sb-ildn")
        out_lines = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
        assert len(out_lines) == 9
        # All OP1 should now be O1P.
        op1_count = sum(1 for ln in out_lines if ln[12:16].strip() == "OP1")
        assert op1_count == 0
        o1p_count = sum(1 for ln in out_lines if ln[12:16].strip() == "O1P")
        assert o1p_count == 4   # one per residue
        # All OP2 should now be O2P.
        op2_count = sum(1 for ln in out_lines if ln[12:16].strip() == "OP2")
        assert op2_count == 0
        o2p_count = sum(1 for ln in out_lines if ln[12:16].strip() == "O2P")
        assert o2p_count == 4
        # DT.C7 is preserved (AMBER uses C7).
        c7_count = sum(1 for ln in out_lines if ln[12:16].strip() == "C7")
        assert c7_count == 1

    def test_charmm36_passes_through_unchanged(self) -> None:
        """charmm36+ matches NADOC naming directly → identical output."""
        pdb = self._four_residue_pdb()
        out = adapt_pdb_for_ff(pdb, "charmm36-jul2022")
        assert out == pdb

    def test_charmm36_feb2026_renames_to_charmm27_naming(self) -> None:
        """charmm36-feb2026_cgenff-5.0 (despite charmm36 name) uses CHARMM27
        naming: OP1/OP2 → O1P/O2P AND DT.C7 → DT.C5M."""
        out = adapt_pdb_for_ff(self._four_residue_pdb(), "charmm36-feb2026_cgenff-5.0")
        out_lines = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
        # OP1/OP2 renamed.
        assert sum(1 for ln in out_lines if ln[12:16].strip() == "OP1") == 0
        assert sum(1 for ln in out_lines if ln[12:16].strip() == "O1P") == 4
        # DT.C7 → C5M (only DT residue gets this rename).
        assert sum(1 for ln in out_lines if ln[12:16].strip() == "C7") == 0
        assert sum(1 for ln in out_lines if ln[12:16].strip() == "C5M") == 1

    def test_unknown_ff_passes_through(self) -> None:
        """Unknown FF name (no charmm/amber prefix match) → returns input
        unchanged (the function uses .startswith() and falls through silently)."""
        pdb = self._four_residue_pdb()
        out = adapt_pdb_for_ff(pdb, "gromos96")
        assert out == pdb

    def test_non_atom_lines_preserved(self) -> None:
        """REMARK / CRYST1 / TER / END lines pass through verbatim."""
        pdb = (
            "REMARK   1 NADOC test\n"
            "CRYST1  100.000  100.000  100.000  90.00  90.00  90.00 P 1           1\n"
            + _atom_line(name=" OP1", res="DA", element=" O") + "\n"
            "TER\nEND\n"
        )
        out = adapt_pdb_for_ff(pdb, "amber99sb-ildn")
        assert "REMARK   1 NADOC test" in out
        assert "CRYST1  100.000" in out
        assert "TER" in out
        assert "END" in out


# ── TestStrip5primePhosphate ─────────────────────────────────────────────────


class TestStrip5primePhosphate:
    def _two_residue_chain(self, chain: str = "A") -> list[str]:
        """First residue (resnum 1) has full P/OP1/OP2/O5'/C5' set.
        Second residue (resnum 2) has the same — only residue 1 should be
        stripped of phosphate atoms."""
        return [
            _atom_line(serial=1, name=" P  ", res="DA", chain=chain, resnum=1, element=" P"),
            _atom_line(serial=2, name=" OP1", res="DA", chain=chain, resnum=1, element=" O"),
            _atom_line(serial=3, name=" OP2", res="DA", chain=chain, resnum=1, element=" O"),
            _atom_line(serial=4, name=" O5'", res="DA", chain=chain, resnum=1, element=" O"),
            _atom_line(serial=5, name=" C5'", res="DA", chain=chain, resnum=1, element=" C"),
            _atom_line(serial=6, name=" P  ", res="DT", chain=chain, resnum=2, element=" P"),
            _atom_line(serial=7, name=" OP1", res="DT", chain=chain, resnum=2, element=" O"),
            _atom_line(serial=8, name=" OP2", res="DT", chain=chain, resnum=2, element=" O"),
            _atom_line(serial=9, name=" O5'", res="DT", chain=chain, resnum=2, element=" O"),
            _atom_line(serial=10, name=" C5'", res="DT", chain=chain, resnum=2, element=" C"),
        ]

    def test_strips_phosphate_from_first_residue_only(self) -> None:
        pdb = "\n".join(self._two_residue_chain()) + "\n"
        out = strip_5prime_phosphate(pdb)
        out_lines = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
        # Residue 1 should have P/OP1/OP2 dropped → 5 - 3 = 2 atoms (O5', C5').
        res1 = [ln for ln in out_lines if ln[22:26].strip() == "1"]
        assert len(res1) == 2
        names_res1 = {ln[12:16].strip() for ln in res1}
        assert names_res1 == {"O5'", "C5'"}
        # Residue 2 keeps all 5 atoms (interior residue, not a chain start).
        res2 = [ln for ln in out_lines if ln[22:26].strip() == "2"]
        assert len(res2) == 5
        names_res2 = {ln[12:16].strip() for ln in res2}
        assert names_res2 == {"P", "OP1", "OP2", "O5'", "C5'"}

    def test_no_phosphate_atoms_unchanged(self) -> None:
        """Input with no 5'-phosphate atoms → identical output (modulo trailing newline)."""
        pdb_lines = [
            _atom_line(serial=1, name=" O5'", res="DA", chain="A", resnum=1, element=" O"),
            _atom_line(serial=2, name=" C5'", res="DA", chain="A", resnum=1, element=" C"),
            _atom_line(serial=3, name=" O5'", res="DT", chain="A", resnum=2, element=" O"),
            _atom_line(serial=4, name=" C5'", res="DT", chain="A", resnum=2, element=" C"),
        ]
        pdb = "\n".join(pdb_lines) + "\n"
        out = strip_5prime_phosphate(pdb)
        assert out.count("ATOM  ") == 4

    def test_strips_at_each_chain_block_start(self) -> None:
        """When chain letter changes, a NEW block starts and its first
        residue's phosphate is also stripped."""
        chainA = self._two_residue_chain(chain="A")
        chainB = self._two_residue_chain(chain="B")
        pdb = "\n".join(chainA + chainB) + "\n"
        out = strip_5prime_phosphate(pdb)
        out_lines = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
        # Two blocks → 2 first-residue strips of 3 atoms each → 20 - 6 = 14.
        assert len(out_lines) == 14
        # Both residue-1's of A and B should be stripped.
        res1_a = [ln for ln in out_lines
                  if ln[21] == "A" and ln[22:26].strip() == "1"]
        res1_b = [ln for ln in out_lines
                  if ln[21] == "B" and ln[22:26].strip() == "1"]
        assert len(res1_a) == 2   # O5', C5' only
        assert len(res1_b) == 2

    def test_strips_at_repeated_chain_letter_block(self) -> None:
        """NADOC reuses chain letters when >26 strands.  A repeated letter
        starting a NEW contiguous block (after a different letter) gets
        treated as a new block-start."""
        # A...A (block 1) → B...B (block 2) → A...A (block 3, same letter as block 1)
        block1 = self._two_residue_chain(chain="A")
        block2 = self._two_residue_chain(chain="B")
        block3 = self._two_residue_chain(chain="A")   # reused chain letter
        pdb = "\n".join(block1 + block2 + block3) + "\n"
        out = strip_5prime_phosphate(pdb)
        out_lines = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
        # 3 blocks × 3 stripped phosphate atoms each = 9 atoms removed.
        # 30 input atoms → 21 output atoms.
        assert len(out_lines) == 21
        # Phosphate (P, OP1, OP2) atoms remaining = 3 (interior residues only:
        # residue 2 of each of the 3 blocks → 3 P + 3 OP1 + 3 OP2 = 9).
        n_phos = sum(1 for ln in out_lines
                     if ln[12:16].strip() in {"P", "OP1", "OP2"})
        assert n_phos == 9

    def test_post_rename_o1p_o2p_also_stripped(self) -> None:
        """The _5P_ATOMS set covers both pre-rename (OP1/OP2) AND post-rename
        (O1P/O2P) phosphate atom names — so calling strip after adapt_pdb_for_ff
        for AMBER still works."""
        pdb_lines = [
            _atom_line(serial=1, name=" P  ", res="DA", chain="A", resnum=1, element=" P"),
            _atom_line(serial=2, name=" O1P", res="DA", chain="A", resnum=1, element=" O"),
            _atom_line(serial=3, name=" O2P", res="DA", chain="A", resnum=1, element=" O"),
            _atom_line(serial=4, name=" O5'", res="DA", chain="A", resnum=1, element=" O"),
            _atom_line(serial=5, name=" C5'", res="DA", chain="A", resnum=1, element=" C"),
        ]
        pdb = "\n".join(pdb_lines) + "\n"
        out = strip_5prime_phosphate(pdb)
        out_lines = [ln for ln in out.splitlines() if ln.startswith("ATOM")]
        # P, O1P, O2P all dropped → 2 remaining (O5', C5').
        assert len(out_lines) == 2
        names = {ln[12:16].strip() for ln in out_lines}
        assert names == {"O5'", "C5'"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
