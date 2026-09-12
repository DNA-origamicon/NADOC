"""PDB aptamers mapped to editable native strands and persistent residue sites.

A logical helix provides addressing only; it does not imply Watson–Crick pairing.
Both coarse and atomic projections read the same saved sites before transforms.
"""

from collections import OrderedDict
from pathlib import Path
import uuid

import numpy as np

from backend.core.models import (
    ClusterRigidTransform,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    NativeResidue,
    Strand,
    Vec3,
)
from backend.core.pdb_to_design import _DNA_RESNAME

CATALOG = [
    {
        "id": "148D",
        "name": "TBA / HD1 — antiparallel G4",
        "ion": "K+",
        "description": "15-nt thrombin-binding aptamer; potassium-responsive G4 motif. Two quartets, three loops.",
        "url": "https://www.rcsb.org/structure/148D",
    },
    {
        "id": "2HY9",
        "name": "Human telomere — hybrid-1 G4",
        "ion": "K+",
        "description": "Intramolecular human telomeric quadruplex determined in potassium solution.",
        "url": "https://www.rcsb.org/structure/2HY9",
    },
    {
        "id": "1C35",
        "name": "TBA — potassium complex",
        "ion": "K+",
        "description": "TBA solution structure from the potassium-saturated/intermediate complex study.",
        "url": "https://www.rcsb.org/structure/1C35",
    },
]
DATA = Path(__file__).resolve().parent.parent / "data" / "aptamers"


def template_content(template_id):
    if template_id not in {entry["id"] for entry in CATALOG}:
        raise ValueError("Unknown aptamer template")
    return (DATA / f"{template_id}.pdb").read_text()


def import_aptamer(content: str, name="Aptamer", source="local PDB") -> Design:
    """First PDB model, preserving chain/TER/segment boundaries and insertion codes.

    File order defines 5′→3′ residue order. Alternate blank/A locations win.
    Incomplete backbone connectivity is rejected rather than silently fabricating
    a covalent strand across missing residues. Non-DNA records are not strands.
    """
    chains = OrderedDict()
    block = 0
    for line in content.splitlines():
        record = line[:6].strip()
        if record == "ENDMDL":
            break
        if record == "TER":
            block += 1
            continue
        if record not in ("ATOM", "HETATM") or len(line) < 54:
            continue
        resname = line[17:20].strip().upper()
        base = _DNA_RESNAME.get(resname)
        if base not in ("A", "C", "G", "T"):
            if line[12:16].strip().replace("*", "'") == "C1'":
                raise ValueError(
                    f"Unsupported nucleic-acid residue {resname}; no residues were imported"
                )
            continue
        if line[16:17] not in (" ", "A", ""):
            continue
        chain = (block, line[21:22], line[72:76].strip())
        key = (line[22:26], line[26:27])
        residues = chains.setdefault(chain, OrderedDict())
        residue = residues.setdefault(key, {"base": base, "atoms": {}})
        atom = line[12:16].strip().replace("*", "'")
        atom = {"O1P": "OP1", "O2P": "OP2"}.get(atom, atom)
        xyz = [float(line[i : i + 8]) / 10 for i in (30, 38, 46)]
        if not np.all(np.isfinite(xyz)):
            raise ValueError("PDB coordinates must be finite")
        residue["atoms"].setdefault(atom, Vec3(x=xyz[0], y=xyz[1], z=xyz[2]))
    if not chains:
        raise ValueError("No supported DNA residues found")
    helices, strands = [], []
    for (block, chain, segment), residues in chains.items():
        sites = []
        previous = None
        for i, ((number, insertion), res) in enumerate(residues.items()):
            atoms = res["atoms"]
            glyco = "N9" if res["base"] in "AG" else "N1"
            if any(k not in atoms for k in ("C1'", "O3'", glyco, "C4", "C2")):
                raise ValueError(
                    f"Incomplete DNA residue {chain}:{number.strip()}{insertion.strip()}"
                )
            if "O2'" in atoms:
                raise ValueError("RNA aptamers are not supported by this DNA importer")
            if previous is not None:
                if (
                    "P" not in atoms
                    or np.linalg.norm(previous - atoms["P"].to_array()) > 0.3
                ):
                    raise ValueError(
                        f"Broken DNA backbone at {chain}:{number.strip()}; split disconnected strands with TER records"
                    )
            previous = atoms["O3'"].to_array()
            sites.append(
                NativeResidue(
                    bp_index=i,
                    base=res["base"],
                    atoms=atoms,
                    source_residue=f"{chain.strip() or '_'}:{segment}:{number.strip()}{insertion.strip()}:{block}",
                )
            )
        hid = f"apt_{uuid.uuid4().hex[:12]}"
        origin = sites[0].atoms["C1'"].to_array()
        helices.append(
            Helix(
                id=hid,
                axis_start=Vec3.from_array(origin),
                axis_end=Vec3.from_array(origin + [0, 0, max(1, len(sites)) * 0.332]),
                length_bp=len(sites),
                native_residues=sites,
                native_source=source,
            )
        )
        strands.append(
            Strand(
                name=f"{name} · {chain.strip() or segment or block + 1}",
                sequence="".join(s.base for s in sites),
                color="#A855F7",
                notes=f"G4 candidate; {source}. Ion response depends on sequence, buffer and attachment geometry.",
                domains=[
                    Domain(
                        helix_id=hid,
                        start_bp=0,
                        end_bp=len(sites) - 1,
                        direction=Direction.FORWARD,
                    )
                ],
            )
        )
    return Design(
        helices=helices,
        strands=strands,
        metadata=DesignMetadata(name=name, tags=["aptamer", "G4", "K+"]),
        cluster_transforms=[
            ClusterRigidTransform(name=name, helix_ids=[h.id for h in helices])
        ],
    )


