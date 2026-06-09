"""
build_single_helix.py — Build a single B-DNA duplex with axial PBC.

Extracts a 7-bp helix segment from B_tube_periodic_1x, extends it to 21 bp
via two additional helix-transform copies, solvates, and writes a NAMD package.

System: one straight B-DNA duplex whose 5'/3' ends are connected across the
z=70.14 Å periodic boundary via two wrap bonds (one per strand).  This is the
minimal control for the B_tube benchmark: if it shows <90% C1'–C1' pairing,
the wrap-bond geometry or NAMD conf is broken, not the multi-helix complexity.

Usage
-----
    python scripts/build_single_helix.py [--dry-run] [--threads T]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
import shutil
import tempfile
import textwrap
from pathlib import Path

import MDAnalysis as mda
import numpy as np

# Allow importing NADOC backend from the project root
_SCRIPT  = Path(__file__).resolve().parent
_EXP     = _SCRIPT.parent
sys.path.insert(0, str(_EXP.parent.parent))  # /home/jojo/Work/NADOC

_SRC_DIR = _EXP / "results" / "periodic_cell_run"
_SRC_PSF = _SRC_DIR / "B_tube_periodic_1x.psf"
_SRC_PDB = _SRC_DIR / "B_tube_periodic_1x.pdb"
_FF      = _SRC_DIR / "forcefield"
_OUT     = (_EXP / "results" / "single_helix_control").resolve()

Z_PERIOD    = 70.14          # Å
N_BP        = 21
N_TMPL      = 7              # bp in extracted template
RISE_PER_BP = Z_PERIOD / N_BP              # 3.3400 Å
TWIST_PER_BP = 2 * np.pi * 2 / N_BP       # 34.286°/bp in radians
_WC = {"DA": "DT", "DT": "DA", "DC": "DG", "DG": "DC"}


@dataclass
class _BridgeAtom:
    """Minimal Atom-compatible object for backend bridge minimizers.

    Coordinates are stored in nm because backend atomistic minimizers use nm.
    """
    x: float
    y: float
    z: float


# ─── geometry helpers ────────────────────────────────────────────────────────

def _rot_z(theta: float) -> np.ndarray:
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])


def _fit_circle(points: np.ndarray) -> np.ndarray:
    """Algebraic least-squares circle centre from 2-D points."""
    xy = points[:, :2]
    A = np.column_stack([2 * xy, np.ones(len(xy))])
    b = (xy ** 2).sum(axis=1)
    params, *_ = np.linalg.lstsq(A, b, rcond=None)
    return params[:2]


# ─── template extraction ─────────────────────────────────────────────────────

def _res_atoms(u: mda.Universe, segid: str, resid: int) -> dict:
    ag = u.select_atoms(f"segid {segid} and resid {resid}")
    return {
        "resname": ag.residues[0].resname,
        "atoms":   [{"name": a.name, "xyz": a.position.copy()} for a in ag.atoms],
    }


def extract_template(u: mda.Universe) -> tuple[list, list]:
    """Return (s1, s2) each a list of 7 residue dicts, ordered by ascending z."""
    s1 = [_res_atoms(u, "DNAB", r) for r in range(1, 8)]           # +Z strand
    s2 = [_res_atoms(u, "DNAA", r) for r in [21, 20, 19, 18, 17, 16, 15]]  # paired +Z order
    return s1, s2


def helix_axis(s1: list, s2: list) -> tuple[np.ndarray, float]:
    """Return (center_xy, z_ref) via circle fit to all 14 C1' positions."""
    all_c1p = [
        next(a["xyz"] for a in r["atoms"] if a["name"] == "C1'")
        for r in s1 + s2
    ]
    center_xy = _fit_circle(np.array(all_c1p))
    z_ref = min(a["xyz"][2] for r in s1 for a in r["atoms"] if a["name"] == "C1'")
    return center_xy, z_ref


