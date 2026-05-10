# Periodic MD Next Milestone: Locked-Z Restraint Ramp

## Purpose

This plan defines the next Periodic MD milestone for NADOC: make the
21 bp honeycomb periodic-cell workflow robust enough that `B_tube.nadoc`
can run through restrained NPT, locked-Z relaxation, restraint ramp-down,
and short unrestrained production with automated health reports.

The goal is not to prove that periodic MD replaces full-origami MD. The
near-term goal is a reliable local-repeat validation workflow:

- explicit solvent and ions,
- axial periodic boundary conditions across one 21 bp honeycomb repeat,
- exact locked Z repeat length,
- NPT-derived lateral X/Y dimensions,
- stable energies and temperature,
- no immediate base-pair collapse after restraint release,
- clear pass/fail artifacts for future tuning.

## Current Context

Primary memory file:

- `memory/periodic_md.md`

Primary implementation files:

- `backend/core/periodic_cell.py`
- `backend/core/namd_solvate.py`
- `experiments/exp23_periodic_cell_benchmark/`

Current test design:

- `workspace/B_tube.nadoc`
- Honeycomb lattice, 24 helices, 305 bp.
- Periodic cell range in current benchmark: `[21, 42)`.
- Exact one-period Z: `21 * 0.334 nm = 7.014 nm = 70.140 Å`.

Current hardware used for local benchmarks:

- CPU: AMD Ryzen 9 9950X, 32 logical CPUs.
- GPU: NVIDIA GeForce RTX 2080 SUPER, 8 GB.
- NAMD: `/home/jojo/Applications/NAMD_3.0.2/namd3`, CUDA build.
- Standard CUDA is preferred for now. A 5,000-step test measured about
  `22.66 ns/day` standard CUDA versus `15.40 ns/day` GPUresident.

## Known Good And Bad Protocols

Known good so far:

- Restrained NPT box discovery runs successfully on `B_tube.nadoc`.
- Fixed-NVT continuation at the NPT final box is energy-stable.
- Locked-Z fixed NVT at exact `Z = 70.140 Å` can run when the handoff performs
  locked-cell minimization before dynamics.
- A 5,000-step locked restrained smoke run completed with finite energies,
  fixed `Z = 70.140 Å`, and current C1' pairing monitor reported `95.8%`
  paired in the single DCD frame.

Known bad so far:

- Directly running dynamics after changing the NPT-compressed Z
  (`~67.235 Å`) back to exact `70.140 Å` produced NAMD sentinel energies
  (`-99999999999.9999`) within about 10 steps.
- Carrying NPT velocities into the restored-Z cell did not fix the issue.
- Preserving the NPT origin is necessary for frame consistency but did not by
  itself fix the sentinel-energy failure.
- Starting from the original PDB in the locked cell can blow up immediately,
  confirming that restrained relaxation is not optional.
- The unrestrained 5,000-step locked smoke was energy-stable but the current
  C1' pairing monitor reported `47.8%` paired in one DCD frame. This may partly
  reflect periodic wrapping/monitor fragility, but it is not acceptable as a
  production-ready pass.
- Brute-force GPUresident pairlist expansion is not viable on the current GPU:
  one large-pairlist attempt hit a CUDA shared-memory patch limit and another
  hit out-of-memory.

## Working Protocol Baseline

The current generated package should be organized as separate phases:

1. `equilibrate_npt.conf`

   Restrained NPT box discovery. DNA heavy atoms restrained through
   `{name}_restraints.pdb`; water and ions are unrestrained.

2. `relax_locked_nvt.template.conf`

   Fixed-cell locked-Z relaxation. X/Y and origin are patched from the stable
   NPT XST tail. Z is restored to exact `70.140 Å`. DNA heavy-atom restraints
   remain on.

3. `production_locked_nvt.template.conf`

   Fixed-cell locked-Z unrestrained production. This should restart from the
   locked relaxation phase, not directly from NPT.

Required handoff behavior:

- Patch X/Y from the stable NPT XST tail, not a single final frame.
- Preserve the averaged XST origin from NPT; do not recompute origin as half
  the patched box.
- Do not include the NPT `.xsc` in locked-Z production, because it can override
  the patched cell.
- Use `binCoordinates` but do not reuse NPT velocities after a Z reset.
- Minimize in the locked cell, then `reinitvels 310`.

## Milestone Definition

The next milestone is complete when `B_tube.nadoc` can run automatically through:

1. restrained NPT,
2. locked-Z restrained relaxation,
3. restraint ramp-down,
4. short unrestrained locked-Z production,
5. automated health report,

