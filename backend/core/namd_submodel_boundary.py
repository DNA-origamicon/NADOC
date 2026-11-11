"""Versioned uniform shell restraints for derived NAMD simulation packages."""

import re
import math

import numpy as np


def boundary_recipe(
    source, residues, representative, distance, kept, mobile, terms, box
):
    """Whole cut-support residues and the outer 0.3 nm remain fixed."""
    retained = set(kept)
    cut_residues = set()
    for name in ("NBOND", "NTHETA", "NPHI", "NIMPHI", "NCRTERM"):
        for term in terms.get(name, []):
            if not all(i in retained for i in term):
                cut_residues.update(residues[i - 1] for i in term if i in retained)
    edge = max(0, float(box.get("shell_nm", 3)) - 0.3)
    fixed = [
        j
        for j, i in enumerate(kept)
        if i not in mobile
        and (
            residues[i - 1] in cut_residues
            or distance[representative[residues[i - 1]]] >= edge
        )
    ]
    fixed_set = set(fixed)
    heavy = [
        j
        for j, i in enumerate(kept)
        if i not in mobile
        and j not in fixed_set
        and float(source["NATOM"][1][i - 1].split()[7]) > 2
    ]
    return dict(
        kind="uniform",
        coefficient_kcal_mol_A2=0.1,
        outer_fixed_nm=0.3,
        fixed_output_indices=fixed,
        restrained_output_indices=heavy,
        reference_policy="Preparation pose; production child starts from its parent checkpoint",
    )


def coefficient_field(value):
    """Keep small effective stage coefficients instead of rounding them to zero."""
    for precision in range(6, 0, -1):
        field = f"{value:.{precision}g}"
        if len(field) <= 6 and math.isclose(
            float(field), value, rel_tol=1e-12, abs_tol=0
        ):
            return field.rjust(6)
    raise ValueError(
        "Cannot preserve the stage restraint coefficient in a six-column PDB field"
    )


def apply_restraints(package_dir, conf, text, atoms, boundary):
    """Merge static stage restraints; keep the shell coefficient independent of scaling.

    Core relaxation restraints retain their effective weights and reference positions.
    Shell references use the package pose, or the production parent's native checkpoint.
    This does not change velocities or restart coordinates.
    """

    def option(key, default=None):
        found = re.search(r"^[ \t]*" + key + r"\s+([^\n#]+)", text, re.M | re.I)
        return found[1].strip() if found else default

    weights = np.zeros(len(atoms))
    references = list(atoms)
    if option("constraints", "off").lower() in ("on", "yes", "true", "1"):
        if option("conskcol", "B").upper() != "B" or float(option("consexp", "2")) != 2:
            raise ValueError("Submodel requires harmonic B-column stage restraints")
        prior_weights = (package_dir / option("conskfile")).read_text().splitlines()
        prior_weights = [s for s in prior_weights if s.startswith(("ATOM  ", "HETATM"))]
        references = [
            s
            for s in (package_dir / option("consref")).read_text().splitlines()
            if s.startswith(("ATOM  ", "HETATM"))
        ]
        if len(prior_weights) != len(atoms) or len(references) != len(atoms):
            raise ValueError("Submodel restraint atom count mismatch")
        weights[:] = [float(s[60:66]) for s in prior_weights]
        weights *= float(option("constraintScaling", "1"))
    shell_reference = atoms
    checkpoint = package_dir / "equilibrated.coor"
    if checkpoint.exists():
        from backend.core.md_shell_reprep import read_namd_coor

        coords = read_namd_coor(checkpoint)
        if len(coords) != len(atoms):
            raise ValueError("Submodel checkpoint atom count mismatch")
        shell_reference = [
            s[:30] + "".join(f"{v:8.3f}" for v in xyz) + s[54:]
            for s, xyz in zip(atoms, coords)
        ]
    for i in boundary["restrained_output_indices"]:
        weights[i] = boundary["coefficient_kcal_mol_A2"]
        references[i] = shell_reference[i]
    marker = f"submodel_restraints_{conf.stem}.pdb"
    (package_dir / marker).write_text(
        "\n".join(
            s[:60] + coefficient_field(k) + s[66:] for s, k in zip(references, weights)
        )
        + "\nEND\n"
    )
    text = re.sub(
        r"^[ \t]*(?:constraints|consref|conskfile|conskcol|consexp|constraintScaling)\s+[^\n]*\n?",
        "",
        text,
        flags=re.M | re.I,
    )
    return (
        f"constraints on\nconsref {marker}\nconskfile {marker}\nconskcol B\nconstraintScaling 1\n"
        + text
    )
