"""Cell overrides and periodic wall coverage, independent of a GPU or MD run."""
import numpy as np
import pytest
from scipy.spatial import cKDTree
from backend.core.namd_solvate import _graphene_pdb_atoms, _recenter_pdb_in_padded_box
from backend.core.namd_graphene import tile_graphene_to_cell, graphene_pressure_conf

DNA = ('ATOM      1  P    DA A   1     -10.000 -20.000 -30.000  1.00  0.00\n'
       'ATOM      2  P    DA A   2      40.000  50.000  60.000  1.00  0.00\nEND\n')


def xyz(pdb):
    return np.array([[float(line[k:k + 8]) / 10 for k in (30, 38, 46)]
                     for line in pdb.splitlines() if line.startswith(('ATOM', 'HETATM'))])


def test_partial_override_and_reset_preserve_calculated_axes():
    automatic, normal = _recenter_pdb_in_padded_box(DNA, 1.2, 'bbox')
    edited, cell = _recenter_pdb_in_padded_box(DNA, 1.2, 'bbox', box_size_nm=(None, 25, None))
    assert cell == (normal[0], 25, normal[2])
    assert np.allclose(xyz(edited).mean(0), np.array(cell) / 2)
    assert _recenter_pdb_in_padded_box(DNA, 1.2, 'bbox', box_size_nm=(None,) * 3) == (automatic, normal)


@pytest.mark.parametrize('value', [-1, 0, float('inf'), float('nan'), 2])
def test_invalid_or_nonfitting_override_rejected(value):
    with pytest.raises(ValueError):
        _recenter_pdb_in_padded_box(DNA, 1.2, 'bbox', box_size_nm=(value, None, None))


@pytest.mark.parametrize('axis', ['-x', '+x', '-y', '+y', '-z', '+z'])
def test_custom_cell_seams_are_as_dense_as_sheet_interior(axis):
    spec = {'surface_axis': axis, 'pore_diameter_nm': 2.1, 'layers': 2}
    seed = _graphene_pdb_atoms(DNA, spec)
    spec['_first_site_nm'] = xyz(seed[0])[0].tolist()
    before = np.array(spec['pore_center_nm'])
    pdb = DNA.replace('END\n', '') + '\n'.join(seed) + '\nEND\n'
    centered, lengths = _recenter_pdb_in_padded_box(pdb, 2, 'bbox', box_size_nm=(14.31, 16.17, 18.19))
    translation = xyz(centered)[0] - xyz(pdb)[0]
    result = tile_graphene_to_cell(centered, lengths, spec)
    assert np.allclose(spec['pore_center_nm'], before + translation, atol=1e-4)
    assert np.allclose(xyz(result)[:2], xyz(centered)[:2])
    n = 'xyz'.index(axis[-1]); tangents = [i for i in range(3) if i != n]
    graph = xyz('\n'.join(line for line in result.splitlines() if line.startswith('HETATM')))
    lateral = graph[np.isclose(graph[:, n], graph[0, n])][:, tangents]
    box = np.array(lengths)[tangents]
    tree = cKDTree(lateral % box, boxsize=box)
    # All edge points must remain within a carbon bond length of a wall site;
    # the old 1.5-nm open strips fail by an order of magnitude.
    for i in range(2):
        q = np.zeros((1000, 2));q[:, i] = np.linspace(0, box[i], 1000)
        assert tree.query(q % box)[0].max() < 0.15
    delta = lateral - np.array(spec['pore_center_nm'])[tangents]
    delta -= box * np.rint(delta / box)
    assert np.linalg.norm(delta, axis=1).min() >= 1.05 - 0.0002
    assert tree.query(lateral % box, k=2)[0][:, 1].min() > 0.1
    assert spec['cell_policy'] == 'fixed_volume'


def test_fixed_wall_cell_disables_barostat_overrides():
    conf = 'langevinPiston on\nBerendsenPressure on\nrun 500\n'
    assert graphene_pressure_conf(conf, enabled=True, fixed_cell=True) == (
        'langevinPiston off\nBerendsenPressure off\nrun 500\n')


