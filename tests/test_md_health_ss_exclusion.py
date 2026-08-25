"""Health scoring excludes deliberately single-stranded residues.

Crossover extra bases (e.g. "6hb_2xT" — unpaired thymines at every junction) and
other designed ssDNA must NOT contribute C1'/WC pairs to the NAMD health metric:
they are never Watson-Crick base-paired by design, so any geometric ss→partner
pairing is spurious and would sink the fraction once dynamics starts.

`build_c1_pairs` / `build_wc_pairs` take an `exclude_residues` set (the same
(chain, resid) keys `md_protocols.identify_unpaired_residues` produces).
`run_health_check` fills it in via `_unpaired_exclusion_set`, which calls
`identify_unpaired_residues` DIRECTLY off the reference structure's own C1'
geometry — unconditionally, not gated on whether the run used declash.

2026-08-19: it used to be gated on a declash-specific side effect (the
`{stem}_build.pdb` backup the declash rebuild leaves behind), on the theory that
only a declashed package could have unpaired residues worth excluding. That was
wrong the moment declash stopped auto-engaging ([[project_declash_reaudit]]): a
non-declash run on an extra-base design has EXACTLY the same unpaired residues —
declash is a minimisation-stage protocol choice, not a fact about the structure —
so gating on it fed 100+ genuinely single-stranded residues into the WC/C1' pair
builders on a real live run, dragging WC health down for pairs that were never
meant to exist. A fully duplex design still has no such residues, so the fix is a
no-op there — a plain design is not what these tests are about.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core import md_health as H

# ── pure: (chain, resid) key convention matches identify_unpaired_residues ─────


def test_residue_key_matches_identify_unpaired_convention():
    # identify_unpaired_residues keys as (str(segid)[-1], str(int(resid))):
    # segid "DNAA" → chain "A".
    atom = SimpleNamespace(segid="DNAA", resid=5)
    assert H._residue_key(atom) == ("A", "5")
    atom2 = SimpleNamespace(segid="I", resid=127)
    assert H._residue_key(atom2) == ("I", "127")


# ── unconditional detection: no marker file required ────────────────────────


def test_unpaired_exclusion_set_empty_on_unparseable_input(tmp_path: Path):
    # No usable PSF/PDB content ⇒ detection can't run ⇒ empty, not a crash.
    psf = tmp_path / "x.psf"
    pdb = tmp_path / "x.pdb"
    psf.write_text("")
    pdb.write_text("")
    assert H._unpaired_exclusion_set(psf, pdb) == set()


def test_unpaired_exclusion_set_swallows_errors(tmp_path: Path):
    # Garbage files ⇒ never raise, just return empty — no marker file involved.
    pdb = tmp_path / "x.pdb"
    psf = tmp_path / "x.psf"
    pdb.write_text("garbage")
    psf.write_text("garbage")
    assert H._unpaired_exclusion_set(psf, pdb) == set()


# A(THY)/B(ADE) 10.5 Å apart ⇒ paired (within _C1_NO_PARTNER_ANG). D(THY, ssDNA)
# sits 100 Å away — no cross-segment C1' neighbour within the 11 Å search ball at
# all, so identify_unpaired_residues finds it unconditionally, straight off the
# geometry, with no {stem}_build.pdb marker anywhere on disk.
_ISOLATED_PSF = """PSF

       1 !NTITLE
 REMARKS test

       3 !NATOM
       1 A        1        THY  C1'  CN7B   0.000000       12.0107           0
       2 B        1        ADE  C1'  CN7B   0.000000       12.0107           0
       3 D        1        THY  C1'  CN7B   0.000000       12.0107           0

       0 !NBOND: bonds

"""

_ISOLATED_PDB = """ATOM      1  C1' THY A   1       0.000   0.000   0.000  1.00  0.00      A
ATOM      2  C1' ADE B   1      10.500   0.000   0.000  1.00  0.00      B
ATOM      3  C1' THY D   1     100.000 100.000 100.000  1.00  0.00      D
END
"""


def test_unpaired_exclusion_set_finds_a_genuinely_isolated_residue_with_no_marker(
    tmp_path: Path,
):
    pytest.importorskip("MDAnalysis")
    psf = tmp_path / "iso.psf"
    pdb = tmp_path / "iso.pdb"
    psf.write_text(_ISOLATED_PSF)
    pdb.write_text(_ISOLATED_PDB)
    assert not (tmp_path / "iso_build.pdb").exists()  # no declash marker present
    assert H._unpaired_exclusion_set(psf, pdb) == {("D", "1")}


# ── behavioral: a spurious ss pair is dropped, the real duplex pair restored ───

_PSF = """PSF

       1 !NTITLE
 REMARKS test

       6 !NATOM
       1 A        1        THY  C1'  CN7B   0.000000       12.0107           0
       2 A        1        THY  N3   NN2U   0.000000       14.0067           0
       3 B        1        ADE  C1'  CN7B   0.000000       12.0107           0
       4 B        1        ADE  N1   NN3A   0.000000       14.0067           0
       5 C        1        THY  C1'  CN7B   0.000000       12.0107           0
       6 C        1        THY  N3   NN2U   0.000000       14.0067           0

       0 !NBOND: bonds

