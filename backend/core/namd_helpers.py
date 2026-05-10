"""Pure helpers extracted from namd_package.py (Refactor 10-A).

These operate on text/strings + lightweight Design metadata only — no
subprocess, no force-field directory lookup, no NAMD install required.
Testable in isolation.

Functions
---------
- `complete_psf(design)`              — Design → full PSF text (delegates to
                                        `_complete_psf_from_stub`)
- `_complete_psf_from_stub(stub)`     — bonds-only PSF stub → full PSF text
- `get_ai_prompt(design)`             — Design → AI assistant prompt string
- `_render_namd_conf(name)`           — design name → NAMD config text

Constants
---------
- `_AI_PROMPT`                        — paste-ready AI assistant context block
"""

from __future__ import annotations

from backend.core.models import Design
from backend.core.pdb_export import export_psf


# ── PSF completion — pure Python, no external tools needed ────────────────────
#
# CHARMM36 NA has no IMPH (improper) terms — only angles and dihedrals.
# We generate both from the bond graph encoded in the stub PSF.

def complete_psf(design: Design) -> str:
    """Return a fully-parameterised PSF (atoms + bonds + angles + dihedrals)
    built from the stub PSF exported by pdb_export.export_psf().

    Angles and dihedrals are generated from the bond graph; no external
    tools (parmed, psfgen, VMD) are required.
    """
    stub = export_psf(design)
    return _complete_psf_from_stub(stub)


