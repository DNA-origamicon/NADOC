---
name: md-prep-relaxation-exp29
description: exp29 supervised-loop harness for finding how to prep strained (forced-ligation + 2xT) designs to survive MD relaxation
metadata: 
  node_type: memory
  type: project
  originSessionId: 9c841111-08f3-4916-83f7-9bfbe84f8a21
---

Supervised, fresh-session-per-cycle search for a preparation recipe that lets a
strained design survive the ENM-release relaxation ladder. Prompted by a
catastrophic **6hb_2xT** relaxation failure (forced ligation + 2× crossover
`extra_bases="TT"`).

**Where:** `experiments/exp29_md_prep_relaxation/` —
`run_cycle.py` (parameterised harness), `EXPERIMENT_LOG.md` (diagnosis + per-cycle
results), `HANDOFF.md` (fresh-session context — read this first to run the next
cycle), `RESULTS.tsv` (cross-cycle table).

**Proxy:** iterate on `workspace/2hb_2xT.nadoc` (same two strain sources, ~31k
atoms, 105 ns/day, ~20 min/cycle) — it's *harsher* than 6hb (fails k=0.5 already),
use the *shape* of the curve not absolute numbers. Harness reuses the real
`prepare_mgh_slow_release` + `run_health_check`; declash auto-enables for this
2xT design. At experiment time this selected the soft integrator (1 fs); the
current builder uses the 2 fs rigid-bond gentle tier. The 2026-08-09 threshold
change exempts 1xT only, so it does not change this experiment's 2xT trigger.

