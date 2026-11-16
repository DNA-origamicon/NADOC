"""Reproduce exploratory isomer-specific oxDNA fits from retained NAMD data.

Reads trajectories only; writes numeric parameters and extraction provenance,
never a molecular structure. The third replica is a validation set, not blind:
all three trajectories were previously inspected in structural analyses.
"""

import argparse
import hashlib
import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np

from backend.physics.oxdna_cpd_fit import ATOM_NAMES, fit, particle_frame, relative_pose

FIT_IDS = ("edb512c46112", "d6bcdef3d59f")
CHECK_IDS = ("770c4764d1a3",)
REPLICAS = {
    "cis-syn": (*FIT_IDS, *CHECK_IDS),
    "cis-anti-I": ("e345c67349bf", "972af34aa9c5", "577c8d057768"),
    "trans-syn-I": ("37d39cc6b88f", "ffef0085e16d", "35254aa13b01"),
    "trans-syn-II": ("9b08bed08561", "395337bdb061", "94d5148b6911"),
}


def extract(record, isomer="cis-syn"):
    path = Path(record["files"][0]["path"])
    package = path.parent.parent
    manifest = package / "photoproduct_forcefield_manifest.json"
    raw = manifest.read_bytes()
    data = json.loads(raw)
    if len(data["lesions"]) != 1 or data["lesions"][0]["stereochemistry"] != isomer:
        raise ValueError("Wrong NAMD isomer")
    endpoints = sorted(
        data["topology_and_placement_audits"]["photoproduct_patch_audit"]["patches"][0][
            "endpoints"
        ],
        key=lambda e: e["endpoint"],
    )
    psf = package / record["config"]["structure"]
    universe = mda.Universe(str(psf), str(path))
    if len(universe.trajectory) != 1000 or not np.isclose(universe.trajectory.dt, 20.0):
        raise ValueError(
            "Expected the registered 20 ns, 20 ps cadence ordinary-mass replica"
        )
    indices = []
    for e in endpoints:
        indices.append(
            [
                universe.select_atoms(
                    f"segid {e['segid']} and resid {e['resid']} and name {name}"
                )[0].index
                for name in ATOM_NAMES
            ]
        )
    positions, rotations, times = [], [], []
    for frame in universe.trajectory[
        250::5
    ]:  # 5–20 ns at 100 ps cadence, ordinary-mass 2 fs runs
        atoms = universe.atoms.positions[np.array(indices)].copy()
        # Product is local; minimum-image both rings about the first N1.
        if frame.dimensions is not None:
            from MDAnalysis.lib.distances import minimize_vectors

            atoms = atoms[0, 0] + minimize_vectors(
                (atoms - atoms[0, 0]).reshape(-1, 3), frame.dimensions
            ).reshape(2, 7, 3)
        p, r = relative_pose(*[particle_frame(x) for x in atoms])
        positions.append(p)
        rotations.append(r)
        times.append(float(frame.time))
    stat = path.stat()
    provenance = {
        "job_id": record["job_id"],
        "trajectory": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sample_times_ps": times,
        "ordered_endpoints": endpoints,
        "psf_sha256": hashlib.sha256(psf.read_bytes()).hexdigest(),
        "forcefield_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "mapped_samples_sha256": hashlib.sha256(
            np.asarray(positions).tobytes() + np.asarray(rotations).tobytes()
        ).hexdigest(),
    }
    return positions, rotations, provenance


def main(records, output, isomer="cis-syn"):
    fit_ids, check_ids = REPLICAS[isomer][:2], REPLICAS[isomer][2:]
    records = {r["job_id"]: r for r in json.loads(Path(records).read_text())}
    samples = {key: extract(records[key], isomer) for key in REPLICAS[isomer]}
    parameters = fit(
        np.concatenate([samples[k][0] for k in fit_ids]),
        np.concatenate([samples[k][1] for k in fit_ids]),
    )
    report = {
        "schema": "nadoc.oxdna-cpd.v1",
        "stereochemistry": isomer,
        "model": "conditional-rigid-weld-v1",
        "qualification": "exploratory; not validated melting thermodynamics",
        "mapping": "thymine-N1-C2-C6-C1-centroid-v1",
        "parameters": parameters,
        "fit_replicas": list(fit_ids),
        "validation_replicas": list(check_ids),
        "validation_is_blind": False,
        "sources": [samples[k][2] for k in samples],
        "per_replica_fits": {k: fit(samples[k][0], samples[k][1]) for k in samples},
        "limitations": [
            "Conditional motif covariance includes environmental restoring forces.",
            "Reacted-pair ordinary base interactions are replaced; surrounding DNA2 interactions remain.",
            "No temperature dependence or altered interactions with third nucleotides were fitted.",
            "No equivalence between Mg-containing NAMD solvent and oxDNA monovalent salt is asserted.",
        ],
    }
    Path(output).write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "samples": parameters["sample_count"],
                "hessian_fit_error": parameters["relative_hessian_fit_error"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records", default="analysis/2hb_publication_20261110/results.json"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--isomer", choices=list(REPLICAS), default="cis-syn")
    args = parser.parse_args()
    main(args.records, args.output, args.isomer)
