# Overview — historical evidence

[Topic head](../../project_atomistic_propagator.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.


# Atomistic Propagator MVP — Loop Head & Handoff

**This file IS the loop head — read the HANDOFF section to resume; any session can pick up from there.**
Detailed design lives in the plan `~/.claude/plans/minimum-viable-atomistic-mellow-manatee.md`
(machine-local, not committed) + the full spec the user pasted. This head is the shared, tracked state.

> **★ NEXT-SESSION PRIORITY (user directive, 2026-07-20): build the BLADE frontend tab.** The science/
> compute is at a good checkpoint (unify + seeding verdict + equilibration benchmark + curved-6hb stable
> relax, all committed). The user wants an in-app BLADE simulation tab between CanDo and SNUPI (unified job
> manager, collapsible card, run/stop/delete). **The build spec is [[project_blade_frontend]] — start there.**
> The remaining SCIENCE task (deferred, not next): the full curved-6hb seed-NAMD showcase on RunPod.

## OVERARCHING GOAL (user spec, 2026-07-18) — the north star
A **machine-learned atomistic simulation engine for DNA origami**: generate FULL atomistic trajectories
(DNA + water + ions) substantially faster than conventional MD, **while explicitly reporting where its
predictions are trustworthy**. Learn a time-propagation operator on coordinates AND velocities. NAMD stays
the reference + fallback. **Must remain fully atomistic at all times** — NOT coarse-grained, NOT a relaxation
predictor, NOT a force-field replacement, NOT backmapping, NOT a static classifier, NOT next-structure-only.

**Two MVP capabilities (co-equal):**
1. **Atomistic time propagation** — train on canonical solvated duplexes; achieve STABLE short
   autoregressive trajectories faster than NAMD (conservative intervals OK; large speedup not required
   initially). Measure where error accumulates.
2. **Calibrated uncertainty** — train with a motif (e.g. DNA bulge) WITHHELD; on a duplex containing it,
   stay confident on ordinary duplex, raise uncertainty LOCALIZED to the bulge + its neighboring
   DNA/water/ions, don't flag the whole box, and emit a proposed region for local NAMD verification.
   (So the withheld bulge is BACK — as the uncertainty test motif, not a scientific target.)

**Long-term:** global ML propagator + uncertainty-triggered LOCAL conventional MD correction →
active-learning loop (propagate → detect uncertainty → local MD → learn → less future fallback).

**Development order (prioritize):** (1) auto NAMD system gen [DONE], (2) reference trajectory storage +
preprocessing [DONE: windows.py], (3) simple atomistic propagation baseline [DONE: baseline.py], (4) STABLE
AUTOREGRESSIVE ROLLOUT [next], (5) quantitative vs NAMD [speed benchmark in progress], (6) ensemble/
multi-signal uncertainty, (7) calibrate predicted vs measured error, (8) spatial uncertainty viz, (9) auto
local-MD region selection, (10) short NAMD verification windows, (11) local correction + motif learning.

**Validation must eventually reproduce MD STATISTICS** (bp/backbone geometry, bend/twist, solvent+ion
distributions, thermal fluctuations, relaxation, time-correlation, free energy of CVs) — distinguish
short-time coordinate / long-time ensemble / dynamical / observable-specific accuracy. A visually plausible
trajectory is NOT sufficient.

**Reconciliation with current work:** the immediate "predict next standard step faster than MD" question
below is exactly MVP-1's propagation kernel at conservative interval. "Full atomistic incl. water+ions" means
the DNA-only export was a shortcut — the real model propagates all atoms. Rollout stability (dev #4) + the
uncertainty track (dev #6-8) are the two big pieces NOT yet built.

## What it is (immediate framing)
A learned time-propagation operator that advances a fully-atomistic DNA–water–ion system. In-repo at
`backend/ml/propagator/`.

**IMMEDIATE QUESTION (MVP-1 kernel; conservative interval):**

> **Can we build a propagator that predicts the next STANDARD MD timestep (1–4 fs) FASTER than full MD?**

NOT large steps. The propagator does ordinary-size steps (4 fs is fine; MD runs 1–2 fs) but **skips the
per-atom force calculation**, instead mapping each atom's LOCAL ENVIRONMENT → a probability distribution of
where it lands next step. Win = COMPUTE per step, not step size.

Why this is the right framing: staying at a native/near-native step **sidesteps the aliasing wall** that
killed the 20 fs deterministic map (fast vibrations are RESOLVED at 4 fs, especially with rigidBonds/rigid
water already on) → next-step prediction is tractable. So the problem splits cleanly:
- **Accuracy half (easy-ish):** can a local model predict the next 4 fs step well? (skill should rise sharply
  vs the 20 fs case — the in-progress 4 fs run + subsample-down sweep quantifies this.)
- **Speed half (the CRUX):** can the learned local predictor be CHEAPER than a classical FF force eval?
  Classical MD force eval is already very cheap; ML force fields (MACE/Allegro/NequIP) typically run MD
  10–100× SLOWER than classical FF (their win is replacing ab-initio, not classical FF). The literature's
  per-step speed wins come from LARGER steps (rejected here) or expensive reference FFs. **Plausible
  real-win regimes to target/measure: (a) avoiding PME/global electrostatics on huge solvated ORIGAMI
  (10^5–10^6 atoms) with a local-cutoff GNN; (b) predicting Δx DIRECTLY (skip both force eval AND
  integration); (c) GPU-batched amortization.** Must be BENCHMARKED, not assumed — get real per-step
  wall-clock: learned local predictor vs the NAMD force+integrate cost, on this system and extrapolated.

The eventual scientific payoff is still duplex fluctuations → crossovers → origami, but the immediate,
testable deliverable is the accuracy+speed feasibility of a native-timestep learned integrator.

## Locked decisions / invariants (don't drift without sign-off)
- **ML code is in-repo** (`backend/ml/propagator/`); torch/e3nn stay an OPTIONAL dep — the core app +
  fast test suite must never import them.
- **Reference trajectories capture positions + velocities + forces** per frame.
- `capture_vel_force` defaults **False** everywhere; only `prepare_propagator_reference` turns it on.
  Ordinary MD jobs must stay byte-identical. **velDCD/forceDCD cadence == position dcdFreq** (frame
  alignment) — an invariant; never let them diverge.
- **Reference protocol = 2 fs, NO HMR, full topology** — HMR + rigidBonds/4 fs distort the microscopic
  dynamics the model learns.
- **Split assigned per system / motif family at generation** (`systems.py`), written into `system.json`,
  **never re-sampled downstream** — frames from one duplex must not straddle train/test.
- **Progression: short duplex → crossovers → origami.** Start on a short duplex (fluctuation MVP), then
  add crossovers (the actual scientific interest), then scale to 6hb/18hb origami. Prove each rung before
  the next.
- **MD substrate = explicit water + ions, run LOCALLY on the GPU** (user decision 2026-07-18). NAMD3 CUDA
  build; capture path already wired via `prepare_propagator_reference`. (Implicit GBIS was the alternative
  — rejected: artificial Langevin damping.)
- **Bulges DEPRIORITIZED** — rare in origami; `bulge_duplex()` stays an unimplemented stub. Not the driver.
- **First propagator has NO torch dep** — torch is not installed; start with a numpy inertial/ridge
  baseline to get a real "how well" number, add torch (equivariant net) only once the loop is proven.

## Current state (2026-07-18)
- **1a DONE + tested** — gated per-frame velocity/force output. Helper
  `namd_helpers.vel_force_dcd_block`; threaded through `_render_namd_conf`,
  `namd_solvate._render_solvated_fast_namd_conf`, `md_protocols._segment_conf` →
  `prepare_mgh_slow_release(capture_vel_force=…)`. New `PROPAGATOR_REFERENCE_PROTOCOL` +
  `prepare_propagator_reference()`. Manifest records `capture_vel_force` + `files.velocities/forces`
  globs. Test: `tests/test_propagator_vel_force_capture.py` (9). NOTE: only render/alignment-verified —
  a real short run must still confirm `.veldcd`/`.forcedcd` are written + MDAnalysis frame-matched.
- **1b DONE + tested** — motif generator `backend/ml/propagator/systems.py`: `canonical_duplex`,
  `nicked_duplex` (staple nick, stays single-scaffold), `mismatch_duplex` (one non-WC pair). Provenance
  metadata → `system.json`, deterministic ids, `default_catalog()`, `write_catalog()`. Every design gated
  through `assert_roundtrip_stable`. Test: `tests/test_propagator_systems.py` (8).
- **Bulge DEFERRED** — awaiting user's construction (see invariants).
- **1c / 1d / 1e / 1f NOT STARTED.**

## Key entry points (reuse, don't rebuild)
- Capture: `backend/core/md_protocols.py` → `prepare_propagator_reference`, `PROPAGATOR_REFERENCE_PROTOCOL`;
  `backend/core/namd_helpers.py` → `vel_force_dcd_block`.
- Generator: `backend/ml/propagator/systems.py`.
- Solvate (1 call → zip): `backend/core/namd_solvate.build_namd_solvated_package(design, …)`.
- Job/run: `backend/core/md_job.new_job`, `namd_runner.start_job`; outputs in `package_dir/output/`.
  Route multi-GB output to the Archive drive via the job `run_dir` (`routes_md._apply_run_dir`).
- Trajectory read: `backend/core/md_trajectory._build_md_nadoc_ctx` (MDAnalysis PSF+DCD;
  `with_atoms=True` gives heavy-atom index+elements); `dcd_fast` for raw reads.
- Analysis (1e reuses): `md_rmsf`, `md_metric_series` (twist/curvature/base-pairing per frame),
  `bp_analysis` (C1′–C1′), `shape_metrics`.
- Oracles: `tests/automation_harness.py` (`assert_roundtrip_stable`, `geometric_nucleotide_count`).
- Existing 6hb/18hb builders (for the later scale-up): `tests/conftest.py` `make_6hb_design`,
  `make_18hb_design` → both delegate to `headless_build.build_bundle`.
