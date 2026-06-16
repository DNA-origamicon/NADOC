# exp29 — Lessons Learned (MD prep-for-relaxation of strained designs)

Distilled from Cycles 1–5 (2026-06-11 → 06-12). Full numbers in `EXPERIMENT_LOG.md`.
These are the transferable lessons; read before the next prep/relaxation debugging.

## The headline reframe

exp29 started to fix a "forced-ligation + 2xT strain melts the structure during ENM
release." **Five cycles later, the strain sources turned out NOT to be the cause.**
A non-strained control (same 2-helix design, forced ligation + 2xT removed) melted at
true-zero restraint to **40.5%** — identical to the strained design's **40.0%**. The
k=0 melt was driven by, in order: electrostatic crowding (~half) + small-bundle
instability (the 2-helix proxy, ~the other half), with the forced ligation/2xT
contributing **~nothing** to the endpoint.

## Lessons (ranked by how much time each would have saved)

1. **Run the feature-removed CONTROL first, not last.** The entire experiment was
   premised on "strain sources X cause melt Y." One control run (X removed) falsified
   that premise — and it was run in Cycle 5, not Cycle 0. **When investigating
   "design feature X causes problem Y," the X-removed control is the cheapest, most
   decisive experiment. Run it before building any fix.**

2. **Localize before you fix — ask WHERE it breaks.** The single highest-value
   diagnostic was free: compute *which* base pairs grow when restraint releases
   (`scripts/localize_swelling.py`, from existing trajectories, ~10 min). Pearson
   r(distance-to-junction, growth) ≈ 0 at onset and **+0.18** at full collapse (the
   junction broke *least*). That one number killed the knot/catenane hypothesis AND
   the "local junction strain" fix the prior handoff had assumed — redirecting the
   whole effort. **A "melt" has a spatial signature; read it before theorizing.**

3. **Don't tune the restraint schedule to fix an unrestrained-equilibrium melt.**
   Cycles 1–3 (longer minimization, finer k-ladder, subdivided final removal) never
   cured it; subdividing the final k=0.01→0 removal made it **worse**. The melt is
   governed by *time spent at low restraint*, not step size — the structure relaxes
   toward its (melted) unrestrained equilibrium, and a gentler path just gives it more
   time to get there. **If the endpoint is path-independent, stop tuning the path.**

4. **A fast proxy's ABSOLUTE numbers lie; only its SHAPE transfers — quantify the
   gap.** The 2-helix proxy melted far harder than the real 6-helix design (k=0: 40%
   vs 56%) because 2 helices lack cooperative base-pairing. The *shape* (monotonic
   melt on release) was real and transferable; the *severity* was a proxy artifact.
   **Confirm absolute pass/fail on the real structure before declaring anything.**

5. **Pre-register the prediction and decision rule before reading results.** Cycles 2
   and 3 wrote numeric predictions + "if k=0 C1' ≥X do A, ≤Y do B" *before* the run.
   This made Model A vs B crisp and prevented post-hoc rationalization. Keep doing it.

6. **Check ionic strength early for any DNA-MD stability problem.** The MGH default
   was `ion_conc_mM = 0` (only neutralizing counterions + 12.5 mM Mg). Adding ~50 mM
   NaCl roughly **halved** the melt (k=0 20→40) and saturated by 50 mM. This is a
   one-line config, not a code fix, and it was the first lever in four cycles to move
   the endpoint. **Salt/screening is cheap and high-yield — rule it in or out first.**

7. **Relieve inter-helix crowding by SCREENING, not by geometry.** Pre-expanding the
   bundle (+10% spacing) improved the *restrained* structure (k=0.5 C1' 97.6, best of
   any arm) but **worsened the release** — pushing helices apart stretches the
   crossovers, storing tension that snaps back as restraint weakens. Salt relieves the
   same crowding with no mechanical penalty. **Two ways to relieve a pressure; pick
   the one that doesn't add a competing strain.**

8. **Geometry-only build minimizers are a latent defect — but verify they're the
   actual culprit before fixing them.** `_minimize_{1,2,3}_extra_base`
   (`atomistic_minimisers.py`) optimize *ideal bond geometry*, never the CHARMM
   forcefield, and are blind to clashes outside a hand-picked `repel_pos`. Real issue,
   worth fixing eventually — but localization (lesson 2) proved it is **not** where
   this melt nucleates, so rewriting it would not have helped. **A plausible code
   smell is not evidence it causes the symptom in front of you.**

## Process / harness improvements made (keep)

- `run_cycle.py` parametrizes the real production protocol: `--ion-conc-mM`,
  `--expand-scale` (geometric lateral expansion, topology-preserving, mirrors the
  frontend 'Q'), `--k-ladder` with `_ensure_enm_files_for_ladder` (auto-generates
  intermediate-k ENM files), `--threads` default **16** (Ryzen 9950X, +p16
  +setcpuaffinity).
- `scripts/localize_swelling.py` — the spatial-signature diagnostic; reusable on any
  job's trajectory.
- The harness IS the real `prepare_mgh_slow_release` + `run_health_check`, only with
  shortened stages — so findings transfer to production by lengthening stages, not
  re-plumbing.

## Settled, cheap production wins (independent of the open k=0 question)

- `ion_conc_mM` default 0 → **~50 mM** (recovers the electrostatic half of the melt;
  50 mM also more physically defensible than 150–300 — less Mg–Na competition).
- `minimize_steps` 4800 → **24000** (Cycle 1; saturates by 24k, cheap).
- ENM range 0.5→0.01 is robust and protective-in-time; declash auto-on; **no**
  pre-expansion.

## Still open (handed to next session — see `NEXT_SESSION.md`)

Whether the structure survives the **full-length** (4.8 ns/stage) Aksimentiev
production protocol on the real 6hb design — and whether "true k=0" is even the
production target, or a low-k handoff to long MD/CG is. The harness (0.3 ns/stage)
cannot answer this: it over-reads via small-bundle + short-time, while Cycle 3 warns
that *longer* holds at low k can melt *more*. Only the real protocol resolves it.
