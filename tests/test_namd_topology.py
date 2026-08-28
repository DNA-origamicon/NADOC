from __future__ import annotations

import pytest

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.md_charge import audit_psf
from backend.core.namd_topology import (
    _ATOM_TO_CHARMM,
    _RESNAME_TO_CHARMM,
    _psfgen_pdb_record,
    _psfgen_script,
    _psfgen_segid,
    _write_segment_pdbs,
    build_charmm_psfgen_topology,
    find_psfgen,
)


def _has_psfgen() -> bool:
    try:
        find_psfgen()
    except RuntimeError:
        return False
    return True


def test_psfgen_name_maps_cover_nadoc_dna_names() -> None:
    assert _RESNAME_TO_CHARMM == {
        "DA": "ADE",
        "DC": "CYT",
        "DG": "GUA",
        "DT": "THY",
    }
    assert _ATOM_TO_CHARMM["OP1"] == "O1P"
    assert _ATOM_TO_CHARMM["OP2"] == "O2P"
    assert _ATOM_TO_CHARMM["C7"] == "C5M"


def test_psfgen_script_applies_auto_namd_style_deoxy_patches(tmp_path) -> None:
    script = _psfgen_script(
        [
            {
                "segid": "DNAA",
                "path": tmp_path / "DNAA.pdb",
                "first_resid": 1,
                "last_resid": 3,
            }
        ],
        tmp_path / "out",
    )

    assert "segment DNAA" in script
    assert "first 5TER" in script
    assert "last 3TER" in script
    assert "patch DEO5 DNAA:1" in script
    assert "patch DEOX DNAA:2" in script
    assert "patch DEOX DNAA:3" in script
    assert "guesscoord" in script
    assert "writepsf" in script


@pytest.mark.skipif(
    not _has_psfgen(),
    reason="psfgen is not installed",
)
def test_charmm_psfgen_topology_builds_hydrogenated_neutral_small_design() -> None:
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design(
        cells=[(0, 0)],
        length_bp=4,
        name="psfgen_smoke",
        strand_filter="scaffold",
    )

    built = build_charmm_psfgen_topology(design)
    audit = audit_psf(
        built.psf_text,
        require_dna_hydrogens=True,
        require_dna_residue_charge=True,
    )

    assert audit.passed
    assert audit.dna_hydrogens > 0
    assert audit.dna_residues == 4
    # First (and only) chain gets the unique psfgen segname D000.
    assert "REMARKS segment D000" in built.psf_text


# ── Regression: many-chain designs (segid collision + serial overflow) ─────────
# A 3x6 square design has 66 strands and >100k atoms.  Two bugs broke its
# equilibrium-aware / NAMD-seed psfgen build:
#   (1) `_psf_segid(chain_id)[:4]` collapsed many chains onto the same segname
#       (A/AA/AB → "DNAA"), overwriting the shared PDB + emitting duplicate
#       `segment` blocks → psfgen "no residue N" FATAL.
#   (2) the global PDB serial passed 99999 mid-file → 6-digit serials shifted the
#       resid column → psfgen read the wrong resids.


def test_psfgen_segid_unique_and_four_chars() -> None:
    """Every chain index maps to a distinct 4-char psfgen segname (no collisions
    up to far more chains than any real design)."""
    ids = [_psfgen_segid(i) for i in range(2000)]
    assert len(set(ids)) == len(ids)  # all unique
    assert all(len(s) == 4 for s in ids)  # psfgen segname width
    assert ids[0] == "D000"
    assert ids[40] == "D014"  # the chain that used to FATAL


def test_design_strand_segids_follow_builder_chain_sort() -> None:
    """Design order and PSF segment order diverge after strand Z."""
    from backend.core.namd_topology import psfgen_dna_segids_for_design

    segids = psfgen_dna_segids_for_design(40)
    assert segids[0] == "D000"  # A is first in both orders
    assert segids[26] == "D001"  # AA sorts immediately after A
    assert segids[1] == "D00F"  # B follows AA..AN in a 40-strand design
    assert len(set(segids)) == 40
    assert all(len(segid) == 4 for segid in segids)


