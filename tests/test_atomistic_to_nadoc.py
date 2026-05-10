"""
Coverage backfill (Refactor 11-B) for ``backend.core.atomistic_to_nadoc``.

Strategy
--------
The disk-fixture round-trip suite (`test_atomistic_round_trip.py`) exercises
the orchestrators against the 10hb design + GROMACS run artefacts.  Those
artefacts are not present in clean checkouts (errors out as
FileNotFoundError; baseline drop) so they cover only ~55% of the module
when the artefacts ARE present, and 18.7% otherwise.

This file lifts coverage by building everything in-memory:

  * a synthetic ``AtomisticModel`` populated with hand-placed P atoms so
    ``build_chain_map`` has deterministic input;
  * a synthetic NADOC-flavoured PDB string (no `pdb2gmx` involvement) so
    ``extract_from_pdb`` and ``build_p_gro_order`` can be tested with known
    expected output;
  * a synthetic GRO string fed straight into MDAnalysis so
    ``extract_from_gro`` and ``_extract_universe`` are exercised without the
    full GROMACS pipeline;
  * a tiny ``Design`` from ``conftest.make_minimal_design`` paired with a
    bead list to drive ``compare_to_design``, ``centroid_offset``, and
    ``_compute_comparison`` through both the AtomisticModel and the
    geometry-layer reference branches.

Tests assert real numeric values (``np.allclose`` with explicit tolerances,
exact RMSD = 0.0 round-trips, hand-computed centroid translations, exact
chain/seq lookups), not "no exception raised".  The XTC orchestrator
(``extract_from_xtc``) needs a real binary trajectory and is marked
``skip`` per Pass 11-B prompt — covered by an env-bound test in
``test_atomistic_round_trip.py`` when the artefacts are present.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.atomistic_to_nadoc import (
    BeadPosition,
    ComparisonResult,
    _build_reference_map,
    _compute_comparison,
    _map_positions,
    _parse_gro_p_positions,
    _unwrap_min_image,
    build_chain_map,
    build_p_gro_order,
    centroid_offset,
    compare_to_design,
    extract_from_gro,
    extract_from_pdb,
)

from tests.conftest import make_minimal_design


# ── Synthetic builders ───────────────────────────────────────────────────────


def _make_atom(
    *,
    serial: int,
    name: str,
    chain_id: str,
    seq_num: int,
    helix_id: str,
    bp_index: int,
    direction: str,
    pos_nm: tuple[float, float, float],
    residue: str = "DA",
    element: str = "P",
    strand_id: str = "s0",
) -> Atom:
    """Construct an ``Atom`` with everything spelled out (no defaults)."""
    return Atom(
        serial=serial,
        name=name,
        element=element,
        residue=residue,
        chain_id=chain_id,
        seq_num=seq_num,
        x=pos_nm[0],
        y=pos_nm[1],
        z=pos_nm[2],
        strand_id=strand_id,
        helix_id=helix_id,
        bp_index=bp_index,
        direction=direction,
    )


def _build_synthetic_model() -> AtomisticModel:
    """
    Build a tiny ``AtomisticModel`` with two strands, three nucleotides each.

    Layout (positions in nm, pre-image-of-P-atom):
      Chain A (strand sA, helix h0, FORWARD):
        bp 0: P at (0.0, 0.0, 0.0)  + C1' filler atom
        bp 1: P at (0.0, 0.0, 0.34)
        bp 2: P at (0.0, 0.0, 0.68)
      Chain B (strand sB, helix h0, REVERSE):
        bp 2: P at (1.0, 0.0, 0.0)
        bp 1: P at (1.0, 0.0, 0.34)
        bp 0: P at (1.0, 0.0, 0.68)

    The C1' atom on A:bp0 is included to confirm ``build_chain_map`` keeps
    only P atoms.
    """
    atoms: list[Atom] = []
    serial = 1

    # Chain A: FORWARD nucleotides at bp 0..2.
    for i in range(3):
        atoms.append(_make_atom(
            serial=serial, name="P", chain_id="A", seq_num=i + 1,
            helix_id="h0", bp_index=i, direction="FORWARD",
            pos_nm=(0.0, 0.0, i * 0.34),
        ))
        serial += 1
    # Filler C1' on bp 0 — must NOT appear in chain_map.
    atoms.append(_make_atom(
        serial=serial, name="C1'", chain_id="A", seq_num=1,
        helix_id="h0", bp_index=0, direction="FORWARD",
        pos_nm=(0.1, 0.0, 0.0), element="C",
    ))
    serial += 1

    # Chain B: REVERSE nucleotides; B:1 pairs with A:bp2, B:2 with A:bp1, B:3 with A:bp0.
    for i in range(3):
        bp_partner = 2 - i  # B:seq=1 → bp 2; B:seq=2 → bp 1; B:seq=3 → bp 0
        atoms.append(_make_atom(
            serial=serial, name="P", chain_id="B", seq_num=i + 1,
            helix_id="h0", bp_index=bp_partner, direction="REVERSE",
            pos_nm=(1.0, 0.0, i * 0.34),
            residue="DT", strand_id="sB",
        ))
        serial += 1

    return AtomisticModel(atoms=atoms, bonds=[])


def _format_pdb_atom(
    *,
    serial: int,
    name: str,
    res_name: str,
    chain_id: str,
    res_seq: int,
    pos_nm: tuple[float, float, float],
    element: str = "P",
) -> str:
    """Format a fixed-width PDB ATOM record matching extract_from_pdb's column slices.

    Column layout per PDB spec:
        cols  1- 6   "ATOM  "
        cols  7-11   serial (right)
        col  12      space
        cols 13-16   atom name (extract_from_pdb uses [12:16])
        col  17      altLoc
        cols 18-20   resName (extract_from_pdb does NOT read this)
        col  21      space
        col  22      chainID  (extract_from_pdb uses [21])
        cols 23-26   resSeq   (extract_from_pdb uses [22:26])
        col  27      iCode + 3 spaces
        cols 31-38   x        (extract_from_pdb uses [30:38], Å)
        cols 39-46   y                              [38:46]
        cols 47-54   z                              [46:54]
        cols 55-60   occupancy
        cols 61-66   tempFactor
        cols 77-78   element
    """
    x_a, y_a, z_a = (10.0 * p for p in pos_nm)  # nm → Å
    return (
        f"ATOM  {serial:>5d} {name:<4s} {res_name:<3s} {chain_id}"
        f"{res_seq:>4d}    "
        f"{x_a:>8.3f}{y_a:>8.3f}{z_a:>8.3f}"
        f"  1.00  0.00          {element:>2s}"
    )


def _build_synthetic_pdb_text() -> str:
    """Build a PDB string mirroring _build_synthetic_model() atom-for-atom.

    Two chain blocks (A then B), 3 residues each, P atom only.  Includes a
    leading non-ATOM header line and a TER between chains so we can verify
    the orchestrator skips them.
    """
    lines: list[str] = ["HEADER    SYNTHETIC TEST                       2026-05-10"]
    serial = 1
    # Chain A
    for i in range(3):
        lines.append(_format_pdb_atom(
            serial=serial, name="P", res_name="DA", chain_id="A",
            res_seq=i + 1, pos_nm=(0.0, 0.0, i * 0.34),
        ))
        serial += 1
    lines.append("TER")
    # Chain B
    for i in range(3):
        lines.append(_format_pdb_atom(
            serial=serial, name="P", res_name="DT", chain_id="B",
            res_seq=i + 1, pos_nm=(1.0, 0.0, i * 0.34),
        ))
        serial += 1
    lines.append("END")
    return "\n".join(lines) + "\n"


def _format_gro_line(
    *, res_id: int, res_name: str, atom_name: str,
    atom_index: int, pos_nm: tuple[float, float, float],
) -> str:
    """Format one GRO atom line (column-anchored)."""
    return (
        f"{res_id:>5d}{res_name:<5s}{atom_name:>5s}{atom_index:>5d}"
        f"{pos_nm[0]:>8.3f}{pos_nm[1]:>8.3f}{pos_nm[2]:>8.3f}"
    )


def _write_synthetic_gro(
    path: Path,
    p_positions_nm: list[tuple[float, float, float]],
    *,
    box_nm: tuple[float, float, float] = (3.0, 3.0, 3.0),
    res_names: list[str] | None = None,
) -> None:
    """Write a single-frame GRO file with P atoms only at the given positions."""
    if res_names is None:
        res_names = ["DA"] * len(p_positions_nm)
    lines: list[str] = ["Synthetic NADOC test", f" {len(p_positions_nm):>4d}"]
    for i, (pos, res_name) in enumerate(zip(p_positions_nm, res_names)):
        lines.append(_format_gro_line(
            res_id=i + 1, res_name=res_name,
            atom_name="P", atom_index=i + 1, pos_nm=pos,
        ))
    bx, by, bz = box_nm
    lines.append(f"{bx:>10.5f}{by:>10.5f}{bz:>10.5f}")
    path.write_text("\n".join(lines) + "\n")


# ── build_chain_map ──────────────────────────────────────────────────────────


class TestBuildChainMap:
    def test_filters_to_p_atoms_only(self):
        """C1' filler atom must NOT appear in chain_map; only P atoms."""
        model = _build_synthetic_model()
        chain_map = build_chain_map(model)

        # 3 P on chain A + 3 P on chain B = 6.  The C1' filler is dropped.
        assert len(chain_map) == 6
        assert all(isinstance(k, tuple) and len(k) == 2 for k in chain_map)

    def test_keys_and_values_match_exactly(self):
        """Hand-verified chain_map content (column-anchored)."""
        model = _build_synthetic_model()
        chain_map = build_chain_map(model)

        # Chain A: seq 1..3 → FORWARD bp 0..2.
        assert chain_map[("A", 1)] == ("h0", 0, "FORWARD")
        assert chain_map[("A", 2)] == ("h0", 1, "FORWARD")
        assert chain_map[("A", 3)] == ("h0", 2, "FORWARD")
        # Chain B: seq 1..3 → REVERSE bp 2..0 (antiparallel pairing).
        assert chain_map[("B", 1)] == ("h0", 2, "REVERSE")
        assert chain_map[("B", 2)] == ("h0", 1, "REVERSE")
        assert chain_map[("B", 3)] == ("h0", 0, "REVERSE")

    def test_empty_model_returns_empty_map(self):
        chain_map = build_chain_map(AtomisticModel(atoms=[], bonds=[]))
        assert chain_map == {}