**Root cause:** the catastrophe is the **ENM step-down (k=0.5→0.1→0.01→0)**, not
minimisation. 6hb holds stably at k=0.5 then WC collapses on the first frame at
k=0.1; 2hb melts monotonically (C1' 90→83→68→29 across the ladder).

**Cycle 1 result (done 2026-06-11):** longer declash minimisation (`minimize_steps`)
helps but is bounded — 24k steps lifts k=0.5 WC 78→85 (fail→pass), saturates by
24k (50k≈24k), and does NOT stop the later-stage melt. **Adopt ~24k min as a cheap
default; insufficient alone.**

**Cycle 2 result (done 2026-06-11):** gentler fine k-ladder
`0.5,0.3,0.2,0.1,0.05,0.02,0.01,0` (min 24k). Pre-registered prediction confirmed.
**The melt is the FINAL restraint removal (k=0.01→0), nothing else:** C1' loses
only ~7 pts across all seven ENM step-downs (90→…→83 at k=0.01), then −34 pts in
the single k=0.01→0 jump → C1' at k=0 = **48.8%** (vs baseline 20; gate is 90).
Subdividing the ENM range 0.5→0.01 is nearly free of cost AND benefit — structure
is fine at any k>0; going to *true zero* exposes the strained equilibrium. WC is
the noisy gate (drops 85→62 on first step-down); weight C1'.
**Two free production wins to keep:** min-24k default + the 0.5→0.01 ENM range is
robust. **Harness gain:** `run_cycle.py` `_ensure_enm_files_for_ladder` now
auto-generates intermediate-k ENM files (prep only emits 0.5/0.1/0.01; bond list
is k-independent so it's a column-3 rewrite) — arbitrary k-ladders now work.

**Cycle 3 result (done 2026-06-11):** subdivide the FINAL removal `final_taper`
`0.1,0.05,0.02,0.01,0.005,0.002,0.001,0` (min 24k, dropped redundant high-k
stages). Pre-registered Model B′ CONFIRMED, sharper: **C1' at k=0 = 17.1%** —
not just no gain over Cycle 2's 48.8, *worse* (subdividing HURT). **The melt is
governed by *time at low restraint*, not step size:** clean monotonic staircase
C1' 93→90→83→68→56→46→27→17 (mean dist 10.36→14.62 Å); structure is melted (27%)
at k=0.001 *before* the last restraint is even removed. Matched-k proof: same
k=0.01 stage = 68 here vs 83 in Cycle 2 (dropped high-k anchoring + lingered low).
The "redundant" 0.5/0.3/0.2 stages are **protective in time**, not free to drop.
**Both remaining MD levers refuted at once** — subdivide-final (this) falsified;
long-hold-at-low-k pre-falsified (this curve IS a low-k hold and it accelerated
the melt; strain *expresses* under weak restraint, doesn't bleed off). Optional
`--stage-ns 0.6` arm deliberately NOT run (longer low-k hold → predicted worse +
violates decision rule).

**MD-RELEASE SEARCH EXHAUSTED & NEGATIVE.** Decision rule ≤55 branch triggered
(17.1 ≪ 55) → path-independent melt confirmed. No restraint ladder keeps this
structure at k=0. Build-side now. Three free defaults survive (min ~24k, ENM
range 0.5→0.01, declash on) but none cure the melt.

**Cycle 3 follow-up — swelling LOCALIZATION (2026-06-11):** asked whether the
melt nucleates AT the strain sources (junction-local ⇒ mechanical/topological) or
across the whole bundle (⇒ global). Script `scripts/localize_swelling.py` on the
**6hb_2xT** declash job `03302b74a7fa` (stable k=0.5 plateau → k=0.1 nucleation;
247 C1' pairs, 111 ss markers from `identify_unpaired_residues`). **Result: melt
is DELOCALIZED — Pearson r(dist-to-junction, growth) = −0.003; NEAR pairs not
enriched, FAR breaks least; top movers scattered across all 6 helices.** This
**re-ranked the build-side hypotheses:** (1) GLOBAL electrostatic — promoted,
cheapest global test = bump `mg_conc_mM`/`ion_conc_mM=150`; (2) GLOBAL
build-geometry / bundle-wide twist+linking strain from the forced ligation, or
ENM-template vs CHARMM36 mismatch — fix relaxes the WHOLE structure vs forcefield,
not a local junction min; (3) too-tight build separation (overlaps #2); (4)
DEMOTED local junction ideal-geometry strain (`_minimize_N_extra_base`) — would
break junction-adjacent pairs first, it doesn't; the geometry-only minimizers
([atomistic_minimisers.py:345], never see the forcefield) are a real defect but
not where the melt nucleates; (5) KILLED knot/catenane — a lock explodes one
region, the bundle loosens uniformly. **Verified:** ionic = 12.5 mM Mg(hexahydrate)
+CUFIX, 0 mM NaCl, PME (origami buffer, not vacuum). **Cross-check done:**
`localize_swelling.py 2hb` on full collapse (C1' 93→12%) gave r=+0.18 (mildly
anti-junction, NEAR breaks least) → delocalization confirmed at BOTH 6hb onset
(r≈0) and 2hb catastrophic melt. Scope caveat closed.

**Cycle 4 salt arm (done 2026-06-11):** `salt150_min24k` = +150 mM NaCl (verified
~167 mM added via genion) on the 12.5 mM Mg buffer, same recipe as 0-salt baseline
`longmin_24000`. **C1' at k=0: 20 → 44.2% (×2.2)** — FIRST lever in 4 cycles to move
the k=0 endpoint. Electrostatics IMPLICATED (not exonerated): screening the global
backbone self-repulsion roughly halves the melt, matching the delocalized-melt
localization. NOT a full cure (44 ≪ 90) and n=1. **Key practical implication: the
production default `ion_conc_mM=0.0` may just be too low — the cheap candidate fix
is raising ionic strength (one-line config), not rewriting the atomistic build.**
Harness gain: `run_cycle.py` now has `--ion-conc-mM` (default 0.0, threaded to
prepare_mgh_slow_release).

**Cycle 4b lateral-expansion arm (done 2026-06-11):** `expand1p1_min24k` = +10%
inter-helix spacing (2.25→2.475 nm, `--expand-scale 1.1`, GEOMETRIC-only, topology
preserved; mirrors frontend 'Q' quick-expand / `expanded_spacing.js`). **Does NOT
help the melt:** improves RESTRAINED structure (k=0.5 C1'=97.6, best of any arm)
but worsens RELEASE (k=0.01=49 vs 76 baseline, k=0=12 ≤ baseline 20). Pushing
helices apart relieves crowding but STRETCHES crossovers → stored tension snaps
back on release → earlier collapse. **Opposite trade-off from salt** (screening
relieves crowding w/o mechanical penalty). Lesson: relieve inter-helix pressure by
SCREENING not pre-expansion. Harness gain: `--expand-scale` (default 1.0 no-op).

**Cycle 4c salt dose-response (done 2026-06-11):** 0/50/150/300 mM NaCl → k=0 C1'
**20/40/44/48**. Screening is REAL but **SATURATES at ~45%**: first 50 mM does +20
(biggest single-lever gain in the whole experiment), then flat (50→300 adds only
+8). **PLATEAU branch → the melt is TWO global contributors, ~half each:**
(1) electrostatic — SOLVED, cheap (~50 mM monovalent, one-line `ion_conc_mM`
default 0→~50; 50 mM also more physical than 150-300); (2) non-electrostatic global
residual (~45→90 gap, untouched by any salt) = build-geometry / bundle-twist strain
= the NEW frontier. `run_salt_ladder.sh` did the 50+300 arms (sequential, GPU-guard).

**Lever scoreboard (k=0 C1', 2hb):** baseline 20 | +10% expand 12 (hurts) | +50mM
40 | +150mM 44 | +300mM 48 | MD-release schedules 17–49 (no durable gain). Only
screening helps, and it saturates.

**Cycle 5 (done 2026-06-12) — BIG REFRAME.** Two runs @50 mM NaCl, +p16:
- `control_50mM` (non-strained 2hb, no FL/2xT): k=0 C1' = **40.5%**, IDENTICAL to
  strained 2hb_2xT (40.0%). **The forced-ligation/2xT strain is NOT the k=0 melt
  driver** — removing it changes the endpoint by ~nothing.
- `6hb_salt50_min24k` (real 6hb): k=0 C1' = **56%** vs 2hb 40 (+16). **Bundle SIZE
  is the lever** (cooperative base-pairing). Confirms the 2hb proxy was harsh — the
  2hb melt was largely a small-bundle artifact, not the strain pathology.
- k=0 driver decomposition: electrostatic ~+20 (salt, solved) + small-bundle
  instability ~+16 (proxy artifact) + residual-to-gate (open). Strain ≈ 0
  contribution to k=0. Still short of 0.90 even for 6hb+salt in fast harness.

**Where it stands / next (domain call):** is true k=0 even the target? 6hb holds
k=0.01 at 78%; if production hands off to long MD/CG at low-but-nonzero k, the
true-zero melt is moot — decide before more tuning. Definitive validation = 6hb @50mM
through FULL 4.8 ns/stage production protocol (~overnight at ~24 ns/day). Original 6hb
symptom was a *WC* fail at k=0.1 (distinct from k=0 C1' melt) — investigate separately
if it's the real blocker. MD-release + salt axes CLOSED.

**Cheap settled production wins:** ion_conc_mM default 0→~50 (electrostatic half);
min ~24k; ENM range 0.5→0.01 robust; declash auto; NO pre-expansion. Harness:
`--ion-conc-mM`, `--expand-scale` (default 1.0), `--threads` default 8→**16** (Ryzen
9950X 16C; +p16+setcpuaffinity).

**exp29 wrapped (2026-06-12):** see `experiments/exp29_md_prep_relaxation/`
`LESSONS_LEARNED.md` (transferable anti-patterns: run feature-removed control FIRST,
localize before fixing, don't tune restraint schedule for a path-independent melt,
proxy absolute numbers lie, check salt early) + `NEXT_SESSION.md` (path to the full
Aksimentiev production sim = `mgh_slow_release` 4.8 ns/stage on 6hb_2xT @50mM/min24k;
blocking domain Q = true-k=0 vs k=0.01 handoff; ~overnight run). The exp29 harness IS
the real `prepare_mgh_slow_release`+`run_health_check`, only shortened — transfers by
lengthening stages. See EXPERIMENT_LOG "Cycle 1–5" + HANDOFF.
[[atomistic-skip-backbone]], [[md-job-system]].
