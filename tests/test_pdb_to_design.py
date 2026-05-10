"""
End-to-end tests for the PDB → Design orchestrators in
``backend.core.pdb_to_design``.

Coverage backfill (Refactor 07-A): exercises ``import_pdb`` and
``merge_pdb_into_design`` against a synthetic 4-bp AT-tract duplex PDB
generated inline.  Lifts ``pdb_to_design.py`` from 0% coverage by hitting
the happy paths plus a sad path on malformed input.

Fixture strategy
----------------
The synthetic-duplex writer is adapted from
``tests/test_pdb_import_geometry.py::_write_synthetic_duplex_pdb`` (Refactor
06-A).  It builds a tiny duplex from the calibrated 1ZEW B-DNA atomistic
templates already shipped in ``backend.core.atomistic`` and rotates each bp
by canonical B-DNA twist (34.3°).  No external fixture file is shipped.

These tests assert that the two orchestrators return a usable
``(Design, AtomisticModel, warnings)`` tuple and that merging preserves an
existing design's identity (helix list, strand IDs).  They do NOT validate
the orchestrators' geometric correctness against literature — that is
covered by ``test_pdb_import_geometry.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.core.atomistic import (
    _DA_BASE,
    _DT_BASE,
    _SUGAR,
)
from backend.core.models import Direction, StrandType
from backend.core.pdb_to_design import import_pdb, merge_pdb_into_design

from tests.conftest import make_minimal_design


# ── Synthetic-duplex PDB writer (adapted from test_pdb_import_geometry) ──────


def _write_synthetic_duplex_pdb(path: str, n_bp: int = 4) -> None:
    """Write a tiny synthetic AT/AT/.../AT duplex PDB to *path*.

    Chain A: TTTT (resSeq 1..N), 5'→3' along +z.
    Chain B: AAAA (resSeq 1..N), antiparallel; B:1 pairs with A:N.
    Each bp is rotated by B-DNA twist (34.3°) and translated by 0.334 nm.
    """
    rise_nm = 0.334
    twist_rad = math.radians(34.3)

    def write_atom(f, serial, name, resName, chainID, resSeq, x, y, z, elem):
        # PDB ATOM record (Angstroms = nm × 10).
        line = (
            "ATOM  "
            f"{serial:>5d} "
            f"{name:<4s} "
            f"{resName:<3s} "
            f"{chainID}"
            f"{resSeq:>4d}    "
            f"{x*10:>8.3f}{y*10:>8.3f}{z*10:>8.3f}"
            f"  1.00  0.00           {elem:<2s}\n"
        )
        f.write(line)

    def write_residue(f, atoms_template, resName, chainID, resSeq, twist, dz, mirror, serial):
        c, s = math.cos(twist), math.sin(twist)
        for name, elem, n, y, z in atoms_template:
            if mirror:
                n, y = -n, -y
            x_w = c * n - s * y
            y_w = s * n + c * y
            z_w = z + dz
            write_atom(f, serial, name, resName, chainID, resSeq, x_w, y_w, z_w, elem)
            serial += 1
        return serial

    with open(path, "w") as f:
        serial = 1
        # Chain A: TTTT (resSeq 1..N) along +z.
        for i in range(n_bp):
            seq = i + 1
            serial = write_residue(
                f, _SUGAR, "DT", "A", seq, i * twist_rad, i * rise_nm, False, serial,
            )
            serial = write_residue(
                f, _DT_BASE, "DT", "A", seq, i * twist_rad, i * rise_nm, False, serial,
            )
        # Chain B: AAAA (resSeq 1..N), antiparallel: B:1 ↔ A:N.
        for i in range(n_bp):
            seq = i + 1
            a_seq = n_bp - i  # B:1 pairs with A:N
            serial = write_residue(
                f, _SUGAR, "DA", "B", seq,
                (a_seq - 1) * twist_rad, (a_seq - 1) * rise_nm, True, serial,
            )
            serial = write_residue(
                f, _DA_BASE, "DA", "B", seq,
                (a_seq - 1) * twist_rad, (a_seq - 1) * rise_nm, True, serial,
            )
        f.write("END\n")


def _synthetic_pdb_text(tmp_path: Path, n_bp: int = 4) -> str:
    """Generate a synthetic n_bp AT-duplex PDB and return its text contents.

    The orchestrators ``import_pdb`` / ``merge_pdb_into_design`` accept PDB
    text (not a file path); the helper materialises the file in *tmp_path*
    purely to reuse the existing writer.
    """
    pdb_path = tmp_path / f"synthetic_{n_bp}bp.pdb"
    _write_synthetic_duplex_pdb(str(pdb_path), n_bp=n_bp)
    return pdb_path.read_text()


# ── import_pdb ───────────────────────────────────────────────────────────────


class TestImportPdb:
    def test_import_pdb_single_duplex_returns_valid_design(self, tmp_path):
        """4-bp synthetic duplex → 1 helix with two antiparallel strands.

        ``import_pdb`` collapses a duplex into one Helix carrying both the
        FORWARD and REVERSE domain (the two strands share helix_id but
        traverse it in opposite Direction).  The first duplex's forward
        strand is assigned StrandType.SCAFFOLD; the reverse is STAPLE.
        """
        n_bp = 4
        content = _synthetic_pdb_text(tmp_path, n_bp=n_bp)

        design, atomistic, warnings = import_pdb(content, cluster_name="Test PDB")

        # One duplex → one helix carrying both strands.
        assert len(design.helices) == 1
        helix = design.helices[0]
        assert helix.length_bp == n_bp
        assert helix.bp_start == 0

        # Two strands: forward (scaffold) + reverse (staple).
        assert len(design.strands) == 2
        directions = {s.domains[0].direction for s in design.strands}
        assert directions == {Direction.FORWARD, Direction.REVERSE}

        types = {s.strand_type for s in design.strands}
        assert StrandType.SCAFFOLD in types
        assert StrandType.STAPLE in types

        # Each strand has one domain spanning the helix.
        for strand in design.strands:
            assert len(strand.domains) == 1
            dom = strand.domains[0]
            assert dom.helix_id == helix.id
            assert {dom.start_bp, dom.end_bp} == {0, n_bp - 1}

        # Sequence assignments match the synthetic input (TTTT / AAAA).
        scaffold = design.scaffold()
        assert scaffold is not None
        assert scaffold.sequence == "T" * n_bp
        # Reverse strand is the antiparallel partner; its sequence reads
        # the antiparallel chain B (AAAA).
        rev = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
        assert rev.sequence == "A" * n_bp

        # A ClusterRigidTransform was created and tagged default.
        assert len(design.cluster_transforms) == 1
        cluster = design.cluster_transforms[0]
        assert cluster.name == "Test PDB"
        assert cluster.is_default is True
        assert helix.id in cluster.helix_ids

        # AtomisticModel populated; warnings is a list of strings.
        assert atomistic is not None
        assert len(atomistic.atoms) > 0
        assert isinstance(warnings, list)
        assert all(isinstance(w, str) for w in warnings)
        # The orchestrator appends an "Imported N duplex(es), M total bp."
        # marker to warnings.
        assert any("Imported" in w and "total bp" in w for w in warnings)

    def test_import_pdb_round_trip_bp_count(self, tmp_path):
        """bp count on the imported helix equals the synthetic input length."""
        n_bp = 6
        content = _synthetic_pdb_text(tmp_path, n_bp=n_bp)
        design, _atomistic, _warnings = import_pdb(content)

        total_bp = sum(h.length_bp for h in design.helices)
        assert total_bp == n_bp

    def test_import_pdb_atomistic_atoms_carry_strand_helix_ids(self, tmp_path):
        """Every atom in the AtomisticModel maps back to a helix + strand
        present in the returned Design (the per-residue mapping table that
        ``_build_pdb_atomistic`` populates is the bridge between layers)."""
        content = _synthetic_pdb_text(tmp_path, n_bp=4)
        design, atomistic, _warnings = import_pdb(content)

        helix_ids = {h.id for h in design.helices}
        strand_ids = {s.id for s in design.strands}

        # Every atom should reference a helix + strand actually in the design.
        for atom in atomistic.atoms:
            assert atom.helix_id in helix_ids
            assert atom.strand_id in strand_ids


# ── merge_pdb_into_design ────────────────────────────────────────────────────


class TestMergePdbIntoDesign:
    def test_merge_pdb_into_design_appends_to_existing(self, tmp_path):
        """Existing helices preserved; new helix(es) appended; cluster added."""
        existing = make_minimal_design(n_helices=1, helix_length_bp=42)
        n_existing_helices = len(existing.helices)
        n_existing_strands = len(existing.strands)
        existing_total_bp = sum(h.length_bp for h in existing.helices)

        n_bp_imported = 4
        content = _synthetic_pdb_text(tmp_path, n_bp=n_bp_imported)
        merged, atomistic, warnings = merge_pdb_into_design(
            existing, content, cluster_name="Merged PDB",
        )

        # Helix list grew by exactly one (single duplex).
        assert len(merged.helices) == n_existing_helices + 1
        # Strand list grew by exactly two (forward + reverse).
        assert len(merged.strands) == n_existing_strands + 2

        # Original helices unchanged (preserved at the head of the list).
        for orig, post in zip(existing.helices, merged.helices):
            assert orig.id == post.id
            assert orig.length_bp == post.length_bp

        # Total bp = original + imported.
        merged_total_bp = sum(h.length_bp for h in merged.helices)
        assert merged_total_bp == existing_total_bp + n_bp_imported

        # A new cluster_transform was appended (existing fixture had none).
        assert len(merged.cluster_transforms) == len(existing.cluster_transforms) + 1
        new_cluster = merged.cluster_transforms[-1]
        assert new_cluster.name == "Merged PDB"

        assert atomistic is not None
        assert isinstance(warnings, list)

    def test_merge_pdb_into_design_preserves_existing_strand_ids(self, tmp_path):
        """All pre-merge strand IDs survive the merge unchanged."""
        existing = make_minimal_design(n_helices=1, helix_length_bp=42)
        original_strand_ids = {s.id for s in existing.strands}

        content = _synthetic_pdb_text(tmp_path, n_bp=4)
        merged, _atomistic, _warnings = merge_pdb_into_design(existing, content)

        merged_strand_ids = {s.id for s in merged.strands}
        # Original IDs are a strict subset of the merged set.
        assert original_strand_ids.issubset(merged_strand_ids)
        # The new strands are exactly the difference (forward + reverse).
        new_ids = merged_strand_ids - original_strand_ids
        assert len(new_ids) == 2

    def test_merge_pdb_into_design_preserves_existing_helix_ids(self, tmp_path):
        """Existing helix IDs survive; new helix IDs are PDB-import flavoured."""
        existing = make_minimal_design(n_helices=2, helix_length_bp=21)
        original_helix_ids = [h.id for h in existing.helices]

        content = _synthetic_pdb_text(tmp_path, n_bp=4)
        merged, _atomistic, _warnings = merge_pdb_into_design(existing, content)

        merged_helix_ids = [h.id for h in merged.helices]
        # Originals appear at the head of the list, in order.
        assert merged_helix_ids[: len(original_helix_ids)] == original_helix_ids
        # New helix IDs follow the ``pdb_<uid>_h<idx>`` convention emitted by
        # ``import_pdb``.
        new_helix_ids = merged_helix_ids[len(original_helix_ids):]
        assert all(hid.startswith("pdb_") for hid in new_helix_ids)


# ── Sad paths ────────────────────────────────────────────────────────────────


class TestImportPdbSadPaths:
    def test_import_pdb_empty_content_raises(self):
        """No DNA residues → orchestrator raises a clear ValueError."""
        with pytest.raises(ValueError, match="No DNA residues"):
            import_pdb("")

    def test_import_pdb_no_dna_residues_raises(self):
        """A PDB with only protein/water records raises before WC detection."""
        content = (
            "ATOM      1  CA  ALA A   1      "
            "  0.000   0.000   0.000  1.00  0.00           C \n"
            "ATOM      2  CA  ALA A   2      "
            "  3.800   0.000   0.000  1.00  0.00           C \n"
            "END\n"
        )
        with pytest.raises(ValueError, match="No DNA residues"):
            import_pdb(content)

    def test_import_pdb_single_strand_raises(self, tmp_path):
        """A single-chain PDB has no Watson-Crick partner → orchestrator raises.

        ``import_pdb`` emits one of two ValueErrors here: either
        ``"No Watson-Crick base pairs detected."`` (if WC detection fails)
        or ``"No valid duplexes found"`` (if pairs are found but every
        duplex is a single-bp). Either is an acceptable rejection of a
        non-duplex input.
        """
        # Generate a 4-bp duplex PDB then strip chain B atoms from the text.
        pdb_path = tmp_path / "single_strand.pdb"
        _write_synthetic_duplex_pdb(str(pdb_path), n_bp=4)
        full = pdb_path.read_text()
        chain_a_only = "".join(
            line + "\n"
            for line in full.splitlines()
            if not (line.startswith("ATOM") and len(line) > 21 and line[21] == "B")
        )
        with pytest.raises(ValueError, match="Watson-Crick|valid duplexes"):
            import_pdb(chain_a_only)
