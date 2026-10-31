"""Independent pose invariants for the isolated review candidate, not production."""

from copy import deepcopy
from types import SimpleNamespace as Row

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from experiments.mrdna_frame_candidate import (
    paired_particle_motion,
    rigid_atom_transport,
    transport_point,
)


def fixture():
    records, source, orientations, particles, names = [], [], [], [], []
    for bp, theta in enumerate((0.2, 0.8, 1.4)):
        radial = np.array([np.cos(theta), np.sin(theta), 0.0])
        second = np.array([np.cos(theta + 2.6), np.sin(theta + 2.6), 0.0])
        axis = np.array([0.0, 0.0, bp * 0.34])
        source.extend([axis + radial, axis + second])
        frame = np.column_stack(
            (radial, np.cross([0.0, 0.0, 1.0], radial), [0.0, 0.0, 1.0])
        )
        orientations.extend([frame, frame @ np.diag([1.0, -1.0, -1.0])])
        center = axis + 0.5 * (radial + second)
        particles.extend([center, center + 0.15 * radial])
        names.extend(["DNA", "O"])
        for strand in range(2):
            index = 2 * bp + strand
            records.append(
                Row(
                    identity=Row(key=lambda index=index: str(index)),
                    pair=str(2 * bp + 1 - strand),
                    model_nucleotide_index=index,
                    render=Row(helix_id="h", bp_index=bp, copy=0),
                    particle_bindings=[
                        Row(particle_index=2 * bp, particle_kind="DNA", weight=1.0)
                    ],
                )
            )
    return (
        Row(records=records),
        np.array(source),
        np.array(orientations),
        names,
        np.array(particles),
    )


def test_zero_motion_preserves_both_cg_and_distinct_native_reference_points():
    manifest, source, orientations, names, particles = fixture()
    original_source, original_particles = source.copy(), particles.copy()
    motion = paired_particle_motion(manifest, source, orientations, names, particles)
    for i, point in enumerate(source):
        assert transport_point(motion["h", i // 2], point) == pytest.approx(
            point, abs=1e-14
        )
        # A native chemical site need not coincide with the CG input bead.
        native_site = point + [0.18, -0.29, 0.07]
        assert transport_point(motion["h", i // 2], native_site) == pytest.approx(
            native_site, abs=1e-14
        )
    np.testing.assert_array_equal(source, original_source)
    np.testing.assert_array_equal(particles, original_particles)


def test_known_rigid_motion_is_recovered_without_resetting_the_structure():
    manifest, source, orientations, names, particles = fixture()
    rotation = Rotation.from_euler("xyz", [17.0, -31.0, 67.0], degrees=True).as_matrix()
    translation = np.array([2.1, -0.9, 3.4])
    final = particles @ rotation.T + translation
    motion = paired_particle_motion(manifest, source, orientations, names, final)
    for i, point in enumerate(source):
        assert transport_point(motion["h", i // 2], point) == pytest.approx(
            rotation @ point + translation,
            abs=1e-13,
        )


def test_orientation_particles_carry_local_twist_without_moving_dna_centers():
    manifest, source, orientations, names, particles = fixture()
    final, expected_rotations = particles.copy(), []
    centers = particles[::2]
    for bp, degrees in enumerate((12.0, -38.0, 73.0)):
        tangent = centers[min(bp + 1, 2)] - centers[max(bp - 1, 0)]
        tangent /= np.linalg.norm(tangent)
        rotation = Rotation.from_rotvec(tangent * np.deg2rad(degrees)).as_matrix()
        final[2 * bp + 1] = centers[bp] + rotation @ (
            particles[2 * bp + 1] - centers[bp]
        )
        expected_rotations.append(rotation)
    motion = paired_particle_motion(manifest, source, orientations, names, final)
    np.testing.assert_array_equal(final[::2], particles[::2])
    for i, point in enumerate(source):
        bp = i // 2
        expected = centers[bp] + expected_rotations[bp] @ (point - centers[bp])
        assert transport_point(motion["h", bp], point) == pytest.approx(
            expected, abs=1e-13
        )


@pytest.mark.parametrize("moving", [False, True], ids=["zero", "rigid"])
def test_written_particle_precision_does_not_deform_native_atoms(moving):
    manifest, source, orientations, names, particles = fixture()
    initial = np.round(particles, 5)
    rotation = (
        Rotation.from_euler("xyz", [17, -31, 67], degrees=True).as_matrix()
        if moving
        else np.eye(3)
    )
    shift = np.array([2.1, -0.9, 3.4]) if moving else np.zeros(3)
    final = initial @ rotation.T + shift
    motion = paired_particle_motion(
        manifest,
        source,
        orientations,
        names,
        final,
        initial_particle_positions_nm=initial,
    )
    # Distinct chemical sites, including a link between different particles.
    points = source[::2] + [0.18, -0.29, 0.07]
    reference = Row(
        atoms=[
            Row(helix_id="h", bp_index=i, name="P", x=p[0], y=p[1], z=p[2])
            for i, p in enumerate(points)
        ],
        bonds=[(0, 1), (1, 2)],
        warnings=[],
    )
    transported = rigid_atom_transport(reference, motion)
    actual = np.array([[a.x, a.y, a.z] for a in transported.atoms])
    np.testing.assert_allclose(actual, points @ rotation.T + shift, atol=1e-12, rtol=0)
    if not moving:
        np.testing.assert_array_equal(actual, points)
    np.testing.assert_array_equal([[a.x, a.y, a.z] for a in reference.atoms], points)
    assert transported.bonds == reference.bonds
    for i, point in enumerate(points):
        np.testing.assert_allclose(
            transport_point(motion["h", i], point),
            rotation @ point + shift,
            atol=1e-12,
            rtol=0,
        )


def test_nonuniform_site_motion_cannot_take_rigid_atom_shortcut():
    manifest, source, orientations, names, particles = fixture()
    final = particles.copy()
    final[-1] += [0.0, 0.02, 0.0]
    motion = paired_particle_motion(
        manifest,
        source,
        orientations,
        names,
        final,
        initial_particle_positions_nm=particles,
    )
    reference = Row(atoms=[Row(helix_id="h", bp_index=i) for i in range(3)])
    assert rigid_atom_transport(reference, motion) is None


@pytest.mark.parametrize(
    "defect", ["missing_orientation", "interpolated", "unpaired", "loop_copy"]
)
def test_unsupported_inputs_refuse_instead_of_silently_resetting(defect):
    manifest, source, orientations, names, particles = fixture()
    manifest = deepcopy(manifest)
    if defect == "missing_orientation":
        names[1] = "NAS"
    elif defect == "interpolated":
        manifest.records[0].particle_bindings[0].weight = 0.5
    elif defect == "unpaired":
        manifest.records[0].pair = None
    else:
        manifest.records[0].render.copy = 1
    original_particles = particles.copy()
    with pytest.raises(ValueError):
        paired_particle_motion(manifest, source, orientations, names, particles)
    np.testing.assert_array_equal(particles, original_particles)
