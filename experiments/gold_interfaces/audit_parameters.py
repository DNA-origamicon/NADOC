"""Read-only candidate audit; this does not select or install a gold force field.

Run from the repository root:
  uv run python -m experiments.gold_interfaces.audit_parameters \
    --sources workspace/gold_model_review_20260914 --output NEW_DIRECTORY
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt


def nonbonded(path, atom_type):
    """Extract a unique active CHARMM NONBONDED entry, preserving Rmin/2."""
    section = None
    found = []
    for line in path.read_text().splitlines():
        fields = line.split("!", 1)[0].split()
        if not fields or fields[0].startswith("*"):
            continue
        if fields[0].upper() in {
            "NONBONDED", "NBFIX", "END", "BONDS", "ANGLES", "DIHEDRALS",
            "IMPROPER", "IMPROPERS", "CMAP", "HBOND",
        }:
            section = fields[0].upper()
        elif section == "NONBONDED" and fields[0] == atom_type:
            found.append((float(fields[2]), float(fields[3])))
    if len(found) != 1:
        raise ValueError(f"Expected one NONBONDED {atom_type} in {path}: {found}")
    epsilon, half_rmin = found[0]
    if not math.isfinite(epsilon + half_rmin) or epsilon >= 0 or half_rmin <= 0:
        raise ValueError(f"Invalid attractive LJ parameters for {atom_type}")
    return {"epsilon_kcal_mol": -epsilon, "rmin_half_A": half_rmin}


def audit(sources, output):
    provenance = json.loads((sources / "sources.json").read_text())
    for name, record in provenance["sources"].items():
        if hashlib.sha256((sources / name).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Source checksum mismatch: {name}")
    ff = Path(__file__).resolve().parents[2] / "backend/data/forcefield"
    water = ff / "toppar_water_ions_cufix.str"
    au = nonbonded(sources / "charmm27_interface_v1_5.prm", "AU")
    atoms = {"AU": au, **{t: nonbonded(water, t) for t in ("OT", "HT", "SOD", "CLA")}}
    polar = sources / "charmm27_interface_v1_5_Aue.prm"
    with zipfile.ZipFile(sources / "geada2018_dataset.zip") as archive:
        if polar.read_bytes() != archive.read(polar.name):
            raise ValueError("Extracted polarizable parameters differ from pinned archive")
    polar_atoms = {t: nonbonded(polar, t) for t in ("AUC", "AUE", "SOD", "CLA")}
    if au != {"epsilon_kcal_mol": 5.29, "rmin_half_A": 1.4755}:
        raise ValueError("Author gold entry differs from reviewed candidate")
    overrides = []
    section = False
    for line in water.read_text().splitlines():
        f = line.split("!", 1)[0].split()
        if not f:
            continue
        if f[0] == "NBFIX":
            section = True
        elif f[0] == "END":
            section = False
        elif section and len(f) >= 4 and set(f[:2]) == {"SOD", "CLA"}:
            overrides.append({"epsilon_kcal_mol": -float(f[2]), "rmin_A": float(f[3])})
    if overrides != [{"epsilon_kcal_mol": 0.083875, "rmin_A": 3.74075}]:
        raise ValueError(f"CUFIX Na-Cl entry differs from reviewed version: {overrides}")
    output.mkdir(parents=True, exist_ok=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    pairs = {}
    for t, p in atoms.items():
        epsilon = math.sqrt(au["epsilon_kcal_mol"] * p["epsilon_kcal_mol"])
        rmin = au["rmin_half_A"] + p["rmin_half_A"]
        sigma = rmin / 2 ** (1 / 6)
        r = np.linspace(0.94 * rmin, 2.5 * rmin, 400)
        x = (rmin / r) ** 6
        energy = epsilon * (x * x - 2 * x)
        force = 12 * epsilon * (x * x - x) / r
        # Independent conventional 4-epsilon/sigma form and numerical derivative.
        def conventional(distance):
            return 4 * epsilon * ((sigma / distance) ** 12 - (sigma / distance) ** 6)

        h = 1e-5
        numeric = -(conventional(r + h) - conventional(r - h)) / (2 * h)
        energy_error = float(np.max(np.abs(energy - conventional(r))))
        force_error = float(np.max(np.abs(force - numeric)))
        if energy_error > 1e-10 or force_error > 1e-6:
            raise ValueError(f"Independent LJ arithmetic check failed for AU-{t}")
        pairs[f"AU-{t}"] = {
            "epsilon_kcal_mol": epsilon, "rmin_A": rmin, "sigma_A": sigma,
            "max_energy_error_kcal_mol": energy_error,
            "max_force_error_kcal_mol_A": force_error,
            "specific_adsorption_validated": False,
        }
        axes[0].plot(r, energy, label=f"Au–{t}")
        axes[1].plot(r, force, label=f"Au–{t}")
        np.savetxt(output / f"AU-{t}.csv", np.c_[r, energy, force, numeric],
                   delimiter=",", header="r_A,U_kcal_mol,F_kcal_mol_A,F_finite_difference", comments="")
    for ax, ylabel in zip(axes, ("Pair energy (kcal/mol)", "Radial force (kcal/mol/Å)")):
        ax.set(xlabel="Atom separation (Å)", ylabel=ylabel)
        ax.axhline(0, color="grey", lw=0.5)
        ax.legend()
    fig.suptitle("Candidate nonpolarizable IFF × NADOC: unswitched LJ only; no image response")
    fig.savefig(output / "candidate_pairs.png", dpi=160)
    plt.close(fig)
    report = {
        "schema": "nadoc.gold_candidate_audit.v1",
        "model_selection": "nonpolarizable baseline selected; audit remains an independent candidate calculation",
        "validation_level": "source/units and independent pair arithmetic only; no native dynamics",
        "sources": provenance,
        "local_forcefield_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(ff.iterdir()) if p.suffix in {".str", ".prm", ".rtf"}},
        "nonpolarizable_atoms": atoms, "polarizable_distribution_atoms": polar_atoms,
        "nadoc_NaCl_NBFIX": overrides[0], "candidate_pairs": pairs,
        "warnings": [
            "AU-HT is nonzero for CHARMM-modified TIP3P; oxygen-only TIP3P/SPC/E is different.",
            "Author CHARMM27 distribution SOD radius differs from NADOC CUFIX; do not load the whole file.",
            "LJ cross pairs are model predictions, not validated specific ion adsorption.",
            "These checks exclude PME, cutoff/switching and native NAMD implementation.",
        ],
    }
    (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(output), "pairs": len(pairs),
                      "max_force_error_kcal_mol_A": max(p["max_force_error_kcal_mol_A"] for p in pairs.values())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.sources, args.output)
