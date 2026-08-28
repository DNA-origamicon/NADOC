"""CHARMM/psfgen topology builders for NADOC NAMD packages."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.core.atomistic import Atom, AtomisticModel, build_atomistic_model
from backend.core.md_charge import audit_psf
from backend.core.models import Design
from backend.core.pdb_export import _chain_char, _cryst1_record, _h36


_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"
_TOP_ALL36_NA = _FF_DIR / "top_all36_na.rtf"
_TOP_ALL36_PROT = _FF_DIR / "top_all36_prot.rtf"

from backend.core.protein import PROTEIN_SENTINEL_PREFIX

_RESNAME_TO_CHARMM = {
    "DA": "ADE",
    "DC": "CYT",
    "DG": "GUA",
    "DT": "THY",
}

# Imported-PDB protein residue names → CHARMM36 protein RTF residue names.
# Histidine defaults to the (neutral, δ-protonated) HSD; AMBER/alt protonation
# names collapse to their CHARMM standard so psfgen finds a residue definition.
_PROT_RESNAME_TO_CHARMM = {
    "HIS": "HSD",
    "HID": "HSD",
    "HIE": "HSE",
    "HIP": "HSP",
    "CYX": "CYS",
    "CYM": "CYS",
    "ASH": "ASP",
    "GLH": "GLU",
    "LYN": "LYS",
    "ARN": "ARG",
    "MSE": "MET",
    "SEC": "CYS",
}

# psfgen atom/residue aliases for heavy-atom-only PDBs (CHARMM-GUI convention):
# HIS→HSD, ILE CD1→CD, C-terminal OXT→OT2.  Applied before reading any segment.
_PROT_PDBALIASES = [
    "pdbalias residue HIS HSD",
    "pdbalias residue HID HSD",
    "pdbalias residue HIE HSE",
    "pdbalias residue HIP HSP",
    "pdbalias residue MSE MET",
    "pdbalias atom ILE CD1 CD",
    "pdbalias atom * OXT OT2",
    "pdbalias atom * O OT1",
]


def _is_protein_atom(atom: Atom) -> bool:
    """True when an atomistic atom belongs to a protein attachment (sentinel)."""
    return atom.helix_id.startswith(PROTEIN_SENTINEL_PREFIX)


def _psfgen_prot_segid(index: int) -> str:
    """Unique 4-char psfgen segname for the *index*-th protein chain (``P000``…)."""
    a = _B36[(index // 1296) % 36]
    b = _B36[(index // 36) % 36]
    c = _B36[index % 36]
    return f"P{a}{b}{c}"


_ATOM_TO_CHARMM = {
    "OP1": "O1P",
    "OP2": "O2P",
    "C7": "C5M",
}


@dataclass(frozen=True)
class CharmmTopologyBuild:
    pdb_text: str
    psf_text: str
    metadata: dict


# psfgen ships *inside* the NAMD tarball (top-level, next to namd3), so the
# conventional NAMD install dirs are also psfgen candidates.  Globbed (not
# version-pinned) so a newer NAMD release is found without a code change;
# CUDA builds sort first.  See docs/namd_setup.md.
def _namd_install_dirs() -> list[str]:
    import glob

    dirs = sorted(glob.glob(str(Path.home() / "Applications" / "NAMD_*")), reverse=True)
    dirs.sort(
        key=lambda d: 0 if "cuda" in os.path.basename(d).lower() else 1
    )  # stable: CUDA first
    return dirs


def _psfgen_candidates() -> list[str]:
    """psfgen candidate paths — globbed at CALL time (psfgen ships inside the NAMD
    tarball), so a NAMD installed after server start is detected without a restart."""
    return ["psfgen", *(str(Path(d) / "psfgen") for d in _namd_install_dirs())]


def _resolve_psfgen(candidate: str | None) -> str | None:
    """Resolve a candidate (PATH name or explicit path) to an existing file, else None."""
    if not candidate:
        return None
    return shutil.which(candidate) or (candidate if Path(candidate).exists() else None)


def find_psfgen() -> str:
    """Return a local psfgen executable path.

    Resolution order:
      1. ``$NADOC_PSFGEN_BIN`` — explicit override (path or PATH-resolvable name).
      2. ``psfgen`` on ``$PATH``.
      3. Conventional ``~/Applications`` NAMD installs (psfgen ships in the tarball).

    See ``docs/namd_setup.md``.
    """
    override = os.environ.get("NADOC_PSFGEN_BIN", "").strip()
    candidates = ([override] if override else []) + _psfgen_candidates()
    for candidate in candidates:
        found = _resolve_psfgen(candidate)
        if found:
            return found
    raise RuntimeError(
        "psfgen not found.  Set $NADOC_PSFGEN_BIN, install NAMD (psfgen ships inside the "
        "NAMD tarball under ~/Applications/...), or add psfgen to PATH.  See docs/namd_setup.md."
    )


def _pdb_atom_name(name: str, element: str) -> str:
    if len(name) >= 4:
        return f"{name[:4]:<4s}"
    if len(element) == 1:
        return f" {name:<3s}"
    return f"{name:<4s}"


def _psfgen_resname(atom: Atom) -> str:
    if _is_protein_atom(atom):
        return _PROT_RESNAME_TO_CHARMM.get(atom.residue, atom.residue)
    return _RESNAME_TO_CHARMM.get(atom.residue, atom.residue)


def _psfgen_atom_name(atom: Atom) -> str:
    if _is_protein_atom(atom):
        return atom.name  # protein atom names (CHARMM aliases applied via pdbalias)
    return _ATOM_TO_CHARMM.get(atom.name, atom.name)


_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _psfgen_segid(index: int) -> str:
    """Unique 4-char psfgen segment name for the *index*-th DNA chain.

    psfgen/NAMD segnames are short fixed-width fields; the old ``_psf_segid()[:4]``
    truncation collapsed many strands onto the same name (e.g. chains ``A``/``AA``/
    ``AB`` all → ``DNAA``), which overwrote the shared ``DNAA.pdb`` and emitted
    duplicate ``segment DNAA`` blocks with mismatched residue counts → psfgen
    "no residue N" FATAL.  ``D`` + 3 base-36 digits gives 46 656 unique names.
    """
    a = _B36[(index // 1296) % 36]
    b = _B36[(index // 36) % 36]
    c = _B36[index % 36]
    return f"D{a}{b}{c}"


def psfgen_dna_segids_for_design(n_strands: int) -> list[str]:
    """Return each design-order DNA strand's packaged PSF segment ID.

    The atomistic builder assigns alphabetic chain IDs in design order (``A`` …
    ``Z``, ``AA`` …), while :func:`_write_segment_pdbs` sorts those chain IDs
    lexicographically before assigning base-36 psfgen segids.  Once a design has
    more than 26 strands, neither decimal nor base-36 encoding of the strand index
    identifies the packaged residue.  Reproduce both ordering steps here.
    """
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def chain_id(strand_index: int) -> str:
        if strand_index < 26:
            return letters[strand_index]
        return letters[strand_index // 26 - 1] + letters[strand_index % 26]

    chain_ids = [chain_id(i) for i in range(n_strands)]
    segid_by_chain = {
        cid: _psfgen_segid(i) for i, cid in enumerate(sorted(chain_ids))
    }
    return [segid_by_chain[cid] for cid in chain_ids]


def _psfgen_pdb_record(atom: Atom, serial: int, segid: str) -> str:
    atom_name = _psfgen_atom_name(atom)
    resname = _psfgen_resname(atom)
    chain = _chain_char(atom.chain_id)
    x_ang = atom.x * 10.0
    y_ang = atom.y * 10.0
    z_ang = atom.z * 10.0
    return (
        f"ATOM  {_h36(serial, 5)} {_pdb_atom_name(atom_name, atom.element)} {resname:>3s} {chain}"
        f"{_h36(atom.seq_num, 4)}    "
        f"{x_ang:8.3f}{y_ang:8.3f}{z_ang:8.3f}"
        f"  1.00  0.00      {segid:<4s}{atom.element:>2s}  "
    )


def _write_segment_pdbs(
    design: Design,
    tmpdir: Path,
    model: AtomisticModel | None = None,
) -> tuple[list[dict], str]:
    if model is None:
        model = build_atomistic_model(design)
    atoms_by_chain: dict[str, list[Atom]] = {}
    for atom in model.atoms:
        atoms_by_chain.setdefault(atom.chain_id, []).append(atom)

    full_lines = [
        "REMARK  NADOC psfgen input model (heavy atoms; CHARMM residue/atom names)",
        _cryst1_record(model.atoms, margin_nm=1.2),
    ]
    segments: list[dict] = []
    serial = 1
    dna_seg_index = 0
    prot_seg_index = 0
    for chain_id, atoms in sorted(atoms_by_chain.items(), key=lambda item: item[0]):
        atoms = sorted(atoms, key=lambda a: (a.seq_num, a.serial))
        is_protein = _is_protein_atom(atoms[0])
        if is_protein:
            segid = _psfgen_prot_segid(prot_seg_index)
            prot_seg_index += 1
        else:
            segid = _psfgen_segid(
                dna_seg_index
            )  # unique 4-char segname (no [:4] collisions)
            dna_seg_index += 1
        residues = sorted({a.seq_num for a in atoms})
        if not residues:
            continue
        seg_lines = [
            "REMARK  NADOC psfgen segment input",
            _cryst1_record(atoms, margin_nm=1.2),
        ]
        for atom in atoms:
            line = _psfgen_pdb_record(atom, serial, segid)
            seg_lines.append(line)
            full_lines.append(line)
            serial += 1
        last = atoms[-1]
        seg_lines.append(
            f"TER   {_h36(serial, 5)}      {_psfgen_resname(last):>3s} "
            f"{_chain_char(last.chain_id)}{_h36(last.seq_num, 4)}"
        )
        full_lines.append(seg_lines[-1])
        serial += 1
        seg_lines.append("END")
        seg_path = tmpdir / f"{segid}.pdb"
        seg_path.write_text("\n".join(seg_lines) + "\n")
        segments.append(
            {
                "segid": segid,
                "chain_id": chain_id,
                "path": seg_path,
                "first_resid": residues[0],
                "last_resid": residues[-1],
                "n_residues": len(residues),
                "n_atoms_input": len(atoms),
                "is_protein": is_protein,
                "resids": residues,
            }
        )

    full_lines.append("END")
    return segments, "\n".join(full_lines) + "\n"


def built_pdb_residue_keys(
    model: AtomisticModel, *, sort_chains: bool = False
) -> list[tuple[str, int, str]]:
    """The ordered per-residue ``(helix_id, bp_index, direction)`` keys of the built
    ``{stem}.pdb`` — a key's list index equals its 0-based residue ordinal in the on-disk
    PDB.

    The two package-PDB generators order chains differently, so ``sort_chains`` must
    match the one that built the package:

    * ``sort_chains=False`` (default) — :func:`backend.core.pdb_export.export_pdb` groups
      chains by ``itertools.groupby`` in FIRST-OCCURRENCE (strand-enumeration) order:
      ``A, B, …, Z, AA, AB, …``.  This is the legacy ``mgh_slow_release`` path
      (``require_full_topology=False``).
    * ``sort_chains=True`` — psfgen's :func:`_write_segment_pdbs` sorts chains
      lexicographically: ``A, AA, AB, …, B, …``.  This is the equilibrium-aware path
      (``require_full_topology=True``).

    Past 26 strands the two orders diverge, so the wrong ``sort_chains`` silently anchors
    offset residues.  Within a chain, residues are always ascending ``seq_num``.  psfgen's
    ``writepdb`` blanks the segid column, so residues can only be addressed positionally
    (the same contiguity/ordinal bridge :func:`_parse_base_ring_residues` uses for the
    ENM).  Protein residues keep their slot (``helix_id`` = sentinel) so DNA ordinals stay
    aligned; they never match a DNA anchor key."""
    atoms_by_chain: dict[str, list[Atom]] = {}
    for atom in model.atoms:
        atoms_by_chain.setdefault(atom.chain_id, []).append(atom)
    chain_order = sorted(atoms_by_chain) if sort_chains else list(atoms_by_chain)
    keys: list[tuple[str, int, str]] = []
    for chain_id in chain_order:
        rep: dict[int, Atom] = {}
        for a in atoms_by_chain[chain_id]:
            rep.setdefault(a.seq_num, a)  # any atom of a residue shares its key
        for seq in sorted(rep):
            a = rep[seq]
            keys.append((a.helix_id, a.bp_index, a.direction))
    return keys


def _tagged_segid_resids(
    model: AtomisticModel, psf_path: Path, tag_attr: str, *, sort_chains: bool = True
) -> set[tuple[str, str]]:
    """``(segid, resid)`` of every psfgen'd DNA residue carrying a per-atom ``tag_attr``.

    Shared ordinal bridge for :func:`extra_base_segid_resids` (``crossover_id``) and
    :func:`extension_segid_resids` (``extension_id``) — see either for the rationale.
    """
    atoms_by_chain: dict[str, list[Atom]] = {}
    for a in model.atoms:
        atoms_by_chain.setdefault(a.chain_id, []).append(a)
    chain_order = sorted(atoms_by_chain) if sort_chains else list(atoms_by_chain)
    tagged_ordinals: set[int] = set()
    ordinal = 0
    for chain_id in chain_order:
        by_res: dict[int, list[Atom]] = {}
        for a in atoms_by_chain[chain_id]:
            by_res.setdefault(a.seq_num, []).append(a)
        for seq in sorted(by_res):
            if any(getattr(x, tag_attr, None) is not None for x in by_res[seq]):
                tagged_ordinals.add(ordinal)
            ordinal += 1
    if not tagged_ordinals:
        return set()

    _DNA = {"THY", "ADE", "CYT", "GUA", "DA", "DT", "DC", "DG"}
    seg_res: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    in_atoms = False
    for line in Path(psf_path).read_text().splitlines():
        if "!NATOM" in line:
            in_atoms = True
            continue
        if "!NBOND" in line:
            break
        if not in_atoms:
            continue
        t = line.split()
        if len(t) >= 8 and t[0].isdigit() and t[3] in _DNA:
            key = (t[1], t[2])
            if key not in seen:
                seen.add(key)
                seg_res.append(key)
    return {seg_res[o] for o in tagged_ordinals if o < len(seg_res)}


def extra_base_segid_resids(
    model: AtomisticModel, psf_path: Path, *, sort_chains: bool = True
) -> set[tuple[str, str]]:
    """``(segid, resid)`` of every crossover extra-base residue in a psfgen'd PSF.

    Extra bases carry NO distinguishing mark in the final CHARMM PSF/PDB (they are
    ordinary THY/ADE/CYT/GUA residues), and geometric single-strand detection misses the
    ones sandwiched at a crossover junction (their C1' sits near a neighbouring duplex
    C1').  But the built PDB's residue ORDER is preserved into the PSF (the same
    contiguity/ordinal bridge the ENM uses — see :func:`built_pdb_residue_keys`), so the
    robust map is by ORDINAL: mark each extra-base residue from the model's per-atom
    ``crossover_id`` tag, then read that ordinal's ``(segid, resid)`` from the PSF's
    ordered DNA residues.  ``sort_chains`` must match the package's chain order (True for
    the psfgen / equilibrium-aware path).

    Used to make the dangling extra bases HEAVY in the HMR PSF
    (``write_hmr_psf(heavy_residues=…)``): their fast heavy-atom torsional modes blow a
    4 fs step, and HMR *lightens* those carbons (thymine C5M, sugar C5') making it worse —
    so their masses are scaled UP instead, slowing the modes below the 4 fs limit
    (equilibrium-exact).  Returns an empty set when the design has no extra bases.
    """
    return _tagged_segid_resids(
        model, psf_path, "crossover_id", sort_chains=sort_chains
    )


def extension_segid_resids(
    model: AtomisticModel, psf_path: Path, *, sort_chains: bool = True
) -> set[tuple[str, str]]:
    """``(segid, resid)`` of every strand-extension tail residue in a psfgen'd PSF.

    Mirrors :func:`extra_base_segid_resids`, keyed on the model's per-atom
    ``extension_id`` tag instead of ``crossover_id``. The same geometric blind spot
    applies: a tail near a densely packed bundle can swing within reach of an
    UNRELATED neighbouring helix's C1' — close enough that pure C1'-distance
    single-strand detection (``identify_unpaired_residues``) reads it as paired, even
    though it has no actual Watson-Crick partner. Confirmed on a real single-base 5′
    tail: 10.72 Å to the nearest (unrelated) cross-chain C1', under the 10.8 Å cutoff
    by 0.08 Å. ``sort_chains`` must match the package's chain order (True for the
    psfgen / equilibrium-aware path).
    """
    return _tagged_segid_resids(model, psf_path, "extension_id", sort_chains=sort_chains)


_ATOMS_KEYS = ("atoms", "atom_names", "atomNames")
_MISSING = object()


def _anchor_atom_names(
    anchor: dict, default_atoms: "set[str] | None"
) -> "frozenset[str] | None":
    """One descriptor's held atom names, or ``None`` for "all heavy atoms".

    KEY PRESENCE is the authority signal, not truthiness.  ``{"atoms": None}`` is an
    anchor that deliberately holds every heavy atom and must NOT fall back; a descriptor
    with no ``atoms`` key at all has no opinion and inherits the job-level default.
    Collapsing the two — e.g. with ``anchor.get("atoms") or default`` — leaks the job
    default into rows that explicitly asked for all-heavy.  Mirrors ``hasAnchorAtoms`` /
    ``anchorAtoms`` in ``frontend/src/scene/efield_math.js``."""
    for key in _ATOMS_KEYS:
        if key not in anchor:
            continue
        raw = anchor[key]
        if raw is None:
            return None
        if isinstance(raw, str):
            raw = raw.split(",")
        names = {str(n).strip() for n in raw if str(n).strip()}
        return frozenset(names) if names else None
    return frozenset(default_atoms) if default_atoms else None


def _union_atom_names(a, b):
    """Merge two residue-level atom sets.  ``None`` is the TOP element (all heavy atoms),
    so it absorbs anything.

    UNION, not last-wins: anchors overlap routinely (a base anchor inside an anchored
    strand), and last-wins would make the result depend on list order — which is add
    order, is reshuffled by ``dedupeAnchors``, and is invisible in the UI.  Union is
    monotone: adding an anchor can only ever hold more, never less."""
    if a is _MISSING:
        return b
    if a is None or b is None:
        return None
    return a | b


def requested_atom_names(atom_map: "dict[int, frozenset[str] | None]") -> list[str]:
    """Every atom name any anchor asked for, sorted — for the "matched nothing" error
    message, which must name what was actually requested rather than only the job-level
    default now that each anchor can carry its own list."""
    return sorted({n for names in atom_map.values() if names for n in names})


def resolve_anchor_atom_map(
    design: Design,
    anchors: "list[dict] | None",
    *,
    model: AtomisticModel | None = None,
    full_topology: bool = False,
    default_atoms: "set[str] | None" = None,
) -> "dict[int, frozenset[str] | None]":
    """Resolve anchor descriptors → ``{residue ordinal: held atom names}``, where a
    ``None`` value means "all heavy atoms of that residue".

    The per-anchor twin of :func:`resolve_anchor_residue_indices` (which is now a thin
    delegate).  Each descriptor may carry its own ``atoms`` list; ``default_atoms`` is
    the job-level ``anchor_atoms`` fallback for descriptors that carry none.

    Feeds :func:`backend.core.md_protocols.write_anchor_restraints_pdb` directly — it
    accepts this mapping in place of a plain ordinal set.

    Two things make this cheap enough to run on every prep:

    * **Anchors are grouped by their atom set before resolving.**  The UI offers four
      presets, so a design with 500 anchors still runs the O(nucleotides)
      ``resolve_anchor_particles`` walk at most five times — not once per anchor.
    * **The atomistic model is built once.**  Pass the generator's own ``model`` when you
      have one; ``full_topology`` must match how the package PDB was built.

    Overlapping anchors UNION their atom sets (see :func:`_union_atom_names`).  Stale /
    ssDNA-only keys drop silently, exactly as before.  Read-only: anchors are a
    JOB-REQUEST annotation, never a topology edit (Three-Layer Law)."""
    if not anchors:
        return {}
    from backend.physics.oxdna_interface import resolve_anchor_particles  # noqa: PLC0415

    groups: dict["frozenset[str] | None", list[dict]] = {}
    for a in anchors:
        groups.setdefault(_anchor_atom_names(a, default_atoms), []).append(a)

    # One residue key can own SEVERAL ordinals: a +1 loop insertion emits a second
    # nucleotide sharing (helix_id, bp_index, direction) — the reason Atom.copy_k
    # exists.  A scalar index would silently anchor only one of the copies.
    if model is None:
        model = build_atomistic_model(design, include_proteins=full_topology)
    ordinals_of_key: dict[tuple[str, int, str], list[int]] = {}
    for i, key in enumerate(built_pdb_residue_keys(model, sort_chains=full_topology)):
        ordinals_of_key.setdefault(key, []).append(i)

    out: dict[int, "frozenset[str] | None"] = {}
    for names, group in groups.items():
        _parts, keys = resolve_anchor_particles(design, group)
        for k in keys:
            if len(k) < 3:
                continue
            for ordinal in ordinals_of_key.get((k[0], k[1], k[2]), ()):
                out[ordinal] = _union_atom_names(out.get(ordinal, _MISSING), names)
    return out


def resolve_anchor_residue_indices(
    design: Design,
    anchors: "list[dict] | None",
    *,
    model: AtomisticModel | None = None,
    full_topology: bool = False,
) -> set[int]:
    """Resolve anchor descriptors → the set of 0-based residue ORDINALS to hold fixed in
    a NAMD run (indices into :func:`built_pdb_residue_keys` == the built PDB's residue
    order).

    Reuses the shared oxDNA anchor-scope resolver
    (:func:`backend.physics.oxdna_interface.resolve_anchor_particles` — overhang /
    cluster / domain / strand / base) to turn scopes into per-nucleotide
    ``(helix_id, bp, direction)`` keys, then maps each to its residue ordinal via the
    :class:`~backend.core.atomistic.Atom` per-atom provenance (the same
    ``(helix_id, bp_index, direction)`` bridge :mod:`backend.core.protein_enm` uses).

    ``full_topology`` MUST match the ``require_full_topology`` the package was built with,
    so the residue ordering mirrors the actual package PDB (psfgen sorts chains + includes
    proteins; ``export_pdb`` keeps natural order + DNA only).  Pass the SAME ``model`` the
    generator used when it is available (a seed model), else one is built to match.

    Stale / ssDNA-only / extra-base-insert keys drop silently, matching
    ``resolve_anchor_particles``' stale-selection tolerance.  Anchors are a
    JOB-REQUEST annotation, never a topology edit (Three-Layer Law): this only reads
    positions/keys.

    Which ATOMS of each resolved residue are held is a separate question — see
    :func:`resolve_anchor_atom_map`, which this delegates to and then discards the atom
    sets of.  Callers that write the marker PDB want that one instead."""
    return set(
        resolve_anchor_atom_map(
            design,
            anchors,
            model=model,
            full_topology=full_topology,
        )
    )


def _psfgen_script(segments: list[dict], output_prefix: Path) -> str:
    has_protein = any(seg.get("is_protein") for seg in segments)
    lines = [
        "package require psfgen",
        "resetpsf",
        f"topology {_TOP_ALL36_NA}",
    ]
    if has_protein:
        lines.append(f"topology {_TOP_ALL36_PROT}")
        lines.extend(_PROT_PDBALIASES)
    for seg in segments:
        segid = seg["segid"]
        path = seg["path"]
        first = seg["first_resid"]
        last = seg["last_resid"]
        if seg.get("is_protein"):
            # Protein segment: psfgen builds peptide angles/dihedrals from the RTF;
            # standard NTER/CTER termini (the RTF DEFA), no DNA DEO5/DEOX patches.
            lines.extend(
                [
                    f"segment {segid} {{",
                    "  first NTER",
                    "  last CTER",
                    "  auto angles dihedrals",
                    f"  pdb {path}",
                    "}",
                    f"coordpdb {path} {segid}",
                ]
            )
            continue
        lines.extend(
            [
                f"segment {segid} {{",
                "  first 5TER",
                "  last 3TER",
                "  auto angles dihedrals",
                f"  pdb {path}",
                "}",
                f"patch DEO5 {segid}:{first}",
            ]
        )
        for resid in range(first + 1, last + 1):
            lines.append(f"patch DEOX {segid}:{resid}")
        lines.extend(
            [
                f"coordpdb {path} {segid}",
            ]
        )
    lines.extend(
        [
            "regenerate angles dihedrals",
            "guesscoord",
            f"writepsf {output_prefix}.psf",
            f"writepdb {output_prefix}.pdb",
            "exit",
        ]
    )
    return "\n".join(lines) + "\n"


def build_charmm_psfgen_topology(
    design: Design,
    *,
    psfgen_path: str | None = None,
    atomistic_model: AtomisticModel | None = None,
) -> CharmmTopologyBuild:
    """Build a full all-hydrogen CHARMM DNA PSF/PDB with psfgen.

    This follows the working AutoNAMD NAMD-side topology convention:
    CHARMM residue names (ADE/CYT/GUA/THY), 5TER/3TER strand termini,
    DEO5 on the 5-prime residue, DEOX on internal/3-prime residues, and
    psfgen guesscoord for hydrogens.

    ``atomistic_model`` (optional) supplies pre-built heavy-atom coordinates —
    pass an oxDNA-relaxed model so psfgen starts from relaxed backbone positions
    instead of ideal B-DNA (the Phase-2 NAMD seed).  Default: build ideal B-DNA.
    """
    design = design.without_reference_geometry()
    if not _TOP_ALL36_NA.exists():
        raise RuntimeError(f"Missing CHARMM NA topology file: {_TOP_ALL36_NA}")
    psfgen = psfgen_path or find_psfgen()
    if atomistic_model is None:
        # include_proteins so any visible protein attachment becomes its own
        # psfgen protein segment (Part B); no-op for protein-free designs.
        atomistic_model = build_atomistic_model(design, include_proteins=True)
    with tempfile.TemporaryDirectory(prefix="nadoc_psfgen_") as raw_tmp:
        tmpdir = Path(raw_tmp)
        segments, input_pdb = _write_segment_pdbs(design, tmpdir, atomistic_model)
        if not segments:
            raise RuntimeError("No DNA segments found for psfgen topology build.")
        out_prefix = tmpdir / "nadoc_charmm"
        script = _psfgen_script(segments, out_prefix)
        script_path = tmpdir / "build_psfgen.tcl"
        script_path.write_text(script)
        proc = subprocess.run(
            [psfgen, str(script_path)],
            cwd=tmpdir,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "psfgen failed while building full DNA topology.\n"
                f"stdout:\n{proc.stdout[-4000:]}\n"
                f"stderr:\n{proc.stderr[-4000:]}"
            )
        psf_path = out_prefix.with_suffix(".psf")
        pdb_path = out_prefix.with_suffix(".pdb")
        if not psf_path.exists() or not pdb_path.exists():
            raise RuntimeError(
                "psfgen completed but did not write PSF/PDB outputs.\n"
                f"stdout:\n{proc.stdout[-4000:]}\n"
                f"stderr:\n{proc.stderr[-4000:]}"
            )
        psf_text = psf_path.read_text(errors="replace")
        pdb_text = pdb_path.read_text(errors="replace")
        audit = audit_psf(
            psf_text,
            require_dna_hydrogens=True,
            require_dna_residue_charge=True,
        )
        if not audit.passed:
            raise RuntimeError(
                "psfgen topology failed audit: " + "; ".join(audit.errors)
            )
        metadata = {
            "topology_builder": "charmm_psfgen",
            "psfgen_path": psfgen,
            "forcefield_topology": str(_TOP_ALL36_NA),
            "segments": [
                {
                    k: str(v) if isinstance(v, Path) else v
                    for k, v in seg.items()
                    if k != "path"
                }
                for seg in segments
            ],
            "audit": audit.to_dict(),
            "psfgen_stdout_tail": proc.stdout[-4000:],
            "psfgen_stderr_tail": proc.stderr[-4000:],
        }
        metadata["json"] = json.dumps(metadata, indent=2)
        return CharmmTopologyBuild(
            pdb_text=pdb_text, psf_text=psf_text, metadata=metadata
        )