def _unit(v):
    length = np.linalg.norm(v)
    if length < 1e-9:
        raise ValueError("Degenerate aptamer residue frame")
    return v / length


def site_geometry(helix, bp):
    sites = helix.native_residues
    site = next((s for s in sites if s.bp_index == bp), None)
    shift = np.zeros(3)
    if site is None:
        # New terminal bases extend the local backbone by ssDNA contour spacing.
        site = min(sites, key=lambda s: abs(s.bp_index - bp))
        edge = 0 if bp < sites[0].bp_index else -1
        if len(sites) > 1:
            other = sites[1 if edge == 0 else -2]
            tangent = _unit(
                site.atoms["C1'"].to_array() - other.atoms["C1'"].to_array()
            )
        else:
            tangent = np.array([0.0, 0.0, -1.0 if edge == 0 else 1.0])
        shift = tangent * abs(bp - site.bp_index) * 0.6
    atoms = {k: v.to_array() + shift for k, v in site.atoms.items()}
    backbone = atoms["C1'"]
    ring = [
        atoms[k]
        for k in ("N1", "C2", "N3", "C4", "C5", "C6", "N7", "C8", "N9")
        if k in atoms
    ]
    base = np.mean(ring, axis=0)
    normal = _unit(base - backbone)
    tangent = _unit(
        np.cross(
            atoms["C4"] - atoms["C2"],
            atoms["N9" if site.base in "AG" else "N1"] - atoms["C2"],
        )
    )
    return backbone, base, normal, tangent, atoms, site


def native_partner_sequence(design, strand):
    """Assign the antiparallel sequence when painting on a native carrier."""
    from backend.core.sequences import domain_bp_range, complement_base, _build_loop_skip_map
    native_ids = {h.id for h in design.helices if h.native_residues}
    if not strand.domains or any(d.helix_id not in native_ids for d in strand.domains):
        return None
    sites = {}
    skips = _build_loop_skip_map(design)
    for existing in design.strands:
        if existing.is_reference:
            continue
        seq = iter(existing.sequence or "")
        for domain in existing.domains:
            for bp in domain_bp_range(domain):
                count = 1 if domain.overhang_id or domain.binds_overhang_id else max(0, 1 + skips.get((domain.helix_id, bp), 0))
                bases = [next(seq, "N") for _ in range(count)]
                if domain.helix_id in native_ids:
                    sites[(domain.helix_id, bp, domain.direction)] = bases
    result = []
    for domain in strand.domains:
        opposite = Direction.REVERSE if domain.direction == Direction.FORWARD else Direction.FORWARD
        for bp in domain_bp_range(domain):
            count = max(0, 1 + skips.get((domain.helix_id, bp), 0))
            partners = sites.get((domain.helix_id, bp, opposite), [])
            result.extend(complement_base(partners[i]) if i < len(partners) else "N" for i in range(count))
    return "".join(result)


def native_core_paired(helix, design):
    """An authored antiparallel partner selects duplex geometry, not ion physics.

    Tail-only binders leave the deposited fold intact. Source residues stay saved
    so deleting/undoing the partner restores the folded state.
    """
    if not helix.native_residues:
        return False
    core = {site.bp_index for site in helix.native_residues}
    occupied = {Direction.FORWARD: set(), Direction.REVERSE: set()}
    for strand in design.strands:
        if strand.is_reference:
            continue
        for domain in strand.domains:
            if domain.helix_id == helix.id:
                lo, hi = sorted((domain.start_bp, domain.end_bp))
                occupied[domain.direction].update(bp for bp in core if lo <= bp <= hi)
    return bool(occupied[Direction.FORWARD] & occupied[Direction.REVERSE])


