"""
Mapping from GROMACS atomistic frames to NADOC bead/slab representations.

Build the chain map once from the design's AtomisticModel, then call one of the
extract_* functions for each frame.  All positions are in nm.

Typical usage
-------------
    model    = build_atomistic_model(design)
    chain_map = build_chain_map(model)

    # From the NADOC input PDB (chain letters preserved):
    pdb_text = Path("input_nadoc.pdb").read_text()
    beads    = extract_from_pdb(pdb_text, chain_map)

    # From a GROMACS GRO/XTC (no chain letters — index-based):
    p_order  = build_p_gro_order(pdb_text, chain_map)
    beads    = extract_from_gro(Path("em.gro"), p_order)

    # Compare to original design:
    stats    = compare_to_design(beads, design)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from backend.core.atomistic import AtomisticModel
    from backend.core.models import Design

# (chain_letter, seq_num_in_chain) → (helix_id, bp_index, direction_str)
ChainMap = dict[tuple[str, int], tuple[str, int, str]]

# Ordered list of (helix_id, bp_index, direction) for GRO index mapping
PAtomOrder = list[tuple[str, int, str]]

_GRO_DNA_RESNAMES = frozenset(
    {
        "DA",
        "DT",
        "DC",
        "DG",
        "DA3",
        "DA5",
        "DT3",
        "DT5",
        "DC3",
        "DC5",
        "DG3",
        "DG5",
        "ADE",
        "THY",
        "CYT",
        "GUA",
        "A",
        "T",
        "C",
        "G",
    }
)


@dataclass(frozen=True)
class BeadPosition:
    """P-atom backbone position mapped to a NADOC nucleotide."""

    helix_id: str
    bp_index: int
    direction: str  # "FORWARD" | "REVERSE"
    pos: np.ndarray  # nm, shape (3,)
    copy: int = 0  # loop-insertion copy index (0 = base / plain nucleotide)


@dataclass
class ComparisonResult:
    n_matched: int
    global_rmsd_nm: float
    per_helix_rmsd_nm: dict[str, float]  # helix_id → RMSD
    max_deviation_nm: float
    n_missing: int  # keys in beads but not in reference


# ── Chain map ─────────────────────────────────────────────────────────────────


# Must equal backend.physics.oxdna_interface._XB_SENTINEL (kept local to avoid a
# core→physics import).  Crossover extra-base atoms map to ("__xb__", crossover_id, k)
# so the MD trajectory keys them uniquely (their stored helix/bp/direction is the
# SOURCE nucleotide's, which would otherwise collide across multiple inserts).
_XB_SENTINEL = "__xb__"
# Must equal backend.physics.oxdna_interface._EXT_PREFIX (same core→physics reason).
_EXT_PREFIX = "__ext_"


def is_synthetic_pkey(key: tuple) -> bool:
    """True for a key that is not a real design position — a crossover extra-base
    insert or a strand-extension tail bead.

    NOTE this cannot be spelled ``isinstance(key[1], int)``: an extension key's second
    element IS an int (its bead index), so every filter written that way to catch
    ``__xb__`` lets extension tails straight through.  Test the helix-id slot instead.
    """
    return isinstance(key[0], str) and key[0].startswith("__")


def md_pkey(atom) -> tuple:
    """The MD/trajectory nucleotide key for a P atom.

    ``("__xb__", crossover_id, extra_base_k)`` for a crossover extra-base insert
    (whose stored helix/bp/direction is the SOURCE nucleotide's and would collide);
    ``("__ext_<id>", bead_index, direction)`` for a strand-extension tail base — the
    SAME key the oxDNA walk emits, so a NAMD trajectory and an oxDNA frame route a
    tail through the identical display path;
    ``(helix_id, bp_index, direction, copy_k)`` for a ``+1`` loop-insertion copy
    (``copy_k >= 1``), whose stored helix/bp/direction ALSO collides with the base it
    bulges off; else the plain ``(helix_id, bp_index, direction)``.  Single source of
    truth shared by ``build_chain_map`` and the MD alignment-reference builder so they
    can never drift (a missed copy crashed the live MD display on the str-vs-int
    compare; a missed loop copy left loop bases un-moved after relaxation).

    The 4-tuple is emitted ONLY for ``copy_k >= 1`` so plain nucleotides and each
    loop's base (copy 0) keep the byte-identical 3-tuple every existing consumer
    expects — mirrors the oxDNA ``copy`` convention (``copy ?? 0``)."""
    if getattr(atom, "crossover_id", None) is not None:
        return (_XB_SENTINEL, atom.crossover_id, atom.extra_base_k)
    if getattr(atom, "extension_id", None) is not None:
        return (f"{_EXT_PREFIX}{atom.extension_id}", atom.ext_k, atom.direction)
    ck = getattr(atom, "copy_k", None)
    if ck:
        return (atom.helix_id, atom.bp_index, atom.direction, int(ck))
    return (atom.helix_id, atom.bp_index, atom.direction)


def md_rigid_reference(model, p_order):
    """Build the Kabsch alignment reference for an MD CG frame.

    Returns ``(eq_positions (N,3), eq_valid (N,), rigid_mask (N,))`` for the N
    entries of *p_order* (the design's P-atom equilibrium positions in nm).
    ``rigid_mask`` excludes entries with no design P atom, ssDNA / loop nucleotides
    (``bp_index < 0``), crossover extra-base inserts (keyed by a string
    ``crossover_id``), AND strand-extension tail beads — all flexible, so including
    them would bias the rigid-body rotation fit.  The ``isinstance`` guard keeps the
    string insert keys from crashing the ``bp_index >= 0`` compare (the live-display
    bug); the ``is_synthetic_pkey`` guard is what catches EXTENSION tails, whose
    ``bp_index`` is a perfectly ordinary non-negative int and so would otherwise be
    treated as rigid dsDNA core."""
    import numpy as np

    p_ref = {
        md_pkey(a): np.array([a.x, a.y, a.z]) for a in model.atoms if a.name == "P"
    }
    eq_list = [p_ref.get(tuple(k)) for k in p_order]
    eq_valid = np.array([v is not None for v in eq_list], dtype=bool)
    eq_positions = np.array([v if v is not None else np.zeros(3) for v in eq_list])
    rigid_mask = eq_valid & np.array(
        [
            (not is_synthetic_pkey(tuple(k))) and isinstance(k[1], int) and k[1] >= 0
            for k in p_order
        ],
        dtype=bool,
    )
    return eq_positions, eq_valid, rigid_mask


def md_snap_mask(p_order, eq_valid, rigid_mask):
    """Atoms that receive the design-eq nearest-image PBC snap in the live display.

    Superset of ``rigid_mask``: rigid dsDNA (bp≥0) PLUS crossover extra-base
    inserts (keyed ``_XB_SENTINEL``) PLUS strand-extension tail beads (keyed
    ``__ext_<id>``).  Both are kept OUT of ``rigid_mask`` (the Kabsch/centroid fit)
    because they are flexible and would bias the rigid-body rotation — but they
    still have a valid, spatially-constrained design-eq position (a tail is only a
    few bases long and is covalently bonded to its anchor), so they must be snapped
    to their nearest periodic image.  Without this, a strand-boundary reset in the
    sequential unwrap can leave an extra base a full box away from the structure
    (the "few bases wrapped" bug).
    Genuinely free ssDNA tails (``bp_index < 0`` integer) stay OUT: their
    transverse swing can exceed the ~half-box, so a whole-box snap would
    over-correct them onto the wrong image.
    """
    import numpy as np

    is_synth = np.array([is_synthetic_pkey(tuple(k)) for k in p_order], dtype=bool)
    return (rigid_mask | is_synth) & eq_valid


def build_chain_map(model: "AtomisticModel") -> ChainMap:
    """
    Build (chain_letter, seq_num) → (helix_id, bp_index, direction) from P atoms.

    chain_letter and seq_num match the PDB written by NADOC's atomistic model —
    the same file that pdb2gmx consumes.  5'-terminal P atoms are included here;
    they are filtered by build_p_gro_order when reading GROMACS output.

    Crossover extra-base P atoms map to the unique key
    ``(_XB_SENTINEL, crossover_id, extra_base_k)`` (their stored helix/bp/direction
    is the SOURCE nucleotide's and would collide), so the MD trajectory can address
    each insert — matching the oxDNA ``__xb__`` contract the frontend already routes.
    """
    chain_map: ChainMap = {}
    for atom in model.atoms:
        if atom.name == "P":
            chain_map[(atom.chain_id, atom.seq_num)] = md_pkey(atom)
    return chain_map


# ── PDB extraction (chain letters preserved) ──────────────────────────────────


def extract_from_pdb(pdb_text: str, chain_map: ChainMap) -> list[BeadPosition]:
    """
    Extract P-atom positions from PDB text and map to NADOC bead positions.

    Positions are converted from Å (PDB) to nm.  Only atoms whose
    (chain_id, seq_num) appear in chain_map are returned; solvent and ions
    are ignored automatically because they have no P atoms in the map.
    """
    beads: list[BeadPosition] = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54:
            continue
        if line[12:16].strip() != "P":
            continue
        chain_id = line[21]
        seq_num = int(line[22:26])
        entry = chain_map.get((chain_id, seq_num))
        if entry is None:
            continue
        helix_id, bp_index, direction = entry[0], entry[1], entry[2]
        copy = entry[3] if len(entry) > 3 else 0
        pos = np.array(
            [
                float(line[30:38]) / 10.0,
                float(line[38:46]) / 10.0,
                float(line[46:54]) / 10.0,
            ]
        )
        beads.append(BeadPosition(helix_id, bp_index, direction, pos, copy))
    return beads


# ── GRO / XTC extraction (index-based, no chain letters) ─────────────────────


def build_p_gro_order(pdb_text: str, chain_map: ChainMap) -> PAtomOrder:
    """
    Build the ordered (helix_id, bp_index, direction) list matching GROMACS DNA P atoms.

    pdb2gmx strips the 5'-terminal P from the first residue of every chain block.
    This function walks the NADOC input PDB in file order, skips those terminals,
    and returns a list whose index i corresponds to the i-th DNA P atom in any
    downstream GROMACS file (GRO, XTC, TRR).

    Parameters
    ----------
    pdb_text   : text of the NADOC input PDB (input_nadoc.pdb)
    chain_map  : from build_chain_map()
    """
    # Detect first residue of each contiguous chain block (one P stripped each).
    block_starts: set[tuple[str, int]] = set()
    prev_chain: str | None = None
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            if len(line) < 26:
                continue
            chain = line[21]
            resnum = int(line[22:26])
            if chain != prev_chain:
                block_starts.add((chain, resnum))
                prev_chain = chain

    # Walk P atoms in PDB file order, skip 5'-terminal entries.
    order: PAtomOrder = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 26:
            continue
        if line[12:16].strip() != "P":
            continue
        chain_id = line[21]
        seq_num = int(line[22:26])
        if (chain_id, seq_num) in block_starts:
            continue  # 5'-terminal P stripped by pdb2gmx
        entry = chain_map.get((chain_id, seq_num))
        if entry is not None:
            order.append(entry)
    return order


def build_p_pdb_order(pdb_text: str, chain_map: ChainMap) -> PAtomOrder:
    """
    Build the ordered (helix_id, bp_index, direction) list for PDB/PSF/DCD data.

    Unlike GROMACS ``pdb2gmx`` outputs, NAMD PSF/DCD packages preserve the P atoms
    present in the NADOC-written PDB.  This therefore walks every mapped P atom in
    PDB file order without stripping 5' terminal phosphates.
    """
    order: PAtomOrder = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 26:
            continue
        if line[12:16].strip() != "P":
            continue
        chain_id = line[21]
        seq_num = int(line[22:26])
        entry = chain_map.get((chain_id, seq_num))
        if entry is not None:
            order.append(entry)
    return order


def load_segid_chain_map(run_dir: Path) -> dict[str, str] | None:
    """Read a NAMD package's psfgen ``segid`` → NADOC ``chain_id`` map.

    CHARMM psfgen re-segments the DNA into one segment per strand (``D000, D001,
    …``) and the PDB's single-character ``chainID`` field cannot hold NADOC's
    multi-character chain ids (``A``, ``AA``, ``AB``, …) — they all collapse to one
    letter, so ``build_p_pdb_order``'s ``(chain_id, resSeq)`` key collides across
    strands.  The package's ``charge_audit.json`` records the true correspondence
    (per-segment ``segid`` + ``chain_id``), which lets us recover each atom's real
    NADOC chain from the PSF's ``segid``.  Returns ``None`` when unavailable.

    Ensemble-replica production packages (``build_replica_package``) don't carry a
    standalone ``charge_audit.json`` — they only hardlink the immutable structure
    files — but their ``manifest.json`` embeds the identical segment metadata under
    ``charge_audit``.  Fall back to that so a replica's flexibility map / P-order
    still resolves via the segid path; otherwise it silently drops the 21
    phosphate-less 5' termini to un-positioned, un-coloured beads.
    """
    import json

    def _segs_to_map(segs) -> dict[str, str] | None:
        if not segs:
            return None
        mapping: dict[str, str] = {}
        for s in segs:
            sid, cid = s.get("segid"), s.get("chain_id")
            if sid is not None and cid is not None:
                mapping[str(sid)] = str(cid)
        return mapping or None

    ca_path = run_dir / "charge_audit.json"
    if ca_path.exists():
        try:
            ca = json.loads(ca_path.read_text())
            segs = (ca.get("topology_metadata") or {}).get("segments") or ca.get(
                "segments"
            )
            m = _segs_to_map(segs)
            if m:
                return m
        except Exception:
            pass

    # Replica packages (no standalone charge_audit.json): the manifest carries the
    # same map under its "charge_audit" field.
    mf_path = run_dir / "manifest.json"
    if mf_path.exists():
        try:
            ca = (json.loads(mf_path.read_text()) or {}).get("charge_audit") or {}
            segs = (ca.get("topology_metadata") or {}).get("segments") or ca.get(
                "segments"
            )
            return _segs_to_map(segs)
        except Exception:
            return None
    return None


def build_p_order_from_universe(u, chain_map: ChainMap, seg2chain: dict[str, str]):
    """Build p_order in trajectory P-atom order for a NAMD PSF/DCD Universe.

    Maps each DNA P atom's ``(segid → NADOC chain_id, resid)`` to its design
    ``(helix_id, bp_index, direction)`` key.  The returned order matches the atom
    order of ``select_atoms("name P and resname <DNA>")`` — i.e. exactly what the
    index-based frame extraction (_extract_universe / _seek_sync) iterates — so no
    reference PDB is needed and the psfgen chainID collision is bypassed.

    Returns ``(p_order, n_unmapped)``.  ``n_unmapped > 0`` means some P atom had no
    design match (chain/resid drift); the caller should fall back rather than serve
    a partial order.
    """
    dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
    order: PAtomOrder = []
    n_unmapped = 0
    for a in dna_p:
        cid = seg2chain.get(str(getattr(a, "segid", "")))
        entry = chain_map.get((cid, int(a.resid))) if cid is not None else None
        if entry is None:
            n_unmapped += 1
            continue
        order.append(entry)
    return order, n_unmapped


def build_termini_specs(u, chain_map: ChainMap, seg2chain: dict[str, str], p_order):
    """Specs for recovering each strand's 5'-terminal nucleotide in a NAMD Universe.

    The 5'-terminal base has NO phosphate — pdb2gmx strips the 5' P — so it is absent
    from the P-indexed ``p_order`` and renders un-positioned/un-coloured in EVERY NAMD
    view (flexibility map, trajectory scrub, live Display-MD).  Each such terminus is
    recovered via its O5' atom, placed off its 3'-neighbour's P (which IS in ``p_order``).

    Returns ``[(design_key, o5_atom_idx, c1_atom_idx, neighbour_p_order_idx), …]`` — one
    per terminus.  Empty when the segid→chain map is unavailable (the same condition under
    which ``build_p_order_from_universe`` is bypassed)."""
    if not seg2chain:
        return []
    p_key_to_idx = {tuple(k): i for i, k in enumerate(p_order)}
    specs: list[tuple] = []
    dna = u.select_atoms("resname " + " ".join(_GRO_DNA_RESNAMES))
    for res in dna.residues:
        if len(res.atoms.select_atoms("name P")):
            continue  # has a P → already in p_order
        o5 = res.atoms.select_atoms("name O5'")
        c1 = res.atoms.select_atoms("name C1'")
        if not len(o5) or not len(c1):
            continue
        cid = seg2chain.get(str(getattr(res.atoms[0], "segid", "")))
        if cid is None:
            continue
        key = chain_map.get((cid, int(res.resid)))  # 5' terminus design key
        nbr_key = chain_map.get((cid, int(res.resid) + 1))  # its 3' neighbour (has P)
        nbr_idx = p_key_to_idx.get(tuple(nbr_key)) if nbr_key is not None else None
        if key is None or nbr_idx is None:
            continue
        specs.append((key, int(o5[0].index), int(c1[0].index), nbr_idx))
    return specs


# Placeholder identity for a heavy atom whose residue has no design key (a residue the
# chain map doesn't cover).  strand_id "" misses every colour lookup → the atom keeps its
# CPK element colour, which is the right fallback for an unidentifiable atom.
_NO_DESIGN_IDENT = {"strand_id": "", "helix_id": "", "bp_index": -1, "direction": ""}


def build_atom_design_meta(
    u,
    heavy_ag,
    p_order,
    model,
    chain_map: ChainMap | None = None,
    seg2chain: dict[str, str] | None = None,
) -> list[dict]:
    """Design identity — ``{strand_id, helix_id, bp_index, direction}`` — per atom of
    *heavy_ag*, in that atom group's order.

    The MD all-atom views (live Display-MD ball-and-stick, trajectory frames, the
    molecular surface) render the SIMULATION's own atoms, which carry no design keys —
    unlike the design's own atomistic model, whose atoms do.  Without this the frontend
    atom colour resolver has nothing to look up, so every MD atom falls back to CPK and
    the strand / base / cluster colouring buttons do nothing.

    Identity is per RESIDUE: each residue's P atom indexes ``p_order`` (the design key
    per trajectory DNA P atom), and the design *model*'s own P atoms carry the strand
    ids under the same ``md_pkey``, so synthetic keys (crossover extra bases,
    strand-extension tails, loop copies) resolve too.  5'-terminal residues have no P
    (pdb2gmx strips it) and so are absent from ``p_order``; they are recovered through
    ``chain_map`` when the segid→chain map is available — the same route
    ``build_termini_specs`` uses for their positions.
    """
    sid_by_key: dict[tuple, str] = {}
    for a in getattr(model, "atoms", ()) or ():
        if a.name == "P":
            sid_by_key.setdefault(md_pkey(a), getattr(a, "strand_id", "") or "")

    key_by_res: dict[int, tuple] = {}
    dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
    p_res = np.asarray(dna_p.resindices)
    for i in range(min(len(p_res), len(p_order))):
        key_by_res[int(p_res[i])] = tuple(p_order[i])

    if chain_map and seg2chain:
        dna = u.select_atoms("resname " + " ".join(_GRO_DNA_RESNAMES))
        for res in dna.residues:
            rix = int(res.ix)
            if rix in key_by_res:
                continue
            cid = seg2chain.get(str(getattr(res.atoms[0], "segid", "") or ""))
            if cid is None:
                continue
            key = chain_map.get((cid, int(res.resid)))
            if key is not None:
                key_by_res[rix] = tuple(key)

    rows: list[dict] = []
    for rix in np.asarray(heavy_ag.resindices):
        key = key_by_res.get(int(rix))
        if key is None:
            rows.append(dict(_NO_DESIGN_IDENT))
            continue
        # A synthetic key's slot 1/2 are not (bp_index, direction) — ("__xb__",
        # crossover_id, extra_base_k) puts a str in slot 1 and an int in slot 2.  Type-
        # check rather than positionally trust, so an extra base still gets its strand
        # colour and simply falls back from the base-letter lookup.
        bp = key[1] if len(key) > 1 and isinstance(key[1], (int, np.integer)) else -1
        dr = key[2] if len(key) > 2 and isinstance(key[2], str) else ""
        rows.append(
            {
                "strand_id": sid_by_key.get(key, ""),
                "helix_id": str(key[0]),
                "bp_index": int(bp),
                "direction": dr,
            }
        )
    return rows


def intern_atom_design_meta(rows: list[dict]) -> dict:
    """Compress ``build_atom_design_meta`` rows into interned parallel arrays.

    A ball-and-stick frame is hundreds of thousands of atoms, and the identity is
    STATIC across frames — repeating four fields per atom per frame would multiply an
    already-large live stream.  The live WebSocket sends this once at load instead:
    three small string tables plus one index (and one bp) per atom.

    ``{strands, helices, dirs, strand_idx, helix_idx, dir_idx, bp}`` — the ``*_idx``
    arrays index their table; every index is valid (the empty string is interned like
    any other value) so the consumer needs no bounds handling.
    """
    strands: list[str] = []
    s_at: dict[str, int] = {}
    helices: list[str] = []
    h_at: dict[str, int] = {}
    dirs: list[str] = []
    d_at: dict[str, int] = {}

    def _idx(val: str, table: list[str], at: dict[str, int]) -> int:
        i = at.get(val)
        if i is None:
            i = len(table)
            table.append(val)
            at[val] = i
        return i

    s_idx: list[int] = []
    h_idx: list[int] = []
    d_idx: list[int] = []
    bp: list[int] = []
    for r in rows:
        s_idx.append(_idx(r["strand_id"], strands, s_at))
        h_idx.append(_idx(r["helix_id"], helices, h_at))
        d_idx.append(_idx(r["direction"], dirs, d_at))
        bp.append(int(r["bp_index"]))
    return {
        "strands": strands,
        "helices": helices,
        "dirs": dirs,
        "strand_idx": s_idx,
        "helix_idx": h_idx,
        "dir_idx": d_idx,
        "bp": bp,
    }


def recover_termini(u, term_specs, p_raw, p_nm, R_align, box_nm, all_pos_A=None):
    """Aligned NADOC-frame positions + base normals for the 5'-terminal nucleotides.

    ``O5'_aligned = neighbourP_aligned + R·minimage(O5'_raw − neighbourP_raw)`` — the
    terminus and its 3'-neighbour P undergo the same rigid transform, so rotating the local
    O5'→neighbourP offset onto the neighbour's already-aligned position is exact.  The base
    normal uses the O5'→C1' vector (the P→C1' analogue).  ``all_pos_A`` (Å) supplies the
    frame's atom positions for the injected fast-path (else read from ``u``).  Returns
    ``(term_pos (M,3) nm, term_norm (M,3))`` — empty arrays when there are no termini or no
    alignment."""
    if not term_specs or R_align is None:
        return np.zeros((0, 3)), np.zeros((0, 3))
    o5_idx = np.array([s[1] for s in term_specs])
    c1_idx = np.array([s[2] for s in term_specs])
    nbr = np.array([s[3] for s in term_specs])
    if all_pos_A is not None:
        o5_raw = all_pos_A[o5_idx] / 10.0
        c1_raw = all_pos_A[c1_idx] / 10.0
    else:
        o5_raw = u.atoms[o5_idx].positions / 10.0
        c1_raw = u.atoms[c1_idx].positions / 10.0
    off = o5_raw - p_raw[nbr]  # O5' relative to its 3'-neighbour's raw P
    dnn = c1_raw - o5_raw  # O5'→C1' base-normal proxy
    if box_nm is not None:
        for _d in range(3):
            if box_nm[_d] > 0:
                off[:, _d] -= np.round(off[:, _d] / box_nm[_d]) * box_nm[_d]
                dnn[:, _d] -= np.round(dnn[:, _d] / box_nm[_d]) * box_nm[_d]
    term_pos = p_nm[nbr] + off @ R_align.T
    dnn = dnn @ R_align.T
    tn = np.linalg.norm(dnn, axis=1, keepdims=True)
    term_norm = dnn / np.where(tn > 1e-6, tn, 1.0)
    return term_pos, term_norm


def extract_from_gro(
    gro_path: Path,
    p_order: PAtomOrder,
    frame: int = 0,
) -> list[BeadPosition]:
    """
    Extract P-atom positions from a GROMACS GRO file and map to NADOC beads.

    GRO files carry no chain information, so mapping is purely by index order:
    the i-th DNA P atom in the GRO corresponds to p_order[i].

    For multi-frame trajectories (XTC/TRR) use extract_from_xtc().
    """
    try:
        import MDAnalysis as mda

        u = mda.Universe(str(gro_path))
        return _extract_universe(u, frame, p_order)
    except ImportError:
        pass

    # Pure-Python fallback for single-frame GRO files.
    p_pos = _parse_gro_p_positions(gro_path)
    return _map_positions(p_pos, p_order)


def extract_from_xtc(
    topology_gro: Path,
    xtc_path: Path,
    p_order: PAtomOrder,
    frame: int = 0,
) -> list[BeadPosition]:
    """
    Extract P-atom positions from an XTC trajectory frame.

    Requires MDAnalysis.  topology_gro is a single-frame GRO (e.g. em.gro)
    used to define the atom topology.
    """
    import MDAnalysis as mda

    u = mda.Universe(str(topology_gro), str(xtc_path))
    return _extract_universe(u, frame, p_order)


_P_BACKBONE_MAX_NM: float = 1.0  # maximum realistic intra-strand P-P distance (nm)


def _unwrap_min_image(positions: np.ndarray, box_nm: np.ndarray) -> np.ndarray:
    """
    Sequential minimum-image unwrapping along the p_order sequence.

    GROMACS wraps all atoms into the primary unit cell, splitting strands that
    cross a periodic boundary.  Consecutive backbone P atoms are ~0.6 nm apart
    (always < half a box length for any reasonable DNA nanostructure box), so
    applying the nearest-image convention between adjacent entries in p_order
    makes each strand whole without needing explicit bond data.

    Strand boundaries (where consecutive p_order entries belong to different
    chains) are detected by the minimum-image distance: if the nearest-image
    distance after correction still exceeds _P_BACKBONE_MAX_NM, the pair is
    treated as a strand boundary and no shift is applied.  This prevents a
    wrongly-placed strand from displacing all subsequent atoms.

    Vectorised (equivalent to the former per-atom loop): the shift added to the
    previous atom is always an integer number of box vectors, so it cancels out of
    the nearest-image rounding — the corrected step between consecutive atoms is
    just the minimum image of their RAW difference, independent of prior
    corrections.  The unwrap therefore reduces to a segmented cumulative sum that
    restarts at each strand boundary (~40× faster than the loop for a 7k-atom
    backbone; validated bit-for-bit against the loop in the test suite).
    """
    dtype = np.asarray(positions).dtype
    pos = np.asarray(positions, dtype=np.float64)
    n = len(pos)
    if n < 2:
        return pos.astype(dtype, copy=True)
    box = np.asarray(box_nm, dtype=np.float64)

    # Minimum image of each consecutive raw difference (per-dim, only where box>0).
    diffs = pos[1:] - pos[:-1]  # (n-1, 3)
    periodic = box > 0
    if periodic.any():
        sub = diffs[:, periodic]
        diffs[:, periodic] = sub - np.round(sub / box[periodic]) * box[periodic]

    # A step longer than a real backbone bond is a strand boundary → the atom it
    # steps INTO resets to its raw position, starting a new segment.
    reset = np.linalg.norm(diffs, axis=1) > _P_BACKBONE_MAX_NM  # (n-1,)

    # Segmented cumulative sum: within a segment starting at s,
    #   out[i] = raw[s] + (cumsum_step[i] - cumsum_step[s]).
    step = np.zeros((n, 3), dtype=np.float64)
    step[1:] = diffs  # step[0] = 0 (segment anchor)
    csum = np.cumsum(step, axis=0)

    seg_start_here = np.zeros(n, dtype=bool)
    seg_start_here[0] = True
    seg_start_here[1:] = reset  # atom i starts a segment iff step i reset
    marker = np.where(seg_start_here, np.arange(n), 0)
    seg_start = np.maximum.accumulate(marker)  # most-recent segment-start index ≤ i

    out = pos[seg_start] + csum - csum[seg_start]
    return out.astype(dtype, copy=False)


def _pbc_circular_centroid(pts: np.ndarray, box_nm: np.ndarray) -> np.ndarray:
    """PBC-robust centroid (per-dimension circular mean).

    A plain mean/median of a structure that NAMD wrapped into TWO clusters a box
    apart lands in the empty gap between them — useless as a center.  The circular
    mean maps each coordinate onto a circle (θ = 2π·x/L), averages the unit vectors,
    and reads the angle back: the true center of a contiguous cluster regardless of
    where the periodic boundary cuts it.  Falls back to the plain mean for a
    non-periodic (box≤0) dimension."""
    pts = np.asarray(pts, dtype=np.float64)
    box = np.asarray(box_nm, dtype=np.float64)
    c = np.zeros(3)
    for d in range(3):
        col = pts[:, d] if pts.ndim == 2 else pts
        L = float(box[d])
        if L <= 0 or len(col) == 0:
            c[d] = float(col.mean()) if len(col) else 0.0
            continue
        ang = col * (2.0 * np.pi / L)
        theta = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
        c[d] = (theta % (2.0 * np.pi)) * (L / (2.0 * np.pi))
    return c


def _nearest_image_to(
    pts: np.ndarray, center: np.ndarray, box_nm: np.ndarray
) -> np.ndarray:
    """Shift each point by whole box vectors to its periodic image nearest ``center``."""
    pts = np.asarray(pts, dtype=np.float64)
    box = np.asarray(box_nm, dtype=np.float64)
    d = pts - center
    for k in range(3):
        if box[k] > 0:
            d[:, k] -= np.round(d[:, k] / box[k]) * box[k]
    return center + d


def _kabsch_rotation(
    mobile_centered: np.ndarray, target_centered: np.ndarray
) -> np.ndarray:
    """Optimal proper rotation R (det +1) with R @ mobileᵀ ≈ targetᵀ — i.e. R maps
    mobile→target.  Both inputs must already be centroid-subtracted (row vectors)."""
    H = np.asarray(mobile_centered).T @ np.asarray(target_centered)
    U, _, Vt = np.linalg.svd(H)
    d = float(np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0)
    return Vt.T @ np.diag([1.0, 1.0, d]) @ U.T


def _strand_runs(p_box: np.ndarray, box_nm: np.ndarray) -> "list[tuple[int, int]]":
    """Contiguous [start, end) runs of ``p_box`` that belong to one strand.

    Uses the SAME criterion as ``_unwrap_min_image``: a step longer than a real backbone
    bond is a strand boundary.  Applied to the ALREADY-UNWRAPPED positions, so a within-
    strand step is the true ~0.6 nm bond and only genuine boundaries exceed it.
    """
    n = len(p_box)
    if n <= 1:
        return [(0, n)]
    steps = np.linalg.norm(np.diff(p_box, axis=0), axis=1)
    starts = [0, *(np.nonzero(steps > _P_BACKBONE_MAX_NM)[0] + 1).tolist()]
    return [(s, e) for s, e in zip(starts, [*starts[1:], n])]


def reassemble_to_posed_reference(
    p_box: np.ndarray,
    box_nm: np.ndarray,
    eq_pos: np.ndarray,
    eq_centroid: np.ndarray,
    rigid_mask: "np.ndarray | None",
    snap_mask: "np.ndarray | None",
) -> "tuple[np.ndarray, np.ndarray]":
    """Pose-first PBC reassembly of a structure onto its design reference.

    The plain translation-only nearest-image snap breaks once the origami has ROTATED
    in the box AND is comparable to / larger than half the box: a distant atom's
    (un-rotated) design reference is then > L/2 from its true position, so
    nearest-image rounding grabs the WRONG periodic image and the atom flies a full
    box across the scene (the "streaks" artefact).  This estimates the rigid-body pose
    (rotation + translation) FIRST, poses the design reference into the box frame, and
    only then nearest-image-snaps — so every atom's reference sits right beside its
    true position and the image is unambiguous even at the ends.

    Steps, all in box coordinates (nm):
      1. PBC-robust centroid ``c_box`` of the rigid backbone (survives a split cluster).
      2. Image all rigid atoms to that centroid — correct for every atom whose radius
         is < L/2 (true for a snugly-solvated bundle; the few beyond are handled next).
      3. Seed Kabsch from all rigid atoms, then ONE inlier refinement dropping any atom
         whose fit residual exceeds ¼·min(box) — exactly the atoms step 2 mis-imaged —
         so the pose is estimated only from reliably-placed atoms.
      4. Pose the FULL design reference into the box frame with that rotation.
      5. Nearest-image-snap every ``snap_mask`` atom to its posed reference; a
         previously-mis-imaged end atom is now RECOVERED because its reference is close.
      6. Free ssDNA (~snap_mask) keeps its sequential-unwrap position (no design snap).

    Returns ``(p_corr_box, c_box)``.  When the structure is un-rotated and un-split the
    result is identical to the old translation-only snap (R≈I, circular≈plain centroid).
    """
    p_box = np.asarray(p_box, dtype=np.float64)
    box = np.asarray(box_nm, dtype=np.float64)
    N = len(p_box)
    rigid = (
        rigid_mask
        if (rigid_mask is not None and np.any(rigid_mask))
        else np.ones(N, bool)
    )

    # 1. robust centroid of the rigid backbone
    c_box = _pbc_circular_centroid(p_box[rigid], box)

    # 2. image rigid atoms to that centroid (correct where radius < half-box)
    p_rigid_c = _nearest_image_to(p_box[rigid], c_box, box)
    eq_rigid = np.asarray(eq_pos, dtype=np.float64)[rigid]

    # 3. seed pose from all rigid, then one inlier refinement (drop mis-imaged ends)
    mob = p_rigid_c - c_box
    tgt = eq_rigid - eq_centroid
    R = _kabsch_rotation(mob, tgt)
    box_pos = box[box > 0]
    if len(box_pos):
        resid = np.linalg.norm(p_rigid_c - ((tgt @ R) + c_box), axis=1)
        inlier = resid < 0.25 * float(np.min(box_pos))
        if 10 <= int(inlier.sum()) < len(resid):
            R = _kabsch_rotation(mob[inlier], tgt[inlier])

    # 4. pose the full design reference into the box frame (design→box is Rᵀ)
    ref_box = (np.asarray(eq_pos, dtype=np.float64) - eq_centroid) @ R + c_box

    # 5. nearest-image snap to the posed reference — PER STRAND RUN, not per atom.
    #
    # A per-atom snap silently tears the backbone apart.  The design reference is an
    # IDEAL structure; wherever the simulated one has drifted more than half a box from
    # it (routine at a flexible crossover or a bundle end), that atom rounds to a
    # different periodic image than its own chain neighbours and jumps a full box on its
    # own.  Measured on the 2hb_1xT 4 fs production: 2 broken O3'-P bonds in EVERY frame,
    # ~3.7-4.4 nm long (= box_x), all inside strand D002 around residues 31-35 — a handful
    # of bases floating off the structure in the MD display.
    #
    # The sequential unwrap already made each strand internally contiguous, and the snap's
    # actual job is only to choose WHICH periodic image a strand sits in (unwrap resets at
    # every strand boundary, so inter-strand placement is arbitrary).  So resolve one
    # integer shift per run and apply it whole: contiguity is then preserved by
    # construction, because a lattice translation cannot change any intra-run distance.
    # The per-run shift is the MEDIAN of its atoms' individual shifts, so a few atoms whose
    # reference is off by >L/2 are outvoted instead of escaping.
    dc = p_box - ref_box
    shift = np.zeros_like(dc)
    for k in range(3):
        if box[k] > 0:
            shift[:, k] = np.round(dc[:, k] / box[k]) * box[k]
    runs = _strand_runs(p_box, box)
    for s, e in runs:
        for k in range(3):
            if box[k] > 0:
                shift[s:e, k] = np.median(shift[s:e, k])
    p_corr = p_box - shift

    # 6. free ssDNA keeps its sequential-unwrap position
    if snap_mask is not None:
        keep = ~np.asarray(snap_mask, dtype=bool)
        p_corr[keep] = p_box[keep]
    return p_corr, c_box


def _extract_universe(
    u: "mda.Universe",
    frame: int,
    p_order: PAtomOrder,
) -> list[BeadPosition]:
    import MDAnalysis as mda  # noqa: F401

    u.trajectory[frame]
    dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
    if len(dna_p) != len(p_order):
        raise ValueError(
            f"Frame {frame}: {len(dna_p)} DNA P atoms in trajectory "
            f"but p_order has {len(p_order)} entries. "
            "Re-build p_order with the correct input PDB."
        )
    positions_nm = dna_p.positions / 10.0  # Å → nm

    # Apply minimum-image sequential unwrap so no P atom is split across a
    # periodic boundary.  Requires box dimensions from the trajectory frame.
    dims = u.dimensions
    if dims is not None and dims[0] > 0:
        box_nm = dims[:3] / 10.0
        positions_nm = _unwrap_min_image(positions_nm, box_nm)

    return [
        BeadPosition(k[0], k[1], k[2], positions_nm[i], k[3] if len(k) > 3 else 0)
        for i, k in enumerate(p_order)
    ]


def _parse_gro_p_positions(gro_path: Path) -> list[np.ndarray]:
    """Parse DNA P-atom positions (nm) from a single-frame GRO file."""
    positions: list[np.ndarray] = []
    lines = Path(gro_path).read_text().splitlines()
    for line in lines[2:]:  # skip title + atom-count lines
        if len(line) < 44:
            break  # reached box-vector line
        res_name = line[5:10].strip()
        atom_name = line[10:15].strip()
        if atom_name == "P" and res_name in _GRO_DNA_RESNAMES:
            try:
                x = float(line[20:28])
                y = float(line[28:36])
                z = float(line[36:44])
                positions.append(np.array([x, y, z]))
            except ValueError:
                continue
    return positions


def _map_positions(
    p_positions: list[np.ndarray],
    p_order: PAtomOrder,
) -> list[BeadPosition]:
    if len(p_positions) != len(p_order):
        raise ValueError(
            f"{len(p_positions)} DNA P atoms found but p_order has {len(p_order)} entries."
        )
    return [
        BeadPosition(k[0], k[1], k[2], pos, k[3] if len(k) > 3 else 0)
        for k, pos in zip(p_order, p_positions)
    ]


# ── Comparison to reference ───────────────────────────────────────────────────


def compare_to_design(
    beads: list[BeadPosition],
    design: "Design",
    *,
    use_geometry_layer: bool = False,
    align_translation: bool = False,
) -> ComparisonResult:
    """
    Compare extracted P-atom positions to reference positions.

    use_geometry_layer=False (default):
        Reference = AtomisticModel P-atom positions (_ATOMISTIC_P_RADIUS ≈ 0.886 nm).
        Expected near-zero RMSD for input_nadoc.pdb; small RMSD for post-EM GRO.

    use_geometry_layer=True:
        Reference = nucleotide_positions() backbone (HELIX_RADIUS = 1.0 nm).
        Will show ~1.1 Å systematic radial offset because P atoms sit at 0.886 nm,
        not 1.0 nm.  Useful for understanding the coordinate-system offset.

    align_translation=True:
        Remove the centroid offset before computing RMSD.  Required when comparing
        GROMACS frames (box coordinate system) to NADOC world coordinates — GROMACS
        translates the structure into the periodic box, introducing a constant shift
        of ~6–7 nm with no rotation.
    """
    ref_map = _build_reference_map(design, use_geometry_layer)
    return _compute_comparison(beads, ref_map, align_translation=align_translation)


def centroid_offset(
    beads: list[BeadPosition],
    design: "Design",
    *,
    use_geometry_layer: bool = False,
) -> np.ndarray:
    """
    Compute the translation T = ref_centroid - bead_centroid.

    Apply as: bead.pos + T  to bring GROMACS-frame positions into NADOC world frame.
    GROMACS does not rotate the structure relative to the input PDB (only translation
    via editconf -c), so a pure centroid alignment is sufficient for visualisation.
    """
    ref_map = _build_reference_map(design, use_geometry_layer)
    bead_pts, ref_pts = [], []
    for bead in beads:
        key = (bead.helix_id, bead.bp_index, bead.direction)
        if key in ref_map:
            bead_pts.append(bead.pos)
            ref_pts.append(ref_map[key])
    if not bead_pts:
        return np.zeros(3)
    return np.mean(ref_pts, axis=0) - np.mean(bead_pts, axis=0)


def _build_reference_map(
    design: "Design",
    use_geometry_layer: bool,
) -> dict[tuple[str, int, str], np.ndarray]:
    if use_geometry_layer:
        from backend.core.geometry import nucleotide_positions

        ref: dict[tuple[str, int, str], np.ndarray] = {}
        for helix in design.helices:
            for nuc in nucleotide_positions(helix):
                key = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
                ref[key] = nuc.position
        return ref
    else:
        from backend.core.atomistic import build_atomistic_model

        model = build_atomistic_model(design)
        ref = {}
        for atom in model.atoms:
            if atom.name == "P":
                key = (atom.helix_id, atom.bp_index, atom.direction)
                ref[key] = np.array([atom.x, atom.y, atom.z])
        return ref


def _compute_comparison(
    beads: list[BeadPosition],
    ref_map: dict[tuple[str, int, str], np.ndarray],
    align_translation: bool = False,
) -> ComparisonResult:
    per_helix_devs: dict[str, list[float]] = {}
    all_devs: list[float] = []
    n_missing = 0

    # Compute centroid translation if requested (GROMACS box → NADOC world frame).
    translation = np.zeros(3)
    if align_translation:
        bead_pts, ref_pts = [], []
        for bead in beads:
            key = (bead.helix_id, bead.bp_index, bead.direction)
            if key in ref_map:
                bead_pts.append(bead.pos)
                ref_pts.append(ref_map[key])
        if bead_pts:
            translation = np.mean(ref_pts, axis=0) - np.mean(bead_pts, axis=0)

    for bead in beads:
        key = (bead.helix_id, bead.bp_index, bead.direction)
        ref_pos = ref_map.get(key)
        if ref_pos is None:
            n_missing += 1
            continue
        dev = float(np.linalg.norm(bead.pos + translation - ref_pos))
        all_devs.append(dev)
        per_helix_devs.setdefault(bead.helix_id, []).append(dev)

    per_helix_rmsd = {
        hid: float(np.sqrt(np.mean(np.array(devs) ** 2)))
        for hid, devs in per_helix_devs.items()
    }
    global_rmsd = float(np.sqrt(np.mean(np.array(all_devs) ** 2))) if all_devs else 0.0
    max_dev = float(max(all_devs)) if all_devs else 0.0

    return ComparisonResult(
        n_matched=len(all_devs),
        global_rmsd_nm=global_rmsd,
        per_helix_rmsd_nm=per_helix_rmsd,
        max_deviation_nm=max_dev,
        n_missing=n_missing,
    )