# ── extract_from_pdb ─────────────────────────────────────────────────────────


class TestExtractFromPdb:
    def test_returns_one_bead_per_chain_map_entry(self):
        model = _build_synthetic_model()
        chain_map = build_chain_map(model)
        pdb_text = _build_synthetic_pdb_text()

        beads = extract_from_pdb(pdb_text, chain_map)

        assert len(beads) == len(chain_map)
        assert all(isinstance(b, BeadPosition) for b in beads)

    def test_bead_positions_round_trip_to_atomistic_model(self):
        """PDB → bead positions should equal the atomistic model values exactly
        modulo PDB's 3-decimal-place storage in Å (= 1e-4 nm precision)."""
        model = _build_synthetic_model()
        chain_map = build_chain_map(model)
        pdb_text = _build_synthetic_pdb_text()

        beads = extract_from_pdb(pdb_text, chain_map)
        # Cross-reference: bead at A:1 should match Atom(serial=1).
        beads_by_key = {(b.helix_id, b.bp_index, b.direction): b for b in beads}

        for atom in model.atoms:
            if atom.name != "P":
                continue
            key = (atom.helix_id, atom.bp_index, atom.direction)
            ref = np.array([atom.x, atom.y, atom.z])
            assert np.allclose(beads_by_key[key].pos, ref, atol=1e-4), (
                f"Round-trip failed for {key}: "
                f"got {beads_by_key[key].pos}, expected {ref}"
            )

    def test_unmapped_chain_seq_is_dropped(self):
        """A PDB record whose (chain, seq) is absent from chain_map is skipped."""
        chain_map = {("A", 1): ("h0", 0, "FORWARD")}
        # Two records: A:1 (mapped) + Z:99 (unmapped).
        pdb_text = (
            _format_pdb_atom(
                serial=1, name="P", res_name="DA", chain_id="A",
                res_seq=1, pos_nm=(0.0, 0.0, 0.0),
            )
            + "\n"
            + _format_pdb_atom(
                serial=2, name="P", res_name="DA", chain_id="Z",
                res_seq=99, pos_nm=(5.0, 5.0, 5.0),
            )
            + "\nEND\n"
        )
        beads = extract_from_pdb(pdb_text, chain_map)
        assert len(beads) == 1
        assert (beads[0].helix_id, beads[0].bp_index) == ("h0", 0)

    def test_short_lines_and_non_atom_records_ignored(self):
        """HEADER, TER, END, and lines < 54 chars must be skipped."""
        chain_map = {("A", 1): ("h0", 0, "FORWARD")}
        pdb_text = (
            "HEADER    short header\n"
            "TER\n"
            + _format_pdb_atom(
                serial=1, name="P", res_name="DA", chain_id="A",
                res_seq=1, pos_nm=(0.5, 0.0, 0.5),
            )
            + "\nEND\n"
        )
        beads = extract_from_pdb(pdb_text, chain_map)
        assert len(beads) == 1
        # Position recovered exactly.
        assert np.allclose(beads[0].pos, np.array([0.5, 0.0, 0.5]), atol=1e-4)

    def test_short_atom_line_below_54_chars_skipped(self):
        """An ATOM line < 54 chars is skipped (no coords yet) without raising."""
        chain_map = {("A", 1): ("h0", 0, "FORWARD")}
        # 30-char ATOM line: "ATOM      1  P    DA  A   1   "
        short = "ATOM      1  P    DA  A   1   "
        assert len(short) < 54
        full = _format_pdb_atom(
            serial=2, name="P", res_name="DA", chain_id="A",
            res_seq=1, pos_nm=(0.0, 0.0, 0.0),
        )
        pdb_text = short + "\n" + full + "\nEND\n"
        beads = extract_from_pdb(pdb_text, chain_map)
        # Only the well-formed line was kept.
        assert len(beads) == 1
        assert np.allclose(beads[0].pos, np.zeros(3), atol=1e-4)

    def test_non_p_atom_records_skipped(self):
        """C1' (or any non-P) records must be filtered."""
        chain_map = {("A", 1): ("h0", 0, "FORWARD")}
        pdb_text = (
            _format_pdb_atom(
                serial=1, name="C1'", res_name="DA", chain_id="A",
                res_seq=1, pos_nm=(0.0, 0.0, 0.0), element=" C",
            )
            + "\n"
            + _format_pdb_atom(
                serial=2, name="P", res_name="DA", chain_id="A",
                res_seq=1, pos_nm=(1.0, 0.0, 0.0),
            )
            + "\nEND\n"
        )
        beads = extract_from_pdb(pdb_text, chain_map)
        assert len(beads) == 1
        assert np.allclose(beads[0].pos, np.array([1.0, 0.0, 0.0]), atol=1e-4)