def _complete_psf_from_stub(stub: str) -> str:
    """Expand a bonds-only stub PSF into a full PSF with angles and dihedrals."""
    import re

    # ── Parse atoms ──────────────────────────────────────────────────────────
    # PSF atom line: serial  seg  resid  resname  name  type  charge  mass  0
    atom_re = re.compile(
        r"^\s*(\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([0-9.+\-Ee]+)\s+([0-9.+\-Ee]+)"
    )
    n_atoms = 0
    # map 1-based serial → index (0-based)
    serial_to_idx: dict[int, int] = {}
    in_atom = False
    atom_lines: list[str] = []
    bond_lines_raw: list[str] = []
    header_lines: list[str] = []
    collecting = "header"

    for line in stub.splitlines():
        stripped = line.strip()
        if "!NATOM" in line:
            m = re.search(r"(\d+)\s+!NATOM", line)
            n_atoms = int(m.group(1)) if m else 0
            in_atom = True
            collecting = "atom"
            header_lines.append(line)
            continue
        if "!NBOND" in line:
            in_atom = False
            collecting = "bond"
            # We'll rebuild the bonds section ourselves — skip this header
            continue
        if collecting == "header":
            header_lines.append(line)
        elif collecting == "atom":
            if stripped == "" or stripped.startswith("!"):
                collecting = "done_atom"
            else:
                m = atom_re.match(line)
                if m:
                    serial = int(m.group(1))
                    serial_to_idx[serial] = len(atom_lines)
                atom_lines.append(line)
        elif collecting == "bond":
            if stripped == "" or stripped.startswith("!"):
                collecting = "done_bond"
            else:
                bond_lines_raw.append(stripped)

    # ── Parse bonds ───────────────────────────────────────────────────────────
    bonds: list[tuple[int, int]] = []   # (0-based idx1, 0-based idx2)
    adj: list[set[int]] = [set() for _ in range(n_atoms)]

    for bl in bond_lines_raw:
        nums = bl.split()
        for i in range(0, len(nums) - 1, 2):
            s1, s2 = int(nums[i]), int(nums[i + 1])
            i1 = serial_to_idx.get(s1)
            i2 = serial_to_idx.get(s2)
            if i1 is not None and i2 is not None:
                bonds.append((i1, i2))
                adj[i1].add(i2)
                adj[i2].add(i1)

    # ── Generate angles from bond graph ───────────────────────────────────────
    # Angle: every unique (a, b, c) where a-b and b-c are bonds, a < c
    angles: list[tuple[int, int, int]] = []
    for b_idx in range(n_atoms):
        nbrs = sorted(adj[b_idx])
        for j, a_idx in enumerate(nbrs):
            for c_idx in nbrs[j + 1:]:
                angles.append((a_idx, b_idx, c_idx))

    # ── Generate proper dihedrals from bond graph ─────────────────────────────
    # Dihedral: every unique (a, b, c, d) where a-b, b-c, c-d bonds exist;
    # a ≠ c, b ≠ d; canonical: (b,c) < (c,b) and a < d for same (b,c).
    seen_dihe: set[tuple[int, int, int, int]] = set()
    dihedrals: list[tuple[int, int, int, int]] = []
    for b_idx in range(n_atoms):
        for c_idx in adj[b_idx]:
            if c_idx <= b_idx:
                continue  # process each bond once
            for a_idx in adj[b_idx]:
                if a_idx == c_idx:
                    continue
                for d_idx in adj[c_idx]:
                    if d_idx == b_idx or d_idx == a_idx:
                        continue
                    key = (min(a_idx, d_idx), b_idx, c_idx, max(a_idx, d_idx))
                    if a_idx > d_idx:
                        key = (d_idx, c_idx, b_idx, a_idx)
                    if key not in seen_dihe:
                        seen_dihe.add(key)
                        dihedrals.append((a_idx, b_idx, c_idx, d_idx))

    # ── Serial numbers (1-based) for output ───────────────────────────────────
    idx_to_serial = {v: k for k, v in serial_to_idx.items()}

    def serial(idx: int) -> int:
        return idx_to_serial.get(idx, idx + 1)

    # ── Build output PSF ──────────────────────────────────────────────────────
    out: list[str] = []
    out.extend(header_lines)
    out.extend(atom_lines)
    out.append("")

    # Bonds
    n_bonds = len(bonds)
    out.append(f"{n_bonds:8d} !NBOND: bonds")
    for i in range(0, n_bonds, 4):
        chunk = bonds[i:i + 4]
        out.append("".join(f"{serial(a):8d}{serial(b):8d}" for a, b in chunk))
    out.append("")

    # Angles
    n_ang = len(angles)
    out.append(f"{n_ang:8d} !NTHETA: angles")
    for i in range(0, n_ang, 3):
        chunk = angles[i:i + 3]
        out.append("".join(f"{serial(a):8d}{serial(b):8d}{serial(c):8d}" for a, b, c in chunk))
    out.append("")

    # Dihedrals
    n_dih = len(dihedrals)
    out.append(f"{n_dih:8d} !NPHI: dihedrals")
    for i in range(0, n_dih, 2):
        chunk = dihedrals[i:i + 2]
        out.append("".join(f"{serial(a):8d}{serial(b):8d}{serial(c):8d}{serial(d):8d}" for a, b, c, d in chunk))
    out.append("")

    # Impropers (none for CHARMM36 NA)
    out.append("       0 !NIMPHI: impropers")
    out.append("")
    out.append("       0 !NDON: donors")
    out.append("")
    out.append("       0 !NACC: acceptors")
    out.append("")
    out.append("       0 !NNB")
    out.append("")
    out.append("       0       0 !NGRP NST2")
    out.append("")
    out.append("       0       0 !NUMLP NUMLPH")
    out.append("")

    return "\n".join(out)


# ── AI-assistant prompt entry point ───────────────────────────────────────────

def get_ai_prompt(design: Design) -> str:
    """Return the AI assistant prompt with the design name substituted in."""
    name = (design.metadata.name or "design").replace(" ", "_")
    return _AI_PROMPT.replace("{name}", name)


# ── NAMD configuration template ───────────────────────────────────────────────