def test_psfgen_pdb_record_serial_stays_five_wide_past_100k() -> None:
    """A serial > 99999 must stay in a 5-char field (hybrid-36) so the resid
    column never shifts."""
    atom = Atom(
        serial=0,
        name="P",
        element="P",
        residue="DA",
        chain_id="A",
        seq_num=37,
        x=1.0,
        y=2.0,
        z=3.0,
        strand_id="s",
        helix_id="h",
        bp_index=0,
        direction="FORWARD",
    )
    rec = _psfgen_pdb_record(atom, 123456, "D014")
    assert rec.startswith("ATOM  ")
    assert len(rec[6:11]) == 5  # serial field exactly 5 chars
    assert rec[11] == " "  # column not shifted
    # resid still parses to seq_num at the fixed hybrid-36 column.
    assert rec[22:26].strip() == "37"


def _alpha_chain_id(i: int) -> str:
    """Excel-style A, B, …, Z, AA, AB, … — distinct alphabetic chain ids,
    including the 2-char ids that triggered the old [:4] segid collision."""
    s, i = "", i + 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _fake_many_chain_model(n_chains: int = 40, n_res: int = 50) -> AtomisticModel:
    """Synthetic many-chain model (distinct chain ids), 2 atoms/residue."""
    atoms: list[Atom] = []
    serial = 0
    for ci in range(n_chains):
        chain_id = _alpha_chain_id(ci)
        for r in range(1, n_res + 1):
            for nm in ("P", "C1'"):
                atoms.append(
                    Atom(
                        serial=serial,
                        name=nm,
                        element="P" if nm == "P" else "C",
                        residue="DA",
                        chain_id=chain_id,
                        seq_num=r,
                        x=0.1 * r,
                        y=0.0,
                        z=0.0,
                        strand_id=f"s{ci}",
                        helix_id="h",
                        bp_index=r,
                        direction="FORWARD",
                    )
                )
                serial += 1
    return AtomisticModel(atoms=atoms, bonds=[])


def test_write_segment_pdbs_unique_segids_and_aligned_resids(tmp_path) -> None:
    """Many chains → unique segids, and every per-segment PDB's resid column lines
    up with the segment's patch range (no shift, no collision).  (The >99999-serial
    column-shift itself is pinned by the record-level test above.)"""
    model = _fake_many_chain_model()
    segs, _ = _write_segment_pdbs(None, tmp_path, model)
    segids = [s["segid"] for s in segs]
    assert len(set(segids)) == len(segids)  # FIX 1: no collisions
    assert len(segids) == 40

    # FIX 2 (column alignment): each segment file's DEOX patch range ⊆ resids
    # actually written at the fixed hybrid-36 resid column.
    for s in segs:
        resids = set()
        for ln in s["path"].read_text().splitlines():
            if ln.startswith("ATOM"):
                resids.add(ln[22:26].strip())
        patch_targets = {str(r) for r in range(s["first_resid"], s["last_resid"] + 1)}
        assert patch_targets <= resids, f"{s['segid']}: patch range escapes PDB resids"


# ── crossover extra bases thread inline in the psfgen residue numbering ────────
#   psfgen bonds residues in seq_num order.  _build_extra_base_atoms appends the
#   inserts at the END of each chain's range; without _thread_inserts_inline
#   psfgen would bond the last insert of one crossover to the first insert of the
#   NEXT (a 50 Å junk O3'→P bond) instead of prev_real → eb → eb → next_real.


def _routed_6hb_with_extra(sequence="TT"):
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.models import LatticeType
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple()
        d = design_state.get_or_404().model_copy(deep=True)
    for x in d.crossovers:
        x.extra_bases = sequence
    return d