# ── build_p_gro_order ────────────────────────────────────────────────────────


class TestBuildPGroOrder:
    def test_strips_5prime_terminal_per_chain(self):
        """pdb2gmx strips the 5' P from each chain block; check N-strands removed."""
        model = _build_synthetic_model()
        chain_map = build_chain_map(model)
        pdb_text = _build_synthetic_pdb_text()

        order = build_p_gro_order(pdb_text, chain_map)

        # 6 P atoms in chain_map - 2 chain blocks (A, B) = 4 entries kept.
        assert len(order) == 4
        # First and last per chain are stripped: A:2, A:3, B:2, B:3 remain.
        kept = set(order)
        # A:2 → bp 1 FWD; A:3 → bp 2 FWD; B:2 → bp 1 REV; B:3 → bp 0 REV.
        assert ("h0", 1, "FORWARD") in kept
        assert ("h0", 2, "FORWARD") in kept
        assert ("h0", 1, "REVERSE") in kept
        assert ("h0", 0, "REVERSE") in kept
        # 5' terminals (A:1, B:1) are stripped:
        assert ("h0", 0, "FORWARD") not in kept
        assert ("h0", 2, "REVERSE") not in kept

    def test_preserves_pdb_file_order(self):
        """Order list must follow PDB file order (A residues before B)."""
        model = _build_synthetic_model()
        chain_map = build_chain_map(model)
        pdb_text = _build_synthetic_pdb_text()
        order = build_p_gro_order(pdb_text, chain_map)
        # First two entries: chain A non-terminal P atoms.
        assert order[0] == ("h0", 1, "FORWARD")
        assert order[1] == ("h0", 2, "FORWARD")
        # Then chain B non-terminal entries.
        assert order[2] == ("h0", 1, "REVERSE")
        assert order[3] == ("h0", 0, "REVERSE")

    def test_blank_lines_and_remarks_dont_break_block_detection(self):
        """REMARK / TER / blank lines mixed in with ATOM records must not affect
        block-start detection.  This exercises both loops' early-out filters."""
        chain_map = {
            ("A", 1): ("h0", 0, "FORWARD"),
            ("A", 2): ("h0", 1, "FORWARD"),
            ("A", 3): ("h0", 2, "FORWARD"),
        }
        atoms = [
            _format_pdb_atom(
                serial=i + 1, name="P", res_name="DA", chain_id="A",
                res_seq=i + 1, pos_nm=(0.0, 0.0, i * 0.34),
            )
            for i in range(3)
        ]
        # Mix non-ATOM lines between ATOM records.
        pdb_text = (
            "REMARK   filler\n"
            + atoms[0] + "\n"
            + "TER\n"
            + atoms[1] + "\n"
            + "\n"  # blank line
            + atoms[2] + "\n"
            + "END\n"
        )
        order = build_p_gro_order(pdb_text, chain_map)
        # Only A:1 is the 5' terminal (stripped).  A:2 and A:3 remain.
        assert order == [("h0", 1, "FORWARD"), ("h0", 2, "FORWARD")]