def _render_namd_conf(name: str) -> str:
    return f"""\
# NAMD configuration generated by NADOC
# GBIS implicit solvent — no water box needed for large DNA origami

structure          {name}.psf
coordinates        {name}.pdb
outputName         output/{name}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
# toppar_water_ions_cufix.str is included in the forcefield/ directory.
# Uncomment the line below only when running explicit-solvent simulations
# that include Na+/K+/Mg2+ ion atoms — not needed for GBIS implicit solvent.
#parameters         forcefield/toppar_water_ions_cufix.str

# ── Implicit solvent (Generalised Born) ───────────────────────────────────────
gbis               on
alphaCutoff        14.0
ionConcentration   0.15

# ── Thermostat ────────────────────────────────────────────────────────────────
temperature        310
langevin           on
langevinDamping    5
langevinTemp       310
langevinHydrogen   off

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             16.0
switching          on
switchdist         14.0
pairlistdist       18.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           1.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── Output ────────────────────────────────────────────────────────────────────
outputEnergies     500
dcdFreq            500
dcdFile            output/{name}.dcd
xstFreq            500
xstFile            output/{name}.xst

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           2000
reinitvels         310
run                50000
"""


# ── AI assistant prompt ────────────────────────────────────────────────────────
# Paste-ready context block for VS Code Copilot Chat, Claude, ChatGPT, etc.
# Included in the ZIP as AI_ASSISTANT_PROMPT.txt and surfaced as a popup in
# the NADOC UI immediately after the export button is clicked.

