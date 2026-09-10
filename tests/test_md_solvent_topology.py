"""Solvent-only topology preserves atom order and residue identity without bonds."""

import numpy as np
import pytest

from backend.core.md_solvent import build_solvent_ctx, solvent_universe


def test_atom_only_psf_matches_full_topology(tmp_path, monkeypatch):
    mda = pytest.importorskip('MDAnalysis')
    psf = tmp_path / 'solvent.psf'
    psf.write_text('''PSF NAMD

       1 !NTITLE
 REMARKS solvent parser regression

       5 !NATOM
       1 DNA 1 DA P P 0.0 30.974 0
       2 WAT 1 TIP3 OH2 OT -0.834 15.999 0
       3 WAT 1 TIP3 H1 HT 0.417 1.008 0
       4 WAT 1 TIP3 H2 HT 0.417 1.008 0
       5 ION 1 SOD SOD SOD 1.0 22.990 0

       2 !NBOND: bonds
       2       3       2       4

       1 !NTHETA: angles
       3       2       4

       0 !NPHI: dihedrals

       0 !NIMPHI: impropers
''')
    full = mda.Universe(str(psf))
    full.load_new(np.arange(15, dtype=np.float32).reshape(1, 5, 3))
    full.dimensions = [30, 30, 30, 90, 90, 90]
    dcd = tmp_path / 'solvent.dcd'
    with mda.Writer(str(dcd), n_atoms=5) as writer:
        writer.write(full.atoms)
    light = solvent_universe(psf, str(dcd))
    for attr in ('names', 'resnames', 'resids', 'segids', 'resindices'):
        np.testing.assert_array_equal(getattr(light.atoms, attr), getattr(full.atoms, attr))
    np.testing.assert_allclose(light.atoms.positions, full.atoms.positions)
    assert len(full.bonds) == 2
    assert len(light.bonds) == 0
    for key, value in build_solvent_ctx(full).items():
        np.testing.assert_array_equal(build_solvent_ctx(light)[key], value)

    from backend.core import md_solvent

    def no_water_triplets(*args):
        raise AssertionError('ion-only setup must not construct water molecules')

    monkeypatch.setattr(md_solvent, 'water_triplets', no_water_triplets)
    ions_only = build_solvent_ctx(light, water=False)
    assert ions_only['n_waters_total'] == 1
    assert ions_only['n_ions'] == 1
    assert ions_only['water_o'].size == ions_only['water_h1'].size == ions_only['water_h2'].size == 0