# ── _parse_gro_p_positions and _map_positions (private helpers) ──────────────


class TestParseGroPositionsHelper:
    def test_parses_p_positions_from_gro(self, tmp_path):
        gro_path = tmp_path / "tiny.gro"
        # 3 P atoms at known coordinates.
        positions = [(0.5, 1.0, 1.5), (0.5, 1.0, 1.84), (0.5, 1.0, 2.18)]
        _write_synthetic_gro(gro_path, positions)

        out = _parse_gro_p_positions(gro_path)

        assert len(out) == 3
        for parsed, expected in zip(out, positions):
            assert np.allclose(parsed, np.array(expected), atol=1e-3)

    def test_corrupt_float_field_swallowed_via_value_error(self, tmp_path):
        """A P-atom line with a non-numeric coord is silently skipped (try/except)."""
        gro_path = tmp_path / "corrupt.gro"
        good = _format_gro_line(
            res_id=1, res_name="DA", atom_name="P",
            atom_index=1, pos_nm=(0.5, 0.5, 0.5),
        )
        # Build a corrupt P-atom line: same column layout but the x-field is
        # "  XXXXXX" (8 chars, non-numeric). _parse_gro_p_positions reads the
        # float at line[20:28]; a ValueError there hits the except branch.
        head = f"{2:>5d}{'DA':<5s}{'P':>5s}{2:>5d}"  # 20 chars
        bad = head + " XXXXXXX" + f"{0.5:>8.3f}{0.5:>8.3f}"  # 44 chars total
        assert len(bad) >= 44
        gro_text = (
            "Corrupt test\n"
            "    2\n"
            f"{good}\n"
            f"{bad}\n"
            "   3.00000   3.00000   3.00000\n"
        )
        gro_path.write_text(gro_text)

        out = _parse_gro_p_positions(gro_path)
        # Only the good record is kept; the corrupt one is swallowed.
        assert len(out) == 1
        assert np.allclose(out[0], np.array([0.5, 0.5, 0.5]), atol=1e-3)

    def test_skips_non_dna_resnames(self, tmp_path):
        """Non-DNA resnames (e.g. SOL) must be filtered out by name AND resname."""
        gro_path = tmp_path / "mixed.gro"
        _write_synthetic_gro(
            gro_path,
            [(0.5, 0.5, 0.5), (1.5, 1.5, 1.5)],
            res_names=["DA", "SOL"],   # second is solvent → must be skipped
        )
        out = _parse_gro_p_positions(gro_path)
        assert len(out) == 1
        assert np.allclose(out[0], np.array([0.5, 0.5, 0.5]), atol=1e-3)


