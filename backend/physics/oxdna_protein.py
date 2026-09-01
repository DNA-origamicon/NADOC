"""oxDNA-format writers for upstream oxDNA's ``DNANM`` protein-DNA hybrid.

Turns the coarse-grained protein beads + ANM springs (``backend.core.protein_cg``)
into the three oxDNA-format artifacts a hybrid run needs:

* a **hybrid topology** (`.top`) — protein particles FIRST (indices ``0..N_prot-1``,
  negative strand ids) then the DNA nucleotides (shifted by ``+N_prot``), with the
  5-field header the fork expects;
* the **protein configuration lines** (`.dat`) — bead positions in oxDNA units;
* the **ANM parameter file** (`.par`) — one spring per line.

Format mirrors the fork's own examples (``ANMUtils/examples/Cage``):
  topology header   ``N_total N_strands N_dna N_protein N_dna_strands``
  protein line      ``-strand aa prev nbr...``   (nbr = ANM neighbours with j>i)
  DNA line          ``strand base n3 n5``        (n3/n5 shifted by +N_protein)
  .par line         ``i j r0 s k``

Pure functions; no FastAPI, no subprocess.  Unit conversion (nm → oxDNA) happens
here via ``NM_TO_OXDNA``; the geometry upstream is all nm.

KEY INVARIANT (verified against the example): in a hybrid topology the **protein
particles occupy the leading indices**, so every DNA particle index — including
the ``n3``/``n5`` neighbour columns and any trap/anchor reference — is offset by
``+N_protein``.  ``dna_particle_index`` is the single source of truth for that map.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from backend.core.constants import NM_TO_OXDNA
from backend.core.models import Design
from backend.core.protein_cg import (
    ANM_CUTOFF_NM,
    ANM_SPRING_K_STIFF,
    ProteinBead,
    anm_springs,
    conjugation_bead_index,
    protein_beads,
)
from backend.physics.oxdna_interface import (
    _strand_nucleotide_order,
    anchor_trap_block,
    box_nm_for_positions,
    nuc_conf_line,
    resolved_nuc_map,
    topology_rows,
)


# ── Fixed-charge model for physical electric fields ─────────────────────────

FIXED_PROTEIN_PH: float = 8.0
SIDECHAIN_CHARGE_PH8: dict[str, int] = {
    "D": -1,
    "E": -1,
    "K": 1,
    "R": 1,
}


def fixed_residue_charge_ph8(
    aa: str, *, n_terminal: bool = False, c_terminal: bool = False
) -> int:
    """Integer charge (in elementary-charge units) for the fixed pH-8 model.

    Asp/Glu are deprotonated, Lys/Arg protonated, and His/Cys/Tyr are neutral.
    Each polypeptide chain contributes a protonated N terminus (+1) and a
    deprotonated C terminus (-1).  Charges are fixed for the whole trajectory;
    this deliberately does not implement constant-pH or charge regulation.
    """
    charge = SIDECHAIN_CHARGE_PH8.get(str(aa).upper(), 0)
    if n_terminal:
        charge += 1
    if c_terminal:
        charge -= 1
    return charge


def fixed_charge_audit_from_topology(top_path: str | Path) -> dict:
    """Return the reproducible pH-8 charge assignment for a DNANM topology.

    This is the public regression/validation seam for the fixed-charge model.
    It reports every protein particle's residue, terminal flags and assigned
    charge plus charge-group and net-charge summaries.  A DNA-only topology
    returns an empty, valid audit.  Malformed hybrid counts fail loudly.
    """
    lines = Path(top_path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("empty oxDNA topology")
    header = lines[0].split()
    if len(header) < 5:
        return {
            "model": "fixed_residue_charges",
            "pH": FIXED_PROTEIN_PH,
            "n_protein": 0,
            "net_charge_e": 0,
            "charge_groups": {},
            "particles": [],
        }
    try:
        n_total, n_dna, n_protein = int(header[0]), int(header[2]), int(header[3])
    except (ValueError, IndexError) as exc:
        raise ValueError("invalid DNANM topology header") from exc
    if n_total != n_dna + n_protein or len(lines) < 1 + n_protein:
        raise ValueError("inconsistent DNANM topology particle counts")

    rows: list[tuple[str, int]] = []
    for particle, line in enumerate(lines[1 : 1 + n_protein]):
        fields = line.split()
        if len(fields) < 3:
            raise ValueError(f"invalid DNANM protein topology row {particle}")
        try:
            prev = int(fields[2])
        except ValueError as exc:
            raise ValueError(f"invalid DNANM protein predecessor at {particle}") from exc
        rows.append((fields[1].upper(), prev))

    starts = {i for i, (_aa, prev) in enumerate(rows) if prev < 0}
    ends = set(range(n_protein)) - {prev for _aa, prev in rows if prev >= 0}
    particles = []
    groups: dict[str, list[int]] = defaultdict(list)
    for particle, (aa, _prev) in enumerate(rows):
        charge = fixed_residue_charge_ph8(
            aa, n_terminal=particle in starts, c_terminal=particle in ends
        )
        particles.append(
            {
                "particle": particle,
                "aa": aa,
                "n_terminal": particle in starts,
                "c_terminal": particle in ends,
                "charge_e": charge,
            }
        )
        if charge:
            groups[str(charge)].append(particle)
    return {
        "model": "fixed_residue_charges",
        "pH": FIXED_PROTEIN_PH,
        "n_protein": n_protein,
        "net_charge_e": sum(p["charge_e"] for p in particles),
        "charge_groups": dict(groups),
        "particles": particles,
    }

# Default conjugation-link spring (oxDNA units), from the ANM-oxDNA tetrahedron
# example (a click linker fitted to atomistic data).  Tunable as advanced params.
CONJ_TRAP_STIFF: float = 1.424
CONJ_TRAP_R0: float = 1.071
# Default positional-anchor stiffness for free/overhang proteins (keep them from
# diffusing away while still letting the body jiggle/tumble).
ANCHOR_STIFF: float = 1.0

# A protein "block" is the list of beads for one attachment (one protein chain in
# the topology, with its own negative strand id).
Block = list[ProteinBead]


def has_proteins(design: Design) -> bool:
    """True when *design* has at least one VISIBLE protein attachment to simulate."""
    return any(
        getattr(a, "visible", True) for a in getattr(design, "protein_attachments", [])
    )


def build_protein_blocks(
    design: Design, geometry: list[dict]
) -> tuple[list, list[Block]]:
    """Resolve every visible protein attachment to (attachment, beads) for oxDNA.

    Returns parallel lists ``(attachments, blocks)`` — one CG bead block per
    attachment, placed in world nm (overhang-anchored attachments use the overhang
    anchor; free ones use their pose).  Attachments whose asset is missing or which
    produce no beads are skipped (kept parallel).  This is the bridge between the
    persisted protein attachments and the hybrid file writers.
    """
    from backend.core.protein import resolve_overhang_anchor

    assets = {a.id: a for a in getattr(design, "protein_assets", [])}
    attachments: list = []
    blocks: list[Block] = []
    for att in getattr(design, "protein_attachments", []):
        if not getattr(att, "visible", True):
            continue
        asset = assets.get(att.asset_id)
        if asset is None:
            continue
        overhang_id = getattr(att.target, "overhang_id", None)
        if overhang_id is not None:
            tip, outward = resolve_overhang_anchor(
                geometry, overhang_id, getattr(att.target, "attach_end", "free_end")
            )
            beads = protein_beads(asset, att, tip=tip, outward=outward)
        else:
            beads = protein_beads(asset, att)
        if not beads:
            continue
        attachments.append(att)
        blocks.append(beads)
    return attachments, blocks


def protein_bead_count(blocks: list[Block]) -> int:
    """Total protein particles across all attachments (= the DNA index offset)."""
    return sum(len(b) for b in blocks)


def _block_offsets(blocks: list[Block]) -> list[int]:
    """Global starting particle index of each block (cumulative bead counts)."""
    offsets, run = [], 0
    for b in blocks:
        offsets.append(run)
        run += len(b)
    return offsets


def dna_index_offset(blocks: list[Block]) -> int:
    """Index of the first DNA particle in the hybrid (= number of protein beads)."""
    return protein_bead_count(blocks)


def dna_particle_index(design: Design, key: tuple, offset: int) -> int | None:
    """Hybrid particle index of a DNA nucleotide ``key`` (3/4-tuple), or None.

    ``offset`` = ``dna_index_offset(blocks)``.  This is the ONE place the
    protein-first ordering is applied to DNA indices — conjugation traps and
    anchors must resolve nucleotide particles through here.
    """
    idx = {k: i for i, k in enumerate(_strand_nucleotide_order(design))}.get(key)
    return None if idx is None else offset + idx


def protein_topology_lines(
    blocks: list[Block], cutoff_nm: float = ANM_CUTOFF_NM
) -> list[str]:
    """Topology lines for the protein particles (global indices, negative strands).

    Each undirected ANM spring ``(i, j)`` (i<j) is recorded once, as ``j`` in
    ``i``'s neighbour list — matching the fork's convention.  ``prev`` is the
    backbone-previous bead (peptide bond), ``-1`` at a chain start.
    """
    offsets = _block_offsets(blocks)
    lines: list[str] = []
    for bi, beads in enumerate(blocks):
        base = offsets[bi]
        strand_id = -(bi + 1)
        nbrs: dict[int, list[int]] = defaultdict(list)
        for s in anm_springs(beads, cutoff_nm):
            nbrs[s.i].append(s.j)
        for b in beads:
            prev_g = base + b.prev_index if b.prev_index >= 0 else -1
            nlist = " ".join(str(base + j) for j in sorted(nbrs[b.index]))
            line = f"{strand_id} {b.aa} {prev_g}"
            if nlist:
                line += f" {nlist}"
            lines.append(line)
    return lines


def protein_conf_lines(blocks: list[Block]) -> list[str]:
    """Configuration (`.dat`) lines for protein beads (positions in oxDNA units).

    15 floats per particle: ``pos a1 a3 v L``.  Orientation is a placeholder
    orthonormal frame (a1=+x, a3=+z) and velocities are zero — for the classic
    ANM (``DNANM``) the protein excluded volume is isotropic, so the orientation
    is immaterial and the relaxation sets velocities.
    """
    lines: list[str] = []
    for beads in blocks:
        for b in beads:
            x, y, z = (float(c) * NM_TO_OXDNA for c in b.pos_nm)
            lines.append(f"{x:.6f} {y:.6f} {z:.6f} 1 0 0 0 0 1 0 0 0 0 0 0")
    return lines


def anm_par_text(
    blocks: list[Block],
    cutoff_nm: float = ANM_CUTOFF_NM,
    k: float = ANM_SPRING_K_STIFF,
) -> str:
    """ANM parameter file: header ``N_protein`` then ``i j r0 s k`` per spring.

    Global particle indices; ``r0`` in oxDNA units; uniform stiff ``k`` (the
    near-rigid body).  The springs match ``protein_topology_lines`` exactly (both
    derive from ``anm_springs`` over the same beads).
    """
    offsets = _block_offsets(blocks)
    lines = [str(protein_bead_count(blocks))]
    for bi, beads in enumerate(blocks):
        base = offsets[bi]
        for s in anm_springs(beads, cutoff_nm):
            r0 = s.r0_nm * NM_TO_OXDNA
            lines.append(f"{base + s.i} {base + s.j} {r0:.10f} s {k}")
    return "\n".join(lines) + "\n"


def hybrid_topology_text(
    design: Design,
    blocks: list[Block],
    cutoff_nm: float = ANM_CUTOFF_NM,
) -> str:
    """Full hybrid topology text: 5-field header + protein lines + shifted DNA lines.

    Header ``N_total N_strands N_dna N_protein N_dna_strands``.  DNA neighbour
    indices are shifted by ``+N_protein`` (protein particles lead).
    """
    n_prot = protein_bead_count(blocks)
    rows, n_dna_strands = topology_rows(design)
    n_dna = len(rows)
    n_total = n_prot + n_dna
    n_strands = n_dna_strands + len(blocks)
    lines = [f"{n_total} {n_strands} {n_dna} {n_prot} {n_dna_strands}"]
    lines += protein_topology_lines(blocks, cutoff_nm)
    for si, base, n3, n5 in rows:
        s3 = n3 + n_prot if n3 >= 0 else -1
        s5 = n5 + n_prot if n5 >= 0 else -1
        lines.append(f"{si} {base} {s3} {s5}")
    return "\n".join(lines) + "\n"


def hybrid_configuration_text(
    design: Design,
    geometry: list[dict],
    blocks: list[Block],
    box_nm: float | None = None,
    *,
    oxdna_native_seed: bool = False,
) -> str:
    """Full hybrid configuration: header + protein bead lines FIRST + DNA lines.

    Box is sized to cover BOTH the protein beads and the DNA backbone so nothing
    starts outside it; protein and DNA share the one box (oxDNA PBC needs a single
    box).  Protein lines lead so their indices are ``0..N_prot-1`` (the topology
    and trap convention).

    ``oxdna_native_seed`` slides the DNA centres of mass to oxDNA's native bonding
    geometry (:func:`~backend.physics.oxdna_interface.oxdna_native_seed_map`) so the
    DNA pairs start bonded; protein beads are unaffected.
    """
    from backend.physics.oxdna_interface import oxdna_native_seed_map

    resolved = resolved_nuc_map(design, geometry)
    if oxdna_native_seed:
        resolved = oxdna_native_seed_map(design, resolved)
    order = _strand_nucleotide_order(design)
    if box_nm is None:
        dna_pos = [n["backbone_position"] for n in resolved.values()]
        prot_pos = [list(b.pos_nm) for blk in blocks for b in blk]
        box_nm = box_nm_for_positions(dna_pos + prot_pos)
    box = box_nm * NM_TO_OXDNA
    lines = [
        "t = 0",
        f"b = {box:.6f} {box:.6f} {box:.6f}",
        "E = 0.000000 0.000000 0.000000",
    ]
    lines += protein_conf_lines(blocks)
    for key in order:
        nuc = resolved.get(key)
        if nuc is not None:
            lines.append(nuc_conf_line(nuc))
        else:
            ctr = box / 2.0
            lines.append(
                f"{ctr:.6f} {ctr:.6f} {ctr:.6f}  1.0 0.0 0.0  0.0 0.0 1.0  "
                "0.0 0.0 0.0  0.0 0.0 0.0"
            )
    return "\n".join(lines) + "\n"


# ── Protein↔DNA tethers + free-protein anchors (external forces) ───────────────


def _mutual_trap_block(
    particle: int, ref_particle: int, stiff: float, r0: float
) -> str:
    """One oxDNA ``mutual_trap`` block (a spring pulling ``particle`` toward
    ``ref_particle`` at equilibrium length ``r0``, oxDNA units)."""
    return (
        "{\n"
        "type = mutual_trap\n"
        f"particle = {particle}\n"
        f"ref_particle = {ref_particle}\n"
        f"stiff = {stiff:.6g}\n"
        f"r0 = {r0:.6g}\n"
        "}\n"
    )


def conjugation_trap_text(
    prot_particle: int,
    dna_particle: int,
    stiff: float = CONJ_TRAP_STIFF,
    r0: float = CONJ_TRAP_R0,
) -> str:
    """A symmetric ``mutual_trap`` pair tethering a protein conjugation bead to the
    handle (binder) terminal nucleotide — the covalent click linker.  Symmetric so
    both particles feel the spring (the ANM-oxDNA convention)."""
    return _mutual_trap_block(
        prot_particle, dna_particle, stiff, r0
    ) + _mutual_trap_block(dna_particle, prot_particle, stiff, r0)


def _block_centroid_bead(beads: Block) -> int:
    """Local index of the bead nearest the block's centroid (its anchor point)."""
    pos = np.array([b.pos_nm for b in beads])
    c = pos.mean(axis=0)
    return int(np.argmin(np.einsum("ij,ij->i", pos - c, pos - c)))


