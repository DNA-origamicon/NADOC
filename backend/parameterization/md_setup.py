"""
Step 2 — GROMACS run directory setup for isolated crossover parameterization.

Builds a fully self-contained run directory for one (variant, restraint_k) pair:
  <run_dir>/
    input.pdb          — NADOC-generated all-atom PDB
    conf.gro           — pdb2gmx + editconf + solvate output
    topol.top          — GROMACS topology
    *.itp              — per-strand topology includes
    posre_terminal.itp — soft restraints on outer-arm terminal P atoms (k-dependent)
    em.mdp             — energy minimisation (steep/SD, PME, with heavy-atom posres)
    nvt.mdp            — 100 ps NVT heat 0→310 K with POSRES
    npt.mdp            — 1 ns NPT equilibration with POSRES
    production.mdp     — 200 ns production, soft terminal restraints only
    run.sh             — sequential EM→NVT→NPT→production launcher
    restraint_log.json — records restraint atoms, k value, sensitivity sweep status

Ion scheme
----------
NaCl at ~150 mM (default).  DNA is first charge-neutralised with Na+, then
additional Na+/Cl- pairs are added to reach the target concentration.
No Mg²⁺ by default — the parameterization target is fast validation; a separate
run with Mg²⁺ can be added when the experimental buffer conditions are finalised.

Restraint philosophy (open question)
-------------------------------------
The ~6 bp outer stubs are restrained with soft harmonic position restraints on
the P atoms of the outermost 2 bp on each stub end.  This mimics being tethered
to the rest of an origami without over-constraining the junction geometry.

What "correct" origami-embedding restraints look like is not fully resolved:
  (a) Soft position restraints (current) — approximates a stiff origami arm
  (b) Orientational restraints — also fixes helix axis direction at terminus
  (c) Gaussian-chain end-to-end force — models the entropic restoring force of
      the flanking dsDNA arms as a spring with k ≈ 3kT/Lp where Lp is the
      persistence length and L is the arm length

The sensitivity sweep (k = 0.5, 1.0, 2.0 kcal/mol/Å²) is critical: if the
extracted inter-arm stiffness matrix changes by more than 20% across this range,
the outer stubs are biasing the result and the restraint model must be revised.

GROMACS units note
------------------
k_gmx [kJ/mol/nm²] = k_kcal [kcal/mol/Å²] × 418.4
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from backend.core.gromacs_package import (
    _build_gromacs_input_pdb,
    _find_gmx,
    _find_top_dir,
    _fix_itp_case,
    _pick_ff,
    _IONS_MDP,
)
from backend.core.models import Design

logger = logging.getLogger(__name__)

# ── Unit conversion ───────────────────────────────────────────────────────────

_KCAL_A2_TO_KJ_NM2 = 418.4   # 1 kcal/mol/Å² → kJ/mol/nm²

# ── Sensitivity-check threshold ───────────────────────────────────────────────
# If any diagonal of the stiffness matrix shifts by more than this fraction
# across the restraint-k sweep, flag the result as unreliable.
RESTRAINT_SENSITIVITY_THRESHOLD = 0.20   # 20%

# ── MDP templates ─────────────────────────────────────────────────────────────

_EM_MDP = """\
; Crossover parameterization — energy minimisation (TIP3P water + NaCl)
; Steep descent with heavy-atom position restraints.
; RESTRAINT_LOG: {restraint_log}

integrator              = steep
emtol                   = 10.0
emstep                  = 0.01
nsteps                  = 10000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

constraints             = none

define                  = -DPOSRES
"""

_NVT_MDP = """\
; Crossover parameterization — NVT heating 0→310 K (100 ps)
; DNA heavy atoms restrained via POSRES_ALL during heating.
; RESTRAINT_LOG: {restraint_log}

integrator              = sd
dt                      = 0.002
nsteps                  = 50000          ; 100 ps

nstxout-compressed      = 5000
nstvout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = no

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4
continuation            = no
gen-vel                 = yes
gen-temp                = 310
gen-seed                = -1

define                  = -DPOSRES
refcoord_scaling        = com
"""

_NPT_MDP = """\
; Crossover parameterization — NPT equilibration (1 ns)
; DNA heavy atoms restrained; box volume equilibrates.
; RESTRAINT_LOG: {restraint_log}

