"""
MD Protocol Presets — config generation for managed NAMD jobs.

Currently implements one preset:

  mgh_slow_release
    MGH explicit-solvent package (Mg-hexahydrate, TIP3P, CHARMM36/CUFIX)
    → Aksimentiev-style ENM minimization and long NPT equilibration
    → ENM ladder k=0.5 → 0.1 → 0.01 → k=0 handoff
    Health gates after every segment:
    C1' paired fraction ≥ 90%
    WC ref-relative ≥ 80% during ENM stages and ≥ 75% during k=0 handoff

Each segment runs to 10%, 50%, or 100% of its stage length so health checks
are frequent early in each new temperature or k setting.
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.spatial import cKDTree

from backend.core.models import Design


LEGACY_PROTOCOL = "mgh_slow_release"
EQUILIBRIUM_AWARE_PROTOCOL = "equilibrium_aware_namd"
SUPPORTED_PROTOCOLS = {LEGACY_PROTOCOL, EQUILIBRIUM_AWARE_PROTOCOL}
AKSIMENTIEV_STEPS_PER_CYCLE = 12


# ── Segment spec ──────────────────────────────────────────────────────────────

@dataclass
class SegmentSpec:
    name:     str              # output name prefix, e.g. "B_tube_01_050K_NVT_k5_p10"
    stage:    str              # human stage label, e.g. "50K NVT k=5.0"
    percent:  float            # 10, 50, or 100
    steps:    int              # MD steps in this segment
    temp:     float            # target temperature (K)
    damping:  float            # Langevin damping (ps^-1)
    scale:    Optional[float]  # restraint k (kcal/mol/Å²); None = unrestrained
    npt:      bool             # True if barostat is on
    previous: str              # output name of the preceding segment (or min)
    reinit:   bool = False     # True → reinitvels + temperature instead of vel continuation
    dcd_freq: int  = 20000     # DCD frame output interval (steps)
    min_c1_paired: float = 0.90
    min_wc_ref_relative: float = 0.85
    extra_bonds_file: Optional[str] = None
    soft: bool = False  # True → rigidBonds none + 1 fs (declash designs with
    #        residual single-stranded contacts that crash RATTLE)


# ── NAMD conf template ────────────────────────────────────────────────────────

def _common_header(
    name_stem: str,
    box: tuple[float, float, float],
    _mgh_extrabonds: bool,
    *,
    rigid_bonds: str = "all",
    timestep: float = 2.0,
) -> str:
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    return f"""\
structure          {name_stem}.psf
coordinates        {name_stem}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            off
wrapWater          off

PME                yes
PMEGridSpacing     1.5

cutoff             10.0
switching          on
switchdist         8.0
pairlistdist       12.0
exclude            scaled1-4
oneFourScaling     1.0

rigidBonds         {rigid_bonds}
rigidTolerance     1.0e-8

langevin           on
langevinHydrogen   off

timestep           {timestep:g}
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      12

