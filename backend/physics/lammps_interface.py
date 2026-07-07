"""oxDNA → LAMMPS (CG-DNA) transcoder — the native NADOC bridge to parallel oxDNA.

LAMMPS with the CG-DNA package runs the *same* oxDNA2 force field NADOC already
uses, but MPI domain-decomposed (see ``project_lammps_oxdna``).  Rather than depend
on the external tacoxDNA tool, this module transcodes NADOC's **own, already
topology-validated** oxDNA files — the ``topology.top`` + ``conf.dat`` that
``oxdna_interface.write_topology``/``write_configuration`` emit and the oxDNA health
checks validate — into a LAMMPS data file + input script.

**No new topology reasoning happens here.**  Strand polarity / 3′→5′ connectivity is
read straight from the oxDNA topology (its ``n3`` neighbour column); per-nucleotide
orientation is read straight from the oxDNA configuration (its ``a1`` = base normal,
``a3`` = 5′→3′ axis vectors).  The only new logic is the mechanical oxDNA→LAMMPS
*format* mapping — and the one non-obvious piece of that, the body-frame →
orientation-quaternion conversion (:func:`exyz_to_quat`), is ported **verbatim** from
the LAMMPS CG-DNA author's reference generator
(``lammps/examples/PACKAGES/cgdna/util/generate.py``, O. Henrich) so the convention
matches LAMMPS's ``atom_style ... ellipsoid oxdna`` exactly.

Layer: Physical only.  This produces a simulation's *starting* configuration; nothing
here is ever written back into Design topology.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ── oxDNA / LAMMPS CG-DNA constants (from the reference generator + examples) ──
# A/C/G/T → LAMMPS atom types 1/2/3/4; the oxDNA2 sequence-dependent H-bond pairs
# are types (1,4)=A·T and (2,3)=C·G, exactly as the pair_coeff lines below assume.
BASE_TO_TYPE: dict[str, int] = {"A": 1, "C": 2, "G": 3, "T": 4}
N_ATOM_TYPES = 4
# Nucleotides are modelled as spheres carrying an orientation; shape + mass are the
# fixed values the CG-DNA generator and examples use (mass is also re-set in the
# input script, so the data-file density is a harmless placeholder of 1).
ELLIPSOID_SHAPE = 1.1739845031423408
NUCLEOTIDE_MASS = 3.1575


# ── body frame → quaternion (VERBATIM port of generate.py:exyz_to_quat) ───────
def exyz_to_quat(mya1, mya3):
    """oxDNA local body frame (a1, a3) → LAMMPS orientation quaternion (w,i,j,k).

    Ported verbatim from the LAMMPS CG-DNA reference generator so the convention is
    guaranteed to match ``atom_style ... ellipsoid oxdna``.  ``mya1`` is the
    backbone→base (base-normal) unit vector, ``mya3`` the 5′→3′ helix-axis unit
    vector; ``a2 = a3 × a1`` completes a right-handed frame whose rows form the
    rotation matrix the quaternion encodes.
    """
    mya1 = np.asarray(mya1, dtype=float)
    mya3 = np.asarray(mya3, dtype=float)
    mya2 = np.cross(mya3, mya1)
    myquat = [1, 0, 0, 0]

    q0sq = 0.25 * (mya1[0] + mya2[1] + mya3[2] + 1.0)
    q1sq = q0sq - 0.5 * (mya2[1] + mya3[2])
    q2sq = q0sq - 0.5 * (mya1[0] + mya3[2])
    q3sq = q0sq - 0.5 * (mya1[0] + mya2[1])

    # some component must be > 1/4 since they sum to 1; compute the rest from it
    if q0sq >= 0.25:
        myquat[0] = np.sqrt(q0sq)
        myquat[1] = (mya2[2] - mya3[1]) / (4.0 * myquat[0])
        myquat[2] = (mya3[0] - mya1[2]) / (4.0 * myquat[0])
        myquat[3] = (mya1[1] - mya2[0]) / (4.0 * myquat[0])
    elif q1sq >= 0.25:
        myquat[1] = np.sqrt(q1sq)
        myquat[0] = (mya2[2] - mya3[1]) / (4.0 * myquat[1])
        myquat[2] = (mya2[0] + mya1[1]) / (4.0 * myquat[1])
        myquat[3] = (mya1[2] + mya3[0]) / (4.0 * myquat[1])
    elif q2sq >= 0.25:
        myquat[2] = np.sqrt(q2sq)
        myquat[0] = (mya3[0] - mya1[2]) / (4.0 * myquat[2])
        myquat[1] = (mya2[0] + mya1[1]) / (4.0 * myquat[2])
        myquat[3] = (mya3[1] + mya2[2]) / (4.0 * myquat[2])
    elif q3sq >= 0.25:
        myquat[3] = np.sqrt(q3sq)
        myquat[0] = (mya1[1] - mya2[0]) / (4.0 * myquat[3])
        myquat[1] = (mya3[0] + mya1[2]) / (4.0 * myquat[3])
        myquat[2] = (mya3[1] + mya2[2]) / (4.0 * myquat[3])

    norm = 1.0 / np.sqrt(
        myquat[0] * myquat[0] + myquat[1] * myquat[1]
        + myquat[2] * myquat[2] + myquat[3] * myquat[3]
    )
    return np.array([myquat[0] * norm, myquat[1] * norm,
                     myquat[2] * norm, myquat[3] * norm])


def quat_to_exyz(q):
    """LAMMPS orientation quaternion (w,i,j,k) → oxDNA body frame ``(a1, a3)``.

    Inverse of :func:`exyz_to_quat`: build the rotation matrix whose COLUMNS are the
    body axes (the convention ``exyz_to_quat`` encodes), then ``a1`` is column 0
    (backbone→base) and ``a3`` is column 2 (5′→3′ axis).  Used for trajectory
    read-back — mapping a LAMMPS dump frame back to an oxDNA configuration.
    """
    w, x, y, z = (float(v) for v in q)
    a1 = np.array([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)])
    a3 = np.array([2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)])
    return a1, a3


def lammps_dump_to_oxdna_traj(dump_text: str, out_path) -> int:
    """Transcode a LAMMPS oxDNA dump (``traj.lammpstrj``) → an oxDNA ``.dat``
    trajectory, so the existing oxDNA trajectory reader/viewer can play a LAMMPS run.

    Expects a dump written with columns ``id mol type x y z c_quat[1..4]`` (what
    :func:`build_input_file` emits).  Each frame's atoms are sorted by id (so the
    order matches the oxDNA topology / NADOC nucleotide order), positions passed
    through, and the orientation quaternion mapped back to oxDNA ``a1``/``a3``.
    Returns the number of frames written.
    """
    lines = dump_text.splitlines()
    frames: list[tuple[np.ndarray, list[tuple[int, np.ndarray, np.ndarray, np.ndarray]]]] = []
    i, n = 0, len(lines)
    while i < n:
        if not lines[i].startswith("ITEM: TIMESTEP"):
            i += 1
            continue
        i += 2                                           # skip TIMESTEP + value
        # NUMBER OF ATOMS
        i += 1
        natoms = int(lines[i].split()[0]); i += 1
        # BOX BOUNDS (3 axes)
        i += 1
        box = []
        for _ in range(3):
            lo, hi = (float(v) for v in lines[i].split()[:2]); box.append(hi - lo); i += 1
        boxv = np.array(box)
        # ATOMS header → column indices
        cols = lines[i].split()[2:]; i += 1
        cx = [cols.index(c) for c in ("x", "y", "z")]
        cq = [cols.index(c) for c in ("c_quat[1]", "c_quat[2]", "c_quat[3]", "c_quat[4]")]
        cid = cols.index("id")
        atoms = []
        for _ in range(natoms):
            f = lines[i].split(); i += 1
            pos = np.array([float(f[cx[0]]), float(f[cx[1]]), float(f[cx[2]])])
            quat = [float(f[cq[0]]), float(f[cq[1]]), float(f[cq[2]]), float(f[cq[3]])]
            a1, a3 = quat_to_exyz(quat)
            atoms.append((int(f[cid]), pos, a1, a3))
        atoms.sort(key=lambda a: a[0])
        frames.append((boxv, atoms))

    with open(out_path, "w", encoding="utf-8") as fh:
        for t, (boxv, atoms) in enumerate(frames):
            fh.write(f"t = {t}\n")
            fh.write(f"b = {boxv[0]:.6f} {boxv[1]:.6f} {boxv[2]:.6f}\n")
            fh.write("E = 0 0 0\n")
            for _id, pos, a1, a3 in atoms:
                fh.write(f"{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f} "
                         f"{a1[0]:.6f} {a1[1]:.6f} {a1[2]:.6f} "
                         f"{a3[0]:.6f} {a3[1]:.6f} {a3[2]:.6f} 0 0 0 0 0 0\n")
    return len(frames)


# ── oxDNA file parsers ────────────────────────────────────────────────────────
@dataclass
class OxdnaTopoRow:
    strand: int   # 1-based strand id
    base: str     # 'A'|'C'|'G'|'T' (or other → treated as unsequenced)
    n3: int       # 0-based 3′ neighbour particle index, -1 if none
    n5: int       # 0-based 5′ neighbour particle index, -1 if none


def parse_topology(text: str) -> tuple[int, list[OxdnaTopoRow]]:
    """Parse an oxDNA ``topology.top`` → ``(n_strands, rows)``.

    Header line is ``<N> <n_strands>``; each subsequent line is
    ``<strand> <base> <n3> <n5>`` with 0-based ``n3``/``n5`` (or -1).
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty oxDNA topology")
    n_atoms, n_strands = (int(x) for x in lines[0].split()[:2])
    rows: list[OxdnaTopoRow] = []
    for ln in lines[1:]:
        p = ln.split()
        rows.append(OxdnaTopoRow(int(p[0]), p[1], int(p[2]), int(p[3])))
    if len(rows) != n_atoms:
        raise ValueError(f"topology header says {n_atoms} atoms but has {len(rows)} rows")
    return n_strands, rows


