---
name: Crossover CG parameterization pipeline
description: New pipeline to derive mrdna CG potentials for non-standard crossover motifs from isolated atomistic MD
type: project
originSessionId: 96f9c7f1-a2dc-42fd-ade8-1e21c39596f9
---
Motivation: mrdna's CG potentials are parameterized for standard crossovers. Extra thymines at a crossover change local mechanics, so stripping and re-injecting was wrong. Correct approach: parameterize CG from isolated 2-crossover atomistic MD.

**Why:** Global shape of full-origami CG was biased because equilibrium was found for the wrong structure (T-stripped).

**How to apply:** Use 2hb_xover_val.nadoc as the parameterization system. Do NOT use the same trajectories for validation.

## Pipeline location
`backend/parameterization/` — 8 modules + `runs/crossover_parameterization/run_pipeline.py`
(+ `check_progress.py`). **`runs/` is gitignored** (`.gitignore:112`), so the driver script and
every artifact are **local to this machine only** — they do not exist on the second computer.
The `runs/crossover_parameterization/` tree froze 2026-04-23 and **all trajectories were deleted**
(what survives: `.itp`/`.mdp`/`.top`/`.sh`/`.pdb`/`.png` + the per-variant JSON below).
`run_pipeline.py` has **zero inbound references** — no test, no justfile recipe, no backend call.
It is hand-run tooling; the backend modules it drives are separately exercised by
`tests/smoke/run.py:33-36`.

