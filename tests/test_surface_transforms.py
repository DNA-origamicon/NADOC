"""Rigid registration shared by hard barriers, graphene and PEG coatings."""
import copy

import numpy as np
import pytest

from backend.core.surface_transforms import (
    RigidTransform, SurfaceFrame, surface_frame, transform_surface,
)


@pytest.mark.parametrize('axis', range(3))
@pytest.mark.parametrize('sign', [-1, 1])
def test_cartesian_world_coordinate_and_oxdna_sign(axis, sign):
    normal = np.eye(3)[axis] * sign * 2
    spec = {'dir': normal.tolist(), 'position_nm': -4}
    frame = surface_frame(spec)
    assert frame.point_nm[axis] == -4
    assert frame.oxdna_plane(2)['position'] == sign * 8
    moved = transform_surface(spec, RigidTransform(translation_nm=(1, 2, 3)))
    assert moved['position_nm'] == -4 + axis + 1
    assert surface_frame(moved).signed_distance(
        RigidTransform(translation_nm=(1, 2, 3)).points([3, 4, 5])
    ) == pytest.approx(frame.signed_distance([3, 4, 5]))


def test_common_transform_preserves_barrier_pore_grafts_and_peg_registration():
    angle = .37
    r = [[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
         [-np.sin(angle), 0, np.cos(angle)]]
    transform = RigidTransform(r, [10, -3, 7])
    spec = {'dir': [0, 0, 1], 'position_nm': 2, 'tangent_u': [1, 0, 0],
            'pore_center_nm': [3, 4, 2], 'graft_sites_nm': [[1, 2, 2], [4, 5, 2]],
            'peg_positions_nm': [[1, 2, 3], [1, 2, 4]],
            'material': 'graphene', 'stiff': 5, 'patch': {'width_nm': 4}}
    before = copy.deepcopy(spec)
    moved = transform_surface(spec, transform)
    assert spec == before
    assert 'position_nm' not in moved
    assert moved['patch'] == spec['patch']
    assert moved['stiff'] == 5
    source, target = surface_frame(spec), surface_frame(moved)
    dna = np.array([[0, 0, 5], [1, 3, -2]])
    assert np.allclose(target.signed_distance(transform.points(dna)), source.signed_distance(dna))
    assert np.allclose(target.project(transform.points(dna)), transform.points(source.project(dna)))
    assert np.allclose(target.signed_distance(moved['graft_sites_nm']), 0)
    assert target.signed_distance(moved['pore_center_nm']) == pytest.approx(0, abs=1e-12)
    assert np.allclose(target.tangent_v, transform.direction(source.tangent_v))
    assert np.allclose(target.signed_distance(moved['peg_positions_nm']), [1, 2])
    for key in ('pore_center_nm', 'graft_sites_nm', 'peg_positions_nm'):
        assert np.allclose(transform.inverse().points(moved[key]), spec[key])
    # Local patch coordinates must survive; rebuilding a basis after rotation fails this.
    offset = np.asarray(spec['graft_sites_nm']) - source.point_nm
    rotated_offset = np.asarray(moved['graft_sites_nm']) - target.point_nm
    assert np.allclose(offset @ source.tangent_u, rotated_offset @ target.tangent_u)


def test_composition_inverse_and_units():
    first = RigidTransform([[0, -1, 0], [1, 0, 0], [0, 0, 1]], [2, 3, 4])
    second = RigidTransform(translation_nm=[-5, 4, 2])
    points = [[1, 2, 3], [4, 5, 6]]
    assert np.allclose(first.then(second).points(points), second.points(first.points(points)))
    assert np.allclose(first.inverse().points(first.points(points)), points)
    plane = SurfaceFrame([2, 3, 4], [0, 0, 1])
    assert plane.namd_plane() == {'normal': [0, 0, 1], 'point_angstrom': [20, 30, 40]}
    assert plane.oxdna_plane(2) == {'dir': [0, 0, 1], 'position': -8}


@pytest.mark.parametrize('rotation', [np.diag([1, 1, -1]), np.diag([2, 1, 1]),
                                      np.ones((3, 3)), np.full((3, 3), np.nan)])
def test_reject_nonrigid_transforms(rotation):
    with pytest.raises(ValueError):
        RigidTransform(rotation)


@pytest.mark.parametrize('normal', [[0, 0, 0], [0, np.nan, 1], [1, 2]])
def test_reject_invalid_normals(normal):
    with pytest.raises(ValueError):
        SurfaceFrame([0, 0, 0], normal)


def test_reject_ambiguous_plane_and_invalid_tangent():
    with pytest.raises(ValueError, match='plane_point_nm'):
        surface_frame({'dir': [1, 1, 0], 'position_nm': 3})
    with pytest.raises(ValueError, match='plane_point_nm'):
        surface_frame({'dir': [1e-6, 0, 1], 'position_nm': 3})
    with pytest.raises(ValueError, match='perpendicular'):
        SurfaceFrame([0, 0, 0], [0, 0, 1], [0, 0, 1])
    with pytest.raises(ValueError):
        RigidTransform(translation_nm=[0, np.inf, 0])
    with pytest.raises(ValueError):
        RigidTransform().points([[np.nan, 0, 0]])


def test_empty_coating_and_explicit_oblique_plane():
    spec = {'dir': [1, 1, 0], 'plane_point_nm': [1, 3, 0],
            'graft_sites_nm': [], 'peg_positions_nm': []}
    moved = transform_surface(spec, RigidTransform(translation_nm=[2, 4, 6]))
    assert moved['graft_sites_nm'] == []
    assert moved['peg_positions_nm'] == []
    assert np.allclose(moved['plane_point_nm'], [3, 7, 6])


def test_seed_recenter_uses_shared_plane_without_backmapping(monkeypatch, tmp_path):
    from dataclasses import dataclass
    from types import SimpleNamespace
    from backend.core import cg_to_atomistic, oxdna_runner

    @dataclass
    class Report:
        test: bool = True

    atoms = [SimpleNamespace(x=10., y=20., z=30.),
             SimpleNamespace(x=12., y=24., z=36.)]
    model = SimpleNamespace(atoms=atoms)
    raw = {'dir': [0, -2, 0], 'position_nm': 18., 'stiff': 5}
    job = SimpleNamespace(run_config={'kind': 'surface_deposition', 'surface': raw},
                          job_dir=lambda _: tmp_path)
    monkeypatch.setattr(oxdna_runner.OxdnaJob, 'load', lambda *_: job)
    monkeypatch.setattr(oxdna_runner, '_load_snapshot_design', lambda _: object())
    monkeypatch.setattr(oxdna_runner, '_latest_relaxed_conf',
                        lambda *_: (tmp_path / 'last_conf.dat', 'relax'))
    monkeypatch.setattr(cg_to_atomistic, 'build_topology_safe_oxdna_seed',
                        lambda *_: (model, None, Report()))
    seed = oxdna_runner.build_namd_seed('test', tmp_path)
    points = np.array([[a.x, a.y, a.z] for a in atoms])
    assert np.allclose(points.mean(axis=0), 0)
    assert seed.deposition_surface['position_nm'] == -4
    assert np.allclose(seed.deposition_surface['pore_center_nm'], [0, -4, 0])
    assert np.allclose(surface_frame(seed.deposition_surface).signed_distance(points), [-2, -6])
    assert raw == {'dir': [0, -2, 0], 'position_nm': 18., 'stiff': 5}
