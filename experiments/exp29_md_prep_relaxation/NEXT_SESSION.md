# exp29 → NEXT SESSION: reproduce the Aksimentiev production simulation

Goal: take the strained 6hb_2xT design all the way through the **full-length
Aksimentiev-tutorial production protocol** and determine whether it survives an
unrestrained (or low-k handoff) 300 K NPT production run — i.e. reach the same
production simulation the Aksimentiev guide describes. exp29 (the fast 0.3 ns/stage
harness) has exhausted what it can answer; this is the real-length confirmation.

Read first: `HANDOFF.md` "Current state" (Cycle 5), `LESSONS_LEARNED.md`,
`EXPERIMENT_LOG.md` Cycle 5.

## What "the Aksimentiev production simulation" is, exactly (already coded)

The target is the **`mgh_slow_release` protocol** (`backend/core/md_protocols.py`,
`mgh_slow_release_segments` + `prepare_mgh_slow_release`), the "Aksimentiev tutorial
shape" (Maffeo & Aksimentiev, *NAR* 48(9):5135, 2020;
`gitlab.engr.illinois.edu/tbgl/tutorials/multi-resolution-dna-nanostructures`):

- **Forcefield / solvent:** CHARMM36 + **CUFIX** ion corrections
  (`toppar_water_ions_cufix.str`), TIP3P water, **Mg-hexahydrate** ions, PME, 10 Å
  cutoff, NPT (Langevin thermostat γ=5, Nosé-Hoover/Langevin piston).
- **Minimization:** ENM k=0.5 + ions.
- **NPT ladder, 300 K, ENM base-ring restraints scaled down:**
  **k=0.5 → 0.1 → 0.01 → k=0**, **4.8 ns each** (2.4M steps @ 2 fs), health check at
  10 / 50 / 100 % of each stage. The final **k=0** ("MGHH_only") stage is the
  unrestrained production handoff.

exp29 ran THIS protocol but at **0.3 ns/stage** (16× short) to iterate fast. The only
thing standing between us and the real production sim is stage length + the settled
config wins + running it on the real design.

## The blocking decision (resolve BEFORE the long run — it's a domain call)

**Does production hand off at true k=0 (fully unrestrained) or at low-but-nonzero k?**
- 6hb holds **k=0.01 at 78% C1'** and only craters at *exactly* zero restraint.
- If the real pipeline continues into long production MD (or a CG handoff) at k=0.01,
  the "true-k=0 melt" exp29 chased is **moot** and we are essentially already there.
- If production genuinely requires unrestrained NPT, the k=0 stability is real and
  must be validated at full length.
This determines whether there is anything left to fix. Ask the user.

## The run to do (config = all exp29 wins folded in)

On **6hb_2xT** (the real design, not the 2hb proxy):

| setting | value | why |
|---|---|---|
| protocol | full `mgh_slow_release` (4.8 ns/stage, real `mgh_slow_release_segments`) | the actual Aksimentiev shape — NOT the 0.3 ns harness |
| `ion_conc_mM` | **50** | recovers the electrostatic ~half of the melt (Cycle 4/4c) |
| `minimize_steps` | **24000** | Cycle 1 win, saturates by 24k |
| declash | auto-on (6hb has ss bases) | required for the 2xT/forced-ligation bases |
| expansion | **none** | Cycle 4b: pre-expansion hurts the release |
| threads | **+p16** | Ryzen 9950X, set in harness default |

Two ways to launch:
1. **Via the real job system** (`prepare_mgh_slow_release` with `protocol=mgh_slow_release`,
   `ion_conc_mM=50`, `minimize_steps=24000`) + `namd_runner` — this is the production
   path and what should ultimately be defaulted.
2. **Via the harness** with `--stage-ns 4.8 --minimize-steps 24000 --ion-conc-mM 50`
   (slower but same machinery, gives the per-stage C1'/WC curve directly).
Cost: ~19 ns total over 4 stages at ~24 ns/day on 6hb ≈ **~19 h (overnight)**.

## The key scientific uncertainty this run resolves

Two findings pull opposite ways at full length:
- **For survival:** salt (+screening) + 6-helix cooperativity already lifted k=0 from
  20 (2hb,0-salt) → 56 (6hb,50 mM) in the *short* harness; full 4.8 ns gives the
  structure time to re-anchor at each k (the harness denies it that).
- **Against survival:** Cycle 3 showed *longer* time at low restraint melts *more*
  (the structure drifts toward its unrestrained equilibrium). A 4.8 ns k=0 stage is
  16× the harness hold.

Whichever wins at full length is the answer. **Decision rule to pre-register:**
- 6hb full-protocol **k=0 C1' ≥ 90 (and WC gate per protocol)** → production sim
  reproduced; fold `ion_conc_mM=50` + `minimize_steps=24000` into the
  `prepare_mgh_slow_release` / `mgh_slow_release_segments` defaults and close exp29.
- **k=0 C1' 56–89** → real-length helps but doesn't fully hold; decide between a
  low-k (k=0.01) production handoff vs a build-side fix.
- **k=0 C1' ≤ ~56** (no better than the short harness) → true-zero is genuinely
  unstable for this design → hand off production at k=0.01, OR pursue the build-side
  forcefield-aware junction relaxation (the geometry-only `_minimize_*_extra_base`
  defect — lesson 8; but note localization says it is not the *nucleus*, so treat as
  a long shot).

## Secondary levers to consider (only if the above is borderline)

- **Throughput:** the declash path runs the **soft integrator (1 fs)** at *every*
  stage, halving ns/day. The soft integrator is only needed early (to relax ss
  contacts without RATTLE crashes). Investigate switching to **rigidBonds + 2 fs**
  after the declash minimization — potential ~2× speedup on the long production run.
- **Ionic physicality:** 50 mM Na + 12.5 mM Mg is defensible for a prep step but not a
  canonical folding buffer. If staying buffer-faithful matters, test **higher Mg
  (25–40 mM), no/low monovalent** as an alternative screening route (divalent is the
  real origami counterion). Compare k=0 vs the 50 mM Na result.
- **Confirm on a second real design** before defaulting the config repo-wide.

## Files / entrypoints

- Protocol: `backend/core/md_protocols.py` — `mgh_slow_release_segments`,
  `prepare_mgh_slow_release` (`ion_conc_mM`, `minimize_steps`, `protocol`).
- Runner: `backend/core/namd_runner.py`; REST: `backend/api/routes_md.py`
  (`CreateJobRequest.ion_conc_mM`).
- Harness: `experiments/exp29_md_prep_relaxation/run_cycle.py` (`--stage-ns`,
  `--ion-conc-mM`, `--threads`, `--expand-scale`).
- Diagnostic: `scripts/localize_swelling.py`.
- Designs: `workspace/6hb_2xT.nadoc` (real), `workspace/2hb_2xT.nadoc` (proxy),
  `workspace/2hb_control.nadoc` (non-strained control).
- Prior 6hb production jobs: `workspace/md_jobs/03302b74a7fa` (declash, died k=0.1),
  `b980e1f52381` (no declash, died k=0.5).