and the report clearly states pass/fail status with links to logs, XST, DCD,
health plots, and summary JSON.

Target run lengths for the milestone:

- NPT discovery: keep current default `250,000` steps (`500 ps`) unless test
  cost becomes excessive.
- Locked restrained relaxation: start at `250,000` steps (`500 ps`), but allow
  shorter smoke settings from the experiment runner.
- Ramp stages: initially `50,000` steps (`100 ps`) per restraint level for a
  practical local test.
- Final unrestrained production: initially `50,000-250,000` steps
  (`100-500 ps`) for validation, not scientific production.

## Proposed Restraint Ramp

Start with DNA heavy-atom positional restraints using the existing B-factor
constraint PDB. Candidate schedule:

| Stage | Restart From | Constraint Scaling | Steps | Notes |
| --- | --- | ---: | ---: | --- |
| NPT | generated PDB | `1.0` | `250,000` | Lateral box discovery |
| locked_relax | NPT restart coordinates | `1.0` | `250,000` | Exact Z, fixed cell |
| ramp_0 | locked_relax | `0.5` | `50,000` | Start release |
| ramp_1 | ramp_0 | `0.25` | `50,000` | Intermediate |
| ramp_2 | ramp_1 | `0.10` | `50,000` | Soft restraint |
| ramp_3 | ramp_2 | `0.03` | `50,000` | Almost free |
| production | ramp_3 | off | `50,000-250,000` | Validation production |

Each stage should use a separate config and output prefix. Keep files explicit
instead of relying on a long monolithic NAMD config; this makes failures easier
to reproduce and lets the frontend represent phases cleanly.

If this schedule still loses base pairing, try a gentler schedule:

| Stage | Constraint Scaling | Steps |
| --- | ---: | ---: |
| locked_relax | `1.0` | `250,000` |
| ramp_0 | `0.75` | `100,000` |
| ramp_1 | `0.50` | `100,000` |
| ramp_2 | `0.30` | `100,000` |
| ramp_3 | `0.20` | `100,000` |
| ramp_4 | `0.10` | `100,000` |
| ramp_5 | `0.05` | `100,000` |
| ramp_6 | `0.02` | `100,000` |
| production | off | `100,000-250,000` |

If the gentle schedule still fails, test whether the exact Z constraint is too
stressed by running a small axial-length sweep around the designed value:

- `Z = 69.0 Å`
- `Z = 69.5 Å`
- `Z = 70.140 Å`
- `Z = 70.5 Å`

Record axial stress/pressure, base-pair retention, and wrap-bond geometry. If a
nearby Z is stable and exact Z is not, that is design feedback rather than just
a simulation bug.

## Health Metrics And Acceptance Criteria

The milestone needs automated checks that are strict enough to catch obvious
failure but not so strict that normal DNA breathing is treated as failure.

Required checks:

- NAMD exit code is zero for every phase.
- No `FATAL ERROR`, `Atoms moving too fast`, `Low global CUDA exclusion count`
  fatal abort, or CUDA out-of-memory in production logs.
- No NAMD sentinel energies: `-99999999999.9999`.
- Temperature remains bounded after equilibration:
  recommended initial bound `250 K <= TEMP <= 370 K`.
- Locked phases have fixed volume and exact Z:
  `abs(Z - 70.140 Å) <= 0.001 Å`.
- X/Y are patched from the NPT tail and remain fixed in locked phases.
- Base-pair retention does not collapse during ramp or final validation:
  initial target `>= 85%` paired for restrained/ramp stages and `>= 75%`
  paired for short unrestrained validation.
- Wrap-bond minimum-image distances remain chemically plausible and do not
  produce discontinuity spikes across frames.
- Water density and total volume are recorded for every phase.
- Pressure is reported but not treated as a hard pass/fail in locked-Z NVT.
  With exact Z imposed, axial stress is diagnostic output.

Monitor caveat:

The current base-pairing monitor uses C1' distances and can be confused by
periodic wrapping and sparse DCD output. Before using it as a hard gate, improve
it to unwrap or minimum-image the periodic cell consistently and write DCD more
frequently during ramp tests.

Recommended ramp DCD settings:

- `dcdFreq 1000` for short tuning runs.
- `xstFreq 500` or `1000` during tuning.
- `outputEnergies 500`.

## Implementation Tasks

### 1. Package generation

- Generate `relax_locked_nvt.template.conf`.
- Generate ramp templates or concrete ramp configs, e.g.
  `ramp_locked_nvt_00.conf`, `ramp_locked_nvt_01.conf`, etc.
