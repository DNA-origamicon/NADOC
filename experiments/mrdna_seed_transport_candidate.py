"""Isolated paired-Fine seed transport; no display, export or simulation caller.

The original native reference comes from mrdna_seed_candidate.native_reference.
Only that provider's fully paired, directly resolved, unposed designs qualify.
The intermediate fine PDB supplies unwrapping context, never a new reference.
No linker is re-solved after measured particle motion: the existing atomic
reference is carried by each base-pair frame, preserving its internal geometry.
"""

from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path

import numpy as np

from backend.core.mrdna_bridge import _unwrapped_universe_positions
from experiments.mrdna_frame_candidate import (
    paired_particle_motion,
    rigid_atom_transport,
    transport_point,
)


def transport_reference(reference, motion):
    """Carry existing atoms, including linker atoms, through their measured frames."""
    common = rigid_atom_transport(reference, motion)
    if common is not None:
        return common
    result = deepcopy(reference)
    for atom in result.atoms:
        key = (atom.helix_id, atom.bp_index)
        if key not in motion:
            raise ValueError("Atomic reference contains an unsupported particle site")
        atom.x, atom.y, atom.z = transport_point(
            motion[key], np.array([atom.x, atom.y, atom.z])
        ).tolist()
    return result


def reconstruct(reference, psf_path, trajectory_path, *, frame=-1):
    """Read a real fine frame and remove rigid drift using DNA centers alone.

    O particles retain their local twist; they must not rotate the global fit.
    File rounding is allowed to remain measured motion rather than triggering
    a different linker construction. There is no molecular deadband or snap.
    """
    import MDAnalysis as mda

    with ExitStack() as cleanup:
        initial = mda.Universe(str(psf_path), str(Path(psf_path).with_suffix(".pdb")))
        cleanup.callback(initial.trajectory.close)
        final = mda.Universe(str(psf_path), str(trajectory_path))
        cleanup.callback(final.trajectory.close)
        final.trajectory[frame]
        names = tuple(initial.atoms.names)
        bonds = {tuple(sorted(map(int, pair))) for pair in initial.bonds.indices}
        if names != reference["names"] or bonds != reference["bonds"]:
            raise ValueError("Candidate requires the native fine PSF particle topology")
        particles = _unwrapped_universe_positions(
            final, initial.atoms.positions
        ).astype(float) / 10
    seed = reference["particles"]
    if particles.shape != seed.shape or not np.isfinite(particles).all():
        raise ValueError("Candidate requires matching finite particle arrays")
    dna = np.flatnonzero(np.asarray(names) == "DNA")
    if len(dna) < 3 or np.linalg.matrix_rank(seed[dna] - seed[dna].mean(0)) < 2:
        raise ValueError("DNA centers do not determine a unique rigid alignment")
    if not np.array_equal(particles[dna], seed[dna]):
        cm, ct = particles[dna].mean(0), seed[dna].mean(0)
        left, _, right = np.linalg.svd((particles[dna] - cm).T @ (seed[dna] - ct))
        rotation = right.T @ left.T
        if np.linalg.det(rotation) < 0:
            right[-1] *= -1
            rotation = right.T @ left.T
        particles = (particles - cm) @ rotation.T + ct
    motion = paired_particle_motion(
        reference["manifest"], reference["points"], reference["orientations"],
        names, particles, initial_particle_positions_nm=seed,
    )
    return {
        "model": transport_reference(reference["model"], motion),
        "motion": motion,
        "aligned_particles": particles,
    }
