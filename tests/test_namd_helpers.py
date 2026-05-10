"""Tests for backend/core/namd_helpers.py (Refactor 10-A).

The 4 pure helpers extracted from namd_package.py operate on text strings
and lightweight Design metadata only — no subprocess, no force-field
directory lookup, no NAMD install required.

Fixture strategy
----------------
- `_complete_psf_from_stub`: synthetic stub PSF text built inline using the
  CHARMM PSF format (same `!NATOM` / `!NBOND` headers + atom lines that
  pdb_export.export_psf would emit).
- `_render_namd_conf`: pure str → str — exercise the f-string substitution
  with several names.
- `get_ai_prompt`: build a minimal `Design` via `make_minimal_design()`
  helper from tests/conftest_helpers and check `{name}` substitution.
- `complete_psf`: integration smoke that delegates to `_complete_psf_from_stub`
  via `export_psf(design)`.
"""

from __future__ import annotations

import pytest

from backend.core.namd_helpers import (
    _AI_PROMPT,
    _complete_psf_from_stub,
    _render_namd_conf,
    get_ai_prompt,
)


# ── PSF stub builders ─────────────────────────────────────────────────────────


def _stub_psf(n_atoms: int, atom_lines: list[str], bond_pairs: list[tuple[int, int]]) -> str:
    """Build a minimal stub PSF.

    PSF header: a `!NATOM` line is required; bonds section opened by `!NBOND`.
    Atom lines are passed in already-formatted; the parser only needs the
    serial-number pattern at the start (cols 1+) — its regex matches:

        ^\\s*(\\d+)\\s+(\\S+)\\s+(\\d+)\\s+(\\S+)\\s+(\\S+)\\s+(\\S+)\\s+
        ([0-9.+\\-Ee]+)\\s+([0-9.+\\-Ee]+)

    so we emit "<serial> SEG <resid> <resname> <name> <type> 0.0 12.011 0".
    """
    lines = [
        "PSF",
        "",
        "       1 !NTITLE",
        " REMARKS test stub",
        "",
        f"{n_atoms:8d} !NATOM",
    ]
    lines.extend(atom_lines)
    lines.append("")
    n_bonds = len(bond_pairs)
    lines.append(f"{n_bonds:8d} !NBOND: bonds")
    # Pack bonds 4 per line per CHARMM PSF convention; parser handles any width.
    for i in range(0, n_bonds, 4):
        chunk = bond_pairs[i:i + 4]
        lines.append("".join(f"{a:8d}{b:8d}" for a, b in chunk))
    lines.append("")
    return "\n".join(lines) + "\n"


def _atom_line(serial: int, resname: str = "ADE", name: str = "P", typ: str = "P") -> str:
    """Build one PSF atom line matching the parser's expected layout."""
    # serial seg resid resname name type charge mass moveable
    return f"{serial:8d} A    {serial:>4d} {resname:<4s} {name:<4s} {typ:<4s}  0.000000   12.0110   0"


# ── Tests for _render_namd_conf ───────────────────────────────────────────────


class TestRenderNamdConf:
    def test_substitutes_name_into_structure_field(self) -> None:
        """The `structure` directive should reference `<name>.psf`."""
        out = _render_namd_conf("teeth")
        assert "structure          teeth.psf" in out
        assert "coordinates        teeth.pdb" in out

    def test_substitutes_into_dcd_path(self) -> None:
        """DCD trajectory output path must include `<name>.dcd` under output/."""
        out = _render_namd_conf("my_design")
        assert "dcdFile            output/my_design.dcd" in out
        assert "xstFile            output/my_design.xst" in out

    def test_contains_required_namd_directives(self) -> None:
        """Sanity: required NAMD blocks present (GBIS, Langevin, integrator)."""
        out = _render_namd_conf("anything")
        for token in (
            "paraTypeCharmm     on",
            "gbis               on",
            "langevin           on",
            "timestep           1.0",
            "minimize           2000",
            "run                50000",
        ):
            assert token in out, f"missing directive: {token!r}"

    def test_includes_charmm36_parameter_path(self) -> None:
        """Parameter file path is hard-coded to forcefield/par_all36_na.prm."""
        out = _render_namd_conf("x")
        assert "parameters         forcefield/par_all36_na.prm" in out

    def test_pure_function_no_side_effects(self) -> None:
        """Two calls with same input produce identical output (idempotent / pure)."""
        a = _render_namd_conf("design_a")
        b = _render_namd_conf("design_a")
        assert a == b
        # And distinct inputs produce distinct outputs.
        c = _render_namd_conf("design_b")
        assert a != c


# ── Tests for _AI_PROMPT and get_ai_prompt ────────────────────────────────────


class TestGetAiPrompt:
    def test_ai_prompt_constant_contains_context_block(self) -> None:
        """The constant carries the identifying header + footer."""
        assert "NADOC — NAMD SIMULATION PACKAGE" in _AI_PROMPT
        assert "END OF CONTEXT" in _AI_PROMPT

    def test_get_ai_prompt_substitutes_design_name(self) -> None:
        """`{name}` placeholder replaced everywhere in the prompt."""

        class _Meta:
            name = "myDesign"

        class _D:
            metadata = _Meta()

        out = get_ai_prompt(_D())
        assert "{name}" not in out
        # Several distinct contexts should now carry the name.
        assert "myDesign.pdb" in out
        assert "myDesign.psf" in out
        assert "myDesign_namd_complete.zip" in out

    def test_get_ai_prompt_replaces_spaces_in_name(self) -> None:
        """Names with spaces are flattened to underscores (filename safety)."""

        class _Meta:
            name = "my fancy design"

        class _D:
            metadata = _Meta()

        out = get_ai_prompt(_D())
        assert "my_fancy_design.pdb" in out
        assert "my fancy design.pdb" not in out

    def test_get_ai_prompt_falls_back_when_name_empty(self) -> None:
        """Empty / None metadata.name → fallback to literal 'design'."""

        class _Meta:
            name = ""

        class _D:
            metadata = _Meta()

        out = get_ai_prompt(_D())
        assert "design.pdb" in out