- Ensure each ramp stage restarts from the previous stage's `.restart.coor`.
- Prefer `binCoordinates` plus `minimize` plus `reinitvels` at the first
  locked-Z stage after NPT.
- For later ramp stages, test whether `binVelocities` from the prior locked
  stage is safe. If instability appears, use fresh velocities at stage starts.
- Keep `namd.conf` as a compatibility alias only; do not rely on it for the
  phase protocol.
- Ensure ZIP extraction preserves executable bits for scripts.

### 2. Lock script

- Keep `scripts/lock_box_from_xst.py` as the source of truth for patching X/Y,
  origin, and exact Z.
- Add optional `--restart-prefix` or `--stage-name` support only if it reduces
  duplicated template text.
- Emit a small JSON sidecar recording:
  - source XST,
  - tail frame count,
  - averaged X/Y/Z source values,
  - patched exact Z,
  - averaged origin,
  - timestamp,
  - command-line arguments.

### 3. Experiment runner

- Add a `--smoke` mode that shortens every phase for quick iteration.
- Add a `--ramp-schedule` argument that accepts a simple comma list such as
  `1.0:50000,0.5:50000,0.25:50000,0.1:50000,0.03:50000,0:100000`.
- Save all logs under one timestamped run directory to avoid overwriting
  known-good artifacts.
- Write `periodic_md_summary.json` with:
  - hardware,
  - NAMD version,
  - config filenames,
  - return codes,
  - final box dimensions,
  - energy/temp/pressure stats,
  - base-pair stats,
  - pass/fail flags.

### 4. Health monitor

- Fix base-pair analysis for periodic wrapping or explicitly document that
  pairing is approximate until unwrapping is implemented.
- Accept an explicit DCD path and output prefix for every phase.
- Parse XST files directly for locked-Z and volume checks.
- Flag sentinel energies as fatal.
- Emit both PNG and JSON outputs.
- Print a concise terminal summary suitable for copying into memory.

### 5. Frontend integration later

Do this after the backend protocol passes the B_tube milestone:

- Show phase list and status in the Periodic MD panel.
- Distinguish `NPT`, `locked relaxation`, `ramp`, and `production`.
- Surface warnings for high axial stress, base-pair loss, and sentinel energies.
- Allow users to download or inspect `periodic_md_summary.json`.

## Test Matrix

Minimum matrix for the milestone:

| Test | Purpose | Expected Result |
| --- | --- | --- |
| standard smoke | End-to-end protocol with shortened phases | Pass |
| exact-Z no minimization | Regression check for known bad handoff | Fail with sentinel or instability |
| exact-Z locked minimization | Confirms handoff fix | Pass |
| restrained locked 5k | Confirms base-pair retention under restraints | Pass |
| unrestrained 5k after ramp | Confirms ramp effectiveness | Pass or informative fail |
| GPUresident benchmark | Performance curiosity only | Must not block milestone |

Optional matrix:

| Test | Purpose |
| --- | --- |
| gentle ramp schedule | Determine if slower release fixes pairing |
| Z sweep | Determine whether exact repeat length is intrinsically stressed |
| multi-period cell, 2x or 3x | Check whether one-period constraints are too artificial |

## Open Questions

- Should the ramp use positional restraints on all DNA heavy atoms, backbone
  only, base atoms only, or helix-axis restraints?
- Is exact `0.334 nm/bp` the right axial repeat length for the atomistic model,
  or should it come from lattice geometry, sequence, salt, or user preference?
- What pressure/stress thresholds are meaningful for locked-Z NVT?
- Should water/ions be regenerated after X/Y is discovered, or is continuing
  from the NPT restart preferable?
- Should NADOC support a pressure-controlled ensemble with X/Y barostat and
  locked Z in another engine, or is fixed-cell NVT the product path?
- What base-pair metric should become authoritative: C1' distance, hydrogen
  bond geometry, base-plane pairing, or a DNA-specific external analyzer?

## Suggested Next Session Prompt

Use this prompt for an independent continuation:

> Read `memory/periodic_md.md` and
> `docs/periodic_md_restraint_ramp_plan.md`. Implement the B_tube Periodic MD
> restraint-ramp milestone. Start by adding generated ramp configs and a smoke
> runner under `experiments/exp23_periodic_cell_benchmark/`. Preserve exact
> locked Z, preserve XST origin, avoid NPT velocity reuse after Z reset, and
> produce a JSON health summary plus PNG plots. Run the smoke schedule on
> `workspace/B_tube.nadoc` and report pass/fail issues.

