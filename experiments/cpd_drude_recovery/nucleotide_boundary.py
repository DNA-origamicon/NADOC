"""Audit fragment-to-nucleotide identities, charge groups and expected graph only."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms


def main(psf_path, frozen_path, output):
    _, atoms, sections = atoms_and_terms(psf_path.read_text())
    fit = json.loads(frozen_path.read_text())
    q = json.loads(checked(fit["permanent_charges"]).read_text())["charges_e"]
    cap = {"CM", "HCM1", "HCM2", "HCM3"}
    lookup = {(row[2], row[4]): i for i, row in atoms.items()}
    if len(lookup) != len(atoms):
        raise ValueError("Ambiguous residue/atom keys")
    adjacency = {i: set() for i in atoms}
    for a, b in sections["NBOND"][3]:
        adjacency[a].add(b)
        adjacency[b].add(a)
    maps = []
    groups = []
    for ring in ("1", "2"):
        fragment = {
            key.split(":")[1]: value
            for key, value in q.items()
            if key.split(":")[0] == ring
        }
        base_serials = set()
        for name, charge in fragment.items():
            if name in cap:
                continue
            native = "C5M" if name == "C7" else name
            serial = lookup[(ring, native)]
            row = atoms[serial]
            attached = [i for i in adjacency[serial] if atoms[i][5] == "DRUD"]
            if len(attached) > 1:
                raise ValueError("Multiple Drudes for a base parent")
            if (
                name in {"N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"}
                and len(attached) != 1
            ):
                raise ValueError("Missing base Drude")
            base_serials.update([serial, *attached])
            native_group_charge = sum(float(atoms[i][6]) for i in [serial, *attached])
            maps.append(
                {
                    "fragment_atom": f"{ring}:{name}",
                    "nucleotide_atom": f"{ring}:{native}",
                    "native_type": row[5],
                    "native_permanent_charge_e": native_group_charge,
                    "candidate_permanent_charge_e": charge,
                    "native_alpha_angstrom3": -float(row[9]),
                    "candidate_alpha_angstrom3": fit["parameters"][
                        "alpha_angstrom3"
                    ].get(f"{ring}:{name}"),
                    "candidate_thole": fit["parameters"]["thole"].get(f"{ring}:{name}"),
                }
            )
        cap_charge = sum(fragment[n] for n in cap)
        if abs(cap_charge) > 1e-10:
            raise ValueError("Nonneutral removed cap")
        groups.append(
            {
                "endpoint": ring,
                "removed_cap_charge_e": cap_charge,
                "native_base_charge_e": sum(float(atoms[i][6]) for i in base_serials),
                "candidate_base_charge_e": sum(
                    value for name, value in fragment.items() if name not in cap
                ),
                "native_base_particle_count": len(base_serials),
                "glycosidic_bond_present": lookup[(ring, "C1'")]
                in adjacency[lookup[(ring, "N1")]],
            }
        )
    junction_terms = []
    for ring in ("1", "2"):
        junction = {lookup[(ring, "N1")], lookup[(ring, "C1'")]}
        for category in ("NBOND", "NTHETA", "NPHI", "NIMPHI"):
            for term in sections.get(category, (None, None, None, []))[3]:
                if not junction.issubset(term):
                    continue
                if any(atoms[i][5] == "DRUD" or float(atoms[i][7]) == 0 for i in term):
                    continue
                junction_terms.append(
                    {
                        "endpoint": ring,
                        "category": category,
                        "atoms": [atoms[i][2] + ":" + atoms[i][4] for i in term],
                        "native_types": [atoms[i][5] for i in term],
                        "central_glycosidic_torsion": category == "NPHI"
                        and set(term[1:3]) == junction,
                    }
                )
    before = sum(float(row[6]) for row in atoms.values())
    after = before + sum(
        g["candidate_base_charge_e"] - g["native_base_charge_e"] for g in groups
    )
    if abs(after - before) > 1e-6:
        raise ValueError("Charge transfer would change full nucleotide charge")
    nuclear = {i for i, row in atoms.items() if row[5] != "DRUD" and float(row[7]) > 0}
    existing = {
        tuple(sorted((a, b)))
        for a, b in sections["NBOND"][3]
        if a in nuclear and b in nuclear
    }
    registry_path = Path("backend/data/forcefield/photoproduct_registry.json")
    registry = json.loads(registry_path.read_text())
    product = next(p for p in registry["products"] if p["id"] == "tt-cpd-cis-anti-i")
    added = []
    for bond in product["graph_delta"]["bonds_added"]:
        a, b = [lookup[tuple(s.split(":"))] for s in bond.split("--")]
        pair = tuple(sorted((a, b)))
        if pair in existing:
            raise ValueError("Crosslink already present in precursor")
        added.append(pair)
    assert len(added) == 2 and len(set(added)) == 2
    expected = existing | set(added)
    write(
        output,
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "Identity, charge accounting and expected nuclear graph only. No product PSF, parameters or geometry is released. Endpoint numbering is a mapping convention, not validation of an anti intrastrand conformation.",
            "precursor": source(psf_path),
            "frozen_fragment": source(frozen_path),
            "registry": source(registry_path),
            "code": source(Path(__file__)),
            "total_charge_before_e": before,
            "hypothetical_total_charge_after_e": after,
            "nuclear_atom_count": len(nuclear),
            "precursor_nuclear_bond_count": len(existing),
            "expected_product_nuclear_bond_count": len(expected),
            "added_bonds": product["graph_delta"]["bonds_added"],
            "endpoint_charge_groups": groups,
            "base_atom_mapping": maps,
            "native_glycosidic_junction_terms_requiring_transfer_review": junction_terms,
            "remaining_requirements": [
                "Replace cap CM by C1-prime with independently validated glycosidic bond/angle/torsion and N1 type treatment.",
                "Validate sugar-bound electrostatics/anisotropy and polarization response; neutrality alone does not validate transfer.",
                "Construct product topology and regenerate all angles/dihedrals/exclusions/Thole pairs using correct graph.",
                "Validate intended strand connectivity and sugar geometry separately; no coordinates or bond orders were inferred here.",
                "Independent full-nucleotide and solvated DNA tests required.",
            ],
        },
    )
    print(
        "Charge preserved:",
        after,
        "expected nuclear graph",
        len(nuclear),
        "atoms",
        len(expected),
        "bonds",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--psf", type=Path, required=True)
    p.add_argument("--frozen", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    main(a.psf, a.frozen, a.output)
