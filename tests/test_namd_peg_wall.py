"""Fast physical-force, emitted Tcl and package integrity oracles; no MD launch."""
import json
import subprocess

import numpy as np
import pytest

from backend.core.namd_peg_wall import RepulsiveSlit, harmonic_graft_block
from experiments.peg_wall.build import build, chain_script, configurations, sha256
from experiments.peg_wall.validate import run_stage, trajectory_metrics, verify_inputs


@pytest.mark.parametrize('axis', [0, 1, 2])
def test_repulsive_wall_force_is_negative_energy_gradient_and_image_invariant(axis):
    wall = RepulsiveSlit(axis=axis, k_kcal_mol_A2=7)
    xyz = np.full((5, 3), 20.)
    xyz[:, axis] = [1, 2, 20, 46, 47]
    energy, forces = wall.energy_forces(xyz)
    assert energy == pytest.approx(14)
    assert forces[:, axis] == pytest.approx([14, 0, 0, 0, -14])
    h = 1e-5
    for i in (0, 2, 4):
        for j in range(3):
            delta = np.zeros_like(xyz); delta[i, j] = h
            derivative = (wall.energy_forces(xyz+delta)[0]-wall.energy_forces(xyz-delta)[0])/(2*h)
            assert forces[i, j] == pytest.approx(-derivative, abs=1e-7)
    shifted = xyz + [48, -96, 144]
    e2, f2 = wall.energy_forces(shifted)
    assert e2 == pytest.approx(energy)
    np.testing.assert_allclose(f2, forces, atol=1e-10)
    assert wall.frames[0].namd_plane()['point_angstrom'][axis] == pytest.approx(2)


@pytest.mark.parametrize('axis', [0, 1, 2])
def test_executed_tcl_matches_physical_oracle(axis):
    wall = RepulsiveSlit(axis=axis)
    xyz = np.array([[1., 1., 1.], [47., 47., 47.], [20., 20., 20.], [49., -47., 97.]])
    # TclForces API stubs exercise actual generated Tcl, including energy bookkeeping.
    coords = '\n'.join(f'set xyz({i}) {{{" ".join(map(str, p))}}}' for i, p in enumerate(xyz, 1))
    script = '''proc addatom {id} {}
proc loadcoords {name} {
    upvar 1 $name xyz
''' + coords + '''
}
proc addforce {id f} {puts "F $id $f"}
proc addenergy {e} {puts "E $e"}
''' + wall.tcl_forces([1, 2, 3, 4]) + '\ncalcforces\n'
    output = subprocess.run(['tclsh'], input=script, text=True, capture_output=True, check=True, timeout=2)
    assert not output.stderr
    expected_e, expected_f = wall.energy_forces(xyz)
    force = np.zeros_like(xyz)
    for line in output.stdout.splitlines():
        tokens = line.split()
        if tokens[0] == 'F':
            force[int(tokens[1])-1] = list(map(float, tokens[2:]))
        if tokens[0] == 'E':
            assert float(tokens[1]) == pytest.approx(expected_e)
    assert 'E ' in output.stdout
    np.testing.assert_allclose(force, expected_f, atol=1e-9)


@pytest.mark.parametrize('kwargs', [dict(box_nm=(0, 4, 4)), dict(box_nm=(4, np.nan, 4)),
                                   dict(axis=3), dict(axis=True), dict(inset_nm=3),
                                   dict(inset_nm=0), dict(k_kcal_mol_A2=-1), dict(k_kcal_mol_A2=np.inf)])
def test_wall_rejects_invalid_physics(kwargs):
    with pytest.raises(ValueError):
        RepulsiveSlit(**kwargs)


def test_wall_atom_ids_and_graft_strength_reject_invalid_inputs():
    for ids in ([], [0], [1, 1], ['1'], [True]):
        with pytest.raises(ValueError):
            RepulsiveSlit().tcl_forces(ids)
    for k in (0, -1, np.nan, np.inf):
        with pytest.raises(ValueError):
            harmonic_graft_block(k)