class TestMapPositionsHelper:
    def test_pairs_positions_with_p_order(self):
        positions = [np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0])]
        p_order = [("h0", 0, "FORWARD"), ("h0", 1, "FORWARD")]

        beads = _map_positions(positions, p_order)

        assert len(beads) == 2
        assert beads[0].helix_id == "h0"
        assert beads[0].bp_index == 0
        assert np.allclose(beads[0].pos, np.array([1.0, 2.0, 3.0]))
        assert np.allclose(beads[1].pos, np.array([4.0, 5.0, 6.0]))

    def test_size_mismatch_raises(self):
        positions = [np.array([1.0, 2.0, 3.0])]
        p_order = [("h0", 0, "FORWARD"), ("h0", 1, "FORWARD")]
        with pytest.raises(ValueError, match=r"1 DNA P atoms .* 2 entries"):
            _map_positions(positions, p_order)


# ── extract_from_gro (MDAnalysis path) ───────────────────────────────────────


class TestExtractFromGro:
    def test_extract_from_gro_returns_one_bead_per_p_order(self, tmp_path):
        """MDAnalysis path: positions in Å are converted to nm and matched
        against p_order entries in file order."""
        gro_path = tmp_path / "em.gro"
        # 2 P atoms in known positions (nm).
        positions_nm = [(0.5, 1.0, 1.5), (0.5, 1.0, 1.84)]
        _write_synthetic_gro(gro_path, positions_nm)

        p_order = [("h0", 0, "FORWARD"), ("h0", 1, "FORWARD")]
        beads = extract_from_gro(gro_path, p_order, frame=0)

        assert len(beads) == 2
        # Position is matched to p_order by index.
        assert beads[0].helix_id == "h0" and beads[0].bp_index == 0
        assert beads[1].helix_id == "h0" and beads[1].bp_index == 1
        # GRO writes %8.3f in nm; MDAnalysis reads Å then we divide by 10.
        # Round-trip precision is ~1e-3 nm.
        assert np.allclose(beads[0].pos, np.array([0.5, 1.0, 1.5]), atol=1e-3)
        assert np.allclose(beads[1].pos, np.array([0.5, 1.0, 1.84]), atol=1e-3)

    def test_extract_from_gro_size_mismatch_raises(self, tmp_path):
        """If trajectory has more/fewer P atoms than p_order, raises ValueError."""
        gro_path = tmp_path / "mismatch.gro"
        _write_synthetic_gro(gro_path, [(0.5, 1.0, 1.5), (0.5, 1.0, 1.84)])
        # p_order says 1 entry but file has 2 P atoms.
        with pytest.raises(ValueError, match=r"2 DNA P atoms"):
            extract_from_gro(gro_path, [("h0", 0, "FORWARD")], frame=0)

    def test_extract_from_gro_unwraps_periodic_image(self, tmp_path):
        """When two consecutive P atoms straddle the box boundary, the unwrap
        step pulls the second back so they remain ~0.34 nm apart, not box-1.

        Box = 3 nm; P atoms at z = 2.95 and z = 0.05 (a periodic-image jump
        of −2.9 nm).  Min-image correction adds +3 nm to the second atom,
        landing it at z = 3.05 — a 0.10 nm intra-strand spacing.
        """
        gro_path = tmp_path / "wrap.gro"
        _write_synthetic_gro(
            gro_path,
            [(0.5, 0.5, 2.95), (0.5, 0.5, 0.05)],
            box_nm=(3.0, 3.0, 3.0),
        )
        p_order = [("h0", 0, "FORWARD"), ("h0", 1, "FORWARD")]
        beads = extract_from_gro(gro_path, p_order, frame=0)

        # After unwrap, the second P should sit at z ≈ 3.05 nm (not 0.05).
        assert beads[1].pos[2] == pytest.approx(3.05, abs=1e-2)
        # First P unchanged.
        assert beads[0].pos[2] == pytest.approx(2.95, abs=1e-2)
        # Spacing now ~0.1 nm, well below the 1.0 nm intra-strand cutoff.
        spacing = float(np.linalg.norm(beads[1].pos - beads[0].pos))
        assert spacing < _backbone_cutoff_nm()


