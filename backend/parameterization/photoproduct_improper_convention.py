"""Audit the signed CHARMM improper convention with real psfgen and NAMD."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pdb(z: float) -> str:
    coordinates = [
        ("CTR", 0.0, 0.0, 0.0),
        ("A", 1.0, 0.0, 0.0),
        ("B", 0.0, 1.0, 0.0),
        ("D", 0.0, 0.0, z),
    ]
    lines = []
    for serial, (name, x, y, z_value) in enumerate(coordinates, start=1):
        lines.append(
            f"ATOM  {serial:5d} {name:<4} TST S   1    "
            f"{x:8.3f}{y:8.3f}{z_value:8.3f}  1.00  0.00      S"
        )
    return "\n".join([*lines, "END", ""])


def _energy_columns(output: str) -> dict[str, float]:
    title = next(line for line in output.splitlines() if line.startswith("ETITLE:"))
    energy = next(line for line in output.splitlines() if line.startswith("ENERGY:"))
    names = title.split()[1:]
    values = energy.split()[1:]
    return dict(zip(names, map(float, values), strict=True))


def _engine_lines(output: str) -> list[str]:
    return [
        line.strip()
        for line in output.splitlines()
        if re.search(r"\b(NAMD Git-|Built with CUDA version|Charm\+\+ Commit ID)", line)
    ]


def audit_namd_improper_convention(
    *, output_dir: Path, psfgen_path: Path, namd_path: Path
) -> dict[str, Any]:
    """Prove that one ordered nonzero CHARMM improper distinguishes reflection.

    This validates engine convention only.  It cannot establish any lesion-specific
    atom order, equilibrium angle, or force constant.
    """

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite improper audit: {output_dir}")
    if not psfgen_path.is_file() or not namd_path.is_file():
        raise FileNotFoundError("real psfgen and NAMD executable paths are required")
    output_dir.mkdir(parents=True)
    rtf_path = output_dir / "test.rtf"
    plus_pdb = output_dir / "plus.pdb"
    minus_pdb = output_dir / "minus.pdb"
    tcl_path = output_dir / "build.tcl"
    parameter_path = output_dir / "test.prm"
    rtf_path.write_text(
        "* NAMD improper convention test\n*\n36 1\n"
        "MASS 1 CT 12.011 C\n"
        "RESI TST 0.0\nGROUP\n"
        "ATOM CTR CT 0.0\nATOM A CT 0.0\nATOM B CT 0.0\nATOM D CT 0.0\n"
        "BOND CTR A CTR B CTR D\nIMPR CTR A B D\nEND\n"
    )
    plus_pdb.write_text(_pdb(1.0))
    minus_pdb.write_text(_pdb(-1.0))
    tcl_path.write_text(
        "topology test.rtf\nsegment S { residue 1 TST }\nwritepsf test.psf\n"
    )
    parameter_path.write_text(
        "* NAMD improper convention test\n*\n"
        "BONDS\nCT CT 100.0 1.0\n"
        "ANGLES\nCT CT CT 0.0 90.0\n"
        "DIHEDRALS\nX CT CT X 0.0 1 0.0\n"
        "IMPROPER\nCT CT CT CT 10.0 0 30.0\n"
        "NONBONDED nbxmod 5 atom cdiel shift vatom vdistance vswitch -\n"
        "cutnb 14.0 ctofnb 12.0 ctonnb 10.0 eps 1.0 e14fac 1.0 wmin 1.5\n"
        "CT 0.0 -0.10 2.0\nEND\n"
    )
    built = subprocess.run(
        [str(psfgen_path), tcl_path.name],
        cwd=output_dir,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    psfgen_output = built.stdout + built.stderr
    psfgen_log = output_dir / "psfgen.log"
    psfgen_log.write_text(psfgen_output)
    if built.returncode != 0 or re.search(r"\b(ERROR|FATAL)\b", psfgen_output, re.I):
        raise RuntimeError(f"psfgen improper-convention fixture failed; see {psfgen_log}")

    energies: dict[str, dict[str, float]] = {}
    run_records = {}
    engine_identity: list[str] = []
    for label in ("plus", "minus"):
        config_path = output_dir / f"{label}.conf"
        config_path.write_text(
            "structure test.psf\n"
            f"coordinates {label}.pdb\n"
            "parameters test.prm\nparaTypeCharmm on\n"
            "exclude scaled1-4\noneFourScaling 1.0\n"
            "cutoff 12.0\nswitching on\nswitchdist 10.0\npairlistdist 14.0\n"
            "temperature 0\noutputEnergies 1\n"
            f"outputName {label}\nrun 0\n"
        )
        completed = subprocess.run(
            [str(namd_path), "+p1", config_path.name],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = completed.stdout + completed.stderr
        log_path = output_dir / f"{label}.log"
        log_path.write_text(output)
        if completed.returncode != 0 or "FATAL ERROR" in output:
            raise RuntimeError(f"NAMD {label} improper fixture failed; see {log_path}")
        energies[label] = _energy_columns(output)
        if label == "plus":
            engine_identity = _engine_lines(output)
        run_records[label] = {
            "config_sha256": _sha256(config_path),
            "log_sha256": _sha256(log_path),
            "return_code": completed.returncode,
        }

    invariant_bond = math.isclose(
        energies["plus"]["BOND"], energies["minus"]["BOND"], abs_tol=1e-8
    )
    invariant_angle = math.isclose(
        energies["plus"]["ANGLE"], energies["minus"]["ANGLE"], abs_tol=1e-8
    )
    improper_distinguished = not math.isclose(
        energies["plus"]["IMPRP"], energies["minus"]["IMPRP"], abs_tol=1e-6
    )
    intended_hand_lower = energies["plus"]["IMPRP"] < energies["minus"]["IMPRP"]
    passed = all(
        (invariant_bond, invariant_angle, improper_distinguished, intended_hand_lower)
    )
    report = {
        "schema": "nadoc.photoproduct-namd-improper-convention-audit.v1",
        "status": "passed_convention_only" if passed else "failed",
        "passed": passed,
        "gate_effect": "none",
        "product_parameter_authority": False,
        "fixture": {
            "ordered_atoms": ["CTR", "A", "B", "D"],
            "improper_k_kcal_mol_rad2": 10.0,
            "improper_equilibrium_degrees": 30.0,
            "reflection": "D z-coordinate +1.0 to -1.0 angstrom",
        },
        "energies_kcal_mol": {
            label: {
                key: values[key]
                for key in ("BOND", "ANGLE", "DIHED", "IMPRP", "POTENTIAL")
            }
            for label, values in energies.items()
        },
        "checks": {
            "bond_energy_invariant": invariant_bond,
            "angle_energy_invariant": invariant_angle,
            "improper_distinguishes_reflection": improper_distinguished,
            "declared_positive_z_hand_is_lower": intended_hand_lower,
        },
        "engine": {
            "namd_path": str(namd_path.resolve()),
            "namd_sha256": _sha256(namd_path),
            "psfgen_path": str(psfgen_path.resolve()),
            "psfgen_sha256": _sha256(psfgen_path),
            "identity_lines": engine_identity,
        },
        "inputs": {
            path.name: _sha256(path)
            for path in (rtf_path, plus_pdb, minus_pdb, parameter_path, tcl_path)
        },
        "runs": run_records,
        "scope_warning": (
            "This audit establishes the NAMD/CHARMM sign and atom-order mechanism only; "
            "it supplies no TT-CPD ordering, equilibrium value, or force constant."
        ),
    }
    report_path = output_dir / "improper_convention_audit.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