# ─── 21-bp duplex builder ────────────────────────────────────────────────────

def build_duplex(s1: list, s2: list,
                 center_xy: np.ndarray, z_ref: float
                 ) -> tuple[list, list]:
    """Return (out_s1, out_s2): 21 residue dicts each, atoms in helix frame.

    Strand 1 (STRA): residue 1 = bp0 at z=0 (5' end), residue 21 = bp20.
    Strand 2 (STRB): residue 1 = bp20 at z=66.80 Å (5' end of antiparallel),
                     residue 21 = bp0 at z=0.  Sequence complement of STRA.
    """
    def _centre(res: dict) -> dict:
        out_atoms = []
        for a in res["atoms"]:
            xyz = a["xyz"].copy()
            xyz[:2] -= center_xy
            xyz[2]  -= z_ref
            out_atoms.append({"name": a["name"], "xyz": xyz})
        return {"resname": res["resname"], "atoms": out_atoms}

    def _apply_copy(res: dict, k: int) -> dict:
        R = _rot_z(k * N_TMPL * TWIST_PER_BP)
        dz = k * N_TMPL * RISE_PER_BP
        out_atoms = []
        for a in res["atoms"]:
            xyz = a["xyz"].copy()
            xyz[:2] = R[:2, :2] @ xyz[:2]
            xyz[2] += dz
            out_atoms.append({"name": a["name"], "xyz": xyz})
        return {"resname": res["resname"], "atoms": out_atoms}

    s1c = [_centre(r) for r in s1]
    s2c = [_centre(r) for r in s2]

    out_s1, out_s2 = [], []
    for k in range(N_BP // N_TMPL):  # 3 copies
        for r in s1c:
            out_s1.append(_apply_copy(r, k))
        for r in s2c:
            out_s2.append(_apply_copy(r, k))

    # Strand 2 is currently ordered bp0..bp20 in ascending z.
    # Reverse so that residue 1 of STRB is at the 5' end (high z, antiparallel).
    out_s2 = list(reversed(out_s2))
    return out_s1, out_s2


def _res_atom_map(residue: dict) -> dict[str, dict]:
    return {a["name"]: a for a in residue["atoms"]}


def _bridge_distance(src: dict, dst: dict, *, z_shift_angstrom: float = 0.0) -> float:
    src_atoms = _res_atom_map(src)
    dst_atoms = _res_atom_map(dst)
    o3 = src_atoms["O3'"]["xyz"]
    p = dst_atoms["P"]["xyz"].copy()
    p[2] += z_shift_angstrom
    return float(np.linalg.norm(o3 - p))


def _minimize_residue_bridge(src: dict, dst: dict, *, z_shift_angstrom: float = 0.0) -> None:
    """Minimize O3'(src), P/O5'/OP1/OP2(dst) bridge geometry in place.

    The existing backend minimizer operates on Atom objects in nm and indexes by
    serial. This adapter keeps the single-helix control script lightweight while
    reusing the canonical C3'-O3'-P-O5'-C5' objective from NADOC.
    """
    from backend.core.atomistic_minimisers import _minimize_backbone_bridge

    src_atoms = _res_atom_map(src)
    dst_atoms = _res_atom_map(dst)
    required_src = ("C3'", "O3'")
    required_dst = ("P", "O5'", "C5'")
    if not all(k in src_atoms for k in required_src):
        return
    if not all(k in dst_atoms for k in required_dst):
        return

    atoms: list[_BridgeAtom] = []
    src_s: dict[str, int] = {}
    dst_s: dict[str, int] = {}

    def _add(atom: dict, mapping: dict[str, int], name: str, shift_z: float = 0.0) -> None:
        xyz_nm = atom["xyz"].copy() / 10.0
        xyz_nm[2] += shift_z / 10.0
        mapping[name] = len(atoms)
        atoms.append(_BridgeAtom(float(xyz_nm[0]), float(xyz_nm[1]), float(xyz_nm[2])))

    for name in ("C3'", "O3'"):
        _add(src_atoms[name], src_s, name)
    for name in ("P", "O5'", "C5'", "OP1", "OP2"):
        if name in dst_atoms:
            _add(dst_atoms[name], dst_s, name, z_shift_angstrom)

    _minimize_backbone_bridge(atoms, src_s, dst_s)

    for name, idx in src_s.items():
        if name == "C3'":
            continue
        src_atoms[name]["xyz"] = np.array([atoms[idx].x, atoms[idx].y, atoms[idx].z]) * 10.0
    for name, idx in dst_s.items():
        if name == "C5'":
            continue
        xyz = np.array([atoms[idx].x, atoms[idx].y, atoms[idx].z]) * 10.0
        xyz[2] -= z_shift_angstrom
        dst_atoms[name]["xyz"] = xyz


def minimize_all_bridges(out_s1: list, out_s2: list) -> None:
    """Apply canonical bridge minimization to adjacent and PBC strand links."""
    print("Minimizing phosphodiester bridges...")
    before = []
    after = []
    for strand, wrap_shift in ((out_s1, Z_PERIOD), (out_s2, -Z_PERIOD)):
        for i in range(N_BP - 1):
            before.append(_bridge_distance(strand[i], strand[i + 1]))
            _minimize_residue_bridge(strand[i], strand[i + 1])
            after.append(_bridge_distance(strand[i], strand[i + 1]))
        before.append(_bridge_distance(strand[-1], strand[0], z_shift_angstrom=wrap_shift))
        _minimize_residue_bridge(strand[-1], strand[0], z_shift_angstrom=wrap_shift)
        after.append(_bridge_distance(strand[-1], strand[0], z_shift_angstrom=wrap_shift))
    print(
        f"  O3'->P distances: before mean={np.mean(before):.3f} Å "
        f"max={np.max(before):.3f} Å; after mean={np.mean(after):.3f} Å "
        f"max={np.max(after):.3f} Å"
    )


def check_geometry(out_s1: list, out_s2: list) -> None:
    print("Geometry check:")
    # C1'–C1' for first/last base pairs
    for i, (r1, r2) in enumerate(zip(out_s1, reversed(list(out_s2)))):
        if i > 2 and i < 18:
            continue
        c1 = next(a["xyz"] for a in r1["atoms"] if a["name"] == "C1'")
        c2 = next(a["xyz"] for a in r2["atoms"] if a["name"] == "C1'")
        print(f"  bp{i:2d}: C1'–C1' = {np.linalg.norm(c1-c2):.3f} Å")

    # O3'→P at copy junctions and wrap bond
    for label, (seg, end_res, start_res_of_next) in [
        ("bp6→bp7",   (out_s1,  6,  7)),
        ("bp13→bp14", (out_s1, 13, 14)),
    ]:
        o3 = next(a["xyz"] for a in seg[end_res]["atoms"] if a["name"] == "O3'")
        p  = next(a["xyz"] for a in seg[start_res_of_next]["atoms"] if a["name"] == "P")
        print(f"  s1 O3'({label}): {np.linalg.norm(o3-p):.3f} Å (target 1.60 Å)")

    o3_wrap = next(a["xyz"] for a in out_s1[-1]["atoms"] if a["name"] == "O3'")
    p_wrap  = next(a["xyz"] for a in out_s1[0]["atoms"]  if a["name"] == "P")
    p_pbc   = p_wrap.copy(); p_pbc[2] += Z_PERIOD
    print(f"  s1 wrap O3'(bp20)→P(bp0) [PBC]: {np.linalg.norm(o3_wrap - p_pbc):.3f} Å")


# ─── PDB / PSF I/O ───────────────────────────────────────────────────────────

def write_strand_pdb(residues: list, segid: str, dest: Path) -> None:
    lines = []
    serial = 1
    for resid, res in enumerate(residues, 1):
        for atom in res["atoms"]:
            x, y, z = atom["xyz"]
            name = f"{atom['name']:<4s}"
            ch = segid[3] if len(segid) > 3 else segid[0]
            lines.append(
                f"ATOM  {serial:5d} {name} {res['resname']:<3s} {ch}"
                f"{resid:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00      {segid:<4s}\n"
            )
            serial += 1
    lines.append("END\n")
    dest.write_text("".join(lines))


def build_psf_from_template(out_s1: list, out_s2: list,
                            strand1_pdb: Path, strand2_pdb: Path,
                            dry_psf: Path, dry_pdb: Path) -> None:
    """Build a PSF stub for the 21-bp duplex from B_tube atom topology via parmed.

    Uses the B_tube PSF as a topology database: extracts atom types/charges/masses
    and intra-residue bonds for each DNA residue type (DA/DT/DG/DC), then writes
    a minimal PSF (NATOM + NBOND) whose atom order matches the strand PDBs.
    Wrap bonds are added later by add_wrap_bonds.
    Also writes the combined dry PDB (both strands).
    """
    import parmed
    from backend.core.namd_solvate import _psf_atom_line

    btube = parmed.load_file(str(_SRC_PSF))

    # Extract per-residue topology for each unique DNA residue type
    res_topo: dict[str, dict] = {}
    for res in btube.residues:
        if res.name in res_topo or res.name not in ("DA", "DT", "DG", "DC"):
            continue
        atoms_info = [
            {"name": a.name, "type": a.type, "charge": a.charge, "mass": a.mass}
            for a in res.atoms
        ]
        res_atom_ids = {id(a) for a in res.atoms}
        seen: set[frozenset] = set()
        intra: list[tuple[str, str]] = []
        for atom in res.atoms:
            for bond in atom.bonds:
                other = bond.atom2 if bond.atom1 is atom else bond.atom1
                if id(other) in res_atom_ids:
                    key: frozenset = frozenset([atom.name, other.name])
                    if key not in seen:
                        seen.add(key)
                        intra.append((atom.name, other.name))
        res_topo[res.name] = {"atoms": atoms_info, "intra_bonds": intra}
        if len(res_topo) == 4:
            break

    print(f"  Residue types extracted: {sorted(res_topo)}")

    # Build NATOM section; track (segid, resid, name) → serial
    natom_lines: list[str] = []
    atom_serials: dict[tuple[str, int, str], int] = {}
    serial = 1
    strands = [("STRA", out_s1), ("STRB", out_s2)]
    for segid, residues in strands:
        for resid_0, res_dict in enumerate(residues):
            resid = resid_0 + 1
            resname = res_dict["resname"]
            topo = res_topo[resname]
            for ai in topo["atoms"]:
                natom_lines.append(
                    _psf_atom_line(serial, segid, resid, resname,
                                   ai["name"], ai["type"], ai["charge"], ai["mass"])
                )
                atom_serials[(segid, resid, ai["name"])] = serial
                serial += 1

    n_atoms = serial - 1

    # Build NBOND: intra-residue bonds + inter-residue O3'→P within each strand
    bond_pairs: list[tuple[int, int]] = []
    for segid, residues in strands:
        for resid_0, res_dict in enumerate(residues):
            resid = resid_0 + 1
            resname = res_dict["resname"]
            for name1, name2 in res_topo[resname]["intra_bonds"]:
                bond_pairs.append((atom_serials[(segid, resid, name1)],
                                   atom_serials[(segid, resid, name2)]))
            if resid < N_BP:
                bond_pairs.append((atom_serials[(segid, resid, "O3'")],
                                   atom_serials[(segid, resid + 1, "P")]))

    n_bonds = len(bond_pairs)
    flat = [n for pair in bond_pairs for n in pair]
    bond_lines = ["".join(f"{flat[i+j]:8d}" for j in range(min(8, len(flat) - i)))
                  for i in range(0, len(flat), 8)]

    psf_text = "\n".join([
        "PSF EXT", "",
        "       1 !NTITLE",
        " REMARKS single B-DNA 21-bp periodic control — build_single_helix.py",
        "",
        f"{n_atoms:>10d} !NATOM",
        *natom_lines, "",
        f"{n_bonds:>10d} !NBOND: bonds",
        *bond_lines, "",
    ]) + "\n"
    dry_psf.write_text(psf_text)
    print(f"  PSF stub written: {n_atoms} atoms, {n_bonds} bonds")

    # Write combined dry PDB: strand1 then strand2 (strip END from strand1)
    s1_text = strand1_pdb.read_text().rstrip()
    if s1_text.endswith("END"):
        s1_text = s1_text[:-3].rstrip()
    dry_pdb.write_text(s1_text + "\n" + strand2_pdb.read_text())
    print(f"  Dry PDB written: {dry_pdb.name}")


def add_wrap_bonds(psf_path: Path) -> None:
    """Add O3'(res21)–P(res1) wrap bonds for STRA and STRB, rebuild angles/dihedrals."""
    from backend.core.namd_helpers import _complete_psf_from_stub

    psf = psf_path.read_text()

    def _serial(seg: str, resid: int, name: str) -> int:
        for line in psf.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1] == seg and parts[2] == str(resid) and parts[4] == name:
                return int(parts[0])
        raise ValueError(f"Atom not found: {seg}:{resid}:{name}")

    o3_a = _serial("STRA", 21, "O3'")
    p_a  = _serial("STRA",  1, "P")
    o3_b = _serial("STRB", 21, "O3'")
    p_b  = _serial("STRB",  1, "P")
    print(f"  Wrap bonds: STRA O3'({o3_a})–P({p_a})  |  STRB O3'({o3_b})–P({p_b})")

    # Build a stub PSF: keep !NATOM and !NBOND sections (+ wrap bonds), drop the rest.
    # _complete_psf_from_stub will regenerate angles/dihedrals from the full bond graph.
    lines = psf.splitlines()

    # Extract atom section
    atom_lines, bond_lines_raw, header_lines = [], [], []
    collecting = "header"
    for line in lines:
        stripped = line.strip()
        if "!NATOM" in line:
            header_lines.append(line)
            collecting = "atom"
            continue
        if "!NBOND" in line:
            collecting = "bond"
            continue
        if collecting == "header":
            header_lines.append(line)
        elif collecting == "atom":
            if stripped and not stripped.startswith("!"):
                atom_lines.append(line)
            else:
                collecting = "between"
        elif collecting == "bond":
            if stripped and not stripped.startswith("!"):
                bond_lines_raw.append(stripped)
            elif stripped.startswith("!"):
                break  # hit next section (angles)

    # Re-parse n_atoms from header
    n_atoms = sum(1 for l in atom_lines if l.strip())

    # Assemble bond numbers list and append wrap bonds
    bond_nums = []
    for bl in bond_lines_raw:
        bond_nums.extend(bl.split())
    bond_nums += [str(o3_a), str(p_a), str(o3_b), str(p_b)]
    n_bonds = len(bond_nums) // 2

    # Build bond lines (8 per line, 8 chars each)
    bond_out = []
    for i in range(0, len(bond_nums), 8):
        chunk = bond_nums[i:i+8]
        bond_out.append("".join(f"{int(x):8d}" for x in chunk))

    # Build stub PSF text (preserve !NTITLE so NAMD accepts the file)
    stub_lines = (
        ["PSF EXT"]
        + [""]
        + ["       1 !NTITLE"]
        + [" REMARKS single B-DNA 21-bp periodic control — build_single_helix.py"]
        + [""]
        + [f"{n_atoms:>8d} !NATOM"]
        + atom_lines
        + [""]
        + [f"{n_bonds:>8d} !NBOND: bonds"]
        + bond_out
        + [""]
    )
    stub = "\n".join(stub_lines) + "\n"

    complete = _complete_psf_from_stub(stub)
    psf_path.write_text(complete)
    print("  Wrap bonds added; angles/dihedrals rebuilt.")


