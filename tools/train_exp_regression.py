"""CPU-only, mapped 0xT pilot: extract, fit, evaluate, and write a review.

Run with OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1, PYTHONPATH=.
Outputs/checkpoints belong under .development-artifacts until explicitly installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from backend.core.atomistic import _build_sequence_map
from backend.core.atomistic_to_nadoc import (
    _unwrap_min_image,
    build_active_design_reference,
    build_namd_coarse_reference,
    load_segid_chain_map,
)
from backend.core.dcd_fast import read_layout
from backend.core.exp_regression import (
    FEATURE_NAMES,
    FEATURE_SCHEMA,
    fit,
    predict_positions,
)
from backend.core.md_trajectory import _DcdPrefixFile
from backend.core.models import Design


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rigid_align(x, reference):
    q = x - x.mean(0)
    ref = reference - reference.mean(0)
    u, _, vt = np.linalg.svd(q.T @ ref)
    return q @ u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt + reference.mean(0)


def rms(x):
    return float(np.sqrt(np.mean(np.sum(np.asarray(x) ** 2, axis=-1))))


def extract(case, out, samples):
    started = time.monotonic()
    package = Path(case["package"])
    source = Path(case["design"])
    design = Design.model_validate_json(source.read_text()).without_reference_geometry()
    if any(c.extra_bases for c in design.crossovers):
        raise ValueError("Training cohort requested by user is 0xT only")
    frozen = out / (case["name"] + "_design.json")
    frozen.write_text(design.model_dump_json())
    psf, pdb, dcd = [package / case[k] for k in ("psf", "pdb", "dcd")]
    layout = read_layout(dcd)
    segment_map = load_segid_chain_map(package)
    cm, package_ref = build_namd_coarse_reference(design, pdb, segment_map)
    native = build_active_design_reference(design)
    sequence = _build_sequence_map(design)
    keys = sorted(native)
    row_for = {key: i for i, key in enumerate(keys)}
    ids, rows, segments, residues = [], [], [], {}
    dna = {"ADE": "A", "THY": "T", "GUA": "G", "CYT": "C"}
    with psf.open() as stream:
        for line in stream:
            if "!NATOM" not in line:
                continue
            n_atoms = int(line.split()[0])
            if n_atoms != layout.n_atoms:
                raise ValueError("PSF/DCD atom count mismatch")
            for atom in range(n_atoms):
                fields = next(stream).split()
                if fields[3] not in dna:
                    continue
                seg, resid = fields[1], int(fields[2])
                key = cm.get((segment_map.get(seg), resid))
                if key not in row_for:
                    raise ValueError(f"Unmapped DNA residue: {seg}:{resid}")
                residues[(seg, resid)] = (key, dna[fields[3]])
                if fields[4] == "P":
                    ids.append(atom)
                    rows.append(row_for[key])
                    segments.append(seg)
            break
    mismatches = [
        (key, base, sequence.get(key))
        for key, base in residues.values()
        if sequence.get(key) not in {None, "N", base}
    ]
    if mismatches:
        raise ValueError(
            f"Design/PSF sequence mismatch: {len(mismatches)}, first={mismatches[0]}"
        )
    if len(residues) != len(native) or len(set(rows)) != len(rows):
        raise ValueError("Incomplete or non-unique residue mapping")
    known = sum(
        sequence.get(key) in "ACGT" if sequence.get(key) else False
        for key, _ in residues.values()
    )
    if known != len(residues):
        raise ValueError(
            "All residue identities must be sequence-verified for this pilot"
        )
    x = np.array([native[k] for k in keys])
    rows, ids = np.array(rows), np.array(ids)
    ref = x[rows]
    packaged = np.array([package_ref[keys[i]] for i in rows])
    package_alignment = rigid_align(packaged, ref)
    reference_rms = rms(package_alignment - ref)
    # Gross mapping errors are not training examples. This is a data integrity
    # check, never an inference design-type restriction.
    if reference_rms > 0.6:
        raise ValueError(
            f"Recovered mapping geometric discrepancy {reference_rms:.3f} nm"
        )
    indices = np.unique(
        np.linspace(layout.n_frames // 2, layout.n_frames - 1, samples, dtype=int)
    )
    frames = []
    unwrap_max = 0.0
    reader = _DcdPrefixFile(dcd, int(ids.max()) + 1)
    try:
        for index in indices:
            coords, dims = reader.frame(int(index))
            raw = coords[ids].astype(float) / 10
            if dims is None or not np.allclose(dims[3:], 90, atol=0.01):
                raise ValueError("Pilot reader expects an orthorhombic NAMD cell")
            unwrapped = _unwrap_min_image(raw, dims[:3] / 10, segments)
            correction = float(np.max(np.linalg.norm(unwrapped - raw, axis=1)))
            unwrap_max = max(unwrap_max, correction)
            # The selected trajectories were written wrapAll off. If a strand
            # crosses images, whole-complex imaging must be added before fitting.
            if correction > 0.01:
                raise ValueError(
                    "Periodic image split requires whole-complex reconstruction"
                )
            frames.append(rigid_align(unwrapped, ref))
    finally:
        reader.close()
    frames = np.array(frames)
    blocks = np.array([block.mean(0) for block in np.array_split(frames, 4)])
    # Keep per-nucleotide targets and motif metadata, not just the fitted six
    # coefficients, so the next encoder can learn explicit crossover features.
    np.savez_compressed(
        out / (case["name"] + "_dataset.npz"),
        input_nm=x,
        mapped_rows=rows,
        target_nm=frames.mean(0),
        block_means_nm=blocks,
        frames_nm=frames.astype(np.float32),
        keys_json=json.dumps(keys),
        extra_base_count=np.zeros(len(x), dtype=np.int32),
    )
    metadata = {
        **case,
        "design_sha256": sha(source),
        "frozen_design_sha256": sha(frozen),
        "psf_sha256": sha(psf),
        "pdb_sha256": sha(pdb),
        "dcd_bytes": dcd.stat().st_size,
        "dcd_frames_at_read": layout.n_frames,
        "sample_frame_indices": indices.tolist(),
        "samples": len(indices),
        "sample_header_time_ns": [
            (layout.first_ps + int(i) * layout.delta_ps) / 1000
            for i in (indices[0], indices[-1])
        ],
        "native_nucleotides": len(x),
        "mapped_phosphates": len(rows),
        "sequence_verified_residues": known,
        "sequence_mismatches": len(mismatches),
        "package_vs_current_native_rms_nm": reference_rms,
        "max_unwrap_correction_nm": unwrap_max,
        "first_last_block_rms_nm": rms(blocks[-1] - blocks[0]),
        "mean_block_rms_to_full_mean_nm": float(
            np.mean([rms(b - frames.mean(0)) for b in blocks])
        ),
        "seconds": time.monotonic() - started,
    }
    (out / (case["name"] + "_provenance.json")).write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    print(json.dumps(metadata), flush=True)
    return dict(
        input_nm=x,
        mapped_rows=rows,
        target_nm=frames.mean(0),
        blocks=blocks,
        name=case["name"],
        metadata=metadata,
    )


def evaluate(sample, coefficients):
    rows = sample["mapped_rows"]
    baseline = rms(sample["input_nm"][rows] - sample["target_nm"])
    predicted = predict_positions(sample["input_nm"], coefficients)[rows]
    error = rms(predicted - sample["target_nm"])
    return {
        "design": sample["name"],
        "baseline_rms_nm": baseline,
        "prediction_rms_nm": error,
        "relative_improvement": 1 - error / baseline,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=256)
    args = parser.parse_args()
    if args.samples < 16:
        parser.error("Use at least 16 frames for the four-block audit")
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        manifest = json.loads(args.manifest.read_text())
        cases = manifest["cases"]
        data = [extract(c, args.output, args.samples) for c in cases]
        validation = []
        for i, held in enumerate(data):
            coefficients = fit([d for j, d in enumerate(data) if i != j])
            validation.append(evaluate(held, coefficients))
        coefficients = fit(data)
        report = {
            "status": "completed",
            "target": "aligned last-half production-window phosphate mean",
            "alpha": 0.01,
            "leave_one_design_out": validation,
            "combined_fit_training_errors": [evaluate(d, coefficients) for d in data],
            "total_seconds": time.monotonic() - started,
            "limitations": [
                "two bundle sizes, one selected lineage each",
                "finite-window means; not certified equilibrium",
                "six global modes cannot learn local crossover or extra-base physics",
                "actual periodic image contacts and atomistic seeding not validated",
            ],
        }
        passed = all(r["relative_improvement"] > 0 for r in validation)
        report["review"] = (
            "Both size holdouts improve on native geometry"
            if passed
            else "At least one size holdout fails to improve: infrastructure pilot only"
        )
        model = {
            "feature_schema": FEATURE_SCHEMA,
            "features": FEATURE_NAMES,
            "coefficients": coefficients.tolist(),
            "training_manifest_sha256": sha(args.manifest),
            "training_inputs": {
                d["name"]: {
                    "design_sha256": d["metadata"]["frozen_design_sha256"],
                    "dataset_sha256": sha(args.output / (d["name"] + "_dataset.npz")),
                }
                for d in data
            },
            "model_card": {
                "id": "exp-0xT-strain-v1",
                "trained_designs": [d["name"] for d in data],
                "trained_extra_base_counts": [0],
                "target": report["target"],
                "limits": "0xT 6HB/24HB infrastructure pilot; finite-window means, no equilibrium or seed validation.",
                "conditions": manifest.get("conditions", {}),
                "validation": validation,
                "review": report["review"],
            },
        }
        if model["model_card"]["conditions"].get("ions"):
            model["model_card"]["limits"] += (
                " " + model["model_card"]["conditions"]["ions"] + "."
            )
        (args.output / "model.json").write_text(json.dumps(model, indent=2) + "\n")
        (args.output / "review.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    except Exception as exc:
        (args.output / "review.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                    "total_seconds": time.monotonic() - started,
                },
                indent=2,
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    main()
