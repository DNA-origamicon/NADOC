"""Versioned neutral INTERFACE gold; no implied metal polarization or Au–S chemistry."""

from copy import deepcopy
import math

MODEL_ID = "iff-au-12-6-neutral-v1"
MODEL = {
    "id": MODEL_ID,
    "schema": "nadoc.gold_model.v1",
    "atom_type": "NAUI", "atom_name": "AU", "residue": "AUI",
    "mass_Da": 196.96657, "charge_e": 0.0,
    "epsilon_kcal_mol": 5.29, "rmin_half_A": 1.4755,
    "lattice_parameter_nm": 0.40782,
    "lattice_note": "Reference fcc starting cell; relax before interpreting mobile structure.",
    "combination_rules": "geometric epsilon; additive Rmin/2; NBFIX takes precedence",
    "capabilities": {"cohesive_gold": True, "native_lj": True,
                     "electronic_polarization": False, "constant_potential": False,
                     "gold_sulfur_bonds": False, "validated_specific_ion_adsorption": False},
    "mobility": ["fixed", "restrained", "mobile"],
    "electrolyte": "CHARMM-modified TIP3P / NADOC CUFIX NaCl",
    "provenance": {
        "doi": "10.1021/jp801931d",
        "distribution": "INTERFACE 1.5 CHARMM",
        "url": "https://raw.githubusercontent.com/hendrikheinz/INTERFACE-force-field-and-surface-models/584179265906d93aa40f7d5b275143985871b654/charmm27_interface_v1_5.prm",
        "sha256": "5edab5e93a422cd5dab389c34c19fd5e7f2a33e240f1a9cdf09017baea177557",
        "entry": "AU 0.0 -5.29 1.4755",
        "adaptation": "Numerical metal entry only, namespaced NAUI; no CHARMM27 bulk parameter import.",
        "redistribution": "Author GitHub has no LICENSE file; no blanket redistribution grant asserted. Numerical facts transcribed with attribution; full upstream file is not packaged.",
    },
}

# These are the reviewed local electrolyte values, not adjustable Au-ion fits.
PARTNERS = {"NAUI": (5.29, 1.4755), "OT": (.1521, 1.7682),
            "HT": (.046, .2245), "SOD": (.0469, 1.41075), "CLA": (.15, 2.27)}


def specification(model_id=MODEL_ID):
    if model_id != MODEL_ID:
        raise ValueError(f"Unsupported gold model {model_id!r}; select {MODEL_ID}")
    return deepcopy(MODEL)


def pair_parameters(partner):
    if partner not in PARTNERS:
        raise ValueError(f"Unqualified gold partner type: {partner}")
    eps, radius = PARTNERS[partner]
    return math.sqrt(5.29 * eps), 1.4755 + radius


def pair_energy_force(r_A, partner):
    """Unswitched pair U and outward radial force in kcal/mol and kcal/mol/Å."""
    if not math.isfinite(r_A) or r_A <= 0:
        raise ValueError("Pair distance must be positive and finite")
    eps, radius = pair_parameters(partner)
    x = (radius / r_A) ** 6
    return eps * (x*x - 2*x), 12*eps*(x*x-x)/r_A


def contact_distance_nm(partner, max_repulsion_kcal_mol=6.0):
    """Inner distance where pair U reaches the positive packing ceiling.

    This is a preparation criterion, not an extra force or surface displacement.
    """
    if not math.isfinite(max_repulsion_kcal_mol) or max_repulsion_kcal_mol <= 0:
        raise ValueError("Packing repulsion ceiling must be positive and finite")
    eps, radius = pair_parameters(partner)
    x = 1 + math.sqrt(1 + max_repulsion_kcal_mol / eps)
    return radius / x ** (1/6) / 10


def parameter_text():
    return """* Neutral INTERFACE 12-6 Au; Heinz et al. 2008, doi:10.1021/jp801931d
* Numerical Au entry from INTERFACE 1.5, renamed AU -> NAUI.
* kcal/mol; Angstrom; CHARMM Rmin/2. No image charge or Au-S terms.
*
NONBONDED
NAUI 0.0 -5.29 1.4755
END
"""


def validate_electrolyte(text):
    """Fail closed when the installed electrolyte differs from the reviewed model."""
    section = None
    entries, nbfix = {}, {}
    for line in text.splitlines():
        f = line.split("!", 1)[0].split()
        if not f or f[0].startswith("*"):
            continue
        if f[0] in ("NONBONDED", "NBFIX", "END"):
            section = f[0]
        elif section == "NONBONDED" and f[0] in PARTNERS:
            entries[f[0]] = (-float(f[2]), float(f[3]))
        elif section == "NBFIX" and len(f) >= 4:
            nbfix[tuple(sorted(f[:2]))] = (-float(f[2]), float(f[3]))
    if entries != {k: v for k, v in PARTNERS.items() if k != "NAUI"}:
        raise ValueError("Gold baseline requires the reviewed CHARMM TIP3P/CUFIX nonbonded parameters")
    for pair, value in {("CLA", "SOD"): (.083875, 3.74075),
                        ("ON3", "SOD"): (.075020, 3.20075)}.items():
        if nbfix.get(pair) != value:
            raise ValueError(f"Gold baseline requires the reviewed CUFIX override {pair}")
