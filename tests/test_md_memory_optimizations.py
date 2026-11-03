"""Scientific and data-format invariants for the measured RAM optimizations."""
import base64
import hashlib
import io
import json

import numpy as np
import pytest

from backend.core import md_health as health
from backend.core.md_protocols import write_hmr_psf, _prepared_hmr_count
from backend.core.trajectory_cache import _pack, _unpack


def psf_fixture(width=10):
    atoms = [
        ('D', '1', 'DA', 'N', 14.007), ('D', '1', 'DA', 'H1', 1.008),
        ('D', '1', 'DA', 'H2', 1.008), ('W', '1', 'TIP3', 'O', 15.999),
        ('W', '1', 'TIP3', 'H1', 1.008), ('W', '1', 'TIP3', 'H2', 1.008),
        ('D', '2', 'DG', 'N', 14.007), ('D', '2', 'DG', 'H', 1.008),
        ('I', '1', 'MGH', 'O', 15.999), ('I', '1', 'MGH', 'H1', 1.008),
        ('I', '1', 'MGH', 'H2', 1.008),
    ]
    lines = [f'{i:10d} {seg:8s} {res:8s} {rn:8s} {name:8s} {name:6s} {0.:14.6f}{mass:14.6f}{0:9d}'
             for i, (seg, res, rn, name, mass) in enumerate(atoms, 1)]
    bonds = [(1, 2), (1, 3), (4, 5), (4, 6), (5, 6), (7, 8), (9, 10), (9, 11), (10, 11)]
    packed = [''.join(f'{a:{width}d}{b:{width}d}' for a, b in bonds[i:i + 4]) for i in range(0, len(bonds), 4)]
    return '\n'.join(['PSF EXT', '', '       1 !NTITLE', ' REMARKS fixture', '',
                      f'{len(atoms):10d} !NATOM', *lines, '', f'{len(bonds):10d} !NBOND: bonds', *packed,
                      '', '       0 !NTHETA: angles', '']) + '\n'


@pytest.mark.parametrize('width', [8, 10])
@pytest.mark.parametrize('heavy', [False, True])
@pytest.mark.parametrize('inplace', [False, True])
def test_streaming_hmr_keeps_mass_order_water_and_fixed_fields(tmp_path, width, heavy, inplace):
    import re
    src = tmp_path / 'input.psf'; dst = src if inplace else tmp_path / 'output.psf'
    original = psf_fixture(width); src.write_text(original)
    count = write_hmr_psf(src, dst, heavy_residues={('D', '2')} if heavy else None)
    # Preserve the legacy sequential treatment of an MGH O-H-H triangle too:
    # the first H changes mass before the second one's parents are inspected.
    masses = [9.975, 3.024, 3.024, 15.999, 1.008, 1.008,
              112.056 if heavy else 11.991, 8.064 if heavy else 3.024,
              13.983, 3.024, 1.008]
    assert count == (3 if heavy else 4)
    expected = original.splitlines()
    for i, mass in enumerate(masses, 6):
        token = list(re.finditer(r'\S+', expected[i]))[7]
        expected[i] = expected[i][:token.start()] + f'{mass:.4f}'.rjust(token.end() - token.start()) + expected[i][token.end():]
    assert dst.read_text() == '\n'.join(expected) + '\n'
    # No hidden temporary files survive an atomic publication.
    assert set(tmp_path.iterdir()) == {src, dst}


def test_hmr_rejects_bad_bond_without_overwriting_output(tmp_path):
    src, dst = tmp_path/'bad.psf', tmp_path/'good.psf'
    src.write_text(psf_fixture().replace(f'{1:10d}{2:10d}', f'{99:10d}{2:10d}'))
    dst.write_text('previous result')
    with pytest.raises(ValueError, match='bond index'):
        write_hmr_psf(src, dst)
    assert dst.read_text() == 'previous result'


def test_hmr_receipt_rejects_changed_inputs_and_outputs(tmp_path):
    src, dst = tmp_path/'system.psf', tmp_path/'system_hmr.psf'
    src.write_text(psf_fixture()); count = write_hmr_psf(src, dst)
    receipt = dict(schema=1, factor=3., hydrogens_repartitioned=count,
                   source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                   hmr_sha256=hashlib.sha256(dst.read_bytes()).hexdigest())
    src.with_suffix('.hmr.json').write_text(json.dumps(receipt))
    assert _prepared_hmr_count(src, dst) == count
    original = dst.read_bytes();dst.write_bytes(original + b'\n')
    assert _prepared_hmr_count(src, dst) is None
    dst.write_bytes(original);src.write_text(src.read_text() + '\n')
    assert _prepared_hmr_count(src, dst) is None