integrator              = sd
dt                      = 0.002
nsteps                  = 500000         ; 1 ns

nstxout-compressed      = 5000
nstvout                 = 0
nstlog                  = 1000
nstenergy               = 1000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = Parrinello-Rahman
pcoupltype              = isotropic
tau-p                   = 2.0
ref-p                   = 1.0
compressibility         = 4.5e-5

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4
continuation            = yes
gen-vel                 = no

define                  = -DPOSRES
refcoord_scaling        = com
"""

_PRODUCTION_MDP = """\
; Crossover parameterization — production run ({prod_ns} ns)
; ONLY terminal outer-arm P atoms are restrained (soft, k={k_kcal} kcal/mol/Å²).
; All other DNA atoms are unrestrained.
;
; RESTRAINT_LOG: {restraint_log}
;
; This run measures the inter-arm 6-DOF fluctuations of the 20 bp
; inter-crossover region.  Do NOT use this trajectory for validation —
; validation uses an independent system (see validation_stub.py).

integrator              = sd
dt                      = 0.002
nsteps                  = {prod_nsteps}

; Save every 20 ps — sufficient for correlation analysis of junction dynamics
nstxout-compressed      = 10000
nstvout                 = 0
nstlog                  = 5000
nstenergy               = 5000

cutoff-scheme           = Verlet
nstlist                 = 20
rlist                   = 1.2
rcoulomb                = 1.0
rvdw                    = 1.0
vdwtype                 = Cut-off
vdw-modifier            = Force-switch
rvdw-switch             = 0.8
pbc                     = xyz

coulombtype             = PME
pme-order               = 4
fourierspacing          = 0.16

tc-grps                 = System
tau-t                   = 10.0
ref-t                   = 310

pcoupl                  = Parrinello-Rahman
pcoupltype              = isotropic
tau-p                   = 2.0
ref-p                   = 1.0
compressibility         = 4.5e-5

constraints             = h-bonds
constraint-algorithm    = LINCS
lincs-iter              = 1
lincs-order             = 4
continuation            = yes
gen-vel                 = no

define                  = -DPOSRES_TERMINAL
refcoord_scaling        = com
"""

_RUN_SH = """\
#!/usr/bin/env bash
# Sequential EM → NVT → NPT → production run.
# Parallel gmx mdrun runs are slower on this hardware; runs are serial.
# Generated by NADOC crossover parameterization pipeline.
set -euo pipefail

GMX={gmx}
NTMPI=1
# Leave 4 threads free for user tasks (Compy5000 has 32 total → cap at 28)
NTOMP=$(( $(nproc --all 2>/dev/null || echo 8) - 4 ))
# EM uses steep (non-dynamical): PME GPU not supported, use nb GPU only.
# MD phases (sd integrator): full GPU offload for nb, PME, and bonded.
# -update gpu omitted: position restraints are active in all phases.
EM_GPU="-nb gpu"
MD_GPU="-nb gpu -pme gpu -bonded gpu"

echo "[$(date)] === Energy minimisation ==="
$GMX grompp -f em.mdp    -c conf.gro   -r conf.gro  -p topol.top -o em.tpr    -maxwarn 10
$GMX mdrun  -v -ntmpi $NTMPI -ntomp $NTOMP $EM_GPU -deffnm em

echo "[$(date)] === NVT heating 0→310 K ==="
$GMX grompp -f nvt.mdp   -c em.gro    -r conf.gro  -p topol.top -o nvt.tpr   -maxwarn 10
$GMX mdrun  -v -ntmpi $NTMPI -ntomp $NTOMP $MD_GPU -deffnm nvt

echo "[$(date)] === NPT equilibration ==="
$GMX grompp -f npt.mdp   -c nvt.gro   -r conf.gro  -t nvt.cpt   -p topol.top -o npt.tpr   -maxwarn 10
$GMX mdrun  -v -ntmpi $NTMPI -ntomp $NTOMP $MD_GPU -deffnm npt

