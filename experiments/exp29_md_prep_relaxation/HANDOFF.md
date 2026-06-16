# exp29 HANDOFF — fresh-session context for the next prep cycle

Paste/point a fresh session at this file. It is the *minimum* context to run the
next cycle without re-reading the whole codebase. Read `EXPERIMENT_LOG.md` next
to it for the full diagnosis and hypothesis order.

## One-paragraph problem statement

Strained DNA-origami designs (forced ligation + inserted single-stranded "2xT"
bases) fail the relaxation health gate. The failure is **not** minimisation — it
is the **ENM restraint step-down** (k=0.5 → 0.1): the strain stored at the
junctions releases the instant the base-ring network loosens and ~13% of marginal
WC pairs pop open (WC 88% → 75% on the first health frame at k=0.1). We are
searching for a *prep recipe* — minimisation length, per-k equilibration time,
and k-ladder gentleness — that lets the structure survive the release. The 6hb
production design is slow; we iterate on `workspace/2hb_2xT.nadoc` (same two
strain sources, ~31k atoms, seconds to prep).

## How to run a cycle

```bash
cd /home/jojo/Work/NADOC
export PATH="$HOME/.local/bin:$PATH"
# one cycle = one recipe; runs in background, ~few min/stage on 2hb
nohup python3 experiments/exp29_md_prep_relaxation/run_cycle.py \
  --label <short_name> [--minimize-steps N] [--stage-ns 0.3] \
  [--equil-ns 0.0] [--k-ladder 0.5,0.1,0.01,0] [--notes "..."] \
  > experiments/exp29_md_prep_relaxation/runs/<short_name>.console.log 2>&1 &
```

Watch it: `tail -f experiments/exp29_md_prep_relaxation/runs/<short_name>.console.log`
Each stage prints `C1'=..% WC=..% passed=..`. The harness runs the **whole**
ladder (does not stop on a failed gate) so you see the full degradation curve.

## Where results land

- `RESULTS.tsv` — one row per cycle (compact cross-cycle comparison).
- `runs/<label>/cycle_result.json` — full per-stage numbers + timings.
- `runs/<label>/package/.../{seg}.log` + `output/{seg}.dcd` — raw NAMD.

## What to do each cycle

1. Pick the next lever from `EXPERIMENT_LOG.md` § Hypotheses (cheapest unfalsified
   first). One variable per cycle.
2. Run it. Read the per-stage C1'/WC curve.
3. **Append a subsection to `EXPERIMENT_LOG.md`**: what was varied, the curve,
   first-fail stage, takeaway. Update the "real lever" line as evidence lands.
4. Update this HANDOFF's "current state" below.
5. Hand off.

## Key facts about the machinery (so you don't re-derive them)

- Prep/health is the **real production code**: `prepare_mgh_slow_release` +
  `run_health_check` from `backend/core/md_protocols.py` / `md_health.py`. The
  harness only shortens and parameterises the ladder; it does not fork the prep.
- **Declash auto-enables** for any design with crossover/forced-ligation
  `extra_bases` (`design_has_extra_bases`). It excludes single-stranded bases from
  the ENM, minimises them out of clash, then rebuilds ENM + heavy-atom restraints
  + health reference from the declashed coords. Declash runs the **soft
  integrator** (rigidBonds none, **1 fs** timestep) — so `dt=1fs` here, 2.4M-step
  production stages are 4.8 ns at 2 fs but the harness computes steps from `dt_fs`.
- Health thresholds: **C1' ≥ 0.90 (primary)**, WC ref-relative ≥ 0.80 (ENM) /
  0.75 (k=0). WC reads low on template builds — weight C1'.