_AI_PROMPT = """\
=============================================================================
NADOC — NAMD SIMULATION PACKAGE: AI ASSISTANT CONTEXT
=============================================================================

Paste this entire block into VS Code Copilot Chat, Claude, ChatGPT, or any
AI assistant. It gives the model full context about this package so it can
guide you through setup, running, and analysing the simulation — no prior
molecular dynamics experience required.

-----------------------------------------------------------------------------
WHAT IS NADOC?
-----------------------------------------------------------------------------
NADOC (Not Another DNA Origami CAD) is a research-grade CAD tool for
designing DNA origami nanostructures. It works with both honeycomb and square
lattice designs and exports simulation-ready packages for NAMD.

This ZIP was generated by NADOC's "Export NAMD Package" feature. It contains
everything needed to run an all-atom molecular dynamics simulation of the DNA
origami structure on a Linux workstation, with no manual file preparation.

-----------------------------------------------------------------------------
WHAT IS IN THIS PACKAGE?
-----------------------------------------------------------------------------
The ZIP extracts to a single folder. Its contents:

  {name}.pdb
    All-atom PDB file. Heavy atoms only; CHARMM36 atom naming convention.
    Crossover geometries have been linearly interpolated (lerp-relaxed) from
    the idealized helix positions to reduce initial bond strain.

  {name}.psf
    CHARMM Protein Structure File — the topology. Defines every atom, bond,
    angle, dihedral, and improper in the system. Generated programmatically
    from CHARMM36 NA residue definitions; no psfgen or VMD required.

  namd.conf
    NAMD input script. Pre-configured for:
      • CHARMM36 nucleic-acid force field + CuFix ion corrections
      • GBIS implicit solvent (generalised Born) at 0.15 M ionic strength
      • NVT ensemble at 310 K (Langevin thermostat)
      • 2000-step conjugate-gradient energy minimisation
      • 50,000 MD steps (50 ps at 1 fs/step) production run
    Edit "run 50000" to change the number of production steps.

  forcefield/
    top_all36_na.rtf          — CHARMM36 NA topology (MacKerell lab, 2022)
    par_all36_na.prm          — CHARMM36 NA parameters
    toppar_water_ions_cufix.str — CuFix NBFIX ion corrections (Aksimentiev lab)

  launch.sh
    One-click bash launcher. On a fresh Ubuntu/Debian system it will:
      1. Install namd2 via apt (requires sudo, one time only)
      2. Detect any NVIDIA GPU and print NAMD3 GPU instructions if found
      3. Determine CPU core count and run NAMD in parallel
      4. Start scripts/monitor.py for a live progress display
    Run with:  bash launch.sh

  scripts/monitor.py
    Real-time progress monitor. Parses the NAMD log and prints a live table
    of step, temperature, pressure, and energy. Requires only Python 3 stdlib.

  output/   (created when the simulation runs)
    {name}.dcd        — DCD trajectory (all atom positions, every 1000 steps)
    {name}.xst        — Extended system (cell) history
    {name}.restart.*  — Restart coordinates, velocities, and cell (every 5000 steps)
    {name}.log        — Full NAMD log (also written to stdout during launch.sh)

-----------------------------------------------------------------------------
STEP-BY-STEP: RUNNING THE SIMULATION
-----------------------------------------------------------------------------

REQUIREMENTS
  • Linux (Ubuntu 20.04+ or Debian 11+ recommended) or WSL2 on Windows
  • ~4 GB RAM minimum; 16 GB+ recommended for large origami (>10,000 atoms)
  • NAMD2 (CPU) — installed automatically by launch.sh on Ubuntu/Debian
  • For GPU acceleration: NAMD3 binary from ks.uiuc.edu (see GPU section)

STEP 1 — Extract the ZIP
  unzip {name}_namd_complete.zip
  cd {name}_namd_complete/

STEP 2 — Run the simulation
  bash launch.sh

  launch.sh will ask for your sudo password once to install namd2 if it is
  not already present. After that it runs fully automatically.

STEP 3 — Watch progress
  The monitor script prints a table like:
    Step    Temp(K)   Total E (kcal/mol)   Wall time
    1000    309.7     -12045.3             0:00:18
    2000    310.2     -12041.8             0:00:35
    ...
  The first ~2000 steps are energy minimisation (temperature may appear as 0).

STEP 4 — Verify completion
  When done you will see "End of program" in the output. Check:
    ls output/
  You should see .dcd, .xst, .log, and .restart.* files.

-----------------------------------------------------------------------------
GPU ACCELERATION (NAMD3)
-----------------------------------------------------------------------------
The apt package namd2 is CPU-only. For GPU runs:
  1. Download NAMD3 from:
       https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=NAMD
     Choose: Linux-x86_64-multicore-CUDA (for NVIDIA GPUs)
  2. Extract and run:
       NAMD_CMD=/path/to/namd3  bash launch.sh
  GPU runs are typically 10–50× faster than CPU for large systems.

-----------------------------------------------------------------------------
VISUALISING RESULTS
-----------------------------------------------------------------------------
NAMD produces DCD trajectory files. The standard tool is VMD (free, UIUC):
  Download: https://www.ks.uiuc.edu/Research/vmd/

Load the structure:
  vmd {name}.pdb {name}.psf

Load with trajectory:
  vmd {name}.pdb {name}.psf -dcd output/{name}.dcd

In VMD:
  • Graphics > Representations — change drawing method to "Tube" or "Licorice"
    for DNA, or "NewCartoon" won't work well (DNA-specific).
  • Extensions > Analysis > RMSD Trajectory Tool — measure structural drift.
  • Movie Maker (Extensions > Visualization > Movie Maker) — render trajectory.

For Python-based analysis, MDAnalysis works well:
  pip install MDAnalysis
  import MDAnalysis as mda
  u = mda.Universe("{name}.psf", "output/{name}.dcd")
  for ts in u.trajectory:
      print(ts.frame, ts.time)

-----------------------------------------------------------------------------
SIMULATION PHYSICS — WHAT AND WHY
-----------------------------------------------------------------------------
Force field:  CHARMM36 nucleic acids (MacKerell lab, Jul 2022 release)
  The standard force field for DNA/RNA all-atom simulations. Well-validated
  against experimental NMR and X-ray data for B-form duplex DNA.

Ion corrections:  CuFix NBFIX (Aksimentiev lab, UIUC)
  Improved Lennard-Jones cross-terms for Na+/Cl− and Mg²⁺ interactions with
  DNA phosphates. Substantially improves ion-condensation accuracy.

Solvent model:  GBIS implicit solvent (ionConcentration 0.15 M)
  DNA origami structures contain tens to hundreds of thousands of atoms.
  Explicit solvent (TIP3P water box) for a 10-helix bundle would require
  ~3 million water atoms — impractical on a workstation.
  GBIS (Generalised Born Implicit Solvent) treats solvent as a continuum
  dielectric, capturing electrostatic screening at a fraction of the cost.
  It is physically appropriate for structure validation and force-balance
  checks, though it underestimates hydrophobic effects.

Temperature:  310 K (37 °C, physiological)
Ensemble:     NVT (constant volume and temperature, Langevin thermostat)
Timestep:     1 fs (conservative for all-atom DNA without hydrogen mass
              repartitioning — ensures stability across glycosidic bonds)

-----------------------------------------------------------------------------
COMMON QUESTIONS
-----------------------------------------------------------------------------
Q: The simulation crashed immediately. What happened?
A: Most likely a bad initial geometry causing infinite forces. Check:
   • FATAL ERROR messages in output/{name}.log
   • "BOND LENGTH EXCEEDS TOLERANCE" — a crossover bond is too long. This
     can happen if the design has isolated helices with no relaxation.
   • Try reducing the timestep: in namd.conf, change "timestep 1.0" to
     "timestep 0.5" and add "rigidBonds none".

Q: launch.sh says "namd2: command not found" and apt install failed.
A: You may not be on Ubuntu/Debian. Install NAMD manually:
     https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=NAMD
   Then set: NAMD_CMD=/path/to/namd2  bash launch.sh

Q: How long will this take?
A: Depends on system size and hardware. Rough guide for the default 50 ps run:
   • Small design  (<5,000 atoms):    5–20 min on 8 CPU cores
   • Medium design (5–50k atoms):    30–120 min on 8 CPU cores
   • Large design  (>50k atoms):     Use GPU (NAMD3) or HPC cluster

Q: How do I run longer?
A: Edit namd.conf. Change:
     run 50000
   to e.g.:
     run 5000000    # 5 ns

Q: How do I restart a stopped simulation?
A: Add these lines to namd.conf (replace and comment the conflicting lines):
     binCoordinates   output/{name}.restart.coor
     binVelocities    output/{name}.restart.vel
     extendedSystem   output/{name}.restart.xsc
   And comment out:  minimize 2000 / reinitvels 310 / guesscoord on

Q: What does the total energy value mean? Is my structure stable?
A: For DNA origami in implicit solvent a total energy of roughly
   −1 to −3 kcal/mol per atom is typical at 310 K. If energy is
   large and positive and fluctuating wildly, the structure is unstable
   (usually a geometry or force-field issue). A gradually decreasing then
   stable total energy indicates the system has equilibrated.

Q: Can I run this on Windows?
A: Use WSL2 (Windows Subsystem for Linux) with Ubuntu 22.04. Install it from
   the Microsoft Store, then run launch.sh inside the WSL2 terminal.

Q: I want to add explicit solvent. How?
A: Remove the GBIS block from namd.conf (lines starting with "GBIS on") and
   add a water box using VMD's solvate plugin or OpenMM's Modeller. You will
   need to increase the box size, add water topology/parameters, and use PME
   electrostatics. This is a significant setup step — ask your AI assistant
   for a full walkthrough.

-----------------------------------------------------------------------------
CITATIONS (please cite if publishing)
-----------------------------------------------------------------------------
  CHARMM36 NA force field:
    Hart et al., J. Chem. Theory Comput. 8, 348–362 (2012)
    Foloppe & MacKerell, J. Comput. Chem. 21, 86–104 (2000)

  CuFix NBFIX ion corrections:
    Yoo & Aksimentiev, J. Phys. Chem. Lett. 3, 45–50 (2012)
    Yoo & Aksimentiev, J. Chem. Theory Comput. 12, 430–443 (2016)

  NAMD:
    Phillips et al., J. Chem. Phys. 153, 044130 (2020)

  NADOC:
    [cite your own work / lab preprint here]

=============================================================================
END OF CONTEXT — you may now ask me anything about this simulation package.
=============================================================================
"""
