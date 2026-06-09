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
import re
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


# ── NAMD conf template ────────────────────────────────────────────────────────

def _common_header(
    name_stem: str,
    box: tuple[float, float, float],
    _mgh_extrabonds: bool,
    *,
    rigid_bonds: str = "all",
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

timestep           2.0
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
    lines = [_common_header(name_stem, box, mgh_extrabonds)]
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
) -> str:
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
    lines.append(f"extraBondsFile     {name_stem}_k{scale:g}.enm.extra\n")
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
    residues: list[_BaseResidue] = []
    by_key: dict[tuple[str, str, str], _BaseResidue] = {}
    atom_ordinal = 0
    for line in pdb_path.read_text(errors="replace").splitlines():
        if not line.startswith("ATOM  "):
            continue
        atom_ordinal += 1
        atom = line[12:16].strip()
        resn = line[17:21].strip()
        chain = line[21:22].strip()
        resid = line[22:26].strip()
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
        key = (chain, resid, resn)
        row = by_key.get(key)
        if row is None:
            row = _BaseResidue(key=key)
            by_key[key] = row
            residues.append(row)
        row.atoms.append((atom_ordinal - 1, atom, pos))
    return [res for res in residues if res.atoms]


def write_aksimentiev_enm_files(
    pdb_path: Path,
    package_dir: Path,
    name_stem: str,
    *,
    base_k: float = 0.5,
    scales: tuple[float, ...] = (0.5, 0.1, 0.01),
    cut_ang: float = 8.0,
    residue_com_cut_ang: float = 30.0,
) -> dict[str, object]:
    """Write tutorial-style base-ring ENM extraBonds files for all k scales."""
    residues = _parse_base_ring_residues(pdb_path)
    if not residues:
        raise RuntimeError(f"No DNA base-ring atoms found for ENM generation in {pdb_path}")

    coms = np.array([res.com for res in residues], dtype=float)
    residue_pairs = cKDTree(coms).query_pairs(residue_com_cut_ang, output_type="ndarray")

    base_records: list[tuple[int, int, float]] = []
    for ri, rj in residue_pairs:
        res_i = residues[int(ri)]
        res_j = residues[int(rj)]
        for idx_i, _name_i, pos_i in res_i.atoms:
            for idx_j, _name_j, pos_j in res_j.atoms:
                dist = math.sqrt(float(np.dot(pos_i - pos_j, pos_i - pos_j)))
                if dist > cut_ang:
                    continue
                a, b = sorted((idx_i, idx_j))
                base_records.append((a, b, dist))

    files: dict[str, int] = {}
    for k in scales:
        filename = f"{name_stem}_k{k:g}.enm.extra"
        path = package_dir / filename
        k_text = f"{k:.6g}"
        with path.open("w") as handle:
            for a, b, dist in base_records:
                handle.write(f"bond{a:10d}{b:10d}{k_text:>10s}{dist:10.3g}\n")
        files[filename] = len(base_records)

    report = {
        "schema": "nadoc.aksimentiev_enm.v1",
        "source_pdb": str(pdb_path),
        "n_residues_with_base_atoms": len(residues),
        "n_residue_pairs_com_le_30A": int(len(residue_pairs)),
        "n_restraints_per_file": len(base_records),
        "base_k_kcal_mol_A2": base_k,
        "scales": list(scales),
        "cut_ang": cut_ang,
        "residue_com_cut_ang": residue_com_cut_ang,
        "base_atoms": sorted(BASE_RING_ATOMS),
        "files": files,
    }
    (package_dir / f"{name_stem}_aksimentiev_enm.report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


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


def mgh_slow_release_segments(name_stem: str) -> tuple[str, list[SegmentSpec]]:
    """Return (min_name, segments) for the mgh_slow_release protocol.

    The minimization name is returned separately because it needs a distinct
    conf/output name that the first warmup segment continues from.

    Default stages mirror the Aksimentiev tutorial shape:
      minimization: ENM k=0.5 + MGHH, 4800 steps by default
      NPT stages: 300 K, ENM k=0.5 -> 0.1 -> 0.01, 4.8 ns each
      handoff: 300 K, k=0, 4.8 ns
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
            segments.append(SegmentSpec(
                name     = seg_name,
                stage    = stage_str,
                percent  = pct,
                steps    = seg_steps,
                temp     = 300.0,
                damping  = 5.0,
                scale    = scale,
                npt      = True,
                previous = previous,
                reinit   = False,
                dcd_freq = _display_dcd_freq(seg_steps),
                min_wc_ref_relative = 0.75 if scale is None else 0.80,
                extra_bonds_file = None if scale is None else f"{name_stem}_k{scale:g}.enm.extra",
            ))
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
) -> tuple[str, str, list[SegmentSpec]]:
    """Build the solvated package and all stage configs in job_dir.

    Calls build_namd_solvated_package (GROMACS solvation step, ~60-120 s).
    Extracts the ZIP to job_dir/package/, then writes:
      - restraints_dna_heavy.pdb
      - {min_name}.conf
      - one .conf per segment
      - manifest.json

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
    pdb_path = package_dir / f"{name_stem}.pdb"
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    enm_report = write_aksimentiev_enm_files(pdb_path, package_dir, name_stem)

    # Create output dir
    (package_dir / "output").mkdir(exist_ok=True)

    # Build segment list
    min_name, segments = mgh_slow_release_segments(name_stem)

    # Write minimization conf
    (package_dir / f"{min_name}.conf").write_text(
        _min_conf(min_name, name_stem, box, mgh_extrabonds, minimize_steps, min_scale)
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
            name     = s["name"],
            stage    = s["stage"],
            percent  = s["percent"],
            steps    = s["steps"],
            temp     = s["temp"],
            damping  = s["damping"],
            scale    = s["scale"],
            npt      = s["npt"],
            previous = s["previous"],
            reinit   = s.get("reinit", False),
            dcd_freq = s.get("dcd_freq", 20000),
            min_c1_paired = s.get("min_c1_paired", 0.90),
            min_wc_ref_relative = s.get("min_wc_ref_relative", 0.85),
            extra_bonds_file = s.get("extra_bonds_file"),
        )
        for s in data["segments"]
    ]
    return min_name, segments