def test_extra_bases_thread_inline_in_seq_num() -> None:
    """Every insert sits immediately after its source-flank nucleotide in the
    chain's seq_num order (insert.seq_num == flank.seq_num + k + 1), NOT clustered
    at the chain tail.  Can-go-red: without _thread_inserts_inline the inserts
    keep their end-appended seq_num far past every real residue."""

    from backend.core.atomistic import build_atomistic_model

    design = _routed_6hb_with_extra("TT")
    model = build_atomistic_model(design)

    # (chain, helix, bp, dir) → seq_num for the real (non-insert) residues.
    real_seq: dict[tuple, int] = {}
    inserts: list = []
    for a in model.atoms:
        if getattr(a, "crossover_id", None) is not None:
            inserts.append(a)
        else:
            real_seq[(a.chain_id, a.helix_id, a.bp_index, a.direction)] = a.seq_num
    assert inserts, "design should have extra-base inserts"

    # Collapse to one entry per insert residue.
    by_res: dict[tuple, "object"] = {}
    for a in inserts:
        by_res.setdefault((a.chain_id, a.crossover_id, a.extra_base_k), a)

    checked = 0
    for (chain, _xo, k), a in by_res.items():
        flank = real_seq.get((chain, a.helix_id, a.bp_index, a.direction))
        if flank is None:  # ambiguous flank (looped helix) — left at tail by design
            continue
        assert a.seq_num == flank + k + 1, (
            f"insert k={k} at seq {a.seq_num} not inline after flank seq {flank}"
        )
        checked += 1
    assert checked > 1, "expected several inline-threaded inserts to verify"


@pytest.mark.skipif(not _has_psfgen(), reason="psfgen is not installed")
def test_extra_base_junction_backbone_bonds_are_sane(tmp_path) -> None:
    """A full CHARMM psfgen topology has no cross-crossover junk bond.

    Can-go-red: without inline threading the inserts bond across crossovers, producing
    tens-of-angstrom O3'→P bonds. The ideal pre-minimisation geometry can reach 3.8 Å
    at inserted junctions, so this topology test uses a 5 Å continuity ceiling rather
    than pretending to validate relaxed bond geometry. Guards the whole seq_num →
    psfgen connectivity chain without changing insert placement.
    """
    import numpy as np

    from backend.core.atomistic import build_atomistic_model

    design = _routed_6hb_with_extra("TT")
    model = build_atomistic_model(design)
    build = build_charmm_psfgen_topology(design, atomistic_model=model)
    assert build.metadata["audit"]["passed"]

    mda = pytest.importorskip("MDAnalysis")
    import warnings

    (tmp_path / "t.psf").write_text(build.psf_text)
    (tmp_path / "t.pdb").write_text(build.pdb_text)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u = mda.Universe(str(tmp_path / "t.psf"), str(tmp_path / "t.pdb"))
        lengths = np.asarray(u.bonds.bonds())
    assert lengths.max() < 5.0, (
        f"a bond spans {lengths.max():.1f} Å — extra-base inserts may not be threaded "
        "inline in the psfgen residue order"
    )


def test_extra_base_segid_resids_maps_extra_bases_by_ordinal(tmp_path):
    """extra_base_segid_resids maps model crossover_id-tagged residues to the PSF's
    (segid, resid) by ORDINAL — the robust bridge, since extra bases are unmarked THY
    residues in the final PSF and geometric ss-detection misses crossover-sandwiched ones."""
    from types import SimpleNamespace as NS

    from backend.core.namd_topology import extra_base_segid_resids

    # chains sorted A,B; chain A residue 2 is an extra base (ordinal 1)
    model = NS(
        atoms=[
            NS(chain_id="A", seq_num=1, crossover_id=None),
            NS(chain_id="A", seq_num=2, crossover_id="xo1"),
            NS(chain_id="A", seq_num=3, crossover_id=None),
            NS(chain_id="B", seq_num=1, crossover_id=None),
        ]
    )
    psf = tmp_path / "t.psf"
    psf.write_text(
        "\n".join(
            [
                "       4 !NATOM",
                "       1 D000     1        THY  C1'  CN7   0.0   12.0   0",
                "       2 D000     2        THY  C1'  CN7   0.0   12.0   0",
                "       3 D000     3        ADE  C1'  CN7   0.0   12.0   0",
                "       4 D001     1        CYT  C1'  CN7   0.0   12.0   0",
                "       0 !NBOND: bonds",
            ]
        )
        + "\n"
    )
    assert extra_base_segid_resids(model, psf) == {("D000", "2")}


def test_extra_base_segid_resids_empty_without_extra_bases(tmp_path):
    from types import SimpleNamespace as NS

    from backend.core.namd_topology import extra_base_segid_resids

    model = NS(atoms=[NS(chain_id="A", seq_num=1, crossover_id=None)])
    psf = tmp_path / "t.psf"
    psf.write_text(
        "       1 !NATOM\n       1 D000 1 THY C1' CN7 0.0 12.0 0\n       0 !NBOND\n"
    )
    assert extra_base_segid_resids(model, psf) == set()