def solvate_and_ionize(dry_psf: Path, dry_pdb: Path) -> tuple[Path, Path, tuple]:
    """Solvate the dry duplex and write the final NAMD PSF/PDB."""
    from backend.core.namd_solvate import (
        _gmx_solvate_periodic,
        _place_ions,
        _ion_counts,
        _count_dna_charge,
        _extend_psf,
        _build_solvated_pdb,
        _find_last_atom_serial,
    )

    pdb_text = dry_pdb.read_text()
    psf_text = dry_psf.read_text()

    with tempfile.TemporaryDirectory(prefix="sh_solv_") as td:
        tmpdir = Path(td)
        print("  Running gmx solvate...")
        waters, box_nm = _gmx_solvate_periodic(
            pdb_text, padding_nm=1.5, periodic_z_nm=Z_PERIOD / 10, tmpdir=tmpdir
        )

    print(f"  {len(waters)} TIP3P water molecules, "
          f"box {box_nm[0]*10:.1f} × {box_nm[1]*10:.1f} × {box_nm[2]*10:.1f} Å")

    dna_charge = _count_dna_charge(pdb_text)
    n_na, n_cl = _ion_counts(len(waters), dna_charge, 150.0, box_nm)
    waters, na_pos, cl_pos = _place_ions(waters, n_na, n_cl)
    print(f"  Ions: {n_na} Na+, {n_cl} Cl−")

    dna_n_atoms = _find_last_atom_serial(psf_text)
    solvated_psf_text = _extend_psf(psf_text, waters, na_pos, cl_pos)
    solvated_pdb_text = _build_solvated_pdb(pdb_text, waters, na_pos, cl_pos, box_nm, dna_n_atoms)

    out_psf = _OUT / "single_helix.psf"
    out_pdb = _OUT / "single_helix.pdb"
    out_psf.write_text(solvated_psf_text)
    out_pdb.write_text(solvated_pdb_text)

    return out_psf, out_pdb, box_nm