def _backbone_cutoff_nm() -> float:
    """Mirror of atomistic_to_nadoc._P_BACKBONE_MAX_NM (kept private)."""
    from backend.core.atomistic_to_nadoc import _P_BACKBONE_MAX_NM
    return _P_BACKBONE_MAX_NM


# ── _unwrap_min_image (private) ──────────────────────────────────────────────


class TestUnwrapMinImage:
    def test_no_op_when_within_cutoff(self):
        """Already-contiguous positions pass through unchanged."""
        positions = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.34],
            [0.0, 0.0, 0.68],
        ])
        out = _unwrap_min_image(positions, np.array([3.0, 3.0, 3.0]))
        assert np.allclose(out, positions)

    def test_strand_boundary_not_shifted(self):
        """If consecutive atoms differ by ~box/2 (interpreted as strand boundary
        after min-image), the shift is NOT applied."""
        # Two atoms 1.5 nm apart in a 3 nm box: nearest image after correction
        # is exactly 1.5 nm (np.round(0.5)=0 in numpy banker's rounding) — well
        # above _P_BACKBONE_MAX_NM (1.0 nm), so the second atom stays put.
        positions = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.5],
        ])
        out = _unwrap_min_image(positions, np.array([3.0, 3.0, 3.0]))
        assert np.allclose(out[0], positions[0])
        assert np.allclose(out[1], positions[1])  # unchanged

    def test_box_zero_skips_dimension(self):
        """When box[d]==0, no min-image correction is applied along that axis."""
        positions = np.array([
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.34],
        ])
        # Box x=0 → x-axis correction skipped → magnitude > 1 nm → no shift.
        out = _unwrap_min_image(positions, np.array([0.0, 3.0, 3.0]))
        assert np.allclose(out, positions)


