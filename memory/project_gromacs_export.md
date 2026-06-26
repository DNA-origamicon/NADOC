---
name: GROMACS export package — status and implementation notes
description: GROMACS simulation package builder for NADOC — status, architecture, known issues, and future plans
type: project
originSessionId: b3c93bcb-73fe-41f0-a4d4-78340b15ad26
---
## Status: implemented and tested (2026-04-15); background job UI added (2026-04-16)

### Files
- `backend/core/gromacs_package.py` — package builder (pdb2gmx server-side, bundles FF)
- `backend/api/crud.py` — endpoints (see §API below)
- `scripts/test_gromacs_6hb_bend.py` — end-to-end test (420bp 6HB, 180° bend)
- `scripts/check_gromacs_bonds.py` — verifies itp bonds match expected model topology

### Architecture
Export phase (server-side): _build_gromacs_input_pdb (reorders atoms 5'→3' per chain) → pdb2gmx → _fix_itp_case → editconf → bundle into ZIP
User phase: launch.sh installs GROMACS if absent, runs grompp+mdrun for EM then NVT

### API endpoints
- `GET  /design/export/gromacs-complete` — synchronous export (kept for testing)
- `GET  /design/export/gromacs-probe`    — GROMACS availability + FF probe
- `POST /design/export/gromacs-start`    — start background job; returns {job_id}
- `GET  /design/export/gromacs-status/{job_id}` — poll {status, error, name}
- `GET  /design/export/gromacs-result/{job_id}` — fetch ZIP; deletes job from store

### Background job store (crud.py)
`_gromacs_jobs: dict[str, dict]` + `_gromacs_jobs_lock` at module level.
Start endpoint deep-copies the design snapshot, spawns a daemon thread, returns UUID.
Result endpoint deletes the job entry after streaming to free memory.

### Frontend toast (non-blocking, upper right)
- `#gromacs-job-toast` at `top: 44px; right: 12px` — same position as `#op-progress`
- Running: blue indeterminate sweep bar, "Building package…"
- Done: bar fills green, "Package ready" + green "↓ Download ZIP" button
- Error: bar fills red, error message shown; × dismiss always available
- Re-clicking export while running is a no-op (no duplicate jobs)
- Download auto-dismisses toast after 1.2 s

### Extra-base crossover fix (2026-04-15)
pdb2gmx ignores CONECT/LINK records and bonds residues by file order within each chain.
Standard export_pdb puts extra-base residues at chain end → pdb2gmx creates wrong direct bonds across junctions.
Fix: `_build_gromacs_input_pdb()` traverses backbone O3'→P bond graph to output atoms in correct 5'→3' order.
Extra-base residues now appear between their src and dst residues in the PDB → pdb2gmx generates correct bonds.

### ITP case mismatch fix (2026-04-16)
Large designs (>26 strands) get lowercase chain IDs (a-z) via `_chain_char` in pdb_export.py.
Some GROMACS versions uppercase the molecule-type name in topol.top while writing ITP files with lowercase letters (or vice versa) → fatal "include file not found" on case-sensitive Linux.
Fix: `_fix_itp_case(tmpdir)` — after pdb2gmx, parse topol.top for `#include "*.itp"` paths, find each file case-insensitively, rename to match the include path exactly.
Called in `build_gromacs_package` between steps 2 (pdb2gmx) and 3 (editconf).

### ZIP structure
`{name}_gromacs/conf.gro, topol.top, topol_DNA_chain_*.itp, posre_DNA_chain_*.itp, amber99sb-ildn.ff/, em.mdp, nvt.mdp, launch.sh, scripts/monitor.py, README.txt, AI_ASSISTANT_PROMPT.txt`

### Force field
- Selected at runtime from installed GROMACS top/
- Preference: charmm36-jul2022 → charmm36m → charmm36 → amber99sb-ildn → amber99sb
- charmm27 EXCLUDED: lacks dna.r2b, so pdb2gmx applies protein termini (NH3+) to DNA chains
- Currently using: amber99sb-ildn (apt GROMACS 2023.3 package)

### Critical PDB preprocessing steps
1. adapt_pdb_for_ff: OP1→O1P, OP2→O2P for AMBER FFs (redundant but safe; dna.arn also handles it)
2. strip_5prime_phosphate: remove P/O1P/O2P from first residue of each chain — AMBER DA5/DT5 termini are 5'-OH only, no phosphate

### Physics settings (validated against AMBER OL15 HJ protocol)
- integrator = sd (Langevin, more stable than md for charged DNA)
- dt = 0.002 fs with h-bond constraints
- vdw-modifier = force-switch, rvdw-switch=1.0, rvdw=1.2
- coulombtype = reaction-field, epsilon-rf=80 (approximates dielectric screening, no water needed)
- tcoupl built into sd integrator, tau-t=10.0, ref-t=310

### Test results (420bp HC 6HB, 180° bend bp 100-300)
- 160,008 atoms after pdb2gmx (12 chains × ~420 residues × ~32 atoms incl. H)
- EM converged: Steepest Descents Fmax < 1000 in 949 steps
- NVT 1000 steps: completed without crash
- Etot: -2,527,101 → -2,452,078 kJ/mol (increase expected: gen_vel adds kinetic energy)

### Known limitations (v1 — simplest version)
1. No explicit water or counterions — reaction-field only; energy is unstable for long runs
2. Crossover bonds NOT in topology — each strand is independent molecule; helices drift apart without restraints
3. Uses 5'-OH termini (no phosphate on first residue) — consistent with AMBER convention

**Why:** User explicitly requested "simplest version"; future version will add ions+water via tleap with AMBER OL15.

### Future version: AMBER OL15 path
- Force field: ff99bsc0 + chiOL4 + ezOL1 + bOL1 (validated by HJ project on other machine)
- Toolchain: AmberTools tleap → parmed/acpype → GROMACS format
- Water: TIP3P, ions: Mg2+ + Cl- (~15 mM MgCl2)
- MDP: PME electrostatics instead of reaction-field, NPT barostat for equilibration
- Reference: `gromacs/production_ol15/production_ol15.mdp` on other machine (HJ project)
