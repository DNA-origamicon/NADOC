"""Part B (MD) — proteins in all-atom NAMD/GROMACS.

Covers: protein atoms appended to the atomistic model (B1), the Cα elastic
network + click linker extraBonds (B3), and the psfgen protein-segment + namd.conf
wiring (B2).
"""

import numpy as np
import pytest

from backend.core.models import (
    ProteinAsset,
    ProteinAtom,
    ProteinAttachment,
    ProteinTargetFree,
)
from tests.conftest import make_6hb_design


# ── fixtures ────────────────────────────────────────────────────────────────


def _sequence(design):
    for s in design.strands:
        n = sum(abs(dom.end_bp - dom.start_bp) + 1 for dom in s.domains)
        s.sequence = ("ACGT" * (n // 4 + 1))[:n]
    return design


def _ca_asset(n_res=4, spacing_nm=0.38, x0=2.0):
    """A protein of *n_res* Cα-only residues on a straight line (one chain)."""
    atoms = [
        ProteinAtom(
            serial=i,
            name="CA",
            element="C",
            res_name="ALA",
            chain_id="A",
            res_seq=i + 1,
            x=x0 + spacing_nm * i,
            y=2.0,
            z=2.0,
        )
        for i in range(n_res)
    ]
    return ProteinAsset(
        name="p",
        atoms=atoms,
        center_of_mass=[x0 + spacing_nm * (n_res - 1) / 2, 2.0, 2.0],
    )


def _free_protein_design(n_res=4, spacing_nm=0.38):
    d = _sequence(make_6hb_design())
    asset = _ca_asset(n_res, spacing_nm)
    d.protein_assets = [asset]
    d.protein_attachments = [
        ProteinAttachment(asset_id=asset.id, target=ProteinTargetFree())
    ]
    return d, asset


# ── B1: atomistic model append ─────────────────────────────────────────────


def test_proteins_excluded_by_default():
    d, _ = _free_protein_design()
    from backend.core.atomistic import build_atomistic_model

    m = build_atomistic_model(d)
    assert not any(a.helix_id.startswith("__protein__") for a in m.atoms)


def test_protein_atoms_appended_with_chain_and_count():
    d, asset = _free_protein_design(n_res=5)
    from backend.core.atomistic import build_atomistic_model

    dna = build_atomistic_model(d)
    full = build_atomistic_model(d, include_proteins=True)
    prot = [a for a in full.atoms if a.helix_id.startswith("__protein__")]
    assert len(full.atoms) - len(dna.atoms) == len(asset.atoms) == len(prot)
    # distinct protein chain id (not a DNA chain), CHARMM-ready residue/atom names
    assert all(a.chain_id.startswith("P") for a in prot)
    assert prot[0].residue == "ALA" and prot[0].name == "CA"
    # serials continue past the DNA atoms (no overlap)
    assert prot[0].serial == len(dna.atoms)


def test_protein_atoms_world_placed_by_pose():
    """A free protein with a translated pose moves its atoms by exactly that delta."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.protein import gizmo_move_to_pose

    d, asset = _free_protein_design(n_res=3)
    base = build_atomistic_model(d, include_proteins=True)
    base_prot = [a for a in base.atoms if a.helix_id.startswith("__protein__")]
    # default pose == identity → atoms sit at PDB coords
    assert base_prot[0].x == pytest.approx(asset.atoms[0].x)

    pose = gizmo_move_to_pose(
        np.eye(4), pivot=[0, 0, 0], translation=[1.0, 0.0, 0.0], rotation=[0, 0, 0, 1]
    )
    d.protein_attachments[0].pose = type(d.protein_attachments[0].pose).from_array(pose)
    moved = build_atomistic_model(d, include_proteins=True)
    moved_prot = [a for a in moved.atoms if a.helix_id.startswith("__protein__")]
    assert moved_prot[0].x == pytest.approx(base_prot[0].x + 1.0)
    assert moved_prot[0].y == pytest.approx(base_prot[0].y)


def test_two_attachments_get_distinct_chains():
    d, asset = _free_protein_design(n_res=3)
    d.protein_attachments.append(
        ProteinAttachment(asset_id=asset.id, target=ProteinTargetFree())
    )
    from backend.core.atomistic import build_atomistic_model

    prot = [
        a
        for a in build_atomistic_model(d, include_proteins=True).atoms
        if a.helix_id.startswith("__protein__")
    ]
    chains = {a.chain_id for a in prot}
    sentinels = {a.helix_id for a in prot}
    assert len(chains) == 2 and len(sentinels) == 2  # PA + PB, two sentinels


# ── B3: Cα elastic network + click linker ──────────────────────────────────


def test_ca_enm_pairs_within_cutoff_symmetric_and_reflengths():
    from backend.core.protein_enm import ca_enm_pairs
    from backend.core.atomistic import build_atomistic_model

    d, _ = _free_protein_design(n_res=4, spacing_nm=0.38)  # 3.8 Å spacing
    prot = [
        a
        for a in build_atomistic_model(d, include_proteins=True).atoms
        if a.helix_id.startswith("__protein__")
    ]
    pairs = ca_enm_pairs(prot, cutoff_ang=12.0)
    # 4 beads, all pairwise distances (3.8, 7.6, 11.4) ≤ 12 → C(4,2) = 6
    assert len(pairs) == 6
    # symmetric: each unordered pair appears once; reference lengths = separation
    by_gap = {
        (j - i): r0
        for (si, sj, r0), (i, j) in zip(
            pairs, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        )
    }
    assert by_gap[1] == pytest.approx(3.8, abs=1e-3)
    assert by_gap[2] == pytest.approx(7.6, abs=1e-3)
    assert by_gap[3] == pytest.approx(11.4, abs=1e-3)


def test_enm_excludes_pairs_beyond_cutoff():
    from backend.core.protein_enm import ca_enm_pairs
    from backend.core.atomistic import build_atomistic_model

    d, _ = _free_protein_design(n_res=4, spacing_nm=0.5)  # 5 Å spacing → (0,3)=15 Å
    prot = [
        a
        for a in build_atomistic_model(d, include_proteins=True).atoms
        if a.helix_id.startswith("__protein__")
    ]
    pairs = ca_enm_pairs(prot, cutoff_ang=12.0)
    # 5, 10 ≤ 12 ; 15 excluded → pairs (0,1)(1,2)(2,3)=5 each + (0,2)(1,3)=10 each = 5 pairs
    assert len(pairs) == 5
    assert all(r0 <= 12.0 for *_, r0 in pairs)


def test_extrabonds_text_format_k_then_b0_zero_based():
    from backend.core.protein_enm import ExtraBond, extrabonds_text

    txt = extrabonds_text([ExtraBond(i=3, j=7, k=10.0, b0_ang=4.2)])
    line = [ln for ln in txt.splitlines() if ln.startswith("bond ")][0]
    # NAMD order: bond <i> <j> <k> <b0>
    assert line.split() == ["bond", "3", "7", "10.0000", "4.2000"]


def test_build_extrabonds_empty_for_dna_only():
    from backend.core.protein_enm import build_protein_extrabonds

    assert build_protein_extrabonds(_sequence(make_6hb_design())) == ""


def test_click_linker_connects_conjugation_atom_to_dna_handle(monkeypatch):
    """The linker extraBond joins the conjugation atom's model serial to the
    DNA handle-terminus backbone atom, resolved via the SHARED binder mapping."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core import protein_enm
    from backend.core.models import ProteinTargetDesign

    d, asset = _free_protein_design(n_res=4)
    # turn the free protein into an overhang-targeted (conjugated) one
    att = d.protein_attachments[0]
    att.target = ProteinTargetDesign(overhang_id="ov", attach_end="free_end")
    att.conjugation_atom_serial = asset.atoms[0].serial  # first CA = conjugation atom

    model = build_atomistic_model(d, include_proteins=True)
    # pick a real DNA nucleotide present in the model as the (mocked) handle terminus
    dna = next(
        a
        for a in model.atoms
        if not a.helix_id.startswith("__protein__") and a.name == "P"
    )
    nuc_key = (dna.helix_id, dna.bp_index, dna.direction)
    monkeypatch.setattr(protein_enm, "_geometry_for_design", None, raising=False)
    import backend.physics.oxdna_protein as oxp

    monkeypatch.setattr(oxp, "binder_terminus_nuc_key", lambda *a, **k: nuc_key)

    bonds = protein_enm.linker_extra_bonds(d, model, geometry=[])
    assert len(bonds) == 1
    b = bonds[0]
    # conjugation atom is the first protein atom (serial == first protein serial)
    conj = next(a for a in model.atoms if a.helix_id.startswith("__protein__"))
    assert {b.i, b.j} == {conj.serial, dna.serial}
    assert b.b0_ang > 0


# ── B2: protein FF files, namd.conf wiring, psfgen segment ──────────────────


def test_protein_forcefield_files_present():
    import backend.core.namd_package as nm

    for f in nm._PROTEIN_FF_FILES:
        assert (nm._FF_DIR / f).exists(), f


def test_namd_conf_adds_protein_params_and_extrabonds():
    from backend.core.namd_helpers import _render_namd_conf

    with_p = _render_namd_conf("x", has_protein=True)
    without = _render_namd_conf("x", has_protein=False)
    assert "par_all36m_prot.prm" in with_p and "extraBonds         on" in with_p
    assert "par_all36m_prot.prm" not in without and "extraBonds" not in without


def test_psfgen_script_marks_protein_segment_without_dna_patches():
    import tempfile
    from pathlib import Path
    from backend.core.atomistic import build_atomistic_model
    from backend.core.namd_topology import _write_segment_pdbs, _psfgen_script

    d, _ = _free_protein_design(n_res=3)
    model = build_atomistic_model(d, include_proteins=True)
    with tempfile.TemporaryDirectory() as t:
        segs, _ = _write_segment_pdbs(d, Path(t), model)
        prot = [s for s in segs if s.get("is_protein")]
        assert len(prot) == 1 and prot[0]["segid"].startswith("P")
        script = _psfgen_script(segs, Path(t) / "out")
    assert "top_all36_prot" in script
    assert "first NTER" in script and "last CTER" in script
    # the protein segment must NOT receive DNA deoxyribose patches
    assert f"patch DEOX {prot[0]['segid']}" not in script
    assert f"patch DEO5 {prot[0]['segid']}" not in script


def _has_psfgen():
    try:
        from backend.core.namd_topology import find_psfgen

        find_psfgen()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_psfgen(), reason="psfgen not installed")
def test_psfgen_builds_protein_plus_dna_topology():
    """psfgen produces a combined DNA+protein PSF that passes the charge audit."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.namd_topology import build_charmm_psfgen_topology

    d = _sequence(make_6hb_design())
    # a real tri-peptide backbone (N, CA, C, O per residue) so psfgen has residues
    atoms, serial = [], 1
    for i, rn in enumerate(["ALA", "GLY", "SER"]):
        for nm, el, dx in [
            ("N", "N", 0.0),
            ("CA", "C", 0.13),
            ("C", "C", 0.25),
            ("O", "O", 0.30),
        ]:
            atoms.append(
                ProteinAtom(
                    serial=serial,
                    name=nm,
                    element=el,
                    res_name=rn,
                    chain_id="A",
                    res_seq=i + 1,
                    x=2.0 + 0.38 * i + dx,
                    y=2.0 + (0.05 if nm == "O" else 0.0),
                    z=2.0,
                )
            )
            serial += 1
    asset = ProteinAsset(name="p", atoms=atoms, center_of_mass=[2.5, 2.0, 2.0])
    d.protein_assets = [asset]
    d.protein_attachments = [
        ProteinAttachment(asset_id=asset.id, target=ProteinTargetFree())
    ]

    model = build_atomistic_model(d, include_proteins=True)
    prot_segids = []
    import tempfile
    from pathlib import Path
    from backend.core.namd_topology import _write_segment_pdbs

    with tempfile.TemporaryDirectory() as t:
        segs, _ = _write_segment_pdbs(d, Path(t), model)
        prot_segids = [s["segid"] for s in segs if s.get("is_protein")]

    build = build_charmm_psfgen_topology(d)
    assert build.metadata["audit"]["passed"]
    # the protein segment landed in the PSF (psfgen added its hydrogens too)
    assert any(seg in build.psf_text for seg in prot_segids)