@dataclass
class OxdnaConfEntry:
    pos: np.ndarray   # centre-of-mass, oxDNA length units
    a1: np.ndarray    # base-normal unit vector
    a3: np.ndarray    # 5′→3′ axis unit vector


def parse_configuration(text: str) -> tuple[np.ndarray, list[OxdnaConfEntry]]:
    """Parse an oxDNA ``conf.dat`` → ``(box_vec, entries)``.

    Line 2 is ``b = bx by bz``; each nucleotide line is 15 floats
    ``x y z  a1x a1y a1z  a3x a3y a3z  vx vy vz  Lx Ly Lz`` (oxDNA units).
    """
    lines = text.splitlines()
    box = np.array([0.0, 0.0, 0.0])
    entries: list[OxdnaConfEntry] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("b"):
            parts = s.replace("=", " ").split()
            box = np.array([float(parts[1]), float(parts[2]), float(parts[3])])
            continue
        if s.startswith("t") or s.startswith("E"):
            continue
        f = [float(x) for x in s.split()]
        if len(f) < 9:
            continue
        entries.append(OxdnaConfEntry(
            pos=np.array(f[0:3]), a1=np.array(f[3:6]), a3=np.array(f[6:9])))
    return box, entries


# ── LAMMPS data-file writer ───────────────────────────────────────────────────
def build_data_file(top_text: str, conf_text: str, *, box_margin: float = 12.0,
                    min_box: float = 24.0, title: str = "NADOC oxDNA2 → LAMMPS CG-DNA") -> str:
    """Transcode an oxDNA (topology, configuration) pair → a LAMMPS data-file string.

    Atom types come from the topology base letters (A/C/G/T→1-4); positions +
    orientation quaternions from the configuration; FENE backbone bonds from the
    topology's 3′-neighbour column (each backbone bond emitted once).  The box is
    sized to enclose every nucleotide with ``box_margin`` (oxDNA units) of padding
    per side, floored at ``min_box`` so it stays larger than the interaction cutoff.

    Raises ``ValueError`` if the design is not fully sequenced (any non-ACGT base) —
    oxDNA binding strengths are sequence-dependent, so an unsequenced design would
    give physically meaningless base pairing.
    """
    _, rows = parse_topology(top_text)
    _box, entries = parse_configuration(conf_text)
    if len(rows) != len(entries):
        raise ValueError(
            f"topology has {len(rows)} nucleotides but configuration has {len(entries)}")
    n = len(rows)

    unsequenced = sorted({r.base for r in rows if r.base.upper() not in BASE_TO_TYPE})
    if unsequenced:
        n_bad = sum(1 for r in rows if r.base.upper() not in BASE_TO_TYPE)
        raise ValueError(
            f"design is not fully sequenced: {n_bad}/{n} nucleotides carry a non-ACGT "
            f"base ({', '.join(unsequenced)!r}). oxDNA base-pair strengths are "
            f"sequence-dependent — assign a full sequence before a LAMMPS run.")

    pos = np.array([e.pos for e in entries])
    lo = pos.min(axis=0) - box_margin
    hi = pos.max(axis=0) + box_margin
    for d in range(3):                       # enforce a minimum box edge per axis
        if hi[d] - lo[d] < min_box:
            mid = 0.5 * (hi[d] + lo[d])
            lo[d], hi[d] = mid - min_box / 2, mid + min_box / 2

    # backbone bonds: one per nucleotide that has a 3′ neighbour (unique per bond)
    bonds = [(i + 1, r.n3 + 1) for i, r in enumerate(rows) if r.n3 >= 0]

    out: list[str] = [f"# {title}", ""]
    out += [f"{n} atoms", f"{len(bonds)} bonds",
            f"{N_ATOM_TYPES} atom types", "1 bond types", f"{n} ellipsoids", ""]
    out += [f"{lo[0]:.8f} {hi[0]:.8f} xlo xhi",
            f"{lo[1]:.8f} {hi[1]:.8f} ylo yhi",
            f"{lo[2]:.8f} {hi[2]:.8f} zlo zhi", ""]
    out += ["Masses", ""] + [f"{t} {NUCLEOTIDE_MASS}" for t in range(1, N_ATOM_TYPES + 1)] + [""]

    out += ["Atoms # hybrid", ""]
    for i, (r, e) in enumerate(zip(rows, entries)):
        t = BASE_TO_TYPE[r.base.upper()]
        # id type x y z molecule-id ellipsoidflag density  (density=1 → mass set in input)
        out.append(f"{i+1} {t} {e.pos[0]:.15e} {e.pos[1]:.15e} {e.pos[2]:.15e} "
                   f"{r.strand} 1 1")
    out.append("")

    out += ["Velocities", ""]
    for i in range(n):
        out.append(f"{i+1} 0 0 0 0 0 0")
    out.append("")

    out += ["Ellipsoids", ""]
    for i, e in enumerate(entries):
        q = exyz_to_quat(e.a1, e.a3)
        out.append(f"{i+1} {ELLIPSOID_SHAPE:.15e} {ELLIPSOID_SHAPE:.15e} "
                   f"{ELLIPSOID_SHAPE:.15e} {q[0]:.15e} {q[1]:.15e} {q[2]:.15e} {q[3]:.15e}")
    out.append("")

    out += ["Bonds", ""]
    for bi, (a, b) in enumerate(bonds, start=1):
        out.append(f"{bi} 1 {a} {b}")
    out.append("")
    return "\n".join(out)