def test_protocol_keeps_wall_and_tethers_in_both_stages_and_resident_in_md():
    configs = configurations(RepulsiveSlit(), 5, 294, 1000, 17)
    for text in configs.values():
        settings = {line.split()[0].lower(): ' '.join(line.split()[1:])
                    for line in text.splitlines() if line and not line.startswith('#')}
        assert settings['constraints'] == 'on'
        assert settings['constraintscaling'] == '5'
        assert settings['consexp'] == '2'
        assert settings['consref'] == settings['conskfile'] == 'grafts.pdb'
        assert settings['tclforces'] == 'on'
        assert settings['langevinpiston'] == 'off'
        assert settings['rigidbonds'] == 'all'
        assert 'fixedatoms' not in settings
    assert 'GPUresident on' in configs['resident']
    assert 'minimize ' not in configs['resident']
    assert 'binCoordinates output/minimize.coor' in configs['resident']


def test_repeat_count_and_geometry_seed_fit_the_declared_cell():
    script = chain_script(8, 2, RepulsiveSlit(), .2)
    residues = [line for line in script.splitlines() if line.startswith('residue ')]
    assert len(residues) == 4*9  # C18 H38 O9: eight EO repeats, two methyl caps
    coords = [list(map(float, line.split('{')[1].rstrip('}').split()))
              for line in script.splitlines() if line.startswith('coord ')]
    assert RepulsiveSlit().energy_forces(coords)[0] == 0
    with pytest.raises(ValueError, match='does not fit'):
        chain_script(100, 2, RepulsiveSlit(), .2)


def test_bad_parameters_do_not_create_a_package(tmp_path):
    out = tmp_path/'package'
    with pytest.raises(ValueError):
        build(tmp_path, out, steps=7)
    assert not out.exists()


def test_input_seal_rejects_changed_force_file(tmp_path):
    force = tmp_path/'wall.tcl'; force.write_text('force v1')
    (tmp_path/'manifest.json').write_text(json.dumps(dict(schema='nadoc.peg_wall_qualification.v1',
                                                        input_hashes={'wall.tcl': sha256(force)})))
    verify_inputs(tmp_path)
    force.write_text('force v2')
    with pytest.raises(ValueError, match='input changed'):
        verify_inputs(tmp_path)


def test_actual_execution_requires_user_opened_session(tmp_path, monkeypatch):
    from experiments.peg_wall import validate
    monkeypatch.setattr(validate, 'ROOT', tmp_path)
    monkeypatch.setattr(validate, 'verify_inputs', lambda p: {})
    def no_launch(*args, **kwargs):
        pytest.fail('engine must not be invoked without a session')
    monkeypatch.setattr(validate.subprocess, 'run', no_launch)
    with pytest.raises(RuntimeError, match='just test-session'):
        run_stage(tmp_path, 'minimize', 'namd3')


def test_trajectory_measures_penetration_tether_and_motion(tmp_path, monkeypatch):
    from experiments.peg_wall import validate
    from types import SimpleNamespace
    reference = np.array([[10., 10., 4.], [10., 10., 8.], [20., 20., 2.]])
    second = reference.copy(); second[0, 0] += .5; second[1, 2] += 1; second[2, 2] -= .25
    monkeypatch.setattr(validate, 'read_pair', lambda *args: dict(atoms=[0]*3, xyz=reference))
    monkeypatch.setattr(validate, 'read_layout', lambda *args: SimpleNamespace(n_atoms=3, n_frames=2, istart=100, nsavc=100))
    monkeypatch.setattr(validate, 'read_frame', lambda p, l, i: ([reference, second][i], None))
    manifest = dict(slit={}, graft_k_kcal_mol_A2=5, audit=dict(anchor_indices_0=[0], peg_indices_0=[0, 1]))
    rows = [dict(TS=100, BOUNDARY=0, MISC=0), dict(TS=200, BOUNDARY=1.25, MISC=.625)]
    result = trajectory_metrics(tmp_path, manifest, rows)
    assert result['sampled_max_penetration_A'] == pytest.approx(.25)
    assert result['sampled_PEG_max_penetration_A'] == 0
    assert result['sampled_max_anchor_displacement_A'] == pytest.approx(.5)
    assert result['sampled_anchor_rms_displacement_A'] == pytest.approx(np.sqrt(.125))
    assert result['sampled_PEG_motion_rms_A'] == pytest.approx(np.sqrt(.625))
    assert result['energy_comparison_frames'] == 2
    assert result['max_force_energy_error_kcal_mol'] == pytest.approx(0)
    rows[1]['MISC'] = 0  # Detect a force/energy path silently missing in the engine.
    assert trajectory_metrics(tmp_path, manifest, rows)['max_force_energy_error_kcal_mol'] == pytest.approx(.625)