def protein_anchor_trap_text(
    beads: Block, base: int, stiff: float = ANCHOR_STIFF
) -> str:
    """A single positional ``trap`` pinning a free/overhang protein's centroid bead
    to its placed position (oxDNA units), so the body cannot diffuse away.  One
    anchor (not all beads) leaves the rigid body free to tumble about it."""
    local = _block_centroid_bead(beads)
    pos0 = beads[local].pos_nm * NM_TO_OXDNA
    return anchor_trap_block(base + local, pos0, stiff)


def binder_terminus_nuc_key(
    design: Design,
    attachment,
    geometry: list[dict],
) -> tuple | None:
    """The DNA nucleotide key (helix_id, bp_index, direction) at a conjugated
    protein's handle terminus — the click-linker attachment point on the DNA.

    Reuses the established geometric approach (no polarity reasoning): the binder
    is the strand bound to the overhang (``Domain.binds_overhang_id``); of its two
    termini, pick the one nearest the overhang's ``attach_end`` anchor.  Returns
    None for a free protein or when the binder/geometry is unavailable.
    """
    target = attachment.target
    overhang_id = getattr(target, "overhang_id", None)
    if overhang_id is None:
        return None
    attach_end = getattr(target, "attach_end", "free_end")

    binder = next(
        (
            s
            for s in design.strands
            if any(
                getattr(d, "binds_overhang_id", None) == overhang_id for d in s.domains
            )
        ),
        None,
    )
    if binder is None:
        return None

    from backend.core.protein import resolve_overhang_anchor

    anchor_pos, _ = resolve_overhang_anchor(geometry, overhang_id, attach_end)
    if anchor_pos is None:
        return None

    best_key, best_d = None, float("inf")
    for n in geometry:
        if n.get("strand_id") != binder.id:
            continue
        if not (n.get("is_five_prime") or n.get("is_three_prime")):
            continue
        p = n.get("backbone_position") or n.get("base_position")
        if p is None:
            continue
        d = float(np.linalg.norm(np.asarray(p, dtype=float) - anchor_pos))
        if d < best_d:
            best_d, best_key = d, (n["helix_id"], n["bp_index"], n["direction"])
    return best_key


