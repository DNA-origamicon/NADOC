"""Train isolated local predictor and evaluate whole-design holdouts on CPU."""

from __future__ import annotations
import argparse
import io
import json
import time
from pathlib import Path
import numpy as np
from backend.core.exp_atomistic import native_atoms, psf_dna_atoms
from backend.core.exp_local import prepare, psf_block, train, predict, geometry
from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.namd_topology import build_charmm_psfgen_topology
from tools.train_exp_regression import sha


def verify_covalent_identity(case, native_psf, native_bonds):
    """Atom identity equality alone does not prove matching covalent topology."""
    _, native_rows = psf_dna_atoms(io.StringIO(native_psf))
    native_index = {identity: i for i, (_, identity, _) in enumerate(native_rows)}
    source = Path(case["package"]) / case["psf"]
    with source.open() as stream:
        _, rows = psf_dna_atoms(stream)
        if set(native_index) != {identity for _, identity, _ in rows}:
            raise ValueError("Native/trajectory DNA atom identity mismatch")
        mapping = {index: native_index[identity] for index, identity, _ in rows}
        for line in stream:
            if "!NBOND" in line:
                count = int(line.split()[0])
                break
        actual = set()
        read = 0
        for line in stream:
            fields = list(map(int, line.split()))
            for a, b in zip(fields[::2], fields[1::2]):
                a, b = a - 1, b - 1
                if a in mapping and b in mapping:
                    actual.add(tuple(sorted((mapping[a], mapping[b]))))
                read += 1
            if read >= count:
                break
    expected = {tuple(sorted(pair)) for pair in native_bonds.tolist()}
    report = dict(
        native_dna_bonds=len(expected),
        trajectory_dna_bonds=len(actual),
        native_only=len(expected - actual),
        trajectory_only=len(actual - expected),
    )
    if expected != actual:
        raise ValueError(
            f"{case['name']}: native/trajectory covalent mismatch {report}"
        )
    return report


def run(root):
    started = time.monotonic()
    cached = Path(".development-artifacts/exp_atoms_20261007")
    cases = json.loads((root / "cases.json").read_text())
    all_data = {}
    for case in cases:
        name = case["name"]
        out = root / name
        target = None
        if name != "platform":
            provenance = json.loads(
                (cached / "training" / f"{name}_provenance.json").read_text()
            )
            if sha(case["design"]) != provenance["design_sha256"]:
                raise ValueError(f"{name}: design changed since atom-label extraction")
            sample = np.load(cached / "training" / f"{name}_atoms.npz")
            native = dict(
                positions_nm=sample["input_nm"],
                names=sample["names"],
                residue_index=sample["residue_index"],
                keys=json.loads(str(sample["keys_json"])),
            )
            psf = (cached / f"{name}.psf").read_text()
            target = sample["target_nm"]
        else:
            design = Design.model_validate_json((out / "design.json").read_text())
            native = native_atoms(design)
            # The second build retains exact PSF bonds for the diagnostic artifact.
            topology = build_charmm_psfgen_topology(
                design, atomistic_model=build_atomistic_model(design)
            )
            psf = topology.psf_text
            (out / "native.psf").write_text(psf)
            (out / "native.pdb").write_text(topology.pdb_text)
        bonds = psf_block(psf, "!NBOND", 2)
        if name != "platform":
            topology_check = verify_covalent_identity(case, psf, bonds)
            (out / "topology_identity.json").write_text(
                json.dumps(topology_check, indent=2)
            )
        data = prepare(native, bonds)
        all_data[name] = (data, target)
        np.savez_compressed(
            out / "native.npz",
            positions_nm=data["x"],
            names=data["names"],
            residue_index=data["ri"],
            keys_json=json.dumps(data["keys"]),
            bonds=bonds,
        )
        print(
            "Prepared",
            name,
            len(data["x"]),
            "atoms",
            len(data["centers"]),
            "nucleotides",
            len(data["ij"]),
            "edges",
            flush=True,
        )
    start = time.monotonic()
    model = train([s for s in all_data.values() if s[1] is not None])
    model["model_card"] = dict(
        id="exp-local-rigid-v1",
        trained_designs=["6hb_0xT", "24hb_0xT"],
        limits="Two finite-window means, historical Na-neutralized/Mg conditions. No equilibrium certification. Rigid native nucleotides; soft inter-residue bond and gross-clash constraints, no angle/torsion/ion/solvent energy. All atoms including H; no extra-base training.",
        source_hashes={c["name"]: sha(root / c["name"] / "design.json") for c in cases},
    )
    training_seconds = time.monotonic() - start
    (root / "model.json").write_text(json.dumps(model, indent=2))
    report = dict(
        training_seconds=training_seconds,
        learned_coefficients=6
        + sum(np.asarray(model[k]["coefficients"]).size for k in ["rotation", "edge"]),
        cases={},
    )
    for name, (data, target) in all_data.items():
        start = time.monotonic()
        # Fit held-out design without any atoms, frames or labels from that design.
        validation_model = (
            train([s for k, s in all_data.items() if k != name and s[1] is not None])
            if target is not None
            else model
        )
        (root / name / "evaluation_model.json").write_text(json.dumps(validation_model))
        prediction_started = time.monotonic()
        prediction, raw, details = predict(data, validation_model)
        details["core_prediction_seconds"] = time.monotonic() - prediction_started
        graph_model = train(
            [
                s
                for k, s in all_data.items()
                if (k != name or target is None) and s[1] is not None
            ],
            use_global_prior=False,
        )
        graph_only, _, _ = predict(data, graph_model, constrain=False)
        np.savez_compressed(
            root / name / "local.npz",
            positions_nm=prediction,
            raw_nm=raw,
            graph_only_nm=graph_only,
        )
        details.update(
            seconds=time.monotonic() - start,
            native_geometry=geometry(data, data["x"]),
            raw_geometry=geometry(data, raw),
            constrained_geometry=geometry(data, prediction),
            evaluation="whole-design holdout"
            if target is not None
            else "no NAMD reference",
        )
        if target is not None:

            def rms(x):
                return float(np.sqrt(np.mean(np.sum((x - target) ** 2, axis=1))))

            details["aligned_training_frame_atom_rms_nm"] = dict(
                native=rms(data["x"]), raw=rms(raw), constrained=rms(prediction)
            )
        report["cases"][name] = details
        (root / "local_review.json").write_text(json.dumps(report, indent=2))
        print(name, json.dumps(details), flush=True)
    report["total_seconds"] = time.monotonic() - started
    (root / "local_review.json").write_text(json.dumps(report, indent=2))
    print("COMPLETED", report["total_seconds"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