outputEnergies     9600
xstFreq            9600
restartfreq        9600
binaryrestart      yes
"""


def _segment_conf(
    spec: SegmentSpec,
    name_stem: str,
    box: tuple[float, float, float],
    mgh_extrabonds: bool,
    *,
    minimize_steps: int = 0,
) -> str:
    # Soft integrator: flexible H bonds + 1 fs timestep.  Needed for declashed
    # designs whose residual single-stranded contacts crash rigid-bond RATTLE.
    rigid_bonds = "none" if spec.soft else "all"
    timestep = 1.0 if spec.soft else 2.0
    lines = [
        _common_header(
            name_stem, box, mgh_extrabonds, rigid_bonds=rigid_bonds, timestep=timestep
        )
    ]
    lines.append(f"outputName         output/{spec.name}\n")
    lines.append(f"dcdFile            output/{spec.name}.dcd\n")
    lines.append(f"dcdFreq            {spec.dcd_freq}\n")
    lines.append(f"xstFile            output/{spec.name}.xst\n")

    if spec.reinit or not spec.previous:
        lines.append(f"temperature        {spec.temp:g}\n")
    lines.append(f"langevinTemp       {spec.temp:g}\n")
    lines.append(f"langevinDamping    {spec.damping:g}\n")

    if spec.npt:
        lines.append("useGroupPressure   yes\n")
        lines.append("useFlexibleCell    no\n")
        lines.append("useConstantArea    no\n")
        lines.append("langevinPiston     on\n")
        lines.append("langevinPistonTarget  1.01325\n")
        lines.append("langevinPistonPeriod  1000.0\n")
        lines.append("langevinPistonDecay   500.0\n")
        lines.append(f"langevinPistonTemp {spec.temp:g}\n")
    else:
        lines.append("langevinPiston     off\n")

    if mgh_extrabonds or spec.extra_bonds_file:
        lines.append("extraBonds         on\n")
        if mgh_extrabonds:
            lines.append("extraBondsFile     mgh_extrabonds.txt\n")
    if spec.extra_bonds_file:
        lines.append(f"extraBondsFile     {spec.extra_bonds_file}\n")

    if spec.scale is not None and not spec.extra_bonds_file:
        lines.append("constraints        on\n")
        lines.append("consref            restraints_dna_heavy.pdb\n")
        lines.append("conskfile          restraints_dna_heavy.pdb\n")
        lines.append("conskcol           B\n")
        lines.append(f"constraintScaling  {spec.scale:g}\n")
    else:
        lines.append("constraints        off\n")

    if spec.previous:
        lines.append(f"binCoordinates     output/{spec.previous}.coor\n")
        if not spec.reinit:
            lines.append(f"binVelocities      output/{spec.previous}.vel\n")
        lines.append(f"extendedSystem     output/{spec.previous}.xsc\n")
    if spec.reinit:
        lines.append(f"reinitvels         {spec.temp:g}\n")

    if minimize_steps:
        lines.append(f"minimize           {minimize_steps}\n")
    if spec.steps:
        lines.append(f"run                {spec.steps}\n")
    return "".join(lines)


def _min_conf(
    min_name: str,
    name_stem: str,
    box: tuple[float, float, float],
    mgh_extrabonds: bool,
    minimize_steps: int,
    scale: float,
    *,
    enm_file: Optional[str] = None,
) -> str:
    # enm_file overrides the default {name_stem}_k{scale}.enm.extra — used by the
    # declash protocol to minimise against an ss-excluded network.
    enm = enm_file or f"{name_stem}_k{scale:g}.enm.extra"
    lines = [_common_header(name_stem, box, mgh_extrabonds, rigid_bonds="none")]
    lines.append(f"outputName         output/{min_name}\n")
    lines.append(f"dcdFile            output/{min_name}.dcd\n")
    lines.append("dcdFreq            0\n")
    lines.append(f"xstFile            output/{min_name}.xst\n")
    lines.append("temperature        0\n")
    lines.append("langevinTemp       0\n")
    lines.append("langevinDamping    5\n")
    lines.append("langevinPiston     off\n")
    lines.append("extraBonds         on\n")
    if mgh_extrabonds:
        lines.append("extraBondsFile     mgh_extrabonds.txt\n")
    lines.append(f"extraBondsFile     {enm}\n")
    lines.append("constraints        off\n")
    lines.append(f"minimize           {minimize_steps}\n")
    return "".join(lines)


# ── Restraints PDB ────────────────────────────────────────────────────────────

def write_restraints_pdb(pdb_path: Path, dst_path: Path) -> None:
    """Write restraints_dna_heavy.pdb with B=1.0 for DNA heavy atoms, B=0 for rest.

    NAMD reads the B-factor column (cols 61-66) as the per-atom constraint
    scaling factor via conskcol B.  DNA heavy atoms get B=1; hydrogens and
    solvent get B=0 (unconstrained).
    """
    lines = []
    for raw in pdb_path.read_text().splitlines(keepends=True):
        if raw.startswith("ATOM"):
            atom_name = raw[12:16].strip()
            value = 0.0 if atom_name.startswith("H") else 1.0
            raw = _set_bfactor(raw, value)
        elif raw.startswith("HETATM"):
            raw = _set_bfactor(raw, 0.0)
        lines.append(raw)
    dst_path.write_text("".join(lines))


def _set_bfactor(line: str, value: float) -> str:
    if not line.endswith("\n"):
        line = line + "\n"
    if len(line) < 67:
        line = line.rstrip("\n").ljust(66) + "\n"
    return f"{line[:60]}{value:6.2f}{line[66:].rstrip()}\n"


# ── Aksimentiev-style ENM extraBonds ─────────────────────────────────────────

BASE_RING_ATOMS = {"N1", "C2", "N3", "C4", "C5", "C6", "N7", "C8", "N9"}
DNA_RESNAMES = {"ADE", "DA", "THY", "DT", "GUA", "DG", "CYT", "DC"}


@dataclass
class _BaseResidue:
    key: tuple[str, str, str]
    atoms: list[tuple[int, str, np.ndarray]] = field(default_factory=list)

    @property
    def com(self) -> np.ndarray:
        return np.mean([pos for _idx, _name, pos in self.atoms], axis=0)


def _parse_base_ring_residues(pdb_path: Path) -> list[_BaseResidue]:
    """Group base-ring atoms into residues by file *contiguity*.

    A residue boundary is any change in the per-atom identity tuple
    ``(segid, chain, resid, resname)`` relative to the previous atom line, plus
    every ``TER`` record.  This is robust at large strand counts where the PDB
    chain column (1 char) and segid column (4 chars) both alias: ``_chain_char``
    cycles every 62 strands and resids are not globally unique, so two
    physically distant residues can share ``(chain, resid, resname)``.  The
    earlier global-dict keying merged every such collision into one residue —
    corrupting its centre-of-mass and base-ring atom list — for ~half the
    residues of a 224-strand design.  Contiguity grouping never merges
    non-adjacent residues, so each physical base keeps its own ENM node and
    atom ordinals (which index NAMD's atom order) stay exact.
    """
    residues: list[_BaseResidue] = []
    current: _BaseResidue | None = None
    prev_id: tuple[str, str, str, str] | None = None
    atom_ordinal = 0
    for line in pdb_path.read_text(errors="replace").splitlines():
        if line.startswith("TER"):
            prev_id = None  # force a residue boundary at every chain terminus
            current = None
            continue
        if not line.startswith("ATOM  "):
            continue
        atom_ordinal += 1
        atom = line[12:16].strip()
        resn = line[17:21].strip()
        chain = line[21:22].strip()
        resid = line[22:26].strip()
        segid = line[72:76].strip()
        atom_id = (segid, chain, resid, resn)
        if atom_id != prev_id:
            current = _BaseResidue(key=(chain, resid, resn))
            residues.append(current)
            prev_id = atom_id
        if "H" in atom or atom in {"P", "O1P", "O2P"} or "'" in atom:
            continue
        if atom not in BASE_RING_ATOMS or resn not in DNA_RESNAMES:
            continue
        try:
            pos = np.array([
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            ], dtype=float)
        except ValueError:
            continue
        assert current is not None  # set on first ATOM after every boundary
        current.atoms.append((atom_ordinal - 1, atom, pos))
    return [res for res in residues if res.atoms]


def write_aksimentiev_enm_files(
    pdb_path: Path,
    package_dir: Path,
    name_stem: str,
    *,
    base_k: float = 0.5,
    scales: tuple[float, ...] = (0.5, 0.1, 0.01),
    cut_ang: float = 8.0,
    progress=None,
    exclude_residues: "set[tuple[str, str]] | None" = None,
) -> dict[str, object]:
    """Write tutorial-style base-ring ENM extraBonds files for all k scales.

    Restraints connect base-ring atoms of DIFFERENT residues within ``cut_ang``.
    A single atom-level KD-tree query finds them in C — the previous
    residue-COM-prefilter + Python atom double-loop was both ~10× slower on large
    designs AND buggy: when the PDB's 1-char chain column collided across many
    strands (>62), two physical residues merged under one key, their centroid
    landed far away, and the 30 Å COM prefilter silently dropped their valid
    restraints.  Working on absolute atom positions avoids that entirely.

    ``exclude_residues`` is a set of (chain_id, resid) keys whose base-ring atoms
    are dropped from the network — used to leave single-stranded / inserted bases
    unrestrained so they can relax out of steric clash (declash protocol).
    """
    residues = _parse_base_ring_residues(pdb_path)
    if exclude_residues:
        residues = [r for r in residues if (r.key[0], r.key[1]) not in exclude_residues]
    if not residues:
        raise RuntimeError(f"No DNA base-ring atoms found for ENM generation in {pdb_path}")

    # Flatten every base-ring atom into parallel arrays (position, global 0-based
    # atom index, owning-residue index).  One atom-level KD-tree query then finds
    # ALL atom pairs within cut_ang in C — replacing the old O(residue_pairs × 81)
    # Python double-loop (142M numpy.dot calls for a 5.7k-base origami → ~5 min).
    pos_list: list[np.ndarray] = []
    gidx_list: list[int] = []
    rid_list: list[int] = []
    for ri, res in enumerate(residues):
        for idx, _name, pos in res.atoms:
            pos_list.append(pos)
            gidx_list.append(idx)
            rid_list.append(ri)
    positions = np.asarray(pos_list, dtype=float)
    gidx = np.asarray(gidx_list, dtype=np.int64)
    rid  = np.asarray(rid_list, dtype=np.int64)

    pairs = cKDTree(positions).query_pairs(cut_ang, output_type="ndarray")
    if len(pairs):
        # Keep only INTER-residue pairs (matches the old loop, which only paired
        # atoms across distinct residues — never within a base ring).
        pairs = pairs[rid[pairs[:, 0]] != rid[pairs[:, 1]]]

    if len(pairs):
        ga = gidx[pairs[:, 0]]
        gb = gidx[pairs[:, 1]]
        lo = np.minimum(ga, gb)               # canonical (a ≤ b) bond ordering
        hi = np.maximum(ga, gb)
        dists = np.linalg.norm(positions[pairs[:, 0]] - positions[pairs[:, 1]], axis=1)
    else:
        lo = hi = np.empty(0, dtype=np.int64)
        dists = np.empty(0, dtype=float)

    n_bonds = int(len(lo))
    if progress is not None:
        progress("enm", 0.5, "Writing elastic-network restraint files…")
    a_str = [f"{int(a):10d}{int(b):10d}" for a, b in zip(lo.tolist(), hi.tolist())]
    d_str = [f"{d:10.3g}\n" for d in dists.tolist()]

    files: dict[str, int] = {}
    for ki, k in enumerate(scales):
        if progress is not None:
            progress("enm", 0.5 + 0.5 * (ki / max(1, len(scales))),
                     "Writing elastic-network restraint files…")
        filename = f"{name_stem}_k{k:g}.enm.extra"
        path = package_dir / filename
        k_col = f"{f'{k:.6g}':>10s}"
        with path.open("w") as handle:
            # Chunked writes: build line blocks so we never hold a full ~470 MB
            # string nor pay a syscall per restraint.
            for start in range(0, n_bonds, 200_000):
                end = min(start + 200_000, n_bonds)
                handle.write("".join(
                    f"bond{a_str[i]}{k_col}{d_str[i]}" for i in range(start, end)
                ))
        files[filename] = n_bonds

    report = {
        "schema": "nadoc.aksimentiev_enm.v1",
        "source_pdb": str(pdb_path),
        "n_residues_with_base_atoms": len(residues),
        "n_base_atoms": int(len(positions)),
        "n_restraints_per_file": n_bonds,
        "base_k_kcal_mol_A2": base_k,
        "scales": list(scales),
        "cut_ang": cut_ang,
        "base_atoms": sorted(BASE_RING_ATOMS),
        "files": files,
    }
    (package_dir / f"{name_stem}_aksimentiev_enm.report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


# ── Declash protocol (single-stranded / inserted-base designs) ────────────────
#
# Designs with extra single-stranded bases at crossovers (e.g. "2xT" — two
# unpaired thymines per junction) are built with those bases in steric clash:
# the geometric layer threads their backbone through the cramped inter-helix gap,
# overlapping neighbouring-helix backbones.  Pinning them with the base-ring ENM
# stores that strain and breaks marginal duplex pairs once dynamics starts, so
# relaxation fails the health gate.
#
# The declash protocol: (1) leave the single-stranded bases OUT of the ENM so
# they can relax out of clash during minimisation; (2) rebuild the ENM ladder,
# heavy-atom restraints and the C1'/WC health reference from the declashed
# coordinates (so the structure is judged against its own relaxed geometry, not
# the clashed build); (3) run the ladder with the soft integrator (rigidBonds
# none + 1 fs) because residual single-stranded contacts crash rigid-bond RATTLE.

_DECLASH_BUILD_PDB_SUFFIX = "_build.pdb"  # backup of the original (clashed) build PDB
_C1_NO_PARTNER_ANG = 10.8  # C1'-C1' beyond this (no cross-seg partner) ⇒ unpaired


def identify_unpaired_residues(psf_path: Path, pdb_path: Path) -> set[tuple[str, str]]:
    """Return (chain_id, resid) of DNA residues with no Watson-Crick partner.

    A residue is "unpaired" (single-stranded) if its C1' atom has no
    cross-segment C1' neighbour within _C1_NO_PARTNER_ANG Å — i.e. it is not
    part of a duplex.  Chain id is taken as the last character of the PSF segid
    (DNAA→A … DNAI→I), matching the PDB chain column.
    """
    import MDAnalysis as mda  # noqa: PLC0415
    from scipy.spatial import cKDTree  # noqa: PLC0415

    u = mda.Universe(str(psf_path), str(pdb_path))
    c1 = u.select_atoms("name C1' C1X")
    if not len(c1):
        return set()
    pos = c1.positions
    seg = c1.segids
    resid = c1.resids
    tree = cKDTree(pos)
    ss: set[tuple[str, str]] = set()
    for k in range(len(pos)):
        nbrs = [
            m
            for m in tree.query_ball_point(pos[k], 11.0)
            if m != k and seg[m] != seg[k]
        ]
        mind = min((float(np.linalg.norm(pos[k] - pos[m])) for m in nbrs), default=99.0)
        if mind > _C1_NO_PARTNER_ANG:
            ss.add((str(seg[k])[-1], str(int(resid[k]))))
    return ss


def write_declashed_pdb(coor_path: Path, src_pdb: Path, dst_pdb: Path) -> int:
    """Write dst_pdb = src_pdb with coordinates replaced by a NAMD .coor file.

    Overwrites only the coordinate columns (31-54) of each ATOM/HETATM line,
    preserving record type, chain, resid and atom order so that downstream
    ENM atom-ordinals and health pair-building stay byte-consistent.  Returns
    the number of atoms rewritten.
    """
    import struct  # noqa: PLC0415

    raw = coor_path.read_bytes()
    n = struct.unpack("<i", raw[:4])[0]
    xyz = np.frombuffer(raw[4 : 4 + n * 24], dtype="<f8").reshape(n, 3)

    out: list[str] = []
    ai = 0
    for line in src_pdb.read_text().splitlines(keepends=True):
        if line.startswith(("ATOM", "HETATM")):
            x, y, z = xyz[ai]
            ai += 1
            line = f"{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}"
        out.append(line)
    if ai != n:
        raise RuntimeError(
            f"Atom count mismatch: PDB has {ai} ATOM/HETATM lines, .coor has {n}"
        )
    dst_pdb.write_text("".join(out))
    return ai


def rebuild_declashed_references(
    package_dir: Path,
    name_stem: str,
    min_coor: Path,
    *,
    scales: tuple[float, ...] = (0.5, 0.1, 0.01),
) -> dict[str, object]:
    """After the declash minimisation, re-anchor every reference to the relaxed coords.

    1. Back up the original build PDB to ``{name_stem}_build.pdb`` and overwrite
       ``{name_stem}.pdb`` with the declashed coordinates from ``min_coor``.
    2. Re-detect single-stranded residues and rebuild the ENM ladder
       ``{name_stem}_k*.enm.extra`` (ss-excluded) + ``restraints_dna_heavy.pdb``
       from the declashed geometry.

    Idempotent: if the build-PDB backup already exists the rebuild is skipped
    (so a resumed job does not re-overwrite).  Returns a small report dict.
    """
    pdb_path = package_dir / f"{name_stem}.pdb"
    psf_path = package_dir / f"{name_stem}.psf"
    build_pdb = package_dir / f"{name_stem}{_DECLASH_BUILD_PDB_SUFFIX}"

    if build_pdb.exists():
        return {"rebuilt": False, "reason": "already declashed (build backup present)"}

    pdb_path.replace(build_pdb)  # preserve original clashed build
    n_atoms = write_declashed_pdb(min_coor, build_pdb, pdb_path)

    ss = identify_unpaired_residues(psf_path, pdb_path)
    enm_report = write_aksimentiev_enm_files(
        pdb_path,
        package_dir,
        name_stem,
        scales=scales,
        exclude_residues=ss,
    )
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    return {
        "rebuilt": True,
        "n_atoms": n_atoms,
        "n_unpaired_excluded": len(ss),
        "enm_restraints_per_file": enm_report.get("n_restraints_per_file"),
    }


def design_has_extra_bases(design: "Design") -> bool:
    """True if the design inserts single-stranded bases at any junction.

    Covers both crossover ``extra_bases`` (e.g. "TT") and forced-ligation
    ``extra_bases`` — the same sources `_build_extra_base_atoms` builds from.
    Such designs are built with the inserted bases in steric clash, so the
    declash protocol is enabled automatically for them.
    """
    if any(
        getattr(xo, "extra_bases", None) for xo in getattr(design, "crossovers", [])
    ):
        return True
    return any(
        getattr(fl, "extra_bases", None)
        for fl in getattr(design, "forced_ligations", [])
    )


# ── Box extraction ────────────────────────────────────────────────────────────

def parse_box_from_namd_conf(conf_text: str) -> tuple[float, float, float]:
    """Extract cellBasisVector diagonal as (bx, by, bz) in Å.

    Expects orthogonal box where off-diagonal elements are zero.
    """
    bx = by = bz = 0.0
    for line in conf_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("cellBasisVector1"):
            parts = stripped.split()
            if len(parts) >= 2:
                bx = float(parts[1])
        elif stripped.startswith("cellBasisVector2"):
            parts = stripped.split()
            if len(parts) >= 3:
                by = float(parts[2])
        elif stripped.startswith("cellBasisVector3"):
            parts = stripped.split()
            if len(parts) >= 4:
                bz = float(parts[3])
    if bx == 0.0 or by == 0.0 or bz == 0.0:
        raise ValueError(f"Could not parse box from NAMD conf (got {bx}, {by}, {bz})")
    return (bx, by, bz)


# ── mgh_slow_release segment sequence ────────────────────────────────────────

def _scale_label(scale: Optional[float]) -> str:
    if scale is None:
        return "unrestrained"
    s = f"{scale:g}"
    return s.replace(".", "p")


def _display_dcd_freq(steps: int) -> int:
    """Write sparse frames for multi-ns relaxation without filling the disk."""
    return 9_600


def _round_up_to_cycle(steps: int, cycle: int = AKSIMENTIEV_STEPS_PER_CYCLE) -> int:
    """NAMD minimize/run steps must be divisible by stepspercycle."""
    if steps <= 0:
        return steps
    remainder = steps % cycle
    return steps if remainder == 0 else steps + (cycle - remainder)


def mgh_slow_release_segments(
    name_stem: str,
    *,
    soft: bool = False,
) -> tuple[str, list[SegmentSpec]]:
    """Return (min_name, segments) for the mgh_slow_release protocol.

    The minimization name is returned separately because it needs a distinct
    conf/output name that the first warmup segment continues from.

    Default stages mirror the Aksimentiev tutorial shape:
      minimization: ENM k=0.5 + MGHH, 4800 steps by default
      NPT stages: 300 K, ENM k=0.5 -> 0.1 -> 0.01, 4.8 ns each
      handoff: 300 K, k=0, 4.8 ns

    ``soft=True`` (declash protocol) runs every stage with the soft integrator
    (rigidBonds none + 1 fs) so residual single-stranded contacts do not crash
    rigid-bond RATTLE.
    """
    min_name = f"{name_stem}_00_min_enm_k0p5"

    # A 2 fs timestep makes 2,400,000 steps = 4.8 ns per stage.
    npt_ladder = [
        (0.5,  2_400_000, "300K_NPT_ENM_k0p5"),
        (0.1,  2_400_000, "300K_NPT_ENM_k0p1"),
        (0.01, 2_400_000, "300K_NPT_ENM_k0p01"),
        (None, 2_400_000, "300K_NPT_MGHH_only"),
    ]

    # Percentages and their fraction of total steps
    pcts = [(10.0, 0.10), (50.0, 0.40), (100.0, 0.50)]  # steps at 10%, then +40%, then +50%

    segments: list[SegmentSpec] = []
    stage_idx = 1
    previous = min_name

    for scale, total_steps, label in npt_ladder:
        stage_str = (
            "300K NPT k=0"
            if scale is None
            else f"300K NPT ENM k={scale}"
        )
        for i, (pct, frac) in enumerate(pcts):
            seg_steps = _round_up_to_cycle(max(100, int(total_steps * frac)))
            seg_name = f"{name_stem}_{stage_idx:02d}_{label}_p{int(pct)}"
            segments.append(
                SegmentSpec(
                    name=seg_name,
                    stage=stage_str,
                    percent=pct,
                    steps=seg_steps,
                    temp=300.0,
                    damping=5.0,
                    scale=scale,
                    npt=True,
                    previous=previous,
                    reinit=False,
                    dcd_freq=_display_dcd_freq(seg_steps),
                    min_wc_ref_relative=0.75 if scale is None else 0.80,
                    extra_bonds_file=None
                    if scale is None
                    else f"{name_stem}_k{scale:g}.enm.extra",
                    soft=soft,
                )
            )
            previous = seg_name
        stage_idx += 1

    return min_name, segments


# ── Full job preparation ──────────────────────────────────────────────────────

def prepare_mgh_slow_release(
    design: Design,
    job_dir: Path,
    *,
    protocol: str = LEGACY_PROTOCOL,
    ion_conc_mM: float = 0.0,
    mg_conc_mM: float = 12.5,
    salt_mode: str = "custom",
    padding_nm: float = 1.2,
    minimize_steps: int = 4_800,
    min_scale: float = 0.5,
    require_full_topology: bool = False,
    seed: int = 42,
    atomistic_model=None,
    progress=None,
    declash: bool = False,
) -> tuple[str, str, list[SegmentSpec]]:
    """Build the solvated package and all stage configs in job_dir.

    ``atomistic_model`` (optional) is a pre-built heavy-atom model supplying the
    DNA starting coordinates — pass an oxDNA-relaxed model (Phase-2 NAMD seed)
    to start NAMD from relaxed positions instead of ideal B-DNA.

    Calls build_namd_solvated_package (GROMACS solvation step, ~60-120 s).
    Extracts the ZIP to job_dir/package/, then writes:
      - restraints_dna_heavy.pdb
      - {min_name}.conf
      - one .conf per segment
      - manifest.json

    Declash (auto-enabled when the design inserts extra bases at crossovers, or
    forced via ``declash=True``): the minimisation runs against an ss-excluded
    ENM so the inserted bases relax out of clash, the runner re-anchors all
    references to the declashed coordinates after minimisation (see
    ``rebuild_declashed_references``), and the ladder runs with the soft
    integrator.

    Returns (package_subdir, name_stem) relative to job_dir.
    """
    from backend.core.namd_solvate import build_namd_solvated_package  # noqa: PLC0415

    minimize_steps = _round_up_to_cycle(minimize_steps)

    zip_bytes = build_namd_solvated_package(
        design,
        padding_nm      = padding_nm,
        ion_conc_mM     = ion_conc_mM,
        mg_conc_mM      = mg_conc_mM,
        mg_hexahydrate  = True,
        require_full_topology = require_full_topology,
        seed            = seed,
        atomistic_model = atomistic_model,
        progress        = progress,
    )

    # Extract ZIP — inner folder is "{name}_namd_solvated/"
    pkg_root = job_dir / "package"
    pkg_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(pkg_root)

    # Discover the extracted subfolder
    inner_dirs = [p for p in pkg_root.iterdir() if p.is_dir()]
    if not inner_dirs:
        raise RuntimeError("ZIP extraction produced no subdirectory.")
    package_dir = inner_dirs[0]       # e.g. package/B_tube_namd_solvated/

    # Derive file stem from {stem}.psf presence
    psf_files = list(package_dir.glob("*.psf"))
    if not psf_files:
        raise RuntimeError(f"No .psf file found in {package_dir}")
    name_stem = psf_files[0].stem     # e.g. "B_tube"

    # Parse box from the generated namd.conf
    namd_conf_path = package_dir / "namd.conf"
    box = parse_box_from_namd_conf(namd_conf_path.read_text())

    mgh_extrabonds = (package_dir / "mgh_extrabonds.txt").exists()

    # Write restraint references and Aksimentiev-style ENM files.
    if progress is not None:
        progress("enm", None, "Building elastic-network restraints…")
    pdb_path = package_dir / f"{name_stem}.pdb"
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    enm_report = write_aksimentiev_enm_files(pdb_path, package_dir, name_stem, progress=progress)

    # Declash: minimise against an ss-excluded ENM so inserted single-stranded
    # bases relax out of clash.  References are rebuilt from the declashed coords
    # by the runner after minimisation (rebuild_declashed_references).  Enabled
    # automatically whenever the design inserts extra bases at crossovers (they
    # are built clashed); the explicit flag can force it on otherwise.
    declash = declash or design_has_extra_bases(design)
    declash_enm_file: Optional[str] = None
    n_unpaired = 0
    if declash:
        ss = identify_unpaired_residues(package_dir / f"{name_stem}.psf", pdb_path)
        n_unpaired = len(ss)
        write_aksimentiev_enm_files(
            pdb_path,
            package_dir,
            f"{name_stem}_declash",
            scales=(min_scale,),
            exclude_residues=ss,
        )
        declash_enm_file = f"{name_stem}_declash_k{min_scale:g}.enm.extra"

    # Create output dir
    if progress is not None:
        progress("finalize", None, "Writing simulation configs…")
    (package_dir / "output").mkdir(exist_ok=True)

    # Build segment list
    min_name, segments = mgh_slow_release_segments(name_stem, soft=declash)

    # Write minimization conf
    (package_dir / f"{min_name}.conf").write_text(
        _min_conf(
            min_name,
            name_stem,
            box,
            mgh_extrabonds,
            minimize_steps,
            min_scale,
            enm_file=declash_enm_file,
        )
    )

    # Write segment confs
    for spec in segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(spec, name_stem, box, mgh_extrabonds)
        )

    charge_audit = {}
    charge_audit_path = package_dir / "charge_audit.json"
    if charge_audit_path.exists():
        charge_audit = json.loads(charge_audit_path.read_text())

    segment_dicts = [
        {
            "name":     s.name,
            "stage":    s.stage,
            "percent":  s.percent,
            "steps":    s.steps,
            "temp":     s.temp,
            "damping":  s.damping,
            "scale":    s.scale,
            "npt":      s.npt,
            "previous": s.previous,
            "reinit":   s.reinit,
            "dcd_freq": s.dcd_freq,
            "min_c1_paired": s.min_c1_paired,
            "min_wc_ref_relative": s.min_wc_ref_relative,
            "extra_bonds_file": s.extra_bonds_file,
            "soft": s.soft,
        }
        for s in segments
    ]

    # Write manifest for human inspection and NADOC trajectory reload.
    manifest = {
        "nadoc_md_run_manifest_version": 1,
        "protocol":    protocol,
        "package_dir": str(package_dir.resolve()),
        "name_stem":   name_stem,
        "files": {
            "topology": f"{name_stem}.psf",
            "coordinates": f"{name_stem}.pdb",
            "base_config": "namd.conf",
            "forcefield_dir": "forcefield",
            "output_dir": "output",
            "charge_audit": "charge_audit.json",
            "restraints": "restraints_dna_heavy.pdb",
        },
        "box_ang":     list(box),
        "mgh_extrabonds": mgh_extrabonds,
        "declash": declash,
        "declash_min_coor": f"output/{min_name}.coor" if declash else None,
        "n_unpaired_excluded": n_unpaired if declash else 0,
        "salt": {
            "mode": salt_mode,
            "nacl_mM": ion_conc_mM,
            "mgcl2_mM": mg_conc_mM,
            "note": "screening mode uses neutralizing Na+ plus 12.5 mM MgCl2/MGH and no extra bulk NaCl",
        },
        "equilibrium_aware": {
            "requires_full_dna_topology": require_full_topology,
            "requires_dna_hydrogens": require_full_topology,
            "requires_neutral_final_psf": require_full_topology,
            "current_package_passed": bool(
                charge_audit.get("production_ready")
                if charge_audit else not require_full_topology
            ),
        },
        "charge_audit": charge_audit,
        "minimization": {
            "name":  min_name,
            "steps": minimize_steps,
            "scale": min_scale,
            "restraint": "aksimentiev_base_ring_enm",
            "extra_bonds_file": f"{name_stem}_k{min_scale:g}.enm.extra",
        },
        "aksimentiev_enm": enm_report,
        "relax_protocol_settings": {
            "stage_length_steps": 2_400_000,
            "stage_length_ns_at_2fs": 4.8,
            "timestep_fs": 2.0,
            "temperature_k": 300.0,
            "langevin_damping_ps_inv": 5.0,
            "pme_grid_spacing_ang": 1.5,
            "switch_cut_pairlist_ang": [8.0, 10.0, 12.0],
            "piston_period_decay_fs": [1000.0, 500.0],
            "output_frequency_steps": 9600,
        },
        "segments": segment_dicts,
        "health_checks": "After every segment: 10%, 50%, and 100% of each stage.",
    }
    manifest_text = json.dumps(manifest, indent=2)
    (package_dir / "manifest.json").write_text(manifest_text)
    (package_dir / "nadoc_md_run.json").write_text(manifest_text)

    # Relative subdir for MdJob
    package_subdir = str(package_dir.relative_to(job_dir))
    return package_subdir, name_stem, segments


def prepare_equilibrium_aware_namd(
    design: Design,
    job_dir: Path,
    **kwargs,
) -> tuple[str, str, list[SegmentSpec]]:
    """Prepare the strict one-button production workflow.

    This wraps the same Mg slow-release ladder, but requires a complete DNA
    topology with hydrogens and a neutral final PSF before any job can queue.
    """
    return prepare_mgh_slow_release(
        design,
        job_dir,
        protocol=EQUILIBRIUM_AWARE_PROTOCOL,
        require_full_topology=True,
        **kwargs,
    )


def segments_from_manifest(manifest_path: Path) -> tuple[str, list[SegmentSpec]]:
    """Reconstruct segment list from an existing manifest.json (for resume)."""
    import json  # noqa: PLC0415

    data = json.loads(manifest_path.read_text())
    min_name = data["minimization"]["name"]
    segments = [
        SegmentSpec(
            name=s["name"],
            stage=s["stage"],
            percent=s["percent"],
            steps=s["steps"],
            temp=s["temp"],
            damping=s["damping"],
            scale=s["scale"],
            npt=s["npt"],
            previous=s["previous"],
            reinit=s.get("reinit", False),
            dcd_freq=s.get("dcd_freq", 20000),
            min_c1_paired=s.get("min_c1_paired", 0.90),
            min_wc_ref_relative=s.get("min_wc_ref_relative", 0.85),
            extra_bonds_file=s.get("extra_bonds_file"),
            soft=s.get("soft", False),
        )
        for s in data["segments"]
    ]
    return min_name, segments