- Production ladder shape (what we're trying to make survivable): min(ENM k=0.5)
  → NPT 300 K k=0.5 → 0.1 → 0.01 → k=0, 4.8 ns each, health at 10/50/100%.
- Hardware: RTX 3080 Ti, NAMD3 at `~/Applications/NAMD_3.0.2/namd3`. Keep one NAMD
  on the GPU at a time. Check `nvidia-smi` before launching.

## Once a recipe survives the 2hb ladder

Promote it to **6hb_2xT** for confirmation (slow — hours), then fold the winning
settings into `mgh_slow_release_segments` / `prepare_mgh_slow_release` defaults
(or expose them on `CreateJobRequest`). The durable build-side fix
(`_minimize_N_extra_base` in `atomistic.py`) is separate and out of harness scope.

## Current state (update every cycle)

- **2026-06-11 — Cycle 1 DONE (baseline + longer minimisation).** Longer min
  **helps but is bounded**: 24k steps lifts k=0.5 WC 78→85 (fail→pass), saturates
  by 24k, and does NOT stop the later-stage melt. **Adopt ~24k min as the cheap
  default.** See EXPERIMENT_LOG Cycle 1.
- **2026-06-11 — Cycle 2 DONE (gentler fine k-ladder `ladder_fine`).** Fine
  ladder `0.5,0.3,0.2,0.1,0.05,0.02,0.01,0`, min 24k. **Pre-registered
  prediction confirmed (Model B / PARTIAL).** Decision metric C1' at k=0 = **48.8%**
  (predicted band 40–70; baseline 20). **The melt is the FINAL restraint removal,
  nothing else:** C1' loses only ~7 pts across all seven ENM step-downs
  (90→…→83 at k=0.01), then −34 pts in the single k=0.01→0 jump (83→48.8).
  Subdividing the ENM range is nearly free of cost AND benefit — the structure is
  fine at any k>0; going to *true zero* exposes the strained equilibrium.
  - **Harness gain:** `run_cycle.py` now auto-generates intermediate-k ENM files
    (`_ensure_enm_files_for_ladder`) — arbitrary k-ladders now work. Without it
    NAMD fatals on the missing `*_k0.3.enm.extra` etc.
  - **Two production wins to keep:** min 24k default (Cycle 1) + the ENM range
    0.5→0.01 is robust (Cycle 2). Neither is the cure, but both are free.
- **2026-06-11 — Cycle 3 DONE (`final_taper`, subdivide the final removal).**
  Ladder `0.1,0.05,0.02,0.01,0.005,0.002,0.001,0`, min 24k, 0.3 ns/stage.
  **Pre-registered Model B′ (path-independent melt) CONFIRMED, sharper than
  predicted.** Decision metric **C1' at k=0 = 17.1%** — not only no gain over
  Cycle 2's 48.8, it is **worse** (and below the 20 baseline). Subdividing the
  final removal **hurt.**
  - **The melt is governed by *time at low restraint*, not step size.** Clean
    monotonic staircase down: C1' 93→90→83→68→56→46→27→17, mean C1' distance
    10.36→14.62 Å. The structure is already melted (27%) at k=0.001, *before* the
    last restraint is removed. Matched-k proof: same k=0.01 stage reads 68.3 here
    vs 82.9 in Cycle 2 — identical restraint, worse structure, because Cycle 3
    dropped the high-k anchoring stages and lingered at low k. The "redundant"
    0.5/0.3/0.2 stages are **protective in time** (pin the native basin while the
    clock runs), not free to drop.
  - **Both remaining MD levers refuted at once.** Lever 1 (subdivide final
    removal) = this cycle, falsified. Lever 2 (long hold at low k to dissipate
    strain) = pre-falsified — this curve *is* a progressive low-k hold and it
    accelerated the melt; under weak restraint strain *expresses* as melt, it
    does not bleed off. The optional `--stage-ns 0.6` arm was deliberately **not
    run** (it is a longer low-k hold → predicted worse, and would violate the
    decision rule).
  - **DECISION RULE TRIGGERED: ≤55 branch (17.1 ≪ 55) → path-independent melt
    confirmed. The MD-release search is EXHAUSTED and NEGATIVE.** No restraint
    ladder keeps this structure intact at k=0.
- **Free process defaults that survive (keep, but they are NOT the cure):** min
  ~24k (Cycle 1); ENM range 0.5→0.01 robust + protective-in-time (Cycle 2/3);
  declash on.
- **2026-06-11 — Cycle 4 DONE (build-side root-cause triage: localization + salt
  + expansion).** Localization (6hb + 2hb) → the melt is **GLOBAL, not
  junction-nucleated** (killed knot/catenane + the local `_minimize_N_extra_base`
  fix the prior handoff assumed). Two global levers tested via the harness:
  - **Salt dose-response 0/50/150/300 mM → k=0 C1' 20/40/44/48.** Electrostatic
    screening is REAL but **SATURATES at ~45%**: first 50 mM does +20 (biggest
    single-lever gain), then flat. **~half the melt is electrostatic (solved,
    cheap: ~50 mM); ~half is NOT (the residual ~45→90 gap).**
  - **+10% lateral expansion → HURTS** (k=0 12 vs 20): improves restrained
    structure but stretches crossovers → earlier collapse. Relieve crowding by
    screening, not pre-expansion.
  - **Settled electrostatic fix:** bump production `ion_conc_mM` default 0→~50 (one
    line, no build change). MD-release axis stays closed.
- **2026-06-12 — Cycle 5 DONE (control discriminator + 6hb attempt). BIG REFRAME.**
  All @50 mM NaCl, baseline recipe, +p16:
  - **`control_50mM`** (non-strained 2hb, no FL/2xT): k=0 C1' = **40.5%** —
    *identical* to strained 2hb_2xT (40.0%). **The forced-ligation/2xT strain is NOT
    the k=0 melt driver.** Removing it changes the endpoint by ~nothing.
  - **`6hb_salt50_min24k`** (real strained 6hb): k=0 C1' = **56%** vs 2hb's 40 (+16).
    **Bundle SIZE is the lever** — more helices = cooperative base-pairing = better
    k=0 survival. Confirms the 2hb proxy was harsh: the 2hb melt was substantially a
    small-bundle artifact, not the strain pathology.
  - **k=0 driver decomposition:** electrostatic ~+20 (salt, solved) + small-bundle
    instability ~+16 (proxy artifact, not a real defect) + residual to gate (open).
    Forced-ligation/2xT strain = NOT a measurable k=0 contributor.
  - Still short of 0.90 even for 6hb+salt in the fast (0.3 ns/stage) harness.
- **NEXT — domain call needed, then one definitive run.**
  1. **Decide the target:** is true k=0 even the goal? 6hb holds **k=0.01 at 78%**; if
     production hands off to long MD/CG at low-but-nonzero k, the true-zero "melt" is
     moot. Settle this before more prep tuning.
  2. **Definitive validation:** 6hb_2xT @50 mM through the **full 4.8 ns/stage
     production protocol** (slow ~24 ns/day → ~4–5 h/stage, overnight).
  3. The original 6hb production symptom was a *WC* failure at **k=0.1** (earlier &
     distinct from the k=0 C1' melt) — if that's the real blocker, investigate it
     separately. **Salt saturated (Cycle 4c) & MD-release closed — don't re-run those.**

### Cycle 4 — build-side ROOT-CAUSE hypotheses (ranked, pre-scribed 2026-06-11)

The k=0 melt is build-side. Candidate root causes, ranked by P(cause)×testability.
**Verified facts:** ionic setup = 12.5 mM Mg²⁺(hexahydrate)+CUFIX, 0 mM NaCl, PME
([md_protocols.py:651-652]) — origami-buffer screening, NOT vacuum. The extra-base
placement minimizers ([atomistic_minimisers.py:345 `_minimize_1_extra_base`]) optimize
a **geometry-only** objective (backbone bond-length/angle bridge + glycosidic C1′→N
alignment + partial steric repulsion vs a few hand-picked atoms) — they never see
the CHARMM forcefield, never relax the surrounding duplex, and are blind to clashes
outside `repel_pos`.

**ZEROTH STEP — localize the swelling — DONE (2026-06-11), result below.** Script
`scripts/localize_swelling.py`, target 6hb_2xT job `03302b74a7fa`. **Finding: the
melt nucleation is DELOCALIZED — Pearson r(dist-to-junction, growth) = −0.003;
NEAR-junction pairs are NOT enriched, FAR breaks least; top movers scattered across
all six helices.** This **re-ranked the hypotheses** (see EXPERIMENT_LOG "Cycle 3
follow-up — swelling LOCALIZATION" for full numbers). Updated ranking:

1. **(GLOBAL) Electrostatic — CONFIRMED partial lever (Cycle 4 salt arm, 2026-06-11).**
   `salt150_min24k`: +150 mM NaCl (verified ~167 mM added) on the 12.5 mM Mg buffer,
   same recipe as 0-salt baseline `longmin_24000`. **C1' at k=0: 20 → 44.2% (×2.2)** —
   the **first lever in 4 cycles to move the k=0 endpoint.** Screening the backbone
   self-repulsion roughly halves the melt, exactly as the global-driver localization
   predicted. NOT a full cure (44 ≪ 90 gate) and n=1. **Crucially this is a one-line
   config change (`ion_conc_mM`), not an atomistic rewrite.** Next: salt LADDER
   (0/50/150/300 mM) — does k=0 keep climbing (electrostatics dominant) or plateau
   ~44 (a 2nd global contributor remains)? Then confirm on 6hb. See EXPERIMENT_LOG
   "Cycle 4 — electrostatic screening".
1b. **Slight lateral expansion — TESTED, does NOT help (Cycle 4b, 2026-06-11).**
   `expand1p1_min24k`: +10% inter-helix spacing (2.25→2.475 nm, `--expand-scale 1.1`,
   topology preserved), 0 salt, baseline recipe. **Improves the RESTRAINED structure
   (k=0.5 C1'=97.6, best of any arm; k=0.1=90) but worsens the RELEASE: k=0.01 craters
   to 48.8 (vs 76 baseline) and k=0=12.2 (≤ baseline 20).** Mechanism: expansion
   relieves crowding (helps under restraint) but stretches crossovers → stored tension
   snaps back as restraint weakens → earlier collapse. Opposite trade-off from salt
   (screening relieves crowding with no mechanical penalty). **Lesson: relieve
   inter-helix pressure by SCREENING, not by pre-expansion.** Smaller expansion not
   worth testing. See EXPERIMENT_LOG "Cycle 4b".

2. **(GLOBAL) Build-geometry / bundle strain — refined.** The forced ligation
   imposes a *bundle-wide* linking-number/twist stress (NOT a local clash), and/or
   the ENM pins the whole duplex to a template B-DNA geometry CHARMM36+CUFIX
   disagrees with; release lets the whole structure swell uniformly. Consistent
   with delocalized nucleation. Test (after electrostatics): if the salt bump does
   nothing, this is it — **fix = relax the *whole* structure against the forcefield
   at build time / let the bundle adjust global twist+length**, NOT a local junction
   minimizer.
3. **Build separation too tight (duplex strain declash never touches).** Declash
   relaxes only ss bases vs a frozen ENM-held duplex ([md_protocols.py:722-740]);
   global duplex compression survives. Overlaps with #2.
4. **DEMOTED — local junction ideal-geometry strain (`_minimize_N_extra_base`).**
   Was the prior cycles' assumed fix. Localization argues against it: if the
   geometry-only backbone-linker placement stored the lethal strain *at the
   junction*, junction-adjacent pairs would break first — they don't. A smarter
   *local* minimizer is unlikely to be the cure on current evidence. (Geometry-only
   placement is still a real defect — `atomistic_minimisers.py:345` never sees the
   forcefield — but its damage isn't where the melt nucleates.)
5. **KILLED — knot / catenane / mechanical lock.** A topological lock explodes one
   region; the bundle loosens uniformly instead. Ruled out by localization.
6. Ion equilibration kinetics (not concentration) — lower. ENM/CHARMM reference
   mismatch folded into #2.

**Cross-check DONE (2026-06-11) — delocalization confirmed at full collapse.**
`localize_swelling.py 2hb` on the final_taper k=0.1→k=0 melt (C1′ 92.7%→12.2%):
**r(dist-to-junction, growth) = +0.18** (mildly anti-junction), NEAR-junction third
breaks LEAST (+2.79 Å vs MID +4.93). The melt is global at both 6hb onset (r≈0) and
2hb catastrophic collapse (r=+0.18). Scope caveat closed; hypotheses 4 & 1-as-local
rejected on both structures.

**Cross-cutting caveat:** 2hb is *harsher* than 6hb (too few WC pairs to stay a
stable bundle once perturbed) — some melt is proxy over-read. Confirm any build-side
fix on **6hb_2xT**, do not declare it on 2hb.
