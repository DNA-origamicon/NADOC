"""User-session-only physical checks for rotated PEG barrier adapters."""
import subprocess

import numpy as np
import pytest

from backend.core.constants import NM_TO_OXDNA
from backend.core.surface_transforms import RigidTransform, transform_surface
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.physics.oxdna_peg import find_peg_oxdna, PegParameters
from backend.physics.oxdna_surface_geometry import resolved_wall
from backend.physics.oxdna_interface import repulsion_plane_block


@pytest.mark.slow
@pytest.mark.parametrize('backend', ['CPU', 'CUDA'])
def test_peg_barrier_force_rotates_with_surface(tmp_path, backend):
    binary = find_peg_oxdna()
    if binary is None:
        pytest.skip('isolated DNA2PEG engine is unavailable')
    angle = .41
    rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
                         [-np.sin(angle), 0, np.cos(angle)]])
    center = np.array([5., 5., 5.])
    transforms = [RigidTransform(), RigidTransform(rotation, center - rotation @ center)]
    results = []
    dt = 1e-5
    for i, transform in enumerate(transforms):
        root = tmp_path / str(i)
        root.mkdir()
        (root / 'topology.top').write_text('1 1\n1 500 -1 -1\n')
        position = transform.points([5, 5, 4.9]) * NM_TO_OXDNA
        a1, a3 = transform.direction([1, 0, 0]), transform.direction([0, 0, 1])
        values = [*position, *a1, *a3, 0, 0, 0, 0, 0, 1e-6]
        (root / 'conf.dat').write_text('t = 0\nb = 30 30 30\nE = 0 0 0\n' +
                                       ' '.join(map(str, values)) + '\n')
        surface = transform_surface({'dir': [0, 0, 1], 'position_nm': 5, 'stiff': 5}, transform)
        plane = resolved_wall(surface, [position])
        (root / 'forces.txt').write_text(repulsion_plane_block(5, plane['dir'], plane['position']))
        stage = OxdnaStageSpec('force', 'production', 'MD', 1, backend, dt=dt,
                              thermostat='no', interaction='DNA2PEG',
                              peg_parameters=PegParameters().engine_parameters(), seed=123,
                              external_forces=True)
        text = render_stage_input(stage, 'topology.top', 'conf.dat', forces_name='forces.txt')
        (root / 'input').write_text(text.replace('refresh_vel = true', 'refresh_vel = false'))
        result = subprocess.run([binary, 'input'], cwd=root, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr[-4000:]
        final = np.loadtxt(root / 'last_conf.dat', skiprows=3).reshape(-1, 15)
        results.append(final[0, 9:12] / dt)
    assert np.allclose(results[0], [0, 0, .5 * NM_TO_OXDNA], atol=2e-4, rtol=2e-4)
    assert np.allclose(results[1], rotation @ results[0], atol=2e-4, rtol=2e-4)
