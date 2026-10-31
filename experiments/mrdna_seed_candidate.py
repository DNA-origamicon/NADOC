"""Isolated file-level fine mrDNA seed reconstruction for geometry review.

No production importer uses this provider. Recreate the unrelaxed native fine
reference from the snapshot, never from an intermediate-stage restart PDB. Only
fully paired, directly resolved fine particles are accepted. The actual restart
PDB supplies periodic unwrapping context, not a replacement molecular reference.
"""

from contextlib import ExitStack
from pathlib import Path
import tempfile

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.mrdna_bridge import _build_nt_arrays, _unwrapped_universe_positions
from backend.core.mrdna_manifest import (
    bind_manifest_to_mrdna_particles,
    build_mrdna_nucleotide_manifest,
)
from backend.parameterization.mrdna_inject import (
    CrossoverPotentialOverride,
    mrdna_model_from_nadoc_parameterized,
)
from experiments.mrdna_frame_candidate import (
    paired_particle_motion,
    rigid_atom_transport,
    transport_point,
)
from scripts.run_deformation_history_e2e import storage_parent


def native_reference(design):
    """Return a native reference with the exact written fine-particle precision."""
    import MDAnalysis as mda

    if design.atomistic_reference is not None:
        raise ValueError("Candidate does not replace a measured atomistic reference")
    if design.deformations or design.nucleotide_transforms or any(
        not np.array_equal(c.translation, [0, 0, 0])
        or not np.array_equal(c.rotation, [0, 0, 0, 1])
        for c in design.cluster_transforms
    ):
        raise ValueError("Candidate requires an unposed native snapshot")
    arrays = _build_nt_arrays(design, return_nt_key=True, return_identity=True)
    native = mrdna_model_from_nadoc_parameterized(
        design, CrossoverPotentialOverride.from_database("T0")
    )
    native.clear_beads()
    native.generate_bead_model(1, 1, local_twist=True, escapable_twist=False)
    manifest = bind_manifest_to_mrdna_particles(
        build_mrdna_nucleotide_manifest(design, design_fingerprint="isolated-reference"),
        native,
    )
    if any(
        r.pair is None or r.render.copy != 0
        or not isinstance(r.render.bp_index, int)
        or len(r.particle_bindings) != 1
        or r.particle_bindings[0].particle_kind != "DNA"
        or r.particle_bindings[0].weight != 1.0
        for r in manifest.records
    ):
        raise ValueError("Candidate requires fully paired direct fine sites")
    with tempfile.TemporaryDirectory(prefix="ms-", dir=storage_parent()) as temp:
        psf, pdb = Path(temp) / "native.psf", Path(temp) / "native.pdb"
        native.write_psf(str(psf))
        native.write_pdb(str(pdb))
        psf_text, pdb_text = psf.read_text(), pdb.read_text()
        u = mda.Universe(str(psf), str(pdb))
        try:
            particles = u.atoms.positions.astype(float) / 10
            names = tuple(u.atoms.names)
            bonds = {tuple(sorted(map(int, pair))) for pair in u.bonds.indices}
        finally:
            u.trajectory.close()
    frames = {}
    model = build_atomistic_model(design, frame_sink=frames)
    return {
        "manifest": manifest,
        "points": arrays[0] / 10,
        "orientations": arrays[4],
        "particles": particles,
        "names": names,
        "bonds": bonds,
        "psf_text": psf_text,
        "pdb_text": pdb_text,
        "model": model,
        "frames": frames,
        "scratch_absent": not Path(temp).exists(),
    }


def reconstruct(design, reference, psf_path, trajectory_path, *, frame=-1):
    """Reconstruct from a snapshot-generated reference, retaining earlier-stage motion.

    Current diagnostic scope requires the native fine particle ordering and
    topology. Reordered, coarse, unpaired, inserted or interpolated sites refuse;
    this is deliberately not a general trajectory decoder or a production path.
    """
    import MDAnalysis as mda

    with ExitStack() as cleanup:
        initial_u = mda.Universe(str(psf_path), str(Path(psf_path).with_suffix(".pdb")))
        cleanup.callback(initial_u.trajectory.close)
        final_u = mda.Universe(str(psf_path), str(trajectory_path))
        cleanup.callback(final_u.trajectory.close)
        final_u.trajectory[frame]
        names = tuple(initial_u.atoms.names)
        bonds = {tuple(sorted(map(int, pair))) for pair in initial_u.bonds.indices}
        if names != reference["names"] or bonds != reference["bonds"]:
            raise ValueError("Candidate requires the native fine PSF particle topology")
        final = _unwrapped_universe_positions(
            final_u, initial_u.atoms.positions
        ).astype(float) / 10
    seed = reference["particles"]
    if final.shape != seed.shape:
        raise ValueError("Candidate particle arrays disagree")
    # Match the production seed convention: remove whole-structure drift.
    # Preserve exact identity before invoking a numerical rigid fit.
    if not np.array_equal(final, seed):
        cm, ct = final.mean(0), seed.mean(0)
        u, _, vt = np.linalg.svd((final - cm).T @ (seed - ct))
        rotation = vt.T @ u.T
        if np.linalg.det(rotation) < 0:
            vt[-1] *= -1
            rotation = vt.T @ u.T
        final = (final - cm) @ rotation.T + ct
    motion = paired_particle_motion(
        reference["manifest"], reference["points"], reference["orientations"],
        names, final, initial_particle_positions_nm=seed,
    )
    points = {
        (r.render.helix_id, r.render.bp_index, r.render.direction): transport_point(
            motion[(r.render.helix_id, r.render.bp_index)],
            reference["points"][r.model_nucleotide_index],
        )
        for r in reference["manifest"].records
    }
    model = rigid_atom_transport(reference["model"], motion)
    if model is None:
        frames = {
            key: (transport_point(motion[key[:2]], origin), motion[key[:2]][2] @ axes)
            for key, (origin, axes) in reference["frames"].items()
        }
        model = build_atomistic_model(
            design, frame_override=frames, apply_design_geometry=False
        )
    return {"model": model, "points": points, "aligned_particles": final, "motion": motion}