def _tail_positions(helix, edge_bp):
    """Ordinary B-DNA attachment slots fitted to the terminal native frame."""
    from backend.core.geometry import nucleotide_positions
    from backend.core.constants import BDNA_RISE_PER_BP

    lo = min(helix.bp_start, edge_bp)
    hi = max(helix.bp_start + helix.length_bp - 1, edge_bp)
    start = np.array([0., 0., (lo - edge_bp) * BDNA_RISE_PER_BP])
    straight = helix.model_copy(update={
        "native_residues": [], "bp_start": lo, "length_bp": hi - lo + 1,
        "axis_start": Vec3.from_array(start),
        "axis_end": Vec3.from_array(start + [0, 0, (hi - lo + 1) * BDNA_RISE_PER_BP]),
        "phase_offset": (lo - edge_bp) * helix.twist_per_bp_rad,
        "loop_skips": [],
    })
    positions = nucleotide_positions(straight)
    anchor = next(n for n in positions if n.bp_index == edge_bp and n.direction == Direction.FORWARD)
    backbone, _, normal, tangent, _, _ = site_geometry(helix, edge_bp)

    def frame(n, t):
        t = _unit(t - np.dot(t, n) * n)
        return np.column_stack((n, np.cross(t, n), t))

    rotation = frame(normal, tangent) @ frame(anchor.base_normal, anchor.axis_tangent).T
    origin = anchor.position.copy()
    from dataclasses import replace
    return [replace(nuc,
        position=backbone + rotation @ (nuc.position - origin),
        base_position=backbone + rotation @ (nuc.base_position - origin),
        base_normal=rotation @ nuc.base_normal,
        axis_tangent=rotation @ nuc.axis_tangent,
        axis_point=None, radial_hat=None, azimuth_rad=None,
    ) for nuc in positions]


def native_positions(helix):
    from backend.core.geometry import NucleotidePosition

    core_lo = min(s.bp_index for s in helix.native_residues)
    core_hi = max(s.bp_index for s in helix.native_residues)
    tails = {}
    for edge in (core_lo, core_hi):
        if (edge == core_lo and helix.bp_start < core_lo) or (edge == core_hi and helix.bp_start + helix.length_bp - 1 > core_hi):
            tails.update({(n.bp_index, n.direction): n for n in _tail_positions(helix, edge)
                          if (n.bp_index < core_lo if edge == core_lo else n.bp_index > core_hi)})
    result = []
    for bp in range(helix.bp_start, helix.bp_start + helix.length_bp):
        if bp < core_lo or bp > core_hi:
            result.extend(tails[(bp, d)] for d in (Direction.FORWARD, Direction.REVERSE))
            continue
        backbone, base, normal, tangent, _, _ = site_geometry(helix, bp)
        for direction in (Direction.FORWARD, Direction.REVERSE):
            result.append(
                NucleotidePosition(
                    helix.id,
                    bp,
                    direction,
                    backbone.copy(),
                    base.copy(),
                    normal.copy(),
                    tangent.copy(),
                )
            )
    return result


def apply_native_atoms(atoms, design):
    """Project saved coordinates onto native atom identities before cluster transforms.

    Matched atoms keep deposited coordinates. New terminal residues use a rigid
    fit of their own base template to the extrapolated terminal frame.
    """
    helices = {h.id: h for h in design.helices if h.native_residues and not native_core_paired(h, design)}
    if not helices:
        return
    groups = {}
    for atom in atoms:
        if atom.helix_id in helices and atom.extension_id is None:
            groups.setdefault(
                (atom.helix_id, atom.bp_index, atom.direction), []
            ).append(atom)
    for (hid, bp, direction), group in groups.items():
        if direction != "FORWARD" or not any(s.bp_index == bp for s in helices[hid].native_residues):
            continue
        _, _, _, _, target, site = site_geometry(helices[hid], bp)
        by_name = {a.name: a for a in group}
        names = [
            n
            for n in ("C1'", "C2'", "C3'", "C4'", "O4'")
            if n in by_name and n in target
        ]
        if len(names) < 3:
            continue
        src = np.array([[by_name[n].x, by_name[n].y, by_name[n].z] for n in names])
        dst = np.array([target[n] for n in names])
        u, _, vt = np.linalg.svd((src - src.mean(0)).T @ (dst - dst.mean(0)))
        rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
        for atom in group:
            p = (
                np.array([atom.x, atom.y, atom.z]) - src.mean(0)
            ) @ rotation + dst.mean(0)
            # Preserve exact source geometry only while this residue's base matches.
            if atom.residue == "D" + site.base and atom.name in target:
                p = target[atom.name]
            atom.x, atom.y, atom.z = map(float, p)
