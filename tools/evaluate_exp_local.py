"""Compare isolated local/strain models with pinned DeepSNUPI on matched nodes."""

from __future__ import annotations
import argparse
import json
from dataclasses import asdict
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.models import Design
from backend.core.exp_regression import predict_positions
from backend.physics.fem_solver import build_fem_mesh
from backend.physics import snupi_reference as sr


def decorate_prediction(initial, prediction, native_centers, mesh_centers):
    """Transport native C1-midpoint offsets with upstream predicted node triads.

    This matches a common observable without interpreting strand polarity or
    claiming that DeepSNUPI provides an atomistic structure.
    """
    r, t, _ = sr._kabsch(initial[:, :3], mesh_centers)
    offset = (native_centers - (initial[:, :3] @ r.T + t)) @ r
    initial_rotation = Rotation.from_rotvec(initial[:, 3:6]).as_matrix()
    final_rotation = Rotation.from_rotvec(prediction[:, 3:6]).as_matrix()
    body = np.einsum("nji,nj->ni", initial_rotation, offset)
    moved = np.einsum("nij,nj->ni", final_rotation, body)
    return (prediction[:, :3] + moved) @ r.T + t


def evaluate(root, prediction_file="local.npz", suffix=""):
    results = {}
    for name in ["6hb_0xT", "24hb_0xT", "platform"]:
        out = root / name
        design = Design.model_validate_json((out / "design.json").read_text())
        native = np.load(out / "native.npz")
        local = np.load(out / prediction_file)
        deep = np.load(out / "deep.npz")
        info = json.loads((out / "deep.json").read_text())
        labels = json.loads((out / "labels.json").read_text())
        source = Path(info["source"])
        nodes = sr.parse_snupi_pdb(source.parent / f"{name}_INIT_STRCT.pdb")
        if not np.allclose(
            np.array([n.pos for n in nodes]), deep["input"][:, :3], atol=1e-3
        ):
            raise ValueError("SNUPI PDB/graph order mismatch")
        mesh = build_fem_mesh(design, material="snupi")
        meshkeys = [(n.helix_id, int(n.global_bp)) for n in mesh.nodes]
        match = sr.match_nodes(
            nodes,
            meshkeys,
            np.array([n.position for n in mesh.nodes]),
            labels=labels,
            residual_tol_nm=0.1,
            min_coverage=1.0,
        )
        (out / "mapping.json").write_text(json.dumps(asdict(match), indent=2))
        if not match.ok or match.n_matched != len(nodes):
            raise ValueError(f"{name}: incomplete/unreliable node mapping: {match}")
        keys = json.loads(str(native["keys_json"]))
        c1 = {
            tuple(keys[int(r)]): i
            for i, (n, r) in enumerate(zip(native["names"], native["residue_index"]))
            if n == "C1'"
        }
        si, first, second, mapped = [], [], [], []
        for s, m in sorted(match.pairs):
            h, bp = meshkeys[m]
            first.append(c1[(h, bp, "FORWARD")])
            second.append(c1[(h, bp, "REVERSE")])
            si.append(s)
            mapped.append([h, bp])
        first, second = np.array(first), np.array(second)

        def center(x):
            return 0.5 * (x[first] + x[second])

        target = None
        if name != "platform":
            target = np.load(
                Path(".development-artifacts/exp_atoms_20261007/training")
                / f"{name}_atoms.npz"
            )
        reference = center(
            target["target_nm"] if target is not None else native["positions_nm"]
        )
        model = json.loads((out / "evaluation_model.json").read_text())
        refined = np.load(out / "deep_refined.npy")
        mesh_mapped = np.array([mesh.nodes[m].position for s, m in sorted(match.pairs)])
        decorated = decorate_prediction(
            deep["input"][si, :6],
            refined[si, :6],
            center(native["positions_nm"]),
            mesh_mapped,
        )
        methods = {
            "native": center(native["positions_nm"]),
            "strain_baseline": center(
                predict_positions(native["positions_nm"], model["global_coefficients"])
            ),
            "local_graph_only_raw": center(local["graph_only_nm"]),
            "local_hybrid_raw": center(local["raw_nm"]),
            "local_hybrid_constrained": center(local["positions_nm"]),
            "deepsnupi_raw": deep["prediction"][si, :3],
            "deepsnupi_refined": refined[si, :3],
            "deepsnupi_refined_C1_observable": decorated,
        }
        metrics, aligned = {}, {}
        for method, x in methods.items():
            r, t, error = sr._kabsch(x, reference)
            aligned[method] = x @ r.T + t
            metrics[method] = {"rms_to_reference_nm": error}
            if target is not None:
                metrics[method]["block_rms_nm"] = [
                    sr._kabsch(x, center(block))[2]
                    for block in target["block_means_nm"]
                ]
        pairwise = {}
        for i, (a, x) in enumerate(methods.items()):
            for b, y in list(methods.items())[i + 1 :]:
                pairwise[a + " vs " + b] = sr._kabsch(x, y)[2]
        report = dict(
            nodes=len(reference),
            nucleotides=len(keys),
            atoms=len(native["positions_nm"]),
            mapping={k: v for k, v in asdict(match).items() if k != "pairs"},
            reference="NAMD late-window mean"
            if target is not None
            else "native NADOC; not ground truth",
            evaluation="whole-design holdout"
            if target is not None
            else "unlabelled transfer; disagreement only",
            methods=metrics,
            pairwise_rms_nm=pairwise,
            deep=info,
        )
        if target is not None:
            report["first_last_block_rms_nm"] = sr._kabsch(
                center(target["block_means_nm"][0]),
                center(target["block_means_nm"][-1]),
            )[2]
            report["all_atom_rms_nm"] = {}
            for method, x in [
                ("native", native["positions_nm"]),
                ("local", local["positions_nm"]),
                (
                    "strain",
                    predict_positions(
                        native["positions_nm"], model["global_coefficients"]
                    ),
                ),
            ]:
                report["all_atom_rms_nm"][method] = sr._kabsch(x, target["target_nm"])[
                    2
                ]
        np.savez_compressed(
            out / f"comparison{suffix}.npz",
            reference=reference,
            keys_json=json.dumps(mapped),
            **aligned,
        )
        (out / f"comparison{suffix}.json").write_text(json.dumps(report, indent=2))
        results[name] = report
        (root / f"comparison{suffix}.json").write_text(json.dumps(results, indent=2))
        print(name, json.dumps(metrics), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.output)