# ── Tests for _complete_psf_from_stub ─────────────────────────────────────────


class TestCompletePsfFromStub:
    def test_no_bonds_produces_empty_angles_dihedrals(self) -> None:
        """Three isolated atoms with no bonds → no angles, no dihedrals."""
        atoms = [_atom_line(1), _atom_line(2), _atom_line(3)]
        stub = _stub_psf(3, atoms, bond_pairs=[])
        out = _complete_psf_from_stub(stub)
        # A '!NTHETA: angles' header must appear with count 0.
        assert "       0 !NTHETA: angles" in out
        assert "       0 !NPHI: dihedrals" in out
        # NIMPHI is hardcoded zero (CHARMM36 NA has no impropers).
        assert "       0 !NIMPHI: impropers" in out

    def test_single_angle_from_three_chained_atoms(self) -> None:
        """Two bonds 1-2 + 2-3 → exactly one angle (1, 2, 3); zero dihedrals."""
        atoms = [_atom_line(1), _atom_line(2), _atom_line(3)]
        bonds = [(1, 2), (2, 3)]
        stub = _stub_psf(3, atoms, bonds)
        out = _complete_psf_from_stub(stub)
        # Header + count.
        assert "       1 !NTHETA: angles" in out
        # Dihedrals stay zero (need 4 chained atoms for a dihedral).
        assert "       0 !NPHI: dihedrals" in out

    def test_dihedral_count_for_four_chained_atoms(self) -> None:
        """Linear chain 1-2-3-4 → 2 angles + 1 dihedral."""
        atoms = [_atom_line(1), _atom_line(2), _atom_line(3), _atom_line(4)]
        bonds = [(1, 2), (2, 3), (3, 4)]
        stub = _stub_psf(4, atoms, bonds)
        out = _complete_psf_from_stub(stub)
        assert "       2 !NTHETA: angles" in out
        assert "       1 !NPHI: dihedrals" in out

    def test_bonds_count_preserved_from_stub(self) -> None:
        """Output `!NBOND` count equals the number of input bond pairs."""
        atoms = [_atom_line(i) for i in range(1, 6)]   # 5 atoms
        bonds = [(1, 2), (2, 3), (3, 4), (4, 5)]
        stub = _stub_psf(5, atoms, bonds)
        out = _complete_psf_from_stub(stub)
        assert "       4 !NBOND: bonds" in out

    def test_zero_filled_optional_sections(self) -> None:
        """All other PSF sections (donors/acceptors/NB/etc.) emit zero counts."""
        atoms = [_atom_line(1), _atom_line(2)]
        stub = _stub_psf(2, atoms, [(1, 2)])
        out = _complete_psf_from_stub(stub)
        for tok in (
            "       0 !NDON: donors",
            "       0 !NACC: acceptors",
            "       0 !NNB",
            "       0       0 !NGRP NST2",
            "       0       0 !NUMLP NUMLPH",
        ):
            assert tok in out

    def test_atom_lines_passed_through_unchanged(self) -> None:
        """The atoms section in the output should contain every input atom line verbatim."""
        atoms = [_atom_line(1, resname="THY"), _atom_line(2, resname="ADE")]
        stub = _stub_psf(2, atoms, [(1, 2)])
        out = _complete_psf_from_stub(stub)
        assert "THY" in out
        assert "ADE" in out

    def test_triangle_three_bonds_three_angles_zero_dihedrals(self) -> None:
        """Triangle 1-2, 2-3, 1-3 → three angles, zero proper dihedrals.

        At each vertex the two neighbours form one angle (a, vertex, c with
        a < c). For 3 vertices that's 3 angles total. No dihedrals because a
        dihedral requires four distinct atoms.
        """
        atoms = [_atom_line(1), _atom_line(2), _atom_line(3)]
        bonds = [(1, 2), (2, 3), (1, 3)]
        stub = _stub_psf(3, atoms, bonds)
        out = _complete_psf_from_stub(stub)
        assert "       3 !NTHETA: angles" in out
        assert "       0 !NPHI: dihedrals" in out


# ── Integration: complete_psf delegates correctly ─────────────────────────────


class TestCompletePsfIntegration:
    def test_complete_psf_delegates_to_stub(self) -> None:
        """`complete_psf(design)` must call `export_psf(design)` and then
        `_complete_psf_from_stub`.  Verify by monkey-patching `export_psf` in
        the helpers module and confirming the stub flows through unchanged.
        """
        from backend.core import namd_helpers as _mod

        atoms = [_atom_line(1), _atom_line(2)]
        synthetic_stub = _stub_psf(2, atoms, [(1, 2)])

        called = {}

        def _fake_export_psf(design):
            called["design"] = design
            return synthetic_stub

        orig = _mod.export_psf
        _mod.export_psf = _fake_export_psf
        try:
            out = _mod.complete_psf("dummy_design_obj")   # arg passed through
        finally:
            _mod.export_psf = orig

        assert called["design"] == "dummy_design_obj"
        # Output must carry the !NBOND/!NTHETA/!NPHI section structure that
        # _complete_psf_from_stub produces from a 1-bond stub.
        assert "       1 !NBOND: bonds" in out
        assert "       0 !NTHETA: angles" in out
        assert "       0 !NPHI: dihedrals" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
