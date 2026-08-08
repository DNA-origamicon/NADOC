"""Health scoring excludes deliberately single-stranded residues.

Crossover extra bases (e.g. "6hb_2xT" — unpaired thymines at every junction) and
other designed ssDNA must NOT contribute C1'/WC pairs to the NAMD health metric:
they are never Watson-Crick base-paired by design, so any geometric ss→partner
pairing is spurious and would sink the fraction once dynamics starts.

`build_c1_pairs` / `build_wc_pairs` take an `exclude_residues` set (the same
(chain, resid) keys `md_protocols.identify_unpaired_residues` produces, which the
declash protocol already excludes from the ENM). `run_health_check` fills it in
only for declashed / extra-base designs (detected by the `{stem}_build.pdb`
backup), so fully-duplex designs are byte-identical to before.
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


# ── gating: exclusion only for declashed / extra-base designs ──────────────────


def test_unpaired_exclusion_set_empty_without_declash_marker(tmp_path: Path):
    # No {stem}_build.pdb backup ⇒ not a declashed design ⇒ empty (zero change).
    psf = tmp_path / "x.psf"
    pdb = tmp_path / "x.pdb"
    psf.write_text("")
    pdb.write_text("")
    assert H._unpaired_exclusion_set(psf, pdb) == set()


def test_unpaired_exclusion_set_swallows_errors(tmp_path: Path):
    # Marker present but files are unreadable ⇒ never raise, just return empty.
    pdb = tmp_path / "x.pdb"
    psf = tmp_path / "x.psf"
    pdb.write_text("garbage")
    psf.write_text("garbage")
    (tmp_path / "x_build.pdb").write_text("garbage")  # declash marker present
    assert H._unpaired_exclusion_set(psf, pdb) == set()


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