def write_restraints(pdb_path: Path) -> Path:
    """Write restraints PDB: B=1.0 for DNA heavy atoms, B=0.0 for water/ions."""
    lines = []
    for line in pdb_path.read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            seg  = line[72:76].strip()
            name = line[12:16].strip()
            bfac = "1.00" if seg in ("STRA", "STRB") and not name.startswith("H") else "0.00"
            line = line[:60] + f"{float(bfac):6.2f}" + line[66:]
        lines.append(line)
    dest = _OUT / "restraints.pdb"
    dest.write_text("\n".join(lines) + "\n")
    return dest


def write_namd_conf(psf: Path, pdb: Path, box_nm: tuple,
                    restraints: Path, threads: int) -> Path:
    bx_a, by_a, bz_a = box_nm[0]*10, box_nm[1]*10, Z_PERIOD
    cx, cy, cz = bx_a/2, by_a/2, bz_a/2

    conf_npt = _OUT / "sh_npt.conf"
    conf_npt.write_text(textwrap.dedent(f"""\
        # sh_npt.conf — single B-DNA helix, isotropic NPT 500 ps
        # Control for B_tube benchmark; rigidBonds all throughout.

        structure          {psf}
        coordinates        {pdb}
        outputName         {_OUT}/output/sh_npt

        set temperature    310

        paraTypeCharmm     on
        parameters         {_FF}/par_all36_na.prm
        parameters         {_FF}/toppar_water_ions_na.str

        cellBasisVector1   {bx_a:.3f}   0.000    0.000
        cellBasisVector2   0.000    {by_a:.3f}   0.000
        cellBasisVector3   0.000    0.000    {bz_a:.3f}
        cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

        wrapAll            on
        wrapWater          on
        wrapNearest        on

        PME                yes
        PMEGridSpacing     1.0

        cutoff             12.0
        switching          on
        switchdist         10.0
        pairlistdist       16.0
        exclude            scaled1-4
        oneFourScaling     1.0

        timestep           2.0
        rigidBonds         all
        rigidTolerance     1.0e-8
        nonbondedFreq      1
        fullElectFrequency 2
        stepspercycle      10

        temperature        $temperature
        langevin           on
        langevinDamping    1.0
        langevinTemp       $temperature
        langevinHydrogen   off

        useFlexibleCell    no
        LangevinPiston     on
        LangevinPistonTarget   1.01325
        LangevinPistonPeriod  200.0
        LangevinPistonDecay   100.0
        LangevinPistonTemp $temperature

        constraints        on
        consRef            {pdb}
        conskFile          {restraints}
        conskcol           B
        constraintScaling  1.0

        dcdFile            {_OUT}/output/sh_npt.dcd
        xstFile            {_OUT}/output/sh_npt.xst
        dcdFreq            2500
        xstFreq            2500
        outputEnergies     2500
        restartFreq        25000

        minimize           5000
        reinitvels         $temperature
        run                250000       ;# 500 ps
    """))

    # Also write a production conf (unrestrained)
    conf_prod = _OUT / "sh_npt_prod.conf"
    conf_prod.write_text(textwrap.dedent(f"""\
        # sh_npt_prod.conf — unrestrained isotropic NPT production from NPT restart
        structure          {psf}
        coordinates        {pdb}
        extendedSystem     {_OUT}/output/sh_npt.restart.xsc
        binCoordinates     {_OUT}/output/sh_npt.restart.coor
        binVelocities      {_OUT}/output/sh_npt.restart.vel
        outputName         {_OUT}/output/sh_npt_prod

        set temperature    310

        paraTypeCharmm     on
        parameters         {_FF}/par_all36_na.prm
        parameters         {_FF}/toppar_water_ions_na.str

        cellBasisVector1   {bx_a:.3f}   0.000    0.000
        cellBasisVector2   0.000    {by_a:.3f}   0.000
        cellBasisVector3   0.000    0.000    {bz_a:.3f}
        cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

        wrapAll            on
        wrapWater          on
        wrapNearest        on

        PME                yes
        PMEGridSpacing     1.0

        cutoff             12.0
        switching          on
        switchdist         10.0
        pairlistdist       16.0
        exclude            scaled1-4
        oneFourScaling     1.0

        timestep           2.0
        rigidBonds         all
        rigidTolerance     1.0e-8
        nonbondedFreq      1
        fullElectFrequency 2
        stepspercycle      10

        langevin           on
        langevinDamping    1.0
        langevinTemp       $temperature
        langevinHydrogen   off

        useFlexibleCell    no
        LangevinPiston     on
        LangevinPistonTarget   1.01325
        LangevinPistonPeriod  200.0
        LangevinPistonDecay   100.0
        LangevinPistonTemp $temperature

        dcdFile            {_OUT}/output/sh_npt_prod.dcd
        xstFile            {_OUT}/output/sh_npt_prod.xst
        dcdFreq            2500
        xstFreq            2500
        outputEnergies     2500
        restartFreq        25000

        run                250000       ;# 500 ps
    """))

    return conf_npt, conf_prod