## Key design decisions
- Parameterization system: `Examples/2hb_xover_val.nadoc` — two antiparallel DX crossovers at bp 13-14 and 34-35, 20 bp inter-crossover measurement region, ~6 bp outer stubs
- NOT a dumbbell: paired crossovers needed to lock Holliday junction isoform
- Outer stubs: soft harmonic position restraints on terminal P atoms (k = 0.5, 1.0, 2.0 kcal/mol/Å² sweep). Open question: exact restraint model for origami-embedding
- Force field: CHARMM36-jul2022, TIP3P, NaCl ~150 mM. Selection is automatic —
  `backend/core/gromacs_package.py:84-90` orders candidates charmm36* before amber, and `_pick_ff`
  (`:163-175`, called from `md_setup.py:484`) **blocks** the amber fallbacks when proteins are
  present. amber99sb-ildn survives only as last-resort fallback (the very first 2026-04-21 test
  ran on it because charmm36 wasn't installed yet — that caveat is closed)
- First batch variants: T0 (baseline), T1, T2
- Sequences: random GC-balanced, seed=42

## Extraction status (as of 2026-04-30)

T0/nominal_c36: 200 ns production complete. T1/nominal: 185 ns. T2/nominal: 10 ns.

**CRITICAL FINDING:** The isolated 2hb system has τ ≈ 11 ns autocorrelation time.
ESS=9-90 for T0 at 200 ns. Need ~2 µs to reach ESS=100 via Method B.

Instead, use **Method A** (local junction extraction from 10hb bundle):
- Module: `backend/parameterization/local_crossover_extract.py` (426 L, 2026-07-13) — hand-run,
  **zero importers**. (A driver `extract_crossover_and_validate.py` was cited here; it does not
  exist on disk and is referenced nowhere. Do not chase it.)
- Key insight: bp-center (avg of both strand C1') at crossover bp position
  gives r0=19.03 Å — matches mrdna default 18.5 Å exactly.
- k_bond from 10hb interior crossovers (bp 1-40): context-dependent
  - 3-3 context: k ≈ 3-5 kJ/mol/Å² 
  - 2-2 context: k ≈ 0.1-0.9 kJ/mol/Å²
  - Pooled mean: 0.047 kJ/mol/Å²

**T1 r0 is a scaled estimate** (22.63 Å, scaled from T0 arm ratio). Replace with
3NN_opt2 bundle extraction when that run completes.

## Extracted parameter database

`backend/data/parameters/crossover_params.json` (2026-05-10) — T0 converged, T1 preliminary,
**T2 absent**. Live T0 record: `r0_ang 19.031`, `k_bond_kJ_mol_ang2 0.04695`
(`source_r0_k_bond: 10hb_local_junction_extraction`, 53 crossovers, pooled ESS 11247),
`hj_equilibrium_angle_deg -7.523`, `k_dihedral 0.4319` w/ `k_dihedral_converged: false`
(`source_hj_angle: 2hb_isolated_T0_200ns`). T1 = `2hb_isolated_T1_185ns`, `converged: false`,
all 6 DOF ESS 15-76.

**This is consumed in production on every mrDNA relax** — `CrossoverPotentialOverride.from_database("T0")`
at `backend/api/ws.py:1513` (one-shot `/ws/mrdna-relax`) and `backend/core/mrdna_runner.py:795`
(job path), both feeding `mrdna_model_from_nadoc_parameterized`. Nothing reads a per-run JSON
from `runs/`.

### Superseded numbers — do not resurrect

The **first** pipeline test (2026-04-21, T0, 10 ns, **amber99sb-ildn**, cubic box) produced
`r0=25.33 Å, k_bond=2.060 kJ/mol/Å², hj_angle=-82.5°, k_dihedral=1.588 kJ/mol/rad²`
(off-diagonal stretch-twist coupling 0.38). Those values are **dead** — wrong force field, 10 ns,
and contradicted by every field of the live DB above. They survive in no file. If you find them
quoted anywhere, it is a stale citation.

### Run artifacts + measured performance (2hb system)

- Per-variant output is **`<variant>/<condition>/params_c36.json`** (`_c36` = charmm36 re-run);
  `T0/nominal_c36/`, `T1/nominal/`, `T2/nominal/`. Plus `variant_meta.json` + `restraint_log.json`.
  There is **no `params.json` and no `convergence_report.json`** anywhere — `convergence.py`
  returns its report as an in-memory dict and never writes that filename.
- The staged `T0/nominal_c36/params_c36.json` on disk is still the **short** run
  (`converged: false`, 10001 frames, ESS 9-90); the 200 ns result went straight to the DB.
- **Triclinic box was the decisive perf fix:** 41,304 atoms in a 4.4×6.7×14.4 nm triclinic cell
  vs ~360k atoms cubic → **8.6× speedup**. Measured NVT 220 / NPT 231 / production 257 ns/day.
- GPU offload: `EM_GPU=-nb gpu`; `MD_GPU=-nb gpu -pme gpu -bonded gpu`. **PME on GPU is
  unsupported for the `steep` integrator**, hence the split.

### Traps already fixed (encoded in code — don't re-derive)

`param_extract.py`: paired-chain selection = longest length appearing ≥2× (`:272-279`, a 42-res
staple was beating the 35-res scaffolds); measurement bp range is **local 0-based** `_MEASUREMENT_BP_LO=8`
/ `_HI=26` (`:65-68`, global bp 15-33 minus 7); PCA axis anchored to frame 0 (`:159`) or per-frame
sign flips zero the q-means; `r0 = |q_mean[:3]|` Euclidean (`:449`), not `q_mean[0]` (axial ≈ 0 for
parallel helices). `md_setup.py`: POSRES_TERMINAL skips chains longer than the longest scaffold
(`max_residues` `:376`, `:394-400`, caller `:615/:630`) — otherwise restraints land **inside the
measurement region**. Also historical: restraint indices must be *local* to the moleculetype block,
and `grompp` needs `-r` for POSRES reference coords.

## First run command (pipeline test)
```bash
cd runs/crossover_parameterization
python run_pipeline.py --variants T0 --prod-ns 10 --no-sweep
# After runs complete:
python run_pipeline.py --extract-only
```

## Module roles
1. `crossover_extract.py` — load design, assign sequences, T-count variants → PDB
2. `md_setup.py` — GROMACS solvation, restraint ITP, MDP files, run.sh
3. `param_extract.py` — MDAnalysis 6-DOF covariance → stiffness matrix → mrdna scalars
4. `convergence.py` — block averaging, ESS, running-mean diagnostics; GATES parameter emission
5. `mrdna_inject.py` — monkey-patches SegmentModel to override crossover bond/dihedral per type
6. `validation_stub.py` — placeholder; requires independent atomistic reference
7. `local_crossover_extract.py` — Method A (10hb local junction); hand-run, no importers
8. `bundle_extract.py` — 10hb bundle line (see `project_bundle_stiffness_params`); hand-run.
   Carries its **own copy of `_ess`** (`:186`), duplicating `convergence.py`

## mrdna injection fragility
- Identifies crossover bonds by r0 ≈ 18.5 Å (±3.0 Å window)
- Identifies HJ dihedrals by angle proximity to hj_equilibrium_angle ± 0/180°
- Monkey-patches SegmentModel temporarily (NOT thread-safe)
- If mrdna crossover code changes, check segmentmodel.py lines 3314-3376
- Per-junction overrides (different T counts in same origami) not yet supported

## Critical rules
- NEVER use parameterization trajectories for validation
- ALWAYS run restraint sensitivity sweep before trusting parameters
- DO NOT extrapolate T=2 from T=1 and T=3 — simulate each independently
