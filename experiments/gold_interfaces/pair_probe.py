"""Independent native force/energy oracle for each Au cross pair (charges zeroed)."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

from backend.core import gold_model
from backend.core.namd_gold_package import dry_pair, config, FF_FILES, sha
from backend.core.namd_solvate import _FF_DIR
from experiments.gold_interfaces.native import read_binary


def probe(output, binary):
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for partner in gold_model.PARTNERS:
        p = output/partner
        p.mkdir()
        (p/"forcefield").mkdir()
        (p/"output").mkdir()
        for name in FF_FILES:
            shutil.copy2(_FF_DIR/name, p/"forcefield"/name)
        (p/"forcefield/gold.prm").write_text(gold_model.parameter_text())
        _, rmin = gold_model.pair_parameters(partner)
        r = round(1.13*rmin, 3)
        psf, pdb = dry_pair(np.array([[1., 1., 1.], [1.+r/10, 1., 1.]]))
        lines = psf.splitlines()
        start = next(i for i, row in enumerate(lines) if "!NATOM" in row)
        # q=0 isolates LJ for ions/water types; production charges are independently audited.
        f = lines[start+2].split()
        f[5] = partner
        lines[start+2] = " ".join(f)
        (p/"system.psf").write_text("\n".join(lines)+"\n")
        (p/"system.pdb").write_text(pdb)
        m = {"geometry": {"kind": "nanoparticle"}, "cell_nm": [4.]*3,
             "mobility": "mobile", "temperature_K": 0., "seed": 17}
        text = config(m, steps=0, prefix="pair", thermostat=False)
        text = text.replace("rigidBonds water", "rigidBonds none")
        text += "output onlyforces output/pair\n"
        (p/"pair.conf").write_text(text)
        with (p/"pair.log").open("w") as stream:
            run = subprocess.run([str(binary), "+p2", "+devices", "0", "pair.conf"], cwd=p,
                                 stdout=stream, stderr=subprocess.STDOUT, timeout=30)
        log = (p/"pair.log").read_text()
        if run.returncode or "End of program" not in log:
            raise RuntimeError(f"Pair probe failed: {p}")
        title = next(line.split()[1:] for line in log.splitlines() if line.startswith("ETITLE:"))
        energy = [line.split()[1:] for line in log.splitlines() if line.startswith("ENERGY:")][-1]
        vdw = float(energy[title.index("VDW")])
        forces = read_binary(p/"output/pair.force")
        expected_u, expected_f = gold_model.pair_energy_force(r, partner)
        error_u = abs(vdw-expected_u)
        expected = np.array([[-expected_f, 0, 0], [expected_f, 0, 0]])
        error_f = float(np.max(np.abs(forces-expected)))
        results.append({"partner": partner, "r_A": r, "energy_kcal_mol": vdw,
                        "expected_energy": expected_u, "max_force_error_kcal_mol_A": error_f,
                        "energy_error_kcal_mol": error_u,
                        "passed": error_u < 6e-5 and error_f < 2e-4})
    report = {"engine_sha256": sha(binary), "scope": "unswitched LJ pair only; neutralized probe types",
              "results": results, "passed": all(r["passed"] for r in results)}
    (output/"results.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report), flush=True)
    if not report["passed"]:
        raise RuntimeError("Native pair arithmetic differs from oracle")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--binary", type=Path, required=True)
    a = p.parse_args()
    probe(a.output, a.binary.resolve())