def _kabsch(P, P_to) -> tuple:
    """Rigid transform (R, t) least-squares mapping points P → P_to (P_to ≈ R·P + t)."""
    P = np.asarray(P, dtype=float)
    Q = np.asarray(P_to, dtype=float)
    Pc, Qc = P.mean(0), Q.mean(0)
    H = (P - Pc).T @ (Q - Qc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return R, Qc - R @ Pc


def protein_display_transforms(
    conf_path,
    reference_path,
    design: Design,
    geometry: list[dict],
    *,
    align: bool = True,
) -> dict:
    """Per-attachment rigid 4×4 (row-major, 16 floats) mapping each protein's DESIGN
    pose to its RELAXED pose in the aligned display frame.

    The protein is near-rigid, so a single rigid transform per protein faithfully
    shows the relaxation: read the relaxed protein beads (leading conf lines), carry
    them through the SAME unwrap+align as the DNA, then Kabsch-fit the design-frame
    beads onto them.  The frontend applies the 4×4 to the (design-posed) protein
    render.  Returns ``{attachment_id: [16 floats]}`` (empty if no protein / mismatch).
    """
    from backend.physics.oxdna_interface import (
        _parse_box_nm,
        _strand_nucleotide_order,
        read_configuration_full,
        read_protein_bead_positions,
        unwrap_align_to_reference,
    )

    order = _strand_nucleotide_order(design)
    prot_sim = read_protein_bead_positions(conf_path, len(order))
    atts, blocks = build_protein_blocks(design, geometry)
    if not prot_sim or len(prot_sim) != protein_bead_count(blocks):
        return {}

    box = _parse_box_nm(conf_path)
    if box is None or not np.all(np.asarray(box) > 0):
        prot_aligned = prot_sim
    else:
        relax = read_configuration_full(conf_path, design)
        ref = read_configuration_full(reference_path, design)
        _, prot_aligned = unwrap_align_to_reference(
            relax, ref, design, box, align=align, extra_points=prot_sim
        )

    out: dict = {}
    cursor = 0
    for att, beads in zip(atts, blocks):
        k = len(beads)
        design_pos = [b.pos_nm for b in beads]
        relaxed_pos = prot_aligned[cursor : cursor + k]
        cursor += k
        if k >= 3:
            R, t = _kabsch(design_pos, relaxed_pos)
        else:  # <3 beads → translation only (no stable rotation)
            R = np.eye(3)
            t = np.mean(relaxed_pos, axis=0) - np.mean(design_pos, axis=0)
        M = np.eye(4)
        M[:3, :3] = R
        M[:3, 3] = t
        out[att.id] = [float(x) for x in M.flatten()]  # row-major 16
    return out


def protein_forces_text(
    design: Design,
    attachments: list,
    blocks: list[Block],
    geometry: list[dict],
    *,
    conj_stiff: float = CONJ_TRAP_STIFF,
    conj_r0: float = CONJ_TRAP_R0,
    anchor_stiff: float = ANCHOR_STIFF,
) -> str:
    """Compose the protein external-forces text for a hybrid run.

    For each attachment (parallel to ``blocks``): if it is conjugated and its
    binder terminus + conjugation bead resolve, emit a conjugation ``mutual_trap``
    (the protein follows the DNA handle); otherwise emit one positional anchor
    ``trap`` on the centroid bead (free/overhang proteins don't drift).
    """
    offsets = _block_offsets(blocks)
    offset = dna_index_offset(blocks)
    parts: list[str] = []
    for att, beads, base in zip(attachments, blocks, offsets):
        conj_local = conjugation_bead_index(beads)
        nt_key = binder_terminus_nuc_key(design, att, geometry)
        dna_p = (
            dna_particle_index(design, nt_key, offset) if nt_key is not None else None
        )
        if conj_local is not None and dna_p is not None:
            parts.append(
                conjugation_trap_text(base + conj_local, dna_p, conj_stiff, conj_r0)
            )
        else:
            parts.append(protein_anchor_trap_text(beads, base, anchor_stiff))
    return "".join(parts)