"""

# A(THY) at origin, B(ADE) 10.5 Å away, C(THY, the ssDNA) 9.0 Å from B (shortest).
# Candidates: B–C (9.0, spurious ss) and A–B (10.5, real duplex); A–C is >13 Å.
_PDB = """ATOM      1  C1' THY A   1       0.000   0.000   0.000  1.00  0.00      A
ATOM      2  N3  THY A   1       1.400   0.000   0.000  1.00  0.00      A
ATOM      3  C1' ADE B   1      10.500   0.000   0.000  1.00  0.00      B
ATOM      4  N1  ADE B   1       9.100   0.000   0.000  1.00  0.00      B
ATOM      5  C1' THY C   1      10.500   9.000   0.000  1.00  0.00      C
ATOM      6  N3  THY C   1       9.100   9.000   0.000  1.00  0.00      C
END
"""


@pytest.fixture()
def mini_ref(tmp_path: Path) -> tuple[Path, Path]:
    pytest.importorskip("MDAnalysis")
    psf = tmp_path / "t.psf"
    pdb = tmp_path / "t.pdb"
    psf.write_text(_PSF)
    pdb.write_text(_PDB)
    return psf, pdb


def test_build_wc_pairs_without_exclusion_forms_the_spurious_ss_pair(mini_ref):
    psf, pdb = mini_ref
    pairs = H.build_wc_pairs(psf, pdb)
    segs = {p.res_a.split(":")[0] for p in pairs} | {
        p.res_b.split(":")[0] for p in pairs
    }
    # The shortest candidate B–C wins, so the ssDNA residue C is (wrongly) paired.
    assert "C" in segs


def test_build_wc_pairs_excludes_ssdna_and_restores_real_pair(mini_ref):
    psf, pdb = mini_ref
    pairs = H.build_wc_pairs(psf, pdb, exclude_residues={("C", "1")})
    segs = {p.res_a.split(":")[0] for p in pairs} | {
        p.res_b.split(":")[0] for p in pairs
    }
    assert "C" not in segs  # ssDNA no longer contributes a pair
    assert {"A", "B"} <= segs  # and the genuine A–B duplex pair is scored


def test_build_c1_pairs_exclusion_drops_the_ss_residue(mini_ref):
    psf, pdb = mini_ref
    # C1' selection order is A, B, C → selection index 2 is the ssDNA residue.
    incl = H.build_c1_pairs(psf, pdb)
    assert 2 in set(incl.pi.tolist()) | set(incl.pj.tolist())
    excl = H.build_c1_pairs(psf, pdb, exclude_residues={("C", "1")})
    assert 2 not in set(excl.pi.tolist()) | set(excl.pj.tolist())


def test_topology_pair_sidecar_overrides_closer_spurious_geometry(mini_ref):
    """The authored A-B duplex wins even though geometric B-C is shorter."""
    psf, pdb = mini_ref
    H._wc_pair_sidecar_path(psf.parent, psf.stem).write_text(
        '{"schema":"nadoc.wc_pairs.v1","pairs":[{"a":["A","1"],"b":["B","1"]}]}'
    )
    wc = H.build_wc_pairs(psf, pdb)
    assert [(p.res_a.split(":")[0], p.res_b.split(":")[0]) for p in wc] == [
        ("A", "B")
    ]
    c1 = H.build_c1_pairs(psf, pdb)
    selected = {0, 1}
    assert set(c1.pi.tolist()) | set(c1.pj.tolist()) == selected


def test_package_registry_authors_pairs_and_all_intentional_ssdna(mini_ref):
    from backend.core.md_protocols import _persist_topology_health_registry

    psf, _pdb = mini_ref
    atoms = [
        SimpleNamespace(
            residue="THY", chain_id="A", seq_num=1, helix_id="h0", bp_index=1,
            direction="FORWARD", copy_k=0, crossover_id=None, extension_id=None,
        ),
        SimpleNamespace(
            residue="ADE", chain_id="B", seq_num=1, helix_id="h0", bp_index=1,
            direction="REVERSE", copy_k=0, crossover_id=None, extension_id=None,
        ),
        SimpleNamespace(
            residue="THY", chain_id="C", seq_num=1, helix_id="h0", bp_index=2,
            direction="FORWARD", copy_k=0, crossover_id=None, extension_id=None,
        ),
    ]
    model = SimpleNamespace(atoms=atoms)
    ss = _persist_topology_health_registry(model, psf, sort_chains=False)
    assert ss == {("C", "1")}
    assert H.read_topology_wc_sidecar(psf.parent, psf.stem) == [
        (("A", "1"), ("B", "1"))
    ]
