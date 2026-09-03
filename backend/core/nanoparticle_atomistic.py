"""Atomistic thiol-DNA linkers for implicit gold nanoparticles.

Gold is deliberately not atomized.  Each supported conjugate therefore ends in
an Au-bound thiolate sulfur at the mathematical particle surface.  The DNA-side
chemistry is an ordinary terminal phosphodiester followed by a propyl thiolate::

    DNA-O-P(O2)-O-CH2-CH2-CH2-S-Au(implicit)

The C3 linker matches the ``-S(CH2)3-`` construct used in the NAMD AuNS-DNA
model of Lee et al. (Nature Communications 2016, doi:10.1038/ncomms13344).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.models import Design


NP_HELIX_PREFIX = "__np__"
LINKER_ATOM_NAMES = ("SNP", "C1L", "C2L", "C3L", "O4L", "PLK", "O1L", "O2L")


@dataclass(frozen=True)
class NanoparticleAnchor:
    nanoparticle_id: str
    strand_id: str
    sulfur_serial: int
    center_ang: tuple[float, float, float]
    radius_ang: float


def _world_point(particle, local) -> np.ndarray:
    return (particle.pose.to_array() @ np.array([*local, 1.0], dtype=float))[:3]


def _orthogonal(unit: np.ndarray) -> np.ndarray:
    trial = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(unit, trial))) > 0.85:
        trial = np.array([0.0, 1.0, 0.0])
    result = np.cross(unit, trial)
    return result / np.linalg.norm(result)


def append_nanoparticle_linkers(model: AtomisticModel, design: Design) -> AtomisticModel:
    """Append real heavy atoms/bonds for supported nanoparticle attachments.

    Only ``direct_thiol`` has a defined molecular topology at present.  Other
    UI schemes remain design/preview options and are rejected by the NAMD
    readiness audit rather than silently receiving invented chemistry.
    """
    particles = {p.id: p for p in design.nanoparticles if p.visible}
    if not particles or not design.nanoparticle_conjugations:
        return model

    atoms = list(model.atoms)
    bonds = list(model.bonds)
    for conjugation in design.nanoparticle_conjugations:
        if conjugation.scheme != "direct_thiol":
            continue
        particle = particles.get(conjugation.nanoparticle_id)
        if particle is None:
            continue
        for record in conjugation.surface_strands:
            residue_atoms = [a for a in atoms if a.strand_id == record.strand_id]
            if not residue_atoms:
                continue
            terminal_seq = 1 if conjugation.attach_end == "5p" else max(a.seq_num for a in residue_atoms)
            terminal = [a for a in residue_atoms if a.seq_num == terminal_seq]
            target_name = "O5'" if conjugation.attach_end == "5p" else "O3'"
            target = next((a for a in terminal if a.name == target_name), None)
            if target is None or any(a.name == "SNP" for a in terminal):
                continue

            sulfur = _world_point(particle, record.sulfur_local_nm)
            target_pos = np.array([target.x, target.y, target.z], dtype=float)
            delta = target_pos - sulfur
            distance = float(np.linalg.norm(delta))
            if distance < 1.0e-8:
                continue
            axis = delta / distance
            side = _orthogonal(axis)

            # Approximate trans heavy-atom geometry, subsequently relaxed by NAMD.
            # Nominal bonded lengths (nm): S-C 0.182, C-C 0.153, C-O 0.143,
            # O-P 0.160, P-O(DNA) 0.160.  A small alternating lateral displacement
            # prevents a singular all-collinear angle/dihedral starting geometry.
            lengths = np.array([0.0, 0.182, 0.335, 0.488, 0.631, 0.791], dtype=float)
            scale = min(1.0, max(0.55, (distance - 0.16) / lengths[-1]))
            backbone = []
            for i, arc in enumerate(lengths):
                pos = sulfur + axis * (arc * scale)
                if 0 < i < len(lengths) - 1:
                    pos = pos + side * (0.025 if i % 2 else -0.025)
                backbone.append(pos)
            # Put linker phosphorus one P-O bond from the DNA terminal oxygen.
            backbone[-1] = target_pos - axis * 0.160
            p = backbone[-1]
            o1 = p + side * 0.148
            o2 = p - side * 0.148
            coords = [*backbone, o1, o2]
            elements = ("S", "C", "C", "C", "O", "P", "O", "O")
            new_serials = []
            for name, element, pos in zip(LINKER_ATOM_NAMES, elements, coords):
                serial = len(atoms)
                atoms.append(Atom(
                    serial=serial, name=name, element=element,
                    residue=target.residue, chain_id=target.chain_id,
                    seq_num=target.seq_num, x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
                    strand_id=target.strand_id, helix_id=target.helix_id,
                    bp_index=target.bp_index, direction=target.direction,
                    is_modified=True,
                ))
                new_serials.append(serial)
            bonds.extend(zip(new_serials[:-3], new_serials[1:-2]))
            # PLK-O1L/O2L and PLK-terminal-DNA-O.
            bonds.extend([(new_serials[5], new_serials[6]), (new_serials[5], new_serials[7]),
                          (new_serials[5], target.serial)])
    return AtomisticModel(atoms=atoms, bonds=bonds)


def nanoparticle_anchors(model: AtomisticModel, design: Design) -> list[NanoparticleAnchor]:
    particles = {p.id: p for p in design.nanoparticles if p.visible}
    result: list[NanoparticleAnchor] = []
    for conjugation in design.nanoparticle_conjugations:
        particle = particles.get(conjugation.nanoparticle_id)
        if particle is None or conjugation.scheme != "direct_thiol":
            continue
        center = _world_point(particle, (0.0, 0.0, 0.0)) * 10.0
        for record in conjugation.surface_strands:
            sulfur = next((a for a in model.atoms if a.strand_id == record.strand_id and a.name == "SNP"), None)
            if sulfur is not None:
                result.append(NanoparticleAnchor(
                    nanoparticle_id=particle.id, strand_id=record.strand_id,
                    sulfur_serial=sulfur.serial,
                    center_ang=tuple(float(v) for v in center),
                    radius_ang=float(particle.diameter_nm * 5.0),
                ))
    return result


def namd_readiness(design: Design) -> dict:
    unsupported = sorted({c.scheme for c in design.nanoparticle_conjugations if c.scheme != "direct_thiol"})
    errors = (["NAMD molecular topology is currently defined only for direct_thiol (C3); "
               f"unsupported schemes: {', '.join(unsupported)}"] if unsupported else [])
    return {
        "passed": not errors,
        "errors": errors,
        "gold_model": "implicit_fixed_sphere",
        "linker": "DNA-O-PO2-O-(CH2)3-S(thiolate)",
        "limitations": [
            "No Au atoms or explicit Au-S bond are present.",
            "The sulfur sites are harmonically restrained to fixed surface coordinates.",
            "Gold polarization, atomistic facets, and Au-S rearrangement are not represented.",
        ],
    }
