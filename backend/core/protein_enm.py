"""Cα elastic-network restraints + DNA-handle click linker for all-atom MD.

Part B (MD) of "proteins in oxDNA + MD".  Imported PDB proteins enter the
all-atom NAMD/GROMACS path as near-rigid bodies: we do NOT care about real
protein dynamics, only that the fold holds at any ionic strength and provides
correct excluded volume + a tether to the DNA.

Two products, both emitted as a NAMD ``extraBonds`` file:

* **Cα elastic network** — every Cα–Cα pair (within one protein) closer than a
  cutoff gets a harmonic restraint at its *current* separation with a stiff force
  constant.  Because the reference lengths come from the imported structure and
  the springs are stiff, the protein keeps its fold regardless of salt /
  temperature (the salt-robustness the user asked for) while still translating /
  tumbling as a rigid body.

* **Click linker** — for a conjugated attachment (one whose ``/conjugate`` route
  created a real ``OH_BINDER`` strand) a single harmonic bond ties the
  conjugation atom to the binder handle's terminal backbone atom — the all-atom
  mirror of the oxDNA ``mutual_trap``.  The DNA nucleotide is resolved through the
  SAME ``binder_terminus_nuc_key`` the oxDNA path uses, so the two simulation
  paths cannot diverge.

Pure + tested.  Coordinates in the AtomisticModel are nm; NAMD extraBonds want Å
(``× 10``).  NAMD extraBonds bond syntax is ``bond <i> <j> <k> <b0>`` with
**0-based** atom indices (k first, reference length second).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.core.protein import PROTEIN_SENTINEL_PREFIX

# ── ENM defaults (tunable) ────────────────────────────────────────────────────
# 12 Å is the lower end of the standard ANM range; stiff k holds the fold near-
# rigid.  Units: cutoff Å, k kcal/mol/Å².
ENM_CUTOFF_ANG: float = 12.0
ENM_K: float = 10.0
# Click-linker harmonic bond (conjugation atom ↔ DNA handle terminus).
LINKER_K: float = 5.0
# DNA backbone atom preference for the linker anchor (P absent at 5′ termini).
_LINKER_DNA_ATOMS = ("P", "C1'", "O5'", "C5'")


@dataclass
class ExtraBond:
    """One NAMD extraBond: 0-based atom indices, force const, reference length (Å)."""
    i: int
    j: int
    k: float
    b0_ang: float


def _dist_ang(a, b) -> float:
    """Distance between two AtomisticModel atoms in Å (model stores nm)."""
    dx = (a.x - b.x) * 10.0
    dy = (a.y - b.y) * 10.0
    dz = (a.z - b.z) * 10.0
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def ca_enm_pairs(ca_atoms: list, cutoff_ang: float = ENM_CUTOFF_ANG) -> list[tuple[int, int, float]]:
    """Every Cα–Cα pair within ``cutoff_ang`` → ``(serial_i, serial_j, r0_ang)``.

    ``ca_atoms`` is the list of one protein's Cα atoms (model order).  Pairs are
    emitted once (``i`` index < ``j`` index in the list; the returned serials are
    the atoms' own model serials).  Reference length = current separation (Å).
    """
    out: list[tuple[int, int, float]] = []
    n = len(ca_atoms)
    for ii in range(n):
        a = ca_atoms[ii]
        for jj in range(ii + 1, n):
            b = ca_atoms[jj]
            d = _dist_ang(a, b)
            if d <= cutoff_ang:
                out.append((a.serial, b.serial, d))
    return out


def _protein_ca_groups(model) -> dict[str, list]:
    """Map each protein sentinel (``__protein__{id}``) → its ordered Cα atoms."""
    groups: dict[str, list] = {}
    for atom in model.atoms:
        if not atom.helix_id.startswith(PROTEIN_SENTINEL_PREFIX):
            continue
        if atom.name.strip() != "CA" or atom.element.upper() != "C":
            continue
        groups.setdefault(atom.helix_id, []).append(atom)
    return groups


def enm_extra_bonds(model, cutoff_ang: float = ENM_CUTOFF_ANG, k: float = ENM_K) -> list[ExtraBond]:
    """Cα elastic-network restraints across all protein attachments in *model*."""
    bonds: list[ExtraBond] = []
    for ca_atoms in _protein_ca_groups(model).values():
        for i, j, r0 in ca_enm_pairs(ca_atoms, cutoff_ang):
            bonds.append(ExtraBond(i=i, j=j, k=k, b0_ang=r0))
    return bonds


# ── Click linker (conjugation atom ↔ DNA handle terminus) ─────────────────────


def _conjugation_model_atom(model, asset, attachment):
    """The protein conjugation atom in *model* (matched by sentinel/resid/name)."""
    serial = getattr(attachment, "conjugation_atom_serial", None)
    if serial is None:
        serial = asset.default_conjugation_atom_serial
    src = next((a for a in asset.atoms if a.serial == serial), None) if serial is not None else None
    if src is None:
        return None
    sentinel = f"{PROTEIN_SENTINEL_PREFIX}{attachment.id}"
    return next(
        (a for a in model.atoms
         if a.helix_id == sentinel and a.seq_num == src.res_seq and a.name.strip() == src.name.strip()),
        None,
    )


def _dna_terminus_model_atom(model, nuc_key):
    """The DNA backbone atom in *model* for nucleotide ``(helix, bp, direction)``."""
    helix_id, bp_index, direction = nuc_key
    by_name = {
        a.name.strip(): a for a in model.atoms
        if a.helix_id == helix_id and a.bp_index == bp_index and a.direction == direction
    }
    for name in _LINKER_DNA_ATOMS:
        if name in by_name:
            return by_name[name]
    return next(iter(by_name.values()), None)


def linker_extra_bonds(
    design, model, geometry: list[dict] | None = None, k: float = LINKER_K,
) -> list[ExtraBond]:
    """One harmonic click-linker extraBond per *conjugated* attachment.

    Reuses ``oxdna_protein.binder_terminus_nuc_key`` (shared with the oxDNA path)
    to resolve the DNA handle terminus; the conjugation atom is matched into the
    model by residue + atom name.  Free / overhang-anchored proteins (no real
    binder) get no linker here — the ENM still holds them rigid.
    """
    from backend.physics.oxdna_protein import binder_terminus_nuc_key

    attachments = [
        a for a in getattr(design, "protein_attachments", [])
        if getattr(a, "visible", True)
    ]
    if not attachments:
        return []
    assets = {a.id: a for a in getattr(design, "protein_assets", [])}
    if geometry is None:
        from backend.core.design_geometry import _geometry_for_design
        geometry = _geometry_for_design(design)

    bonds: list[ExtraBond] = []
    for att in attachments:
        asset = assets.get(att.asset_id)
        if asset is None:
            continue
        nuc_key = binder_terminus_nuc_key(design, att, geometry)
        if nuc_key is None:
            continue
        conj = _conjugation_model_atom(model, asset, att)
        dna = _dna_terminus_model_atom(model, nuc_key)
        if conj is None or dna is None:
            continue
        bonds.append(ExtraBond(i=conj.serial, j=dna.serial, k=k, b0_ang=_dist_ang(conj, dna)))
    return bonds


def extrabonds_text(bonds: list[ExtraBond]) -> str:
    """NAMD extraBonds file text (``bond <i> <j> <k> <b0>``, 0-based, k then b0)."""
    lines = [
        "# NADOC protein extraBonds (Part B / MD)",
        "# Cα elastic network (fold-locking, salt-robust) + DNA-handle click linker.",
        "# Format: bond <atom_i> <atom_j> <k kcal/mol/Å²> <b0 Å>  (0-based atom indices).",
    ]
    for b in bonds:
        lines.append(f"bond {b.i} {b.j} {b.k:.4f} {b.b0_ang:.4f}")
    return "\n".join(lines) + "\n"


def build_protein_extrabonds(design, model=None, geometry: list[dict] | None = None) -> str:
    """Full protein extraBonds text (ENM + click linkers), or ``""`` if no protein.

    ``model`` should be an AtomisticModel built with ``include_proteins=True`` so
    its protein atoms are present; built on demand when omitted.
    """
    from backend.physics.oxdna_protein import has_proteins

    if not has_proteins(design):
        return ""
    if model is None:
        from backend.core.atomistic import build_atomistic_model
        model = build_atomistic_model(design, include_proteins=True)
    bonds = enm_extra_bonds(model) + linker_extra_bonds(design, model, geometry)
    if not bonds:
        return ""
    return extrabonds_text(bonds)
