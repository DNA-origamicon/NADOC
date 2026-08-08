"""Unit tests for backend.core.protein_cg — per-residue Cα beads + ANM springs."""

import numpy as np

from backend.core.models import (
    Mat4x4,
    ProteinAsset,
    ProteinAtom,
    ProteinAttachment,
    ProteinTargetFree,
)
from backend.core.protein_cg import (
    AA_3TO1,
    aa_one_letter,
    anm_springs,
    conjugation_bead_index,
    protein_beads,
)


def _atom(serial, name, res_name, chain, res_seq, x, y, z, element="C"):
    return ProteinAtom(
        serial=serial,
        name=name,
        element=element,
        res_name=res_name,
        chain_id=chain,
        res_seq=res_seq,
        x=x,
        y=y,
        z=z,
    )


def _asset(atoms, conj=None):
    return ProteinAsset(
        name="t",
        atoms=atoms,
        center_of_mass=[0.0, 0.0, 0.0],
        default_conjugation_atom_serial=conj,
    )


def _three_residue_two_chain():
    # Chain A: res 1 (ALA) Cα at x=0, res 2 (CYS) Cα at x=0.5; Chain B: res 1 (GLY) Cα at x=5.
    atoms = [
        _atom(1, "N", "ALA", "A", 1, -0.1, 0, 0, "N"),
        _atom(2, "CA", "ALA", "A", 1, 0.0, 0, 0),
        _atom(3, "CA", "CYS", "A", 2, 0.5, 0, 0),
        _atom(4, "SG", "CYS", "A", 2, 0.6, 0, 0, "S"),
        _atom(5, "CA", "GLY", "B", 1, 5.0, 0, 0),
    ]
    return _asset(atoms)


def test_aa_one_letter_canonical_and_variant_and_unknown():
    assert aa_one_letter("ALA") == "A"
    assert aa_one_letter("HSD") == "H"  # CHARMM histidine variant
    assert aa_one_letter("CYX") == "C"  # disulfide cysteine
    assert aa_one_letter("UNK") == "G"  # unknown → glycine fallback
    assert all(len(v) == 1 for v in AA_3TO1.values())


def test_one_bead_per_residue_at_ca():
    asset = _three_residue_two_chain()
    beads = protein_beads(asset)
    assert len(beads) == 3  # 3 residues, NOT 5 atoms
    assert [b.aa for b in beads] == ["A", "C", "G"]
    # bead position is the Cα, not the residue centroid
    assert np.allclose(beads[0].pos_nm, [0.0, 0.0, 0.0])
    assert np.allclose(beads[1].pos_nm, [0.5, 0.0, 0.0])
    assert np.allclose(beads[2].pos_nm, [5.0, 0.0, 0.0])


def test_prev_index_resets_at_chain_boundary():
    beads = protein_beads(_three_residue_two_chain())
    assert beads[0].prev_index == -1  # chain A start
    assert beads[1].prev_index == 0  # within chain A
    assert beads[2].prev_index == -1  # chain B start (NOT 1)


def test_bead_fallback_to_centroid_when_no_ca():
    # A residue with no CA → centroid of its heavy atoms.
    atoms = [
        _atom(1, "N", "ALA", "A", 1, 0.0, 0, 0, "N"),
        _atom(2, "CB", "ALA", "A", 1, 2.0, 0, 0),
    ]
    beads = protein_beads(_asset(atoms))
    assert len(beads) == 1
    assert np.allclose(beads[0].pos_nm, [1.0, 0.0, 0.0])  # mean of N and CB


def test_conjugation_bead_flagged_by_residue():
    # Conjugation atom = the CYS SG (serial 4) → its residue (bead index 1).
    asset = _three_residue_two_chain()
    asset.default_conjugation_atom_serial = 4
    att = ProteinAttachment(
        asset_id=asset.id, target=ProteinTargetFree(), conjugation_atom_serial=4
    )
    beads = protein_beads(asset, att)
    assert conjugation_bead_index(beads) == 1
    assert beads[1].is_conjugation and not beads[0].is_conjugation


def test_world_pose_translates_beads():
    asset = _three_residue_two_chain()
    pose = np.eye(4)
    pose[1, 3] = 7.0  # translate +7 nm in y
    att = ProteinAttachment(
        asset_id=asset.id, target=ProteinTargetFree(), pose=Mat4x4.from_array(pose)
    )
    beads = protein_beads(asset, att)
    assert np.allclose(beads[0].pos_nm, [0.0, 7.0, 0.0])
    assert np.allclose(beads[2].pos_nm, [5.0, 7.0, 0.0])


def test_anm_springs_respect_cutoff_and_ordering():
    beads = protein_beads(_three_residue_two_chain())
    # cutoff 1.5 nm: A0–A1 (0.5 nm) bonded; B (5 nm away) isolated.
    springs = anm_springs(beads, cutoff_nm=1.5)
    pairs = {(s.i, s.j) for s in springs}
    assert pairs == {(0, 1)}
    assert all(s.j > s.i for s in springs)
    assert abs(springs[0].r0_nm - 0.5) < 1e-9


def test_anm_springs_larger_cutoff_connects_all():
    beads = protein_beads(_three_residue_two_chain())
    springs = anm_springs(beads, cutoff_nm=6.0)  # now reaches chain B
    assert {(s.i, s.j) for s in springs} == {(0, 1), (0, 2), (1, 2)}


def test_anm_springs_empty_for_single_bead():
    atoms = [_atom(1, "CA", "ALA", "A", 1, 0, 0, 0)]
    assert anm_springs(protein_beads(_asset(atoms))) == []