# ── compare_to_design / centroid_offset / _compute_comparison ────────────────


class TestCompareToDesign:
    def test_geometry_layer_zero_rmsd_round_trip(self):
        """When beads ARE the geometry-layer reference, RMSD must be 0."""
        from backend.core.geometry import nucleotide_positions

        design = make_minimal_design(n_helices=1, helix_length_bp=8)
        # Build beads that exactly match the geometry-layer positions.
        beads: list[BeadPosition] = []
        for helix in design.helices:
            for nuc in nucleotide_positions(helix):
                beads.append(BeadPosition(
                    helix_id=nuc.helix_id,
                    bp_index=nuc.bp_index,
                    direction=nuc.direction.value,
                    pos=nuc.position.copy(),
                ))

        result = compare_to_design(beads, design, use_geometry_layer=True)

        assert isinstance(result, ComparisonResult)
        assert result.n_missing == 0
        assert result.n_matched == len(beads)
        assert result.global_rmsd_nm == pytest.approx(0.0, abs=1e-9)
        assert result.max_deviation_nm == pytest.approx(0.0, abs=1e-9)
        # per_helix_rmsd_nm has one key per helix, each rmsd 0.
        assert set(result.per_helix_rmsd_nm.keys()) == {h.id for h in design.helices}
        for rmsd in result.per_helix_rmsd_nm.values():
            assert rmsd == pytest.approx(0.0, abs=1e-9)

    def test_geometry_layer_constant_offset_yields_known_rmsd(self):
        """Add a constant 0.5 nm shift in +z to every bead → RMSD = 0.5 nm exactly."""
        from backend.core.geometry import nucleotide_positions

        design = make_minimal_design(n_helices=1, helix_length_bp=4)
        shift = np.array([0.0, 0.0, 0.5])
        beads = [
            BeadPosition(
                helix_id=nuc.helix_id, bp_index=nuc.bp_index,
                direction=nuc.direction.value,
                pos=nuc.position + shift,
            )
            for h in design.helices for nuc in nucleotide_positions(h)
        ]
        result = compare_to_design(beads, design, use_geometry_layer=True)
        assert result.global_rmsd_nm == pytest.approx(0.5, abs=1e-9)
        assert result.max_deviation_nm == pytest.approx(0.5, abs=1e-9)

    def test_align_translation_removes_centroid_shift(self):
        """A constant translation cancels under align_translation=True."""
        from backend.core.geometry import nucleotide_positions

        design = make_minimal_design(n_helices=1, helix_length_bp=4)
        shift = np.array([5.0, 6.0, 7.0])
        beads = [
            BeadPosition(
                helix_id=nuc.helix_id, bp_index=nuc.bp_index,
                direction=nuc.direction.value,
                pos=nuc.position + shift,
            )
            for h in design.helices for nuc in nucleotide_positions(h)
        ]
        result = compare_to_design(
            beads, design, use_geometry_layer=True, align_translation=True,
        )
        assert result.global_rmsd_nm == pytest.approx(0.0, abs=1e-9)
        assert result.max_deviation_nm == pytest.approx(0.0, abs=1e-9)

    def test_n_missing_counts_unmatched_keys(self):
        from backend.core.geometry import nucleotide_positions

        design = make_minimal_design(n_helices=1, helix_length_bp=4)
        beads = [
            BeadPosition(
                helix_id=nuc.helix_id, bp_index=nuc.bp_index,
                direction=nuc.direction.value,
                pos=nuc.position.copy(),
            )
            for h in design.helices for nuc in nucleotide_positions(h)
        ]
        # Inject one bogus bead whose key is absent from the reference.
        beads.append(BeadPosition(
            helix_id="ghost", bp_index=999, direction="FORWARD",
            pos=np.zeros(3),
        ))
        result = compare_to_design(beads, design, use_geometry_layer=True)
        assert result.n_missing == 1
        assert result.n_matched == len(beads) - 1


