"""Independent geometric invariants for the isolated atomic transport candidate."""

from copy import deepcopy
from types import SimpleNamespace as Row

import numpy as np
from scipy.spatial.transform import Rotation

from experiments.mrdna_frame_candidate import paired_particle_motion
from experiments.mrdna_seed_transport_candidate import transport_reference
from tests.test_mrdna_frame_candidate import fixture


def reference_atoms(source):
    points = source + [0.18, -0.29, 0.07]
    model = Row(
        atoms=[Row(helix_id="h", bp_index=i // 2, name="P" if i % 2 else "O3'",
                   x=p[0], y=p[1], z=p[2]) for i, p in enumerate(points)],
        bonds=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)],
    )
    return model, points


def xyz(model):
    return np.array([[a.x, a.y, a.z] for a in model.atoms])


def test_float32_rigid_particle_motion_does_not_trigger_linker_reconstruction():
    manifest, source, orientations, names, particles = fixture()
    initial = (particles * 10).astype(np.float32).astype(float) / 10
    rotation = Rotation.from_euler("xyz", [17, -31, 67], degrees=True).as_matrix()
    shift = np.array([2.1, -0.9, 3.4])
    exact = initial @ rotation.T + shift
    final = (exact * 10).astype(np.float32).astype(float) / 10
    motion = paired_particle_motion(manifest, source, orientations, names, final,
                                    initial_particle_positions_nm=initial)
    reference, points = reference_atoms(source)
    original = deepcopy(reference)
    result = transport_reference(reference, motion)
    # Coordinate quantization is magnified by the short 0.15-nm O lever arm.
    # This independent rigid-pose control retains P/O3' atoms in the comparison.
    np.testing.assert_allclose(xyz(result), points @ rotation.T + shift, atol=1e-5, rtol=0)
    assert result.bonds == reference.bonds
    assert reference == original


def test_nonuniform_twist_preserves_each_native_base_pair_including_linker_atoms():
    manifest, source, orientations, names, particles = fixture()
    final = particles.copy()
    reference, points = reference_atoms(source)
    expected = points.copy()
    centers = particles[::2]
    for bp, angle in enumerate((12, -38, 73)):
        tangent = centers[min(bp + 1, 2)] - centers[max(bp - 1, 0)]
        rotation = Rotation.from_rotvec(tangent / np.linalg.norm(tangent) * np.deg2rad(angle)).as_matrix()
        final[2 * bp + 1] = centers[bp] + rotation @ (particles[2 * bp + 1] - centers[bp])
        expected[2 * bp:2 * bp + 2] = (points[2 * bp:2 * bp + 2] - centers[bp]) @ rotation.T + centers[bp]
    motion = paired_particle_motion(manifest, source, orientations, names, final,
                                    initial_particle_positions_nm=particles)
    result = transport_reference(reference, motion)
    np.testing.assert_allclose(xyz(result), expected, atol=1e-13, rtol=0)
    for a, b in ((0, 1), (2, 3), (4, 5)):
        np.testing.assert_allclose(np.linalg.norm(xyz(result)[a] - xyz(result)[b]),
                                   np.linalg.norm(points[a] - points[b]), atol=1e-14, rtol=0)
    assert result.bonds == reference.bonds


def test_exact_identity_returns_exact_native_atoms():
    manifest, source, orientations, names, particles = fixture()
    motion = paired_particle_motion(manifest, source, orientations, names, particles,
                                    initial_particle_positions_nm=particles)
    reference, points = reference_atoms(source)
    result = transport_reference(reference, motion)
    np.testing.assert_array_equal(xyz(result), points)
    assert result == reference
    assert result is not reference