def test_reference_reader_matches_mdanalysis_and_reuses_only_within_check(tmp_path, monkeypatch):
    import MDAnalysis as mda
    from tests.test_md_health_ss_exclusion import _ISOLATED_PSF, _ISOLATED_PDB
    psf, pdb = tmp_path/'system.psf', tmp_path/'system.pdb'
    psf.write_text(_ISOLATED_PSF);pdb.write_text('CRYST1   60.000   70.000   80.000  90.00  90.00  90.00 P 1           1\n' + _ISOLATED_PDB)
    reference = mda.Universe(str(psf), str(pdb))
    calls = [];reader = health._read_reference_pdb
    def counted(*args):
        calls.append(1);return reader(*args)
    monkeypatch.setattr(health, '_read_reference_pdb', counted)
    @health._shared_health_topology
    def evaluate():
        first = health._health_universe(psf, pdb)
        np.testing.assert_array_equal(first.atoms.positions, reference.atoms.positions)
        np.testing.assert_array_equal(first.dimensions, reference.dimensions)
        first.atoms.positions = first.atoms.positions + 20
        second = health._health_universe(psf, pdb)
        np.testing.assert_array_equal(second.atoms.positions, reference.atoms.positions)
        assert first._topology is second._topology
    evaluate();assert len(calls) == 1
    evaluate();assert len(calls) == 2
    assert health._HEALTH_REFERENCES.get() is None
    assert health._HEALTH_TOPOLOGIES.get() is None


def test_reference_rejects_wrong_atom_count_and_reads_first_model(tmp_path):
    from tests.test_md_health_ss_exclusion import _ISOLATED_PDB
    p = tmp_path/'ref.pdb';p.write_text(_ISOLATED_PDB)
    n = sum(line[:6] in ('ATOM  ', 'HETATM') for line in _ISOLATED_PDB.splitlines())
    with pytest.raises(ValueError, match='atoms'):
        health._read_reference_pdb(p, n + 1)
    with pytest.raises(ValueError, match='atoms'):
        health._read_reference_pdb(p, n - 1)
    before, _ = health._read_reference_pdb(p, n)
    p.write_text('MODEL        1\n'+_ISOLATED_PDB+'\nENDMDL\nMODEL        2\n'+_ISOLATED_PDB+'\nENDMDL\n')
    after, _ = health._read_reference_pdb(p, n)
    np.testing.assert_array_equal(before, after)


@pytest.mark.parametrize('value', [
    np.arange(1000, dtype='>f4')[::3], np.array(1.5), np.empty((0,3)),
    np.array([(3., 2)], dtype=[('x', '<f8'), ('id', '<i4')]),
    np.array([(3., 2)], dtype=[('链', '<f8'), ('id', '<i4')]),
    np.array([['text', 3], [None, True]], dtype=object),
])
def test_cache_typed_arrays_preserve_dtype_shape_and_values(value):
    result = _unpack(json.loads(json.dumps(_pack(value))))
    assert result.dtype == value.dtype
    assert result.shape == value.shape
    np.testing.assert_array_equal(result, value)


def test_cache_preserves_keys_literals_lists_large_integers_and_nonfinite():
    value = {'$nadoc_cache': 'dict', 'tuple_key': {(1,'x'): (2,3)},
             'big': [2**80]*256, 'mixed': [True,1,2.5],
             'floats': [-0., float('nan'), float('inf')]*100,
             'ints': list(range(300)), 'bools': [False,True]*150}
    out = _unpack(json.loads(json.dumps(_pack(value))))
    for key in value.keys()-{'floats'}:assert out[key] == value[key]
    assert type(out['floats']) is list
    np.testing.assert_array_equal(out['floats'], value['floats'])
    assert np.signbit(out['floats'][0])


def test_cache_never_loads_pickled_object_arrays():
    stream = io.BytesIO();np.save(stream, np.array([object()], dtype=object), allow_pickle=True)
    with pytest.raises(ValueError, match='allow_pickle'):
        _unpack({'$nadoc_cache':'array','data':base64.b64encode(stream.getvalue()).decode()})


def test_cache_object_array_preserves_empty_shape_and_list_elements():
    for array in [np.empty((0,3), dtype=object), np.empty(2, dtype=object)]:
        if array.size:
            array[0] = [1,2];array[1] = {'x': 3}
        result = _unpack(json.loads(json.dumps(_pack(array))))
        assert result.shape == array.shape
        np.testing.assert_array_equal(result, array)


def test_health_topology_omits_connectivity_but_preserves_atom_data(tmp_path):
    import MDAnalysis as mda
    from MDAnalysis.topology.PSFParser import PSFParser
    psf=tmp_path/'system.psf';psf.write_text(psf_fixture())
    with PSFParser(psf) as reader:
        full=reader.parse()
    coords=np.zeros((1,11,3), dtype=np.float32)
    reference=mda.Universe(full, coords.copy(), format='MEMORY')
    optimized=health._health_universe(psf, coords.copy(), format='MEMORY')
    assert len(reference.bonds) == 9
    assert len(optimized.bonds) == 0
    for name in ['ids','names','types','resids','resindices','segids','resnames','charges','masses']:
        np.testing.assert_array_equal(getattr(optimized.atoms,name),getattr(reference.atoms,name))


def test_streaming_hmr_preserves_existing_file_permissions(tmp_path):
    src=tmp_path/'system.psf';src.write_text(psf_fixture());src.chmod(0o640)
    write_hmr_psf(src,src)
    assert src.stat().st_mode & 0o777 == 0o640


def test_corrupt_cache_array_cannot_allocate_from_an_unbacked_shape():
    stream=io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, dict(descr='<f8',shape=(2**60,),fortran_order=False))
    with pytest.raises(ValueError, match='cached array bytes'):
        _unpack({'$nadoc_cache':'array','data':base64.b64encode(stream.getvalue()).decode()})
