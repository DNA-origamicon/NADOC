"""Implicit-solvent (GBIS) NAMD protocol — dry package, no PME, NVT-only ladder.

The GBIS path exists so a large origami that overflows a small GPU's VRAM in
explicit water (NAMD dies at buildTileLists) can still relax: implicit solvent
drops the system to DNA-only (~6-7x fewer atoms).  These pin the invariants that
make it correct and distinct from the explicit path — no water/ions in the PSF,
GBIS electrostatics (not PME) in every conf, and no barostat (NVT), since there
is no periodic cell to apply pressure to.

Runs fully headless: GBIS needs no GROMACS solvation, only psfgen topology.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.core.lattice import LatticeType, make_bundle_design
from backend.core.md_prep_progress import build_prep_phases
from backend.core.md_protocols import IMPLICIT_GBIS_PROTOCOL, SUPPORTED_PROTOCOLS
from backend.core.namd_gbis import prepare_implicit_gbis_namd


def _small_design(name="gbis_test"):
    return make_bundle_design(
        [(0, 0), (0, 1)], 32, name=name, lattice_type=LatticeType.SQUARE
    )


@pytest.fixture(scope="module")
def gbis_package():
    d = _small_design()
    with tempfile.TemporaryDirectory() as td:
        jd = Path(td)
        subdir, stem, segs = prepare_implicit_gbis_namd(d, jd, minimize_steps=120)
        pkg = jd / subdir
        yield {
            "pkg": pkg,
            "stem": stem,
            "segs": segs,
            "confs": {p.name: p.read_text() for p in pkg.glob("*.conf")},
            "psf": (pkg / f"{stem}.psf").read_text(),
        }


def test_protocol_registered():
    assert IMPLICIT_GBIS_PROTOCOL in SUPPORTED_PROTOCOLS


def test_prep_phases_drop_solvation():
    keys = {p.key for p in build_prep_phases(seeded=False, implicit=True)}
    assert "solvate" not in keys and "assemble" not in keys
    assert {"topology", "enm", "finalize"} <= keys
    # Explicit path still has them.
    exp = {p.key for p in build_prep_phases(seeded=False, implicit=False)}
    assert {"solvate", "assemble"} <= exp


def test_dry_psf_has_no_water_or_magnesium(gbis_package):
    psf = gbis_package["psf"]
    assert "TIP3" not in psf and "HOH" not in psf, "GBIS package must ship no water"
    assert "MGH" not in psf, "GBIS package must ship no Mg(H2O)6 clusters"


def test_every_conf_is_gbis_not_pme(gbis_package):
    assert gbis_package["confs"], "expected minimize + segment confs"
    for name, txt in gbis_package["confs"].items():
        assert "gbis               on" in txt, f"{name} missing GBIS block"
        assert "PME                yes" not in txt, f"{name} still has PME"
        assert "cellBasisVector1" not in txt, f"{name} still has a periodic cell"
        assert "solventDielectric  78.5" in txt, f"{name} missing GB dielectric"


def test_ladder_is_nvt_only(gbis_package):
    # No segment may switch the Langevin piston on — implicit solvent has no box.
    for name, txt in gbis_package["confs"].items():
        assert "langevinPiston     on" not in txt, f"{name} enabled a barostat"


def test_enm_restraints_present_and_referenced(gbis_package):
    pkg = gbis_package["pkg"]
    enm_files = list(pkg.glob("*.enm.extra"))
    assert enm_files, "no ENM extraBonds files written"
    min_conf = next(t for n, t in gbis_package["confs"].items() if "min" in n)
    assert "extraBonds         on" in min_conf
    assert ".enm.extra" in min_conf


def test_ion_conc_maps_from_nacl_mM():
    # 300 mM NaCl → GBIS ionConcentration 0.3 M.
    d = _small_design("gbis_salt")
    with tempfile.TemporaryDirectory() as td:
        subdir, stem, segs = prepare_implicit_gbis_namd(
            d, Path(td), minimize_steps=120, ion_conc_mM=300.0
        )
        min_conf = next((Path(td) / subdir).glob("*min*.conf")).read_text()
        assert "ionConcentration   0.3" in min_conf


def test_crossover_extra_bases_are_topology_exactly_excluded_through_a_real_build():
    """Both extra bases at a junction land in the ss-exclusion sidecar AND in
    md_health's exclusion set, through the REAL psfgen path — not a synthetic
    fixture.  Pure C1'-distance geometry alone misses one of the two (measured:
    it sits sandwiched near the opposite duplex); topology_ss_exclusion_set
    places both by their crossover_id tag mapped through the PSF ordinal, so it
    cannot miss one regardless of 3D proximity."""
    from backend.core.md_health import (
        _unpaired_exclusion_set,
        identify_unpaired_residues,
        read_topology_ss_sidecar,
    )
    from backend.core.models import Crossover, Direction, HalfCrossover

    d = _small_design("gbis_xb")
    xo = Crossover(
        id="xo_extra",
        half_a=HalfCrossover(helix_id=d.helices[0].id, index=6, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=d.helices[1].id, index=6, strand=Direction.REVERSE),
        extra_bases="TT",
    )
    d = d.model_copy(update={"crossovers": [xo]})

    with tempfile.TemporaryDirectory() as td:
        jd = Path(td)
        subdir, stem, segs = prepare_implicit_gbis_namd(d, jd, minimize_steps=120)
        pkg = jd / subdir
        psf, pdb = pkg / f"{stem}.psf", pkg / f"{stem}.pdb"

        sidecar = read_topology_ss_sidecar(pkg, stem)
        assert len(sidecar) == 2  # both TT inserts, by topology

        geometry_only = identify_unpaired_residues(psf, pdb)
        assert not sidecar <= geometry_only  # confirms geometry alone still misses one

        health_exclusion = _unpaired_exclusion_set(psf, pdb)
        assert sidecar <= health_exclusion


def test_strand_extension_tails_are_topology_exactly_excluded_through_a_real_build():
    """A 5'/3' terminal ssDNA tail (StrandExtension) lands in the ss-exclusion
    sidecar through the real psfgen path — matching the crossover-extra-base
    check above.  A tail near a densely packed bundle can swing within reach of
    an unrelated neighbour (measured on a real design: 10.72 Å, under the 10.8 Å
    no-partner cutoff), so this specifically exercises extension_segid_resids's
    topology-exact (ordinal, not distance) placement."""
    from backend.core.md_health import _unpaired_exclusion_set, read_topology_ss_sidecar
    from backend.core.models import StrandExtension

    d = _small_design("gbis_ext")
    d = d.model_copy(
        update={
            "extensions": [
                StrandExtension(
                    strand_id=d.strands[0].id, end="three_prime", sequence="TT"
                )
            ]
        }
    )

    with tempfile.TemporaryDirectory() as td:
        jd = Path(td)
        subdir, stem, segs = prepare_implicit_gbis_namd(d, jd, minimize_steps=120)
        pkg = jd / subdir
        psf, pdb = pkg / f"{stem}.psf", pkg / f"{stem}.pdb"

        sidecar = read_topology_ss_sidecar(pkg, stem)
        assert len(sidecar) == 2  # both tail bases

        health_exclusion = _unpaired_exclusion_set(psf, pdb)
        assert sidecar <= health_exclusion