def build(dry_run: bool = False, threads: int = 16, bridge_minimize: bool = False) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "output").mkdir(exist_ok=True)

    # ── 1. Extract template ───────────────────────────────────────────────────
    print("Loading B_tube...")
    u = mda.Universe(str(_SRC_PSF), str(_SRC_PDB))
    s1, s2 = extract_template(u)
    print(f"  Strand 1: {' '.join(r['resname'] for r in s1)}")
    print(f"  Strand 2: {' '.join(r['resname'] for r in s2)} (paired order)")
    for i, (r1, r2) in enumerate(zip(s1, s2)):
        assert r2["resname"] == _WC[r1["resname"]], f"bp{i} not WC: {r1['resname']}:{r2['resname']}"

    # ── 2. Build 21-bp duplex ─────────────────────────────────────────────────
    print("\nBuilding 21-bp duplex...")
    center_xy, z_ref = helix_axis(s1, s2)
    print(f"  Helix axis: ({center_xy[0]:.3f}, {center_xy[1]:.3f})  z_ref={z_ref:.3f}")
    out_s1, out_s2 = build_duplex(s1, s2, center_xy, z_ref)
    check_geometry(out_s1, out_s2)
    if bridge_minimize:
        minimize_all_bridges(out_s1, out_s2)
        check_geometry(out_s1, out_s2)

    if dry_run:
        print("\n[DRY RUN] Stopping before file I/O.")
        return

    # ── 3. Write strand PDBs (atom order must match PSF topology) ─────────────
    strand1_pdb = _OUT / "strand1.pdb"
    strand2_pdb = _OUT / "strand2.pdb"
    write_strand_pdb(out_s1, "STRA", strand1_pdb)
    write_strand_pdb(out_s2, "STRB", strand2_pdb)
    print(f"\nStrand PDBs written: {strand1_pdb.name}, {strand2_pdb.name}")

    # ── 4. Build PSF stub from B_tube topology ────────────────────────────────
    print("\nBuilding PSF from B_tube template...")
    dry_psf = _OUT / "duplex_dry.psf"
    dry_pdb = _OUT / "duplex_dry.pdb"
    build_psf_from_template(out_s1, out_s2, strand1_pdb, strand2_pdb, dry_psf, dry_pdb)

    # ── 5. Add wrap bonds ─────────────────────────────────────────────────────
    print("\nAdding wrap bonds...")
    add_wrap_bonds(dry_psf)

    # ── 6. Solvate + ionize ───────────────────────────────────────────────────
    print("\nSolvating...")
    final_psf, final_pdb, box_nm = solvate_and_ionize(dry_psf, dry_pdb)
    print(f"  Final PSF: {final_psf.name} ({final_psf.stat().st_size//1024} kB)")

    # ── 7. Write restraints and NAMD conf ─────────────────────────────────────
    print("\nWriting NAMD conf...")
    restraints = write_restraints(final_pdb)
    conf_npt, conf_prod = write_namd_conf(final_psf, final_pdb, box_nm, restraints, threads)

    # Symlink forcefield
    ff_link = _OUT / "forcefield"
    if not ff_link.exists():
        ff_link.symlink_to(_FF)

    print(f"\nBuild complete. Output: {_OUT}")
    print(f"  Solvated PSF:  {final_psf.name}")
    print(f"  Solvated PDB:  {final_pdb.name}")
    print(f"  NPT conf:      {conf_npt.name}")
    print(f"  Prod conf:     {conf_prod.name}")
    print()
    print(f"To run:")
    print(f"  mkdir -p {_OUT}/output")
    namd_bin = shutil.which("namd3") or "namd3"
    print(f"  {namd_bin} +p{threads} +devices 0 {conf_npt} > {_OUT}/output/sh_npt.log")


def main() -> None:
    global _OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--bridge-minimize", action="store_true",
                    help="Apply local phosphodiester bridge minimization before PSF/PDB output")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Override output directory for this single-helix variant")
    args = ap.parse_args()
    if args.out_dir is not None:
        _OUT = args.out_dir.resolve()
    build(dry_run=args.dry_run, threads=args.threads, bridge_minimize=args.bridge_minimize)


if __name__ == "__main__":
    main()
