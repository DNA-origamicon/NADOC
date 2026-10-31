"""Qualify the isolated paired-particle candidate under prescribed motion.

This runs no dynamics and changes no production decoder. It uses actual fine
mrDNA particles, a full phase turn, and independently prescribed rigid/twist
motions. Reference atom frames are transported, rather than inferring a new
chemical frame from a displaced backbone point. Unsupported sites still refuse.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.atomistic import atomistic_to_json, build_atomistic_model
from backend.core.deformation import effective_helix_for_geometry
from backend.core.models import Design
from backend.core.molecular_placement_audit import (
    _affected_serials,
    _defect_serials,
    _model_diagnostics,
)
from backend.core.mrdna_bridge import _build_nt_arrays
from backend.parameterization.mrdna_inject import (
    CrossoverPotentialOverride,
    mrdna_model_from_nadoc_parameterized,
)
from backend.core.mrdna_manifest import (
    bind_manifest_to_mrdna_particles,
    build_mrdna_nucleotide_manifest,
)
from experiments.mrdna_frame_candidate import (
    paired_particle_motion,
    rigid_atom_transport,
    transport_point,
)
from experiments.mrdna_frame_review_figure import junction_defects
from scripts.run_deformation_history_e2e import storage_parent

ROOT = Path(__file__).resolve().parents[1]
FLEXIBLE_NAMES = {"P", "OP1", "OP2", "O3'", "O5'"}


def transported_atom_frames(reference_frames, motion):
    """Transport the exact native stamp frames through measured particle motion."""
    return {
        key: (transport_point(motion[key[:2]], origin), motion[key[:2]][2] @ axes)
        for key, (origin, axes) in reference_frames.items()
    }


def atom_identity(atom):
    return (
        atom.strand_id,
        atom.helix_id,
        atom.bp_index,
        atom.direction,
        atom.copy_k,
        atom.crossover_id,
        atom.extra_base_k,
        atom.name,
    )


def xyz(model):
    return np.array([[atom.x, atom.y, atom.z] for atom in model.atoms])


def qualify(output: Path, phases=range(0, 360, 10)):
    import MDAnalysis as mda

    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "Examples/2hb_xover_val.nadoc"
    original = Design.model_validate_json(source.read_text())
    posed_clusters = any(
        not np.array_equal(cluster.translation, [0, 0, 0])
        or not np.array_equal(cluster.rotation, [0, 0, 0, 1])
        for cluster in original.cluster_transforms
    )
    if original.deformations or posed_clusters or original.nucleotide_transforms:
        raise ValueError("This diagnostic requires an unposed native reference")
    original_snapshot = original.model_dump_json()
    original_model = build_atomistic_model(original)
    original_xyz = xyz(original_model)
    results = []
    with (
        tempfile.TemporaryDirectory(prefix="mf-", dir=storage_parent()) as temporary,
        ExitStack() as cleanup,
    ):
        scratch = Path(temporary)
        for phase in phases:
            design = original.model_copy(deep=True)
            # Grid normalization overrides stored phase. Resolve the exact
            # native carrier first, then vary its phase only in this diagnostic.
            design.helices = [
                effective_helix_for_geometry(h, original).model_copy(
                    update={
                        "grid_pos": None,
                        "phase_offset": effective_helix_for_geometry(
                            h, original
                        ).phase_offset
                        + float(np.deg2rad(phase)),
                    }
                )
                for h in original.helices
            ]
            snapshot = design.model_dump_json()
            arrays = _build_nt_arrays(design, return_nt_key=True, return_identity=True)
            source_points, orientations = arrays[0] / 10, arrays[4]
            native = mrdna_model_from_nadoc_parameterized(
                design, CrossoverPotentialOverride.from_database("T0")
            )
            native.clear_beads()
            native.generate_bead_model(1, 1, local_twist=True, escapable_twist=False)
            psf, pdb = scratch / "fine.psf", scratch / "fine.pdb"
            native.write_psf(str(psf))
            native.write_pdb(str(pdb))
            manifest = bind_manifest_to_mrdna_particles(
                build_mrdna_nucleotide_manifest(
                    design, design_fingerprint="isolated-motion"
                ),
                native,
            )
            universe = mda.Universe(str(psf), str(pdb))
            cleanup.callback(universe.trajectory.close)
            particles = universe.atoms.positions.astype(float) / 10
            names = [atom.name for atom in universe.atoms]
            reference_frames = {}
            reference = build_atomistic_model(design, frame_sink=reference_frames)
            reference_xyz = xyz(reference)
            if phase == 0:
                np.testing.assert_allclose(
                    reference_xyz, original_xyz, atol=1e-12, rtol=0
                )
            else:
                if np.max(np.linalg.norm(reference_xyz - original_xyz, axis=1)) < 0.01:
                    raise AssertionError(
                        "The requested phase did not change atom placement"
                    )
            reference_identity = [atom_identity(atom) for atom in reference.atoms]
            rigid = Rotation.from_euler("xyz", [17, -31, 67], degrees=True).as_matrix()
            shift = np.array([2.1, -0.9, 3.4])
            for mode in ("zero", "rigid", "local_twist"):
                final = particles.copy()
                expected = {}
                for record in manifest.records:
                    key = (record.render.helix_id, record.render.bp_index)
                    if key in expected:
                        continue
                    index = record.particle_bindings[0].particle_index
                    if mode == "rigid":
                        expected[key] = (rigid, shift)
                        final[index : index + 2] = (
                            particles[index : index + 2] @ rigid.T + shift
                        )
                    elif mode == "local_twist":
                        # Rotate O about its actual local particle tangent, leaving DNA fixed.
                        bps = sorted(
                            {
                                r.render.bp_index
                                for r in manifest.records
                                if r.render.helix_id == key[0]
                            }
                        )
                        sites = {
                            r.render.bp_index: r.particle_bindings[0].particle_index
                            for r in manifest.records
                            if r.render.helix_id == key[0]
                        }
                        at = bps.index(key[1])
                        tangent = (
                            particles[sites[bps[min(at + 1, len(bps) - 1)]]]
                            - particles[sites[bps[max(at - 1, 0)]]]
                        )
                        tangent /= np.linalg.norm(tangent)
                        rotation = Rotation.from_rotvec(
                            tangent * np.deg2rad(12 * np.sin(key[1] / 7))
                        ).as_matrix()
                        final[index + 1] = particles[index] + rotation @ (
                            particles[index + 1] - particles[index]
                        )
                        # The prescribed rotation uses the actual quantized DNA
                        # particle as pivot, exactly as the O update above does.
                        pivot = particles[index]
                        expected[key] = (rotation, pivot - rotation @ pivot)
                    else:
                        expected[key] = (np.eye(3), np.zeros(3))
                motion = paired_particle_motion(
                    manifest,
                    source_points,
                    orientations,
                    names,
                    final,
                    initial_particle_positions_nm=particles,
                )
                candidate = rigid_atom_transport(reference, motion)
                if candidate is None:
                    candidate = build_atomistic_model(
                        design,
                        frame_override=transported_atom_frames(
                            reference_frames, motion
                        ),
                        apply_design_geometry=False,
                    )
                candidate_xyz = xyz(candidate)
                assert [
                    atom_identity(atom) for atom in candidate.atoms
                ] == reference_identity
                assert candidate.bonds == reference.bonds
                expected_xyz = np.array(
                    [
                        expected[(atom.helix_id, atom.bp_index)][0] @ point
                        + expected[(atom.helix_id, atom.bp_index)][1]
                        for atom, point in zip(reference.atoms, reference_xyz)
                    ]
                )
                errors = np.linalg.norm(candidate_xyz - expected_xyz, axis=1)
                rigid_atoms = [
                    i
                    for i, atom in enumerate(reference.atoms)
                    if atom.name not in FLEXIBLE_NAMES
                ]
                point_errors = []
                for record in manifest.records:
                    key = (record.render.helix_id, record.render.bp_index)
                    point = source_points[record.model_nucleotide_index]
                    rotation, translation = expected[key]
                    point_errors.append(
                        float(
                            np.linalg.norm(
                                transport_point(motion[key], point)
                                - (rotation @ point + translation)
                            )
                        )
                    )
                row = {
                    "phase_deg": phase,
                    "motion": mode,
                    "atoms": len(reference.atoms),
                    "point_max_error_nm": max(point_errors),
                    "rigid_atom_max_error_nm": float(max(errors[rigid_atoms])),
                    "all_atom_max_error_nm": float(max(errors)),
                    "reference_diagnostics": _model_diagnostics(design, reference),
                    "candidate_diagnostics": _model_diagnostics(design, candidate),
                    "junctions": [
                        {
                            "serials": [i, j],
                            "identities": [
                                reference_identity[i],
                                reference_identity[j],
                            ],
                            "reference_length_nm": float(
                                np.linalg.norm(reference_xyz[i] - reference_xyz[j])
                            ),
                            "candidate_length_nm": float(
                                np.linalg.norm(candidate_xyz[i] - candidate_xyz[j])
                            ),
                        }
                        for i, j in reference.bonds
                        if reference.atoms[i].helix_id != reference.atoms[j].helix_id
                    ],
                }
                results.append(row)
                print(
                    json.dumps(
                        {k: v for k, v in row.items() if "diagnostics" not in k}
                    ),
                    flush=True,
                )
                if mode == "zero":
                    from backend.core.mrdna_runner import build_md_seed_override

                    production = build_atomistic_model(
                        design,
                        nuc_pos_override=build_md_seed_override(design, psf, pdb),
                        apply_design_geometry=False,
                    )
                    assert [
                        atom_identity(atom) for atom in production.atoms
                    ] == reference_identity
                    assert production.bonds == reference.bonds
                    models = {
                        "reference": reference,
                        "current": production,
                        "candidate": candidate,
                    }
                    positions = {side: xyz(model) for side, model in models.items()}
                    diagnostics = {
                        side: _model_diagnostics(design, model)
                        for side, model in models.items()
                    }
                    affected, displacement = _affected_serials(
                        production,
                        candidate,
                        diagnostics["current"],
                        diagnostics["candidate"],
                    )
                    bundle = {
                        "phase_deg": phase,
                        "read_only": True,
                        "ready_for_review": False,
                        "purpose": "Production zero-step MD seed versus isolated particle-frame transport; native reference retained.",
                        "construction": [
                            "Open Examples/2hb_xover_val.nadoc: two helices, 140 nucleotides; preserve the topology.",
                            "Phase sweep only: resolve native helix frames, detach their diagnostic grid normalization, and roll those frames. Phase zero must match the native atoms exactly. No swept design is saved.",
                            "Generate fine mrDNA initial particles and read those same particles with zero dynamics steps.",
                            "Current: the production MD-seed override with default smoothing, followed by the atomistic builder.",
                            "Candidate: measure motion between the actual initial/final particle frames so PDB rounding is not treated as motion. Uniform rigid motion transports the existing native atoms exactly, including linkers. Nonrigid motion transports native atom frames through the same atomistic builder.",
                            "This is an isolated diagnostic program, not an authored feature-log operation or a simulation result.",
                        ],
                        "source": str(source.relative_to(ROOT)),
                        "source_sha256": hashlib.sha256(
                            source.read_bytes()
                        ).hexdigest(),
                        "affected_atom_serials": affected,
                        "displacement": displacement,
                        "defect_atom_serials": {
                            s: _defect_serials(d) for s, d in diagnostics.items()
                        },
                        "junctions": [
                            {
                                "serials": [i, j],
                                "identities": [
                                    reference_identity[i],
                                    reference_identity[j],
                                ],
                                "length_nm": {
                                    s: float(
                                        np.linalg.norm(
                                            positions[s][i] - positions[s][j]
                                        )
                                    )
                                    for s, m in models.items()
                                },
                                "max_endpoint_displacement_nm": float(
                                    max(
                                        np.linalg.norm(
                                            positions["candidate"][k]
                                            - positions["current"][k]
                                        )
                                        for k in (i, j)
                                    )
                                ),
                                "defects": {
                                    s: junction_defects(m, diagnostics[s], (i, j))
                                    for s, m in models.items()
                                },
                            }
                            for i, j in reference.bonds
                            if reference.atoms[i].helix_id
                            != reference.atoms[j].helix_id
                        ],
                        **{
                            side: {
                                **atomistic_to_json(model),
                                "atoms": [asdict(a) for a in model.atoms],
                                "diagnostics": diagnostics[side],
                            }
                            for side, model in models.items()
                        },
                    }
                    artifact = (
                        "frame-reconstruction.preliminary.json.gz"
                        if phase == 0
                        else f"phase-{phase:03d}.json.gz"
                    )
                    row["zero_step_artifact"] = artifact
                    row["production_diagnostics"] = diagnostics["current"]
                    with gzip.open(output / artifact, "wt") as stream:
                        json.dump(bundle, stream, separators=(",", ":"))
                assert design.model_dump_json() == snapshot
        assert original.model_dump_json() == original_snapshot
        size = sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file())
    report = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "code_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "experiments/mrdna_frame_candidate.py",
                "experiments/mrdna_frame_qualification.py",
                "backend/core/mrdna_bridge.py",
                "backend/core/mrdna_decoder.py",
                "backend/core/mrdna_runner.py",
                "backend/core/atomistic.py",
            )
        },
        "rows": results,
        "cleanup": {
            "path": str(scratch),
            "absent": not scratch.exists(),
            "bytes_removed": size,
        },
        "limits": [
            "No dynamics, production placement or geometry oracle changes.",
            "Only direct paired fine sites; ssDNA, interpolated sites and loop copies remain unsupported.",
            "Flexible linker atoms are reported separately; no tolerance is relaxed to hide reconstruction drift.",
            "This is qualification evidence, not authorization or an approval-ready UI artifact.",
        ],
    }
    (output / "frame-qualification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase-step", type=int, default=10)
    args = parser.parse_args()
    if not 0 < args.phase_step <= 360:
        parser.error("--phase-step must be between 1 and 360")
    qualify(args.output, range(0, 360, args.phase_step))