class TestCentroidOffset:
    def test_centroid_offset_matches_constant_shift(self):
        """Beads shifted by ``shift`` → centroid_offset returns -shift."""
        from backend.core.geometry import nucleotide_positions

        design = make_minimal_design(n_helices=1, helix_length_bp=4)
        shift = np.array([2.0, -3.0, 4.0])
        beads = [
            BeadPosition(
                helix_id=nuc.helix_id, bp_index=nuc.bp_index,
                direction=nuc.direction.value,
                pos=nuc.position + shift,
            )
            for h in design.helices for nuc in nucleotide_positions(h)
        ]
        T = centroid_offset(beads, design, use_geometry_layer=True)
        assert np.allclose(T, -shift, atol=1e-9)

    def test_centroid_offset_no_overlap_returns_zero(self):
        """When beads share no keys with the reference, centroid_offset = 0."""
        design = make_minimal_design(n_helices=1, helix_length_bp=4)
        beads = [BeadPosition(
            helix_id="ghost", bp_index=0, direction="FORWARD",
            pos=np.array([7.0, 8.0, 9.0]),
        )]
        T = centroid_offset(beads, design, use_geometry_layer=True)
        assert np.allclose(T, np.zeros(3))


class TestBuildReferenceMapAndCompute:
    def test_build_reference_map_geometry_layer_keys(self):
        """Geometry-layer reference map has one key per nucleotide_position."""
        from backend.core.geometry import nucleotide_positions

        design = make_minimal_design(n_helices=1, helix_length_bp=6)
        ref_map = _build_reference_map(design, use_geometry_layer=True)

        expected_keys = set()
        for h in design.helices:
            for nuc in nucleotide_positions(h):
                expected_keys.add((nuc.helix_id, nuc.bp_index, nuc.direction.value))
        assert set(ref_map.keys()) == expected_keys
        # All values are 3-vectors (positions).
        for v in ref_map.values():
            assert isinstance(v, np.ndarray) and v.shape == (3,)

    def test_compute_comparison_handles_empty_input(self):
        """With zero beads, RMSD = 0 and per_helix dict is empty."""
        result = _compute_comparison([], {}, align_translation=False)
        assert result.n_matched == 0
        assert result.n_missing == 0
        assert result.global_rmsd_nm == 0.0
        assert result.max_deviation_nm == 0.0
        assert result.per_helix_rmsd_nm == {}

    def test_compute_comparison_per_helix_rmsd_separates_helices(self):
        """Two beads in two different helices → two entries in per_helix_rmsd_nm."""
        ref_map = {
            ("hA", 0, "FORWARD"): np.array([0.0, 0.0, 0.0]),
            ("hB", 0, "FORWARD"): np.array([0.0, 0.0, 0.0]),
        }
        beads = [
            BeadPosition("hA", 0, "FORWARD", np.array([0.3, 0.0, 0.0])),
            BeadPosition("hB", 0, "FORWARD", np.array([0.4, 0.0, 0.0])),
        ]
        result = _compute_comparison(beads, ref_map, align_translation=False)
        assert set(result.per_helix_rmsd_nm.keys()) == {"hA", "hB"}
        assert result.per_helix_rmsd_nm["hA"] == pytest.approx(0.3, abs=1e-9)
        assert result.per_helix_rmsd_nm["hB"] == pytest.approx(0.4, abs=1e-9)
        # Global RMSD = sqrt((0.3^2 + 0.4^2) / 2) = sqrt(0.125) ≈ 0.3535...
        assert result.global_rmsd_nm == pytest.approx(math.sqrt(0.125), abs=1e-9)
        assert result.max_deviation_nm == pytest.approx(0.4, abs=1e-9)


# ── extract_from_xtc — env-bound, skip-marked per Pass 11-B prompt ───────────


@pytest.mark.skip(
    reason="extract_from_xtc requires a real binary XTC trajectory; "
           "covered by tests/test_atomistic_round_trip.py when 10hb fixtures "
           "are present (env-bound, Pass 11-B prompt §Stop conditions).",
)
def test_extract_from_xtc_requires_binary_fixture():
    """Marker test — body intentionally empty."""
    pytest.fail("Should be skipped by marker.")