def test_api_accepts_partial_axes_and_rejects_invalid_dimensions():
    from backend.api.routes_md import CreateJobRequest
    assert CreateJobRequest(box_size_nm=[None, 20, None]).box_size_nm == (None, 20, None)
    for values in ([0, 20, 20], [20, 20], [20, float('inf'), 20]):
        with pytest.raises(ValueError):
            CreateJobRequest(box_size_nm=values)


def test_preview_recalculates_automatic_axes_and_keeps_manual_values(monkeypatch):
    from backend.core import md_box_preview as preview
    from backend.core.models import Design
    from backend.api.routes_md import CreateJobRequest
    monkeypatch.setattr(preview, '_design_pdb', lambda _: DNA)
    request = CreateJobRequest(box_mode='bbox', padding_nm=1.2, devices='cpu', box_size_nm=[None, 25, None])
    # The no-strands design is only a serialization carrier here; a non-graphene
    # request must still size the provided atomistic seed.
    result = preview.preview_box(Design(), request)
    assert result['selected_nm'][1] == 25
    assert result['selected_nm'][0] == result['calculated_nm'][0]
    reset = preview.preview_box(Design(), request.model_copy(update={'box_size_nm': None}))
    assert reset['selected_nm'] == result['calculated_nm']
    preview._calculated_box.cache_clear()


def test_periodic_wall_manifest_forces_fixed_volume_for_production(tmp_path):
    import json
    from backend.core.md_protocols import package_npt_allowed
    (tmp_path / 'manifest.json').write_text(json.dumps({
        'graphene_nanopore': {'cell_policy': 'fixed_volume'},
        'solvation': {'npt_allowed': False},
    }))
    assert not package_npt_allowed(tmp_path)


@pytest.mark.slow
@pytest.mark.namd
def test_real_solvation_preserves_cell_and_magnesium_restraint_indices():
    import io
    import json
    import shutil
    import zipfile
    from backend.core.models import Design
    from backend.core.namd_solvate import build_namd_solvated_package
    if not shutil.which('gmx'):
        pytest.skip('GROMACS is required for this preparation test')
    spec = {'surface_axis': '-y', 'pore_diameter_nm': 2.1, 'layers': 1, 'atomistic_clearance_nm': 0}
    content = build_namd_solvated_package(
        Design(), graphene_nanopore=spec, graphene_only=True,
        box_size_nm=(6, 8, 7), padding_nm=2, box_mode='bbox', devices='cpu',
        ion_conc_mM=0, mg_conc_mM=12.5, mg_hexahydrate=True,
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        def read(suffix):
            return archive.read(next(n for n in archive.namelist() if n.endswith(suffix))).decode()
        audit = json.loads(read('charge_audit.json'))
        assert audit['ionization']['box_nm'] == [6, 8, 7]
        assert audit['ionization']['neutral']
        psf = iter(read('.psf').splitlines())
        for line in psf:
            if '!NATOM' in line:
                count = int(line.split()[0]);break
        atoms = [next(psf).split() for _ in range(count)]
        bonds = [line.split() for line in read('mgh_extrabonds.txt').splitlines() if line.startswith('bond ')]
        assert len(bonds) == 6 * audit['ionization']['n_mg'] > 0
        for bond in bonds:
            mg, oxygen = (atoms[int(i)] for i in bond[1:3])
            assert mg[3] == oxygen[3] == 'MGH'
            assert mg[4] == 'MG'
            assert oxygen[4].startswith('O')
            assert mg[1:3] == oxygen[1:3]
        from backend.core.md_plan import parse_conf_directives
        for path in archive.namelist():
            if path.endswith('.conf'):
                params = parse_conf_directives(archive.read(path).decode())
                assert params.get('langevinpiston', 'off') == 'off'
        assert len(xyz(read('.pdb'))) == count
