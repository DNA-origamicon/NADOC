"""Prepare zero-step MRDNA evidence without changing production or running dynamics.

The preliminary bundle is deliberately not registered as an approval-ready UI
case: phase controls and nonzero atomistic transport remain to be qualified.
"""

from pathlib import Path
import json
import os
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def build_review(output):
    from scripts.run_deformation_history_e2e import storage_parent

    OUT = Path(output)
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="__mrdna-zero-", dir=storage_parent()
    ) as tmp:
        root = Path(tmp)
        print("Owned scratch", root, flush=True)
        for name in ("cache", "tmp"):
            (root / name).mkdir()
        os.environ.update(
            TMPDIR=str(root / "tmp"),
            TMP=str(root / "tmp"),
            TEMP=str(root / "tmp"),
            XDG_CACHE_HOME=str(root / "cache"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        import numpy as np
        from backend.core.models import Design
        from backend.core.mrdna_bridge import (
            _build_nt_arrays,
            nuc_pos_override_from_arbd_strands,
        )
        from backend.core.mrdna_decoder import (
            decode_mrdna_frame,
            _mrdna_seed_reference_by_key,
        )
        from backend.core.mrdna_manifest import (
            build_mrdna_nucleotide_manifest,
            bind_manifest_to_mrdna_particles,
        )
        from backend.parameterization.mrdna_inject import (
            CrossoverPotentialOverride,
            mrdna_model_from_nadoc_parameterized,
        )
        from tests.test_mrdna_pipeline import _ideal_positions

        design = Design.model_validate_json(
            (REPO / "Examples/2hb_xover_val.nadoc").read_text()
        )
        native_snapshot = design.model_dump_json()
        arrays = _build_nt_arrays(design, return_nt_key=True, return_identity=True)
        positions, keys = arrays[0] / 10, arrays[6]
        model = mrdna_model_from_nadoc_parameterized(
            design, CrossoverPotentialOverride.from_database("T0")
        )
        model.clear_beads()
        model.generate_bead_model(1, 1, local_twist=True, escapable_twist=False)
        psf, pdb = root / "zero-2.psf", root / "zero-2.pdb"
        model.write_psf(str(psf))
        model.write_pdb(str(pdb))
        manifest = bind_manifest_to_mrdna_particles(
            build_mrdna_nucleotide_manifest(
                design, design_fingerprint="zero-step-review"
            ),
            model,
        )
        manifest.write(root)
        print("Native fine model ready", len(manifest.records), flush=True)
        old = nuc_pos_override_from_arbd_strands(
            design, str(psf), str(pdb), frame=0, sigma_nt=0
        )
        current = decode_mrdna_frame(root, psf, pdb, design=design, frame=0)
        native = _mrdna_seed_reference_by_key(design)
        decoded = {
            (p["helix_id"], p["bp_index"], p["direction"], p["copy"]): p
            for p in current["positions"]
        }
        import MDAnalysis as mda
        from scipy.spatial.transform import Rotation

        universe = mda.Universe(str(psf), str(pdb))
        xyz = universe.atoms.positions.astype(float) / 10
        from experiments.mrdna_frame_candidate import (
            paired_particle_motion,
            transport_point,
        )

        motion = paired_particle_motion(
            manifest, positions, arrays[4], [a.name for a in universe.atoms], xyz
        )
        angle_rows = [
            {
                "key": list(key),
                "center_error_nm": float(np.linalg.norm(after - before)),
                "orientation_error_deg": float(
                    Rotation.from_matrix(rotation).magnitude() * 180 / np.pi
                ),
            }
            for key, (before, after, rotation) in motion.items()
        ]
        from backend.core.mrdna_runner import build_md_seed_override

        production = build_md_seed_override(design, psf, pdb)
        ideal = _ideal_positions(design)
        rows = []
        for key, index in keys.items():
            if key not in decoded or key not in native or key[:3] not in old:
                continue
            row = {
                "key": list(key),
                "seed": positions[index].tolist(),
                "native": native[key]["backbone_position"],
                "old": old[key[:3]].tolist(),
                "production": production[key[:3]].tolist(),
                "manifest": decoded[key]["backbone_position"],
                "old_oracle": ideal[key[:3]].tolist(),
            }
            row["relative_frame"] = transport_point(
                motion[key[:2]], positions[index]
            ).tolist()
            row["relative_native"] = transport_point(
                motion[key[:2]], native[key]["backbone_position"]
            ).tolist()
            rows.append(row)

        def summary(left, right):
            errors = np.array(
                [np.linalg.norm(np.array(r[left]) - r[right]) for r in rows]
            )
            return {
                "count": len(errors),
                "mean_nm": float(np.mean(errors)),
                "max_nm": float(np.max(errors)),
            }

        comparisons = {
            f"{left}_vs_{right}": summary(left, right)
            for left, right in (
                ("seed", "native"),
                ("old", "seed"),
                ("old", "native"),
                ("old", "old_oracle"),
                ("production", "seed"),
                ("manifest", "seed"),
                ("manifest", "native"),
                ("relative_frame", "seed"),
                ("relative_native", "native"),
            )
        }
        assert len(rows) == len(keys) == len(manifest.records) == 140
        assert comparisons["relative_frame_vs_seed"]["max_nm"] < 1e-4
        assert comparisons["relative_native_vs_native"]["max_nm"] < 1e-4
        result = {
            "comparisons": comparisons,
            "quality": current["quality"],
            "rows": rows,
            "particle_frames": angle_rows,
        }
        from backend.core.atomistic import build_atomistic_model, atomistic_to_json
        from backend.core.molecular_placement_audit import _model_diagnostics

        models = {"native": build_atomistic_model(design)}
        for side, column in (
            ("old", "old"),
            ("current", "production"),
            ("candidate", "relative_frame"),
            ("exact_input", "seed"),
        ):
            override = {tuple(row["key"][:3]): np.asarray(row[column]) for row in rows}
            models[side] = build_atomistic_model(
                design, nuc_pos_override=override, apply_design_geometry=False
            )
        identity = lambda a: (
            a.strand_id,
            a.helix_id,
            a.bp_index,
            a.direction,
            a.copy_k,
            a.crossover_id,
            a.extra_base_k,
            a.name,
        )
        for model in models.values():
            assert model.bonds == models["native"].bonds
            assert list(map(identity, model.atoms)) == list(
                map(identity, models["native"].atoms)
            )
        xyz_by_side = {
            side: np.array([[a.x, a.y, a.z] for a in model.atoms])
            for side, model in models.items()
        }
        result["atomistic"] = {}
        for side, model in models.items():
            error = np.linalg.norm(xyz_by_side[side] - xyz_by_side["native"], axis=1)
            validation = _model_diagnostics(design, model)
            result["atomistic"][side] = {
                "atoms": len(model.atoms),
                "mean_displacement_from_native_nm": float(np.mean(error)),
                "max_displacement_from_native_nm": float(np.max(error)),
                "validation": validation,
                "largest_displacements": [
                    {
                        "serial": int(i),
                        "identity": identity(model.atoms[i]),
                        "distance_nm": float(error[i]),
                    }
                    for i in np.argsort(error)[-20:][::-1]
                ],
            }
        # Retain every atom for later in-app review, with exact detector findings.
        # This preliminary bundle is not an approval request: phase controls and
        # atomistic reconstruction of nonzero motion are still unqualified.
        import gzip, hashlib
        from backend.core.molecular_placement_audit import (
            _affected_serials,
            _defect_serials,
        )

        diagnostics = {
            side: result["atomistic"][side]["validation"]
            for side in ("current", "candidate")
        }
        affected, displacement = _affected_serials(
            models["current"],
            models["candidate"],
            diagnostics["current"],
            diagnostics["candidate"],
        )
        junctions = []
        for i, j in models["native"].bonds:
            a, b = models["native"].atoms[i], models["native"].atoms[j]
            if a.helix_id == b.helix_id:
                continue
            junctions.append(
                {
                    "serials": [i, j],
                    "identities": [identity(a), identity(b)],
                    "length_nm": {
                        side: float(np.linalg.norm(xyz[i] - xyz[j]))
                        for side, xyz in xyz_by_side.items()
                    },
                    "max_endpoint_displacement_nm": float(
                        max(
                            np.linalg.norm(
                                xyz_by_side["candidate"][k] - xyz_by_side["current"][k]
                            )
                            for k in (i, j)
                        )
                    ),
                }
            )
        result["junctions"] = junctions
        result["source_sha256"] = hashlib.sha256(
            (REPO / "Examples/2hb_xover_val.nadoc").read_bytes()
        ).hexdigest()
        result["code_sha256"] = {
            name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
            for name in (
                "backend/core/mrdna_bridge.py",
                "backend/core/mrdna_decoder.py",
                "backend/core/mrdna_runner.py",
                "backend/core/atomistic.py",
                "experiments/mrdna_frame_candidate.py",
                "experiments/mrdna_zero_step_review.py",
            )
        }
        result["limits"] = [
            "No ARBD steps or production simulations run.",
            "Current uses production MD seed override with default sigma_nt=1.5; old reproduces the failing sigma_nt=0 test.",
            "Candidate only diagnoses direct paired fine DNA sites; no production decoder changes.",
            "Nonzero atomistic transport, ssDNA, interpolated/coarse sites, loop copies and phase sweep remain unqualified.",
            "Raw CG input and native chemical backbone are distinct coordinate conventions.",
            "The default linker minimizer amplifies very small coordinate differences; exact-input control retained.",
        ]
        bundle = {
            "schema": "nadoc.mrdna-zero-step-review.preliminary.v1",
            "read_only": True,
            "ready_for_review": False,
            "construction": [
                "Open Examples/2hb_xover_val.nadoc: two helices, 140 nucleotides; retain topology.",
                "Generate the fine mrDNA initial coordinates: one DNA particle and one orientation particle per base pair.",
                "Read those same coordinates with zero dynamics steps.",
                "Current: existing production MD-seed decoder, default smoothing; then the existing atomistic builder.",
                "Candidate: transport the CG input sites by measured local particle motion; then the same atomistic builder. This is an isolated diagnostic, with no native feature-log edit.",
            ],
            "source": "Examples/2hb_xover_val.nadoc",
            "source_sha256": result["source_sha256"],
            "current_design": design.model_dump(mode="json"),
            "candidate_design": design.model_dump(mode="json"),
            **{
                side: {
                    **atomistic_to_json(models[side]),
                    "diagnostics": diagnostics[side],
                }
                for side in diagnostics
            },
            "native": atomistic_to_json(models["native"]),
            "affected_atom_serials": affected,
            "defect_atom_serials": {
                side: _defect_serials(d) for side, d in diagnostics.items()
            },
            "displacement": displacement,
            "junctions": junctions,
            "limits": result["limits"],
        }
        assert design.model_dump_json() == native_snapshot
        with gzip.open(OUT / "comparison.preliminary.json.gz", "wt") as stream:
            json.dump(bundle, stream, separators=(",", ":"))
        (OUT / "zero-step-comparison.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(comparisons, indent=2), flush=True)
        print(
            "atomistic",
            json.dumps(
                {
                    side: {
                        k: v
                        for k, v in row.items()
                        if k not in ("validation", "largest_displacements")
                    }
                    for side, row in result["atomistic"].items()
                }
            ),
            flush=True,
        )
        size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    assert not root.exists()
    (OUT / "probe-cleanup.json").write_text(
        json.dumps({"root": str(root), "absent": True, "bytes_removed": size}, indent=2)
    )
    print("Cleanup verified", root, flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO
        / ".development-artifacts/feature-history-focus/mrdna-decoder-review",
    )
    build_review(parser.parse_args().output)
