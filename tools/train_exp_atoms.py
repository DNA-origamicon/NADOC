"""CPU all-atom follow-up to the mapped 0xT Exp pilot. No dynamics are launched."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import time

import numpy as np

from backend.core.exp_atomistic import SCHEMA, native_atoms, psf_dna_atoms
from backend.core.exp_regression import FEATURE_NAMES, fit, predict_positions
from backend.core.dcd_fast import read_layout
from backend.core.md_trajectory import _DcdPrefixFile
from backend.core.models import Design
from tools.train_exp_regression import rms, sha


def extract(case, output, frames):
    design = Design.model_validate_json(Path(case["design"]).read_text())
    native = native_atoms(design)
    package = Path(case["package"])
    with (package / case["psf"]).open() as stream:
        total, rows = psf_dna_atoms(stream)
    actual = {identity: (index, resname) for index, identity, resname in rows}
    if set(actual) != set(native["identities"]):
        raise ValueError("Native and training all-atom identities differ")
    indices = np.array([actual[k][0] for k in native["identities"]])
    dcd = package / case["dcd"]
    layout = read_layout(dcd)
    if total != layout.n_atoms:
        raise ValueError("PSF/DCD count mismatch")
    selected = np.unique(
        np.linspace(layout.n_frames // 2, layout.n_frames - 1, frames, dtype=int)
    )
    x = native["positions_nm"]
    anchor = np.array([i for i, n in enumerate(native["names"]) if n == "P"])
    ref = x[anchor]
    centroid = ref.mean(0)
    blocks = np.zeros((4, len(x), 3))
    counts = np.zeros(4, dtype=int)
    reader = _DcdPrefixFile(dcd, int(indices.max()) + 1)
    try:
        for j, index in enumerate(selected):
            xyz, _ = reader.frame(int(index))
            xyz = xyz[indices].astype(float) / 10
            center = xyz[anchor].mean(0)
            u, _, vt = np.linalg.svd((xyz[anchor] - center).T @ (ref - centroid))
            rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
            aligned = (xyz - center) @ rotation + centroid
            block = min(3, j * 4 // len(selected))
            blocks[block] += aligned
            counts[block] += 1
    finally:
        reader.close()
    if not counts.all():
        raise ValueError("Insufficient sampled frames")
    means = blocks / counts[:, None, None]
    target = blocks.sum(0) / counts.sum()
    heavy = np.array([e != "H" for e in native["elements"]])
    np.savez_compressed(
        output / (case["name"] + "_atoms.npz"),
        input_nm=x,
        target_nm=target,
        block_means_nm=means,
        heavy=heavy,
        names=native["names"],
        residue_index=native["residue_index"],
        keys_json=json.dumps(native["keys"]),
    )
    meta = {
        "job_id": case["job_id"],
        "atoms": len(x),
        "heavy_atoms": int(heavy.sum()),
        "hydrogens": int((~heavy).sum()),
        "frames": len(selected),
        "frame_indices": selected.tolist(),
        "psf_sha256": sha(package / case["psf"]),
        "design_sha256": sha(case["design"]),
        "first_last_block_rms_nm": rms(means[-1] - means[0]),
    }
    (output / (case["name"] + "_provenance.json")).write_text(
        json.dumps(meta, indent=2)
    )
    print(case["name"], meta["atoms"], "atoms", flush=True)
    return dict(
        name=case["name"],
        input_nm=x,
        target_nm=target,
        mapped_rows=np.arange(len(x)),
        heavy=heavy,
    )


def evaluate(sample, coefficients):
    x, y = sample["input_nm"], sample["target_nm"]
    predicted = predict_positions(x, coefficients)
    return {
        "design": sample["name"],
        "native_all_atom_rms_nm": rms(x - y),
        "predicted_all_atom_rms_nm": rms(predicted - y),
        "native_heavy_atom_rms_nm": rms((x - y)[sample["heavy"]]),
        "predicted_heavy_atom_rms_nm": rms((predicted - y)[sample["heavy"]]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        manifest = json.loads(args.manifest.read_text())
        data = [extract(case, args.output, 128) for case in manifest["cases"]]
        folds = [
            evaluate(d, fit([other for other in data if other is not d])) for d in data
        ]
        coefficients = fit(data)
        card = {
            "id": "exp-0xT-atoms-v1",
            "trained_designs": [d["name"] for d in data],
            "trained_extra_base_counts": [0],
            "conditions": manifest["conditions"],
            "limits": "All DNA atoms including H; six global modes only. Historical Na-neutralized Mg runs. No equilibrium/seed validation.",
            "validation": folds,
        }
        model = {
            "feature_schema": SCHEMA,
            "features": FEATURE_NAMES,
            "coefficients": coefficients.tolist(),
            "model_card": card,
            "manifest_sha256": sha(args.manifest),
        }
        (args.output / "model.json").write_text(json.dumps(model, indent=2) + "\n")
        report = {
            "status": "completed",
            "seconds": time.monotonic() - started,
            "leave_one_size_out": folds,
            "training_errors": [evaluate(d, coefficients) for d in data],
        }
        (args.output / "review.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    except Exception as exc:
        (args.output / "review.json").write_text(
            json.dumps({"status": "failed", "error": str(exc)})
        )
        raise


if __name__ == "__main__":
    main()