# ── LAMMPS input-script writer ────────────────────────────────────────────────
@dataclass
class LammpsInputParams:
    data_file: str = "data.oxdna"       # read_data source (relative to run cwd)
    traj_file: str = "traj.lammpstrj"   # dump output
    steps: int = 100_000                # MD steps
    dump_every: int = 1000              # frames every N steps
    temperature: float = 0.1            # oxDNA reduced units (0.1 ≈ 300 K)
    salt_molar: float = 0.5             # Debye-Hückel salt concentration [M]
    timestep: float = 1e-5              # oxDNA lj-unit timestep
    langevin_damp: float = 2.5          # thermostat damping (oxDNA time units)
    seed: int = 457145                  # Langevin RNG seed
    thermo_every: int = 1000            # console thermo cadence
    # Soft-start: FIRE energy-minimise the seed before the production run so
    # overstretched crossover/nick backbone bonds (the idealised B-DNA seed can
    # place bonds past oxDNA's native FENE length) relax into range first — the
    # equivalent of standalone oxDNA's "min" stage.  Measured effect on a badly
    # strained seed: production-start E_bond 9.1 → 0.07.  0 iterations skips it.
    relax_iters: int = 2000


# The six oxDNA2 pair-overlay coeff lines + FENE bond coeff, taken from the LAMMPS
# CG-DNA lj-units oxDNA2 example (``examples/.../oxDNA2/duplex2/in.duplex2``).  Only
# temperature (``{T}``) and salt (``{RHOS}``) are substituted; the potential form is
# the shipped reference so a NADOC run reproduces the validated force field.
_OXDNA2_FF = """# oxDNA2 FENE backbone
bond_style oxdna2/fene
bond_coeff * 2.0 0.25 0.7564
special_bonds lj 0 1 1

# oxDNA2 pair interactions (excluded vol, stacking, H-bond, cross/coax-stacking, Debye-Huckel)
pair_style hybrid/overlay oxdna2/excv oxdna2/stk oxdna2/hbond oxdna2/xstk oxdna2/coaxstk oxdna2/dh
pair_coeff * * oxdna2/excv    2.0 0.7 0.675 2.0 0.515 0.5 2.0 0.33 0.32
pair_coeff * * oxdna2/stk     seqav {T} 1.3523 2.6717 6.0 0.4 0.9 0.32 0.75 1.3 0 0.8 0.9 0 0.95 0.9 0 0.95 2.0 0.65 2.0 0.65
pair_coeff * * oxdna2/hbond   seqav 0.0 8.0 0.4 0.75 0.34 0.7 1.5 0 0.7 1.5 0 0.7 1.5 0 0.7 0.46 3.141592653589793 0.7 4.0 1.5707963267948966 0.45 4.0 1.5707963267948966 0.45
pair_coeff 1 4 oxdna2/hbond   seqav 1.0678 8.0 0.4 0.75 0.34 0.7 1.5 0 0.7 1.5 0 0.7 1.5 0 0.7 0.46 3.141592653589793 0.7 4.0 1.5707963267948966 0.45 4.0 1.5707963267948966 0.45
pair_coeff 2 3 oxdna2/hbond   seqav 1.0678 8.0 0.4 0.75 0.34 0.7 1.5 0 0.7 1.5 0 0.7 1.5 0 0.7 0.46 3.141592653589793 0.7 4.0 1.5707963267948966 0.45 4.0 1.5707963267948966 0.45
pair_coeff * * oxdna2/xstk    47.5 0.575 0.675 0.495 0.655 2.25 0.791592653589793 0.58 1.7 1.0 0.68 1.7 1.0 0.68 1.5 0 0.65 1.7 0.875 0.68 1.7 0.875 0.68
pair_coeff * * oxdna2/coaxstk 58.5 0.4 0.6 0.22 0.58 2.0 2.891592653589793 0.65 1.3 0 0.8 0.9 0 0.95 0.9 0 0.95 40.0 3.116592653589793
pair_coeff * * oxdna2/dh      {T} {RHOS} 0.815"""