echo "[$(date)] === Production ({prod_ns} ns) ==="
$GMX grompp -f production.mdp -c npt.gro -r conf.gro -t npt.cpt -p topol.top -o prod.tpr -maxwarn 10
$GMX mdrun  -v -ntmpi $NTMPI -ntomp $NTOMP $MD_GPU -deffnm prod

echo "[$(date)] === Done. Production trajectory: prod.xtc ==="
"""

# ── Restraint ITP helpers ─────────────────────────────────────────────────────

def _build_posre_section(
    atom_indices_1based: list[int],
    k_gmx: float,
    comment: str,
) -> str:
    """Write a [ position_restraints ] section with local 1-based atom indices."""
    lines = [
        f"; {comment}",
        "[ position_restraints ]",
        "; ai  funct   fcx         fcy         fcz",
    ]
    for idx in atom_indices_1based:
        lines.append(f"{idx:6d}  1  {k_gmx:10.2f}  {k_gmx:10.2f}  {k_gmx:10.2f}")
    return "\n".join(lines) + "\n"


def _parse_itp_terminal_p_local_indices(
    itp_text: str,
    n_terminal_residues: int = 2,
) -> list[int]:
    """
    Parse a GROMACS molecule ITP [ atoms ] section and return LOCAL 1-based
    indices of P atoms in the first and last n_terminal_residues residues.

    ITP [ atoms ] columns (space-separated):
        nr  type  resnr  residue  atom  cgnr  charge  mass  ...
    We need: nr (local index), resnr, atom name.
    """
    in_atoms = False
    records: list[tuple[int, int, str]] = []   # (local_idx, resid, atom_name)
    for line in itp_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "atoms" in stripped.lower():
            in_atoms = True
            continue
        if stripped.startswith("["):
            in_atoms = False
            continue
        if not in_atoms or not stripped or stripped.startswith(";"):
            continue
        parts = stripped.split()
        if len(parts) >= 5:
            try:
                records.append((int(parts[0]), int(parts[2]), parts[4]))
            except ValueError:
                continue

    if not records:
        return []
    resids = sorted({r for _, r, _ in records})
    terminal = set(resids[:n_terminal_residues] + resids[-n_terminal_residues:])
    return [idx for idx, resid, name in records if resid in terminal and name == "P"]


def _count_itp_residues(itp_text: str) -> int:
    """Return the number of distinct residues in an ITP [ atoms ] section."""
    in_atoms = False
    resids: set[int] = set()
    for line in itp_text.splitlines():
        s = line.strip()
        if s.startswith("[") and "atoms" in s.lower():
            in_atoms = True; continue
        if s.startswith("["):
            in_atoms = False; continue
        if not in_atoms or not s or s.startswith(";"):
            continue
        parts = s.split()
        if len(parts) >= 3:
            try:
                resids.add(int(parts[2]))
            except ValueError:
                pass
    return len(resids)


def _inject_terminal_posres_into_chain_itp(
    itp_path: Path,
    k_gmx: float,
    n_terminal_residues: int = 2,
    max_residues: int | None = None,
) -> int:
    """
    Patch a per-chain ITP file to include a POSRES_TERMINAL block.

    Returns the number of P atoms restrained (0 if none found or skipped).
    Modifies the file in-place.

    Parameters
    ----------
    max_residues : int | None
        If set, skip chains with more than this many residues.  Used to
        exclude the central crossover staple (which spans both junction
        positions and has its "terminal" residues in the measurement region,
        not on the outer arm stubs).
    """
    itp_text = itp_path.read_text()

    if max_residues is not None:
        n_res = _count_itp_residues(itp_text)
        if n_res > max_residues:
            logger.debug(
                "Skipping POSRES_TERMINAL for %s: %d residues > max %d "
                "(likely central crossover staple with terminals in measurement region).",
                itp_path.name, n_res, max_residues,
            )
            return 0

    p_indices = _parse_itp_terminal_p_local_indices(itp_text, n_terminal_residues)
    if not p_indices:
        logger.debug("No terminal P atoms found in %s — skipping POSRES_TERMINAL.", itp_path.name)
        return 0

    posre_section = _build_posre_section(
        p_indices,
        k_gmx,
        comment=(
            f"POSRES_TERMINAL: outer-arm terminal P atoms only\n"
            f"; k = {k_gmx:.1f} kJ/mol/nm² | {itp_path.name}"
        ),
    )
    terminal_block = (
        "\n#ifdef POSRES_TERMINAL\n"
        + posre_section
        + "#endif\n"
    )
    # Append at end of itp (after all other sections)
    itp_path.write_text(itp_text.rstrip("\n") + "\n" + terminal_block)
    logger.debug(
        "Injected POSRES_TERMINAL into %s: %d P atoms",
        itp_path.name, len(p_indices),
    )
    return len(p_indices)


# ── Main setup function ───────────────────────────────────────────────────────

def setup_run_directory(
    design: Design,
    pdb_path: str | Path,
    run_dir: str | Path,
    variant_label: str,
    restraint_k_kcal: float = 1.0,
    prod_ns: int = 200,
    nacl_conc_mM: float = 150.0,
    sequence_seed: int = 42,
    is_sensitivity_sweep: bool = False,
) -> Path:
    """
    Build a self-contained GROMACS run directory for one (variant, restraint_k) pair.

    Parameters
    ----------
    design : Design
        The sequenced, T-count-modified design.
    pdb_path : path
        The all-atom PDB from crossover_extract.generate_variant_pdb().
    run_dir : path
        Output directory to create.  Will be created if absent.
    variant_label : str
        E.g. "T0", "T1" — used for logging and restraint_log.json.
    restraint_k_kcal : float
        Outer-arm terminal restraint spring constant in kcal/mol/Å²
        (default: 1.0).  Must be one of the values in CrossoverVariant.
        restraint_k_kcal_per_mol_per_A2 to be part of the sensitivity sweep.
    prod_ns : int
        Production run length in nanoseconds (default: 200).
    nacl_conc_mM : float
        NaCl concentration in mM (default: 150).
    sequence_seed : int
        Recorded in restraint_log.json for reproducibility.
    is_sensitivity_sweep : bool
        If True, annotate this run as part of the restraint sensitivity sweep.

    Returns
    -------
    Path of the created run directory.

    Raises
    ------
    RuntimeError
        If any GROMACS command fails.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    gmx = _find_gmx()
    top_dir = _find_top_dir()
    ff = _pick_ff(top_dir)
    ff_dir = top_dir / f"{ff}.ff"

    k_gmx = restraint_k_kcal * _KCAL_A2_TO_KJ_NM2
    prod_nsteps = int(prod_ns * 1e6 / 2)   # dt=0.002 ps → steps per ns = 500000
    nacl_conc_M = nacl_conc_mM / 1000.0

    restraint_log_entry = {
        "variant": variant_label,
        "restraint_k_kcal_per_mol_per_A2": restraint_k_kcal,
        "restraint_k_kJ_per_mol_per_nm2": k_gmx,
        "restrained_atoms": "P atoms of outermost 2 bp on each outer arm stub",
        "restraint_model": "harmonic_position_restraints",
        "open_question": (
            "The appropriate restraint model for origami-embedding is not settled. "
            "Current: soft position restraints (pos. only). "
            "Alternatives: orientational restraints, Gaussian-chain end-force. "
            "Check sensitivity sweep results to assess bias."
        ),
        "is_sensitivity_sweep_run": is_sensitivity_sweep,
        "nacl_conc_mM": nacl_conc_mM,
        "prod_ns": prod_ns,
        "force_field": ff,
        "sequence_seed": sequence_seed,
        "sensitivity_threshold": RESTRAINT_SENSITIVITY_THRESHOLD,
        "sensitivity_check": (
            "PENDING — run param_extract.check_restraint_sensitivity() "
            "after all k-sweep trajectories complete"
        ),
    }

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        # ── 1. pdb2gmx ───────────────────────────────────────────────────────
        adapted = _build_gromacs_input_pdb(design, ff, box_margin_nm=2.0)
        input_pdb = tmpdir / "input.pdb"
        input_pdb.write_text(adapted)

        # charmm36-feb2026 requires explicit DNA terminus selection via -ter.
        # Without it, pdb2gmx defaults to protein N-terminal (NH3+) which
        # requires backbone N atom absent in DNA → fatal error.
        # Verified working: index 4 = 5TER (N-term), index 6 = 3TER (C-term).
        _n_chains = len({
            line[21] for line in adapted.splitlines()
            if line.startswith(("ATOM", "HETATM"))
        })
        _needs_ter = ff.startswith("charmm36-feb2026")
        _pdb2gmx_cmd = [
            gmx, "pdb2gmx",
            "-f", str(input_pdb),
            "-o", str(tmpdir / "conf_raw.gro"),
            "-p", str(tmpdir / "topol.top"),
            "-ignh", "-ff", ff, "-water", "tip3p", "-nobackup",
        ]
        if _needs_ter:
            _pdb2gmx_cmd.append("-ter")
        r = subprocess.run(
            _pdb2gmx_cmd,
            input=("4\n6\n" * _n_chains) if _needs_ter else None,
            capture_output=True, text=True, cwd=str(tmpdir),
        )
        if r.returncode != 0:
            raise RuntimeError(f"pdb2gmx failed:\n{r.stderr[-3000:]}")
        _fix_itp_case(tmpdir)

        # ── 2. editconf — centre + box ────────────────────────────────────────
        r = subprocess.run(
            [gmx, "editconf",
             "-f", str(tmpdir / "conf_raw.gro"),
             "-o", str(tmpdir / "conf_edit.gro"),
             "-c", "-d", "1.2", "-bt", "triclinic", "-nobackup"],
            capture_output=True, text=True, cwd=str(tmpdir),
        )
        if r.returncode != 0:
            raise RuntimeError(f"editconf failed:\n{r.stderr[-2000:]}")

        # ── 3. solvate ────────────────────────────────────────────────────────
        r = subprocess.run(
            [gmx, "solvate",
             "-cp", str(tmpdir / "conf_edit.gro"),
             "-cs", "spc216.gro",
             "-o",  str(tmpdir / "solvated.gro"),
             "-p",  str(tmpdir / "topol.top"),
             "-nobackup"],
            capture_output=True, text=True, cwd=str(tmpdir),
        )
        if r.returncode != 0:
            raise RuntimeError(f"solvate failed:\n{r.stderr[-2000:]}")

        # ── 4. genion — NaCl counterions ─────────────────────────────────────
        (tmpdir / "ions.mdp").write_text(_IONS_MDP)
        r = subprocess.run(
            [gmx, "grompp",
             "-f", str(tmpdir / "ions.mdp"),
             "-c", str(tmpdir / "solvated.gro"),
             "-p", str(tmpdir / "topol.top"),
             "-o", str(tmpdir / "ions.tpr"),
             "-maxwarn", "20", "-nobackup"],
            capture_output=True, text=True, cwd=str(tmpdir),
        )
        if r.returncode != 0:
            raise RuntimeError(f"grompp (ions) failed:\n{r.stderr[-2000:]}")

        # NaCl: Na+ neutralises DNA charge (-), then NaCl pairs for concentration
        r = subprocess.run(
            [gmx, "genion",
             "-s",     str(tmpdir / "ions.tpr"),
             "-o",     str(tmpdir / "conf.gro"),
             "-p",     str(tmpdir / "topol.top"),
             "-pname", "NA", "-pq", "1",
             "-nname", "CL", "-nq", "-1",
             "-neutral",
             "-conc",  str(nacl_conc_M),
             "-nobackup"],
            input="SOL\n",
            capture_output=True, text=True, cwd=str(tmpdir),
        )
        if r.returncode != 0:
            raise RuntimeError(f"genion failed:\n{r.stderr[-2000:]}")

        # ── 5. Inject POSRES_TERMINAL into each per-chain ITP ────────────────
        # GROMACS position restraints must be inside a moleculetype block with
        # LOCAL atom indices.  We patch each pdb2gmx-generated chain ITP directly.
        #
        # EM/NVT/NPT use the pdb2gmx-standard `#ifdef POSRES` (all heavy atoms).
        # Production uses `#ifdef POSRES_TERMINAL` (outer-arm P atoms only).
        #
        # max_residues: skip any chain longer than the longest scaffold strand.
        # The central crossover staple spans both junction arms (42 residues in
        # the 2hb design), making its ITP "terminal" residues fall in the
        # measurement region rather than on the outer arm stubs.
        from backend.core.models import StrandType as _StrandType
        _scaffold_lengths = [
            sum(abs(dom.end_bp - dom.start_bp) + 1 for dom in s.domains)
            for s in design.strands if s.strand_type == _StrandType.SCAFFOLD
        ]
        _max_res = max(_scaffold_lengths) if _scaffold_lengths else None

        chain_itps = sorted(tmpdir.glob("topol_DNA_chain_*.itp"))
        total_p_restrained = 0
        for itp_path in chain_itps:
            n = _inject_terminal_posres_into_chain_itp(
                itp_path, k_gmx, max_residues=_max_res
            )
            total_p_restrained += n

        restraint_log_entry["n_restrained_p_atoms"] = total_p_restrained
        restraint_log_entry["patched_chain_itps"] = [p.name for p in chain_itps]
        if total_p_restrained == 0:
            logger.warning(
                "No terminal P atoms found in any chain ITP — "
                "POSRES_TERMINAL will have no effect.  "
                "Check that pdb2gmx produced topol_DNA_chain_*.itp files."
            )

        # ── 6. Write MDP files ────────────────────────────────────────────────
        log_str = f"variant={variant_label}, k={restraint_k_kcal} kcal/mol/Å²"
        (tmpdir / "em.mdp").write_text(_EM_MDP.format(restraint_log=log_str))
        (tmpdir / "nvt.mdp").write_text(_NVT_MDP.format(restraint_log=log_str))
        (tmpdir / "npt.mdp").write_text(_NPT_MDP.format(restraint_log=log_str))
        (tmpdir / "production.mdp").write_text(
            _PRODUCTION_MDP.format(
                prod_ns=prod_ns,
                prod_nsteps=prod_nsteps,
                k_kcal=restraint_k_kcal,
                restraint_log=log_str,
            )
        )

        # ── 7. Write run script ───────────────────────────────────────────────
        (tmpdir / "run.sh").write_text(_RUN_SH.format(gmx=gmx, prod_ns=prod_ns))

        # ── 8. Copy everything to output directory ────────────────────────────
        for src in tmpdir.iterdir():
            dst = run_dir / src.name
            if src.is_file():
                dst.write_bytes(src.read_bytes())

    # Write the original (pre-pdb2gmx) PDB for reference
    (run_dir / "input_nadoc.pdb").write_bytes(Path(pdb_path).read_bytes())

    # Write restraint log
    (run_dir / "restraint_log.json").write_text(
        json.dumps(restraint_log_entry, indent=2)
    )

    # Copy force-field directory
    ff_out = run_dir / f"{ff}.ff"
    if not ff_out.exists():
        import shutil
        shutil.copytree(str(ff_dir), str(ff_out))

    logger.info(
        "Run directory ready: %s (variant=%s, k=%.1f kcal/mol/Å², %d ns)",
        run_dir, variant_label, restraint_k_kcal, prod_ns,
    )
    return run_dir


def setup_sensitivity_sweep(
    design: Design,
    pdb_path: str | Path,
    base_run_dir: str | Path,
    variant_label: str,
    k_values: list[float] | None = None,
    prod_ns: int = 50,
    nacl_conc_mM: float = 150.0,
) -> dict[float, Path]:
    """
    Set up run directories for all k values in the restraint sensitivity sweep.

    For the sensitivity check, prod_ns defaults to 50 ns — enough to see whether
    parameters vary with k, but short enough to run quickly before committing to
    full 200 ns runs.

    Parameters
    ----------
    k_values : list of floats (kcal/mol/Å²)
        Restraint spring constants to sweep.  Default: [0.5, 1.0, 2.0].

    Returns
    -------
    dict mapping k_value → run directory Path.
    """
    if k_values is None:
        k_values = [0.5, 1.0, 2.0]

    return {
        k: setup_run_directory(
            design=design,
            pdb_path=pdb_path,
            run_dir=Path(base_run_dir) / f"k{k:.1f}".replace(".", "p"),
            variant_label=variant_label,
            restraint_k_kcal=k,
            prod_ns=prod_ns,
            nacl_conc_mM=nacl_conc_mM,
            is_sensitivity_sweep=True,
        )
        for k in k_values
    }