def build_input_file(p: LammpsInputParams) -> str:
    """Generate the LAMMPS ``in.lammps`` script for an oxDNA2 CG-DNA run.

    Langevin-thermostatted NVE of aspherical particles (``fix nve/asphere`` +
    ``fix langevin ... angmom``), the exact idiom the CG-DNA examples use, plus a
    custom dump carrying position + orientation quaternion per frame so the run can
    later be read back into NADOC's oxDNA trajectory viewers (a follow-up phase).

    When ``relax_iters > 0`` the script FIRE-minimises the seed first (a **soft
    start**) so overstretched crossover/nick backbone bonds relax into oxDNA's FENE
    range before the production run, then ``reset_timestep 0`` so the dumped
    trajectory is the production run alone (steps 0…``steps``).  ``minimize`` relaxes
    translational positions only; nucleotide orientations keep their (correct) seed
    values and are re-thermalised by the production MD.
    """
    ff = _OXDNA2_FF.replace("{T}", repr(p.temperature)).replace("{RHOS}", repr(p.salt_molar))
    warmup = ""
    if p.relax_iters > 0:
        warmup = (
            "# ── soft-start: FIRE-minimise overstretched seed bonds into range ──\n"
            "min_style fire\n"
            f"minimize 1e-4 1e-6 {p.relax_iters} {p.relax_iters * 10}\n"
            "reset_timestep 0\n\n"
        )
    return f"""# NADOC-generated LAMMPS oxDNA2 (CG-DNA) run
units lj
dimension 3
newton on
boundary p p p

atom_style hybrid bond ellipsoid oxdna
atom_modify sort 0 1.0

read_data {p.data_file}
set atom * mass {NUCLEOTIDE_MASS}
group all type 1 {N_ATOM_TYPES}

# neighbour lists
neighbor 2.0 bin
neigh_modify every 1 delay 0 check yes

{ff}

# Langevin-thermostatted NVE of oriented (aspherical) nucleotides
fix 1 all nve/asphere
fix 2 all langevin {p.temperature!r} {p.temperature!r} {p.langevin_damp!r} {p.seed} angmom 10
comm_modify cutoff 3.8
thermo {p.thermo_every}
thermo_style custom step temp epair ebond etotal

{warmup}# ── production run ──
timestep {p.timestep!r}
compute quat all property/atom quatw quati quatj quatk
dump traj all custom {p.dump_every} {p.traj_file} id mol type x y z c_quat[1] c_quat[2] c_quat[3] c_quat[4]
dump_modify traj sort id

run {p.steps}
write_data last_config.data nocoeff
"""
