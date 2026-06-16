# exp29 — MD structure-prep for relaxation of strained designs

**Status:** active · **Started:** 2026-06-11
**Test design:** `workspace/2hb_2xT.nadoc` (fast proxy) — production target is `6hb_2xT`.
**Harness:** `run_cycle.py` (one invocation = one prep recipe = one "cycle").

---

## The problem

The latest **6hb_2xT** relaxation failed catastrophically at the health gate.
`2hb_2xT` is the small proxy: 2 helices, 3 strands, **2× crossover `extra_bases="TT"`
plus one forced ligation** — i.e. it exercises both strain sources we care about
(inserted single-stranded bases + a forced ligation) in a structure that prepares
in ~1 s and runs a ladder stage in minutes instead of hours.

## What actually failed (root-cause from the 6hb runs)

Two 6hb_2xT jobs in `workspace/md_jobs/`:

| job | declash | died at | C1' | WC |
|-----|---------|---------|-----|-----|
| `b980e1f52381` | no  | stage 01 (k=0.5) | 85.2% | 77.2% |
| `03302b74a7fa` | yes | stage 02 (k=0.1) | 89.5% | 75.0% |

Reading `03302…/output/health.jsonl` frame-by-frame is the key evidence:

- **Stage 01 (ENM k=0.5):** WC holds **~86–89%**, C1' **~91–92%**, *stable across the
  full 4.8 ns* (p10 → p50 → p100 all pass).
- **Stage 02 (ENM k=0.1):** on the **very first health frame** after the restraint
  step-down, WC collapses **88% → 75%** and stays there; C1' slips to 89.5%.

**Conclusion: the failure is the ENM step-down k=0.5 → k=0.1, not minimisation.**
The structure minimises fine and is stable while the strong base-ring network
holds it. The strain stored at the forced ligation + 2xT insertions is released
the instant the network loosens, and ~13% of WC pairs (the marginal ones near
those junctions) pop open.

> ⚠️ The user's stated first hypothesis is "longer minimisation." The 6hb evidence
> predicts longer minimisation alone will **not** fix this (the structure is
> already stable at k=0.5; the problem is the release transient). We still test it
> first because it's the cheapest knob — but the harness is built to vary the
> **k-ladder gentleness** and **per-k equilibration**, which the data says are the
> real levers. Treat "longer min" as cycle 1, not the expected answer.

## Health-gate semantics (so numbers are read correctly)

- `run_health_check` reads `{stem}.psf` + `{stem}.pdb` (reference) + `output/{seg}.dcd`.
- For declash designs the reference `.pdb` is the **declashed** geometry (rebuilt
  by `rebuild_declashed_references` after minimisation), so WC is judged against
  the relaxed build, not the clashed one.
- **C1' paired ≥ 90%** is the primary structural metric (see
  `memory/feedback_wc_calibration.md` — template builds inflate ~25% of WC ref
  distances, so WC ref-relative runs low and is the noisier gate). WC threshold is
  0.80 during ENM stages, 0.75 at k=0.

## Hypotheses / levers (in planned test order)

1. **Longer minimisation** (cycle 1) — `--minimize-steps 4800 → 24000 → 50000`.
   Expected weak effect per the diagnosis; establishes whether residual build
   strain is min-limited at all.
2. **Longer settle at the first k before release** — `--equil-ns` holds k=0.5
   longer before stepping down. Tests whether the transient is a rate problem.
3. **Gentler k-ladder** — insert intermediate k's, e.g. `--k-ladder 0.5,0.3,0.2,0.1,0.05,0.01,0`.
   The hypothesis the data most supports: smaller steps = smaller release transient.
4. **Build-side fix** (out of harness scope) — the durable fix is the extra-base
   backbone minimiser in `atomistic.py` (`_minimize_N_extra_base`) storing less
   strain at build time. See `memory/project_md_job_system.md` declash note.

## Cycles run

See `RESULTS.tsv` for the compact cross-cycle table; per-cycle detail in
`runs/<label>/cycle_result.json`. Notes below are the human interpretation.

### Cycle 1 — baseline + longer minimisation

**Harness validated** end-to-end on 2hb: prep 1 s, min 5 s (4800 steps), declash
rebuild OK (8 ss residues excluded, 31 021 atoms), **105 ns/day** (1 fs soft
integrator), ~4 min/ladder-stage, whole cycle ~20 min. Good fast proxy.

**`baseline_min4800`** (production-default min, 0.3 ns/stage):

| k | 0.5 | 0.1 | 0.01 | 0 |
|---|-----|-----|------|---|
| C1' % | 90.2 | 82.9 | 68.3 | **29.3** |
| WC %  | 77.5 | 60.0 | 20.0 | **0.0** |

The 2hb proxy **melts completely** as the ENM releases — monotonic collapse from
the first stage, total disintegration at k=0. Note this is *worse/earlier* than
6hb (which held k=0.5 stably): the 2-helix bundle has too few WC pairs and the
forced ligation is proportionally more disruptive, so it fails the WC gate
already at k=0.5. The proxy is a valid "won't survive relaxation" stressor, but
it is **harsher** than 6hb — read absolute numbers with that in mind; the *shape*
(monotonic melt on release) is the transferable signal.

**Longer minimisation arms** — `minimize_steps` controls the **declash
minimisation** (ss bases relaxing out of clash against the ss-excluded ENM), so
this is a real lever, not a no-op:

| min steps | k0.5 (C1/WC) | k0.1 | k0.01 | k0 | first-fail | min wall |
|-----------|--------------|------|-------|-----|-----------|----------|
| 4800 (baseline) | 90 / **78 FAIL** | 83 / 60 | 68 / 20 | 29 / 0 | stage 1 | 5 s |
| 24000 | 90 / **85 PASS** | 85 / 50 | 76 / 22 | 20 / 5 | stage 2 | 24 s |
| 50000 | 93 / **82 PASS** | 83 / 52 | 76 / 25 | 24 / 8 | stage 2 | 54 s |

**Verdict (answers "does the process benefit from longer minimisation?"): YES,
but bounded.**
- Longer min **rescues the first stage**: k=0.5 WC 78→85 (fail→pass), C1' holds
  ≥90. First-failure moves stage 1 → stage 2. So it is worth doing.
- The benefit **saturates by ~24k steps** — 50k is within noise of 24k at every
  stage. Minimisation is cheap (24 s) so a default bump to ~24k steps is free and
  strictly helps; beyond ~50k buys nothing here.
- It does **NOT** fix the core failure: the k-release melt (k0.1 → 0.01 → 0) is
  essentially unchanged by min length. Min relieves *residual build strain*; it
  cannot stop the *ENM-release transient*. The structure still fully melts by k=0
  in all three arms.

**Real-lever standing:** the diagnosis holds. Minimisation is a useful *first*
fix (adopt ~24k default) but the design only survives relaxation if the
**k-ladder release** is made gentler / slower. That is Cycle 2.

### Cycle 2 — gentler k-ladder release (NEXT, not yet run)

Hypothesis: the melt is a release-rate problem. Smaller k steps and/or longer
equilibration at each k shrink the per-step transient so marginal WC pairs
re-anchor instead of popping. Use the ~24k min from Cycle 1 as the fixed base.
Suggested arms:
- `--k-ladder 0.5,0.3,0.2,0.1,0.05,0.02,0.01,0` (finer steps)
- `--equil-ns 0.5` (hold first k longer before stepping down)
- combine the two if either alone helps.
Watch whether C1' at k=0.01 and k=0 stops collapsing (baseline: 68→29; target:
stays ≥90). If even a fine ladder melts at k=0, the conclusion shifts to a
**build-side** fix (`_minimize_N_extra_base` in `atomistic.py`) — the forced
ligation may be storing strain no MD release schedule can dissipate.

#### Cycle 2 — PRE-REGISTERED PREDICTION (written before the run)

**Arm:** `ladder_fine` — `--minimize-steps 24000 --stage-ns 0.3
--k-ladder 0.5,0.3,0.2,0.1,0.05,0.02,0.01,0` (8 stages). Min fixed at the
Cycle-1 winner (24k); only the release schedule changes.

**Two competing mechanisms, two distinct predictions:**

- **Model A — kinetic / release-rate (the HANDOFF hypothesis).** The melt is a
  per-step transient proportional to the size of each k-drop. Spreading the same
  total release over more, smaller steps shrinks every transient, so marginal WC
  pairs re-anchor at each plateau instead of popping. *Predicts:* C1' stays ≥ 90
  through the whole ladder **including k=0**, WC ≥ 75 at k=0 → **PASS**.

- **Model B — stored-strain / thermodynamic (my prior).** The forced ligation
  stores a fixed strain whose k=0 equilibrium is melted; path cannot change the
  endpoint. Critically, the baseline's catastrophic step is the **final 0.01→0
  removal** (C1' 76→20), and the fine ladder does **not** subdivide that last
  jump. *Predicts:* intermediate stages hold better than baseline, but the
  structure **still melts at k=0** → **FAIL**.

**Pre-registered numeric prediction (my best estimate = Model B / "partial"):**

| k | 0.5 | 0.3 | 0.2 | 0.1 | 0.05 | 0.02 | 0.01 | 0 |
|---|-----|-----|-----|-----|------|------|------|---|
| C1' pred % | 90 | 89 | 88 | 87 | 85 | 83 | 80 | **35** |
| WC pred %  | 85 | 81 | 77 | 65 | 56 | 48 | 38 | **10** |

**Decision metric = C1' at k=0** (baseline `longmin_24000` = 20%):
- **≥ 90** → Model A confirmed, ladder gentleness is the fix. Promote to 6hb.
- **40–70** → PARTIAL: gentler release helps but residual build strain remains;
  next lever = subdivide the *final* 0.01→0 removal (add 0.005, 0.002, 0.001)
  and/or hold longer at k=0.01, before pivoting build-side.
- **≤ 30** (≈ baseline) → Model B confirmed, path-independent melt; pivot to the
  build-side fix (`_minimize_N_extra_base` in `atomistic.py`).

**Secondary check:** do the intermediate stages (k=0.1, 0.05, 0.01) hold WC
*above* the baseline's same-k values (50 @ k=0.1, 22 @ k=0.01)? If yes, the
finer steps demonstrably reduce the transient even if the endpoint still fails —
that isolates the final removal as the lethal event.

#### Cycle 2 — RESULTS  (`ladder_fine`, 2026-06-11)

**Harness fix required first.** Initial run crashed at stage 2: NAMD `FATAL
ERROR: UNABLE TO OPEN EXTRA BONDS FILE 2hb_noT_k0.3.enm.extra`. Production prep
(`write_aksimentiev_enm_files`) only emits ENM files for the canonical scales
(0.5, 0.1, 0.01); intermediate k's have no file. The base-ring bond list +
equilibrium lengths are computed **once and are k-independent** — only column 3
(the scale) varies — so `run_cycle.py` now auto-generates any missing
intermediate-k file from an existing one (`_ensure_enm_files_for_ladder`, called
after the declash rebuild so it inherits the ss-excluded 12 256-restraint list).
Byte-for-byte what production would emit for those scales. Re-ran clean.

**Actual per-stage curve** (min 24k, 0.3 ns/stage, declash on):

| k | 0.5 | 0.3 | 0.2 | 0.1 | 0.05 | 0.02 | 0.01 | **0** |
|---|-----|-----|-----|-----|------|------|------|-----|
| C1' % | 90.2 | 92.7 | 87.8 | 87.8 | 87.8 | 85.4 | 82.9 | **48.8** |
| C1' mean Å | 10.38 | 10.16 | 10.26 | 10.36 | 10.49 | 10.61 | 10.71 | **11.95** |
| WC % | 85.0 | 62.5 | 62.5 | 60.0 | 45.0 | 40.0 | 25.0 | **12.5** |

**Prediction vs actual (pre-registered):**
- **C1' intermediate stages — excellent match.** Predicted 90→89→88→87→85→83→80;
  actual 90→93→88→88→88→85→83. Within ~3 pts everywhere. The ENM holds C1'
  essentially flat at *any* k>0.
- **Decision metric C1' at k=0 — predicted 35, actual 48.8 → lands in the
  PARTIAL band (40–70), as predicted.** Slightly better than my point estimate
  but the same verdict. **Model B confirmed, Model A rejected.**
- **WC — I over-estimated upper-stage retention.** Predicted a gentle 85→81→77
  decline; actual drops 85→62.5 on the *first* step-down then declines. WC
  (h-bond geometry) loosens immediately as restraints weaken; it is the noisier,
  template-inflated gate (per `feedback_wc_calibration.md`) — weight C1'.

**The decisive finding — the melt is the FINAL restraint removal, nothing
else.** C1' loses only ~7 points across the *seven* ENM step-downs from k=0.5
to k=0.01 (mean C1' distance creeps 10.38 → 10.71 Å — negligible). Then the
single k=0.01→0 removal costs **−34 points** (82.9 → 48.8; mean distance jumps
10.71 → 11.95 Å). All the damage is concentrated in going to *true zero*, which
the fine ladder deliberately did **not** subdivide.

**Verdict: gentler intermediate steps help but are not the lever.** vs baseline
`longmin_24000` (k=0 C1' = 20), the fine ladder more than doubles surviving C1'
(20 → 48.8) — real, measurable improvement — but still fails the 0.90 gate by a
wide margin. The finer steps reduce the per-step transient (intermediate WC also
runs above baseline: k=0.1 WC 60 vs 50, k=0.01 C1' 83 vs 76), confirming the
release-rate hypothesis is *partially* right, but the dominant failure is
thermodynamic: removing the last restraint exposes the strained k=0 equilibrium.

**Real-lever standing (updated):** Cycle 1 said "min helps, bounded; k-ladder is
the real lever." Cycle 2 refines this: **subdividing the ENM range (0.5→0.01) is
nearly free of cost but also nearly free of benefit — the structure is fine at
any k>0. The lethal event is the final 0.01→0 removal.** Two unfalsified levers
remain before the build-side pivot:
1. **Subdivide the final removal** — `…,0.01,0.005,0.002,0.001,0`. Directly tests
   whether the k=0 collapse is a removal-*rate* transient (recoverable) or a
   genuine melted endpoint (not). This is Cycle 3.
2. **Long hold at low k before removal** — equilibrate fully at k=0.01 so
   residual strain dissipates *while still restrained*, then remove. (Harness
   `--equil-ns` only holds the *first* k; needs a small extension to hold the
   *last* k, or just bump `--stage-ns` for a uniformly longer hold.)

If Cycle 3's subdivided final removal still collapses C1' at true k=0 (≤~55,
i.e. no better than this run's 48.8), the conclusion is **path-independent
melt → pivot to the build-side fix** (`_minimize_N_extra_base` in
`atomistic.py`): the forced ligation stores strain no release schedule can shed.

### Cycle 3 — subdivide the FINAL removal (`final_taper`)

The last unfalsified MD lever. Cycle 2 localised the entire melt to the single
`k=0.01 → 0` removal (−34 C1' pts; the seven step-downs above it cost only ~7
pts combined). This cycle subdivides exactly that lethal jump.

**Arm:** `final_taper` — `--minimize-steps 24000 --stage-ns 0.3
--k-ladder 0.1,0.05,0.02,0.01,0.005,0.002,0.001,0` (8 stages). Drops the
redundant high-k 0.5/0.3/0.2 stages (Cycle 2 proved they cost nothing) and
spends the budget tapering the approach to zero: four sub-steps
(0.005 → 0.002 → 0.001 → 0) now bridge what was a single cliff, each held 0.3 ns.

#### Cycle 3 — PRE-REGISTERED PREDICTION (written before the run)

**Two competing mechanisms, sharpened for the final removal:**

- **Model A′ — removal-rate transient (recoverable).** The k=0 collapse is a
  kinetic shock from yanking the last restraint in one step. Bridging it with
  four sub-steps lets marginal pairs re-anchor at each low-k plateau, so the
  damage spreads thin and the endpoint largely survives. *Predicts:* C1' at k=0
  ≥ 90 (or at least ≥ 60, a clear gain over Cycle 2's 48.8).

- **Model B′ — melted endpoint (path-independent).** The forced ligation's k=0
  equilibrium is genuinely melted; no restraint schedule changes the endpoint,
  only the trajectory to it. Sub-steps make the *descent* visibly progressive
  (C1' steps down through 0.005/0.002/0.001 instead of cliffing) but converge to
  the same melted basin. *Predicts:* C1' at k=0 ≈ 48–55 — within noise of Cycle
  2, no real gain.

**My prior = Model B′.** Cycle 2 already rejected Model A at the range level and
showed the structure is fine at *any* k>0 — the pathology is specifically *true
zero*, which is a property of the unrestrained equilibrium, not the rate of
approach. Subdividing changes the path, not the basin.

**Pre-registered numeric prediction (best estimate = Model B′):**

| k | 0.1 | 0.05 | 0.02 | 0.01 | 0.005 | 0.002 | 0.001 | 0 |
|---|-----|------|------|------|-------|-------|-------|---|
| C1' pred % | 88 | 87 | 85 | 83 | 80 | 75 | 68 | **52** |
| WC pred %  | 60 | 45  | 40  | 25  | 22    | 20    | 18    | **13** |

Distinguishing signature: under Model B′ the low-k sub-steps (0.005/0.002/0.001)
show a *staircase* down toward the melt; under Model A′ they stay flat (≥80) and
the endpoint holds.

**Decision metric = C1' at k=0** (Cycle 2 `ladder_fine` = 48.8%):
- **≥ 90** → final-removal transient was the whole problem; fold the taper into
  `mgh_slow_release_segments`, promote to 6hb_2xT.
- **~55–89** → taper helps further; push it (more sub-steps / longer holds) or
  combine with a long k=0.01 equilibration.
- **≤ ~55** (≈ 48.8, no real gain) → **path-independent melt confirmed. STOP
  tuning MD release. Pivot to the build-side fix** (`_minimize_N_extra_base` in
  `atomistic.py`).

#### Cycle 3 — RESULTS (`final_taper`, 2026-06-11)

**Actual per-stage curve** (min 24k, 0.3 ns/stage, declash on; 10 ss bases
excluded, 11 908 ENM restraints/file, 5 intermediate-k files auto-generated;
~106 ns/day, ~250 s/stage):

| k | 0.1 | 0.05 | 0.02 | 0.01 | 0.005 | 0.002 | 0.001 | **0** |
|---|-----|------|------|------|-------|-------|-------|-----|
| C1' %     | 92.7 | 90.2 | 82.9 | 68.3 | 56.1 | 46.3 | 26.8 | **17.1** |
| C1' mean Å | 10.36 | 10.54 | 10.96 | 11.51 | 11.91 | 12.52 | 13.46 | **14.62** |
| WC %      | 45.0 | 37.5 | 30.0 | 22.5 | 20.0 | 15.0 | 0.0  | **2.5** |

**Decision metric C1' at k=0 = 17.1%** (Cycle 2 `ladder_fine` = 48.8; baseline
`longmin_24000` = 20). Firmly in the **≤55 band**. Subdividing the final removal
**made the endpoint worse, not better.**

**Prediction vs actual (pre-registered):**
- **Verdict band — correct.** I pre-registered Model B′ (melted endpoint,
  path-independent) → C1' at k=0 ≈ 48–55, ≤55 band, pivot build-side. Actual
  17.1 is in that band (the pivot call), though **below** my 52 point estimate —
  the taper didn't just fail to help, it actively hurt.
- **Distinguishing signature — Model B′ confirmed, sharper than predicted.** I
  said the low-k sub-steps would form a "staircase down toward the melt" under
  B′ vs "stay flat ≥80" under A′ (recoverable transient). Actual: a clean
  monotonic staircase — C1' 68→56→46→27→17 and mean distance 11.5→11.9→12.5→
  13.5→14.6 Å across the four sub-steps. **The structure melts at low-but-nonzero
  k given hold time; it is fully gone (27%) before the last restraint is even
  removed.** Model A′ (rate transient) is decisively rejected.

**Why subdividing made it WORSE — the mechanism, now fully resolved.** The melt
is governed by **time spent at low restraint, not by step size.** Two reads of
the same data:
1. *Matched-k comparison:* at the identical k=0.01 stage, Cycle 2 held C1' 82.9
   (mean 10.71 Å) but Cycle 3 read 68.3 (mean 11.51 Å) — **same restraint
   strength, worse structure.** Cycle 3 reached k=0.01 having dropped the high-k
   0.5/0.3/0.2 anchoring stages, so it had been weakly restrained longer.
2. *Time-at-low-k:* Cycle 3 spent ~1.5 ns at k≤0.01 (five stages) vs Cycle 2's
   ~0.6 ns (two). More dwell at weak restraint = more melt. The "redundant"
   high-k stages we proved *cost nothing structurally* in Cycle 2 were in fact
   *protective in time* — they keep the structure pinned to the native basin
   while the clock runs, delaying the slide. Removing them and lingering at low k
   handed the strained equilibrium the time it needed to win.

**This refutes BOTH remaining MD levers at once:**
- **Lever 1 (subdivide final removal) — falsified.** This cycle. Smaller final
  steps *did* shrink the literal last-step drop (Cycle 2: 82.9→48.8 = −34 in one
  jump; Cycle 3: 26.8→17.1 = −10 in the last jump) — but irrelevantly, because
  the structure had already melted to 27% *during* the taper while still
  restrained.
- **Lever 2 (long hold at low k to "dissipate strain while restrained") —
  pre-falsified by this curve.** Cycle 3 *is* a progressive low-k hold, and it
  **accelerated** the melt. Holding longer at k=0.01 would dissipate nothing; it
  would melt further. The premise that strain bleeds off harmlessly under weak
  restraint is wrong — under weak restraint the strain *expresses* as the melt.

**Verdict: path-independent (path-aggravated) melt CONFIRMED. STOP tuning the MD
release schedule.** No restraint ladder — gentler, finer, or longer-held — keeps
this structure intact at k=0, because the unrestrained equilibrium of the
forced-ligation + 2xT design is genuinely melted and any sufficiently-weak
restraint held long enough converges to it. The decision rule's ≤55 branch is
triggered unambiguously (17.1 ≪ 55).

**Second arm (`--stage-ns 0.6`) deliberately NOT run.** It is a *longer* low-k
hold — exactly the move this curve shows makes things worse — and running it
would violate the pre-registered decision rule (≤55 → stop tuning release). Its
outcome is already predicted: a worse k=0 endpoint.

**Real-lever standing (final for the MD-release axis):** The MD-release search is
**exhausted and negative.** Three free/cheap process wins survive as defaults
(min ~24k; the ENM range 0.5→0.01 is robust and protective in time; declash
on), but none cure the melt. **The cure must move build-side:**
`_minimize_N_extra_base` in `atomistic.py` — make the forced ligation store less
strain at build time so the k=0 equilibrium is native, not melted. See
`memory/project_md_job_system.md` declash note + `project_atomistic_skip_backbone.md`.
**exp29's MD-prep question is answered: NO restraint schedule fixes this. → Cycle 4 is build-side.**

#### Cycle 3 follow-up — swelling LOCALIZATION (2026-06-11, root-cause triage)

**Question:** when the restraint releases, do the pairs that loosen first ring the
strain sources (junction-local ⇒ mechanical/topological) or scatter across the
whole bundle (delocalized ⇒ global driver)? This splits the build-side hypothesis
set for free. Script: `scripts/localize_swelling.py`.

**Target = 6hb_2xT** (not the 2hb proxy — avoids the over-read), declash job
`workspace/md_jobs/03302b74a7fa`. It held stably through all of k=0.5 (stage01,
125 frames) then **nucleated** the melt at the k=0.5→0.1 step-down (stage02, 25
frames). Comparing the two windows isolates *nucleation*. C1′ pairs from the gate's
own `build_c1_pairs`; junction markers = the authoritative ss set the declash
excludes (`identify_unpaired_residues`, 10.8 Å) = 111 residues; per-pair C1′–C1′
distances frame-averaged (rotation-invariant), minimum-image.

**Result — the nucleation is DELOCALIZED, not junction-correlated:**

| dist-to-junction third | NEAR (5–13 Å) | MID (13–21 Å) | FAR (21–35 Å) |
|---|---|---|---|
| mean C1′ growth (k0.5→k0.1) | +0.14 Å | +0.24 Å | +0.15 Å |
| frac pairs broke (>+1 Å) | 7% | 9% | 2% |

- **Pearson r(dist-to-junction, growth) = −0.003** (n=247 pairs). Flat.
- NEAR is **not** enriched; FAR breaks *least*. Top-10 movers (+1.2 to +2.1 Å)
  are scattered djunc 7.6–27.8 Å across all six helices (segments DNAA/B/D/E/F/G,
  mostly vs the scaffold DNAI). No ring of damage around the 2xT inserts or the
  forced ligation.

**What this rules out / re-ranks:**
- **KILLS hypothesis 4 (knot / catenane / mechanical lock).** A topological lock
  explodes *one* region; instead the whole bundle loosens uniformly. Ruled out.
- **DEMOTES hypothesis 1 *as a local junction fix*.** If the geometry-only
  backbone-linker placement stored the lethal strain *at the junction*, the
  junction-adjacent pairs would break first. They don't. So a smarter *local*
  junction minimizer (`_minimize_N_extra_base`) is **not** the cure on this
  evidence — the melt driver is not local to where that code acts.
- **POINTS TO a GLOBAL driver.** Two delocalized candidates survive, which
  localization alone cannot separate:
  - **(3) electrostatic** — global backbone self-repulsion the ENM was masking;
  - **(1′/6, refined) global build-geometry / bundle strain** — the forced
    ligation imposes a *bundle-wide* linking-number/twist stress (not a local
    clash), and/or the ENM pins the whole duplex to a template B-DNA geometry
    CHARMM36+CUFIX disagrees with; on release the whole structure relaxes/swells
    uniformly.

**Scope caveat (now CLOSED by the 2hb cross-check below):** the 6hb signal is the
**nucleation** step (k0.5→0.1, ~3% of pairs moved; WC dropped 88→75 while C1′ moved
only +0.17 Å mean); 6hb never reached k=0. To confirm the pattern at *full collapse*
I ran the same script on the 2hb `final_taper` k=0 trajectory.

**2hb full-collapse cross-check (`localize_swelling.py 2hb`).** k=0.1 intact
(C1′ 92.7%) → k=0 melted (C1′ 12.2%, mean 10.37→14.12 Å — the real collapse, 41
pairs, 10 ss markers, 20 frames each):

| dist-to-junction third | NEAR (6–11 Å) | MID (11–22 Å) | FAR (23–34 Å) |
|---|---|---|---|
| mean C1′ growth (k0.1→k0) | +2.79 Å | +4.93 Å | +3.51 Å |
| frac pairs broke (>+1 Å) | 86% | 100% | 92% |

- **Pearson r(dist-to-junction, growth) = +0.18** — *positive* (mildly anti-junction;
  far pairs grow slightly more), the opposite of a mechanical-lock signature.
- **NEAR-junction breaks LEAST** (+2.79 Å, the smallest of the three thirds); MID
  worst. Biggest single mover (+9.93 Å) sits 18 Å from any junction. Top-10 span
  djunc 6.9–32.2 Å.
- (2hb caveat: only 2 helices, so "far" ≈ helix termini that always fray — the
  positive r is partly small-bundle geometry. Core conclusion is unambiguous
  regardless: NEAR is not enriched, it is the least-damaged third.)

**Verdict: the melt is GLOBAL at BOTH onset (6hb, r≈0) and catastrophic collapse
(2hb, r=+0.18). No junction nucleation at any stage.** Hypotheses 4 (knot/catenane)
and 1-as-local-junction-strain are rejected on both structures; the driver is a
delocalized, whole-bundle force. Electrostatic vs global-build-geometry remains the
open split → next test = salt/Mg bump (exonerate-or-implicate electrostatics).

**Next cheap test = exonerate-or-implicate electrostatics (hypothesis 3).** Re-run
the ladder with `mg_conc_mM` bumped and/or `ion_conc_mM=150`. If the k=0 endpoint
barely moves → electrostatics exonerated → the cause is **global build-geometry**
(the fix is to relax the *whole* structure against the forcefield at build time, or
let the bundle adjust global twist/length — NOT a local junction minimizer). If it
improves → screening is (part of) it. Either way, localization has redirected
Cycle 4 away from the local `_minimize_N_extra_base` fix the prior cycles assumed.

### Cycle 4 — electrostatic screening (salt arm, `salt150_min24k`)

Localization (Cycle 3 follow-up) pointed to a **global** melt driver and split the
remaining build-side hypotheses into *electrostatic* vs *global build-geometry*.
This arm tests electrostatics directly: add 150 mM monovalent salt on top of the
12.5 mM Mg origami buffer and ask whether screening the backbone self-repulsion
rescues the k=0 endpoint. **Harness gain:** `run_cycle.py` now exposes
`--ion-conc-mM` (threaded to `prepare_mgh_slow_release(ion_conc_mM=…)`); default 0.0
so all prior cycles are unaffected.

**Validity check:** genion added **+29 NaCl pairs** (Cl 4→33, Na 96→125) into ~9 600
waters ≈ **167 mM** (integer-ion rounding of the 150 mM target). Mg equal in both
arms (12.5 mM, controlled). The arm cleanly isolates monovalent screening.

**Arm:** `salt150_min24k` — `--minimize-steps 24000 --stage-ns 0.3
--k-ladder 0.5,0.1,0.01,0 --ion-conc-mM 150`. **Identical recipe to the 0-salt
baseline `longmin_24000`**, so added salt is the only variable.

| k | 0.5 | 0.1 | 0.01 | **0** |
|---|-----|-----|------|-----|
| C1' % (+150 mM NaCl) | 90.7 | 83.7 | 67.4 | **44.2** |
| C1' % (0 salt, longmin_24000) | 90.2 | 85.0 | 76.0 | **20.0** |
| WC % (+150 mM NaCl) | 82.0 | 51.3 | 25.6 | **10.3** |
| WC % (0 salt) | 85.0 | 50.0 | 22.0 | **5.1** |

**Decision metric C1' at k=0: 20.0 → 44.2% (×2.2).** A large, unambiguous rise
(≈10 of 41 pairs) — far beyond the ~2.4%/pair granularity. **Verdict: electrostatics
IMPLICATED, not exonerated.** Screening the backbone self-repulsion roughly halves
the melt, exactly as the *global*-driver localization predicted. This is the **first
lever in four cycles that moved the k=0 endpoint** — every restraint-schedule knob
left it at 17–49; salt lifts the floor.

**But not a full cure (44 ≪ 90 gate).** Two reads, not yet separated:
- screening is the dominant lever but 150 mM is not enough → more salt / higher Mg
  should keep climbing;
- electrostatics is one of two global contributors (the other = build-geometry /
  bundle-twist strain) → salt plateaus near ~44 and the rest needs a build-side fix.
The k=0.01 stage is slightly *lower* with salt (67 vs 76) while k=0 is much higher
(44 vs 20); the intermediate difference is within borderline-stage run-to-run noise,
the endpoint difference is not.

**Caveats:** n=1 vs n=1 (single run each) — magnitude is large and mechanistically
coherent, but a replicate (or a salt *ladder*: 0/50/150/300 mM) would harden it.
2hb-proxy harshness still applies; confirm on 6hb. **Physicality:** 12.5 mM Mg +
150 mM Na is high total ionic strength and not a typical *folding* buffer (high Na
competes with Mg), but this is a *relaxation-prep* step — screening to prevent
artifactual melt is legitimate; the defensible production value still needs picking.

**Real-lever standing (updated):** MD-release axis is closed (Cycles 1–3). The melt
is a **global** force (localization). **Electrostatic screening is now a confirmed,
cheap, partial lever** — and critically it is a *one-line config change*
(`ion_conc_mM` default), not an atomistic-build rewrite. Next: (a) salt ladder to
see if k=0 keeps climbing (dominant vs one-of-two), (b) confirm on 6hb, (c) if salt
plateaus, the residual is build-geometry → relax the whole structure against the
forcefield.

### Cycle 4b — slight lateral expansion (geometric arm, `expand1p1_min24k`)

Tests the "give the bundle more room" lever (hypotheses 2/3, the user's
"increase starting separation"). Build the structure with **+10% lateral
inter-helix spacing** (2.25→2.475 nm) before relaxation — a toned-down,
build-time version of the frontend 'Q' quick-expand. **Harness gain:**
`run_cycle.py` now has `--expand-scale` (GEOMETRIC-only: radial scaling of helix
axes about the bundle centroid, mirroring `scene/expanded_spacing.js`
`_computeOffsets`; topology — strands/crossovers/extra_bases — fully preserved;
default 1.0 = no-op). Verified: scale 1.1 → helix0-helix1 dist 2.25→2.475 nm
(×1.1), topology unchanged, original design unmutated.

**Arm:** `expand1p1_min24k` — `--expand-scale 1.1`, 0 salt, otherwise identical to
the baseline recipe (`longmin_24000`).

| k | 0.5 | 0.1 | 0.01 | **0** |
|---|-----|-----|------|-----|
| C1' % (+10% expand) | **97.6** | **90.2** | 48.8 | **12.2** |
| C1' % (0-salt baseline) | 90.2 | 85.0 | 76.0 | 20.0 |
| WC % (+10% expand) | 87.2 | 61.5 | 17.9 | 7.7 |

**Verdict: expansion does NOT help the melt — it improves the RESTRAINED structure
but worsens the RELEASE.** At k=0.5 it is the cleanest structure of any arm (C1'
97.6, WC 87.2 — both the highest seen), and it leads at k=0.1 too: pushing helices
apart genuinely relieves real crowding while the ENM holds. **But the collapse
arrives *earlier*:** k=0.01 craters to 48.8 (vs baseline 76, salt 67 — a clear
27-pt degradation, well beyond noise) and k=0 ends at 12.2 (≤ baseline 20). The
cliff moved one stage *up* the ladder (k0.01→0 → k0.1→0.01).

**Mechanism (coherent with localization + salt):** +10% spacing relieves
steric/electrostatic inter-helix crowding (helps under restraint) but **stretches
every crossover**, storing inter-helix tension that snaps back as the restraint
weakens → earlier, harder collapse. This is the *opposite* trade-off from salt,
which relieved the same crowding by **screening** (no mechanical penalty) and so
was the lever that actually saved the endpoint. Two arms, same crowding relief at
high k, opposite endpoint outcomes — isolating *mechanical penalty* as the
discriminator.

**Takeaway:** the cure is to reduce inter-helix electrostatic/steric pressure
*without adding geometric strain* → screening (salt/Mg), not pre-expansion. A
smaller expansion (1.05) would only be a weaker version of the same losing
trade-off; not worth a cycle. (Diagnostic bonus: that +10% spacing nearly perfects
the k=0.5 structure confirms the restrained bundle *is* crowded — corroborating the
global-crowding picture.)

### Cycle 4c — salt dose-response ladder (`salt050` / `salt300`, completing 0/50/150/300)

Hardens the single-point salt result (Cycle 4) into a dose-response and decides
**dominant vs one-of-two**: does k=0 keep climbing with [NaCl] (electrostatics is
*the* lever) or saturate (a 2nd global contributor remains)? All four arms share
the baseline recipe; [NaCl] on 12.5 mM Mg is the only variable.

| [NaCl] mM | 0 | 50 | 150 | 300 |
|-----------|-----|-----|-----|-----|
| **k=0 C1' %** | 20 | **40** | 44 | 48 |
| k=0.01 C1' % | 76 | 74 | 67 | 74 |
| k=0.1 C1' % | 85 | 83 | 84 | 86 |
| k=0.5 C1' % | 90 | 88 | 91 | 90 |

**Verdict: screening SATURATES at ~45% — PLATEAU branch of the decision rule.**
The first 50 mM does almost all the work (20→40, +20 — the largest single-lever
gain in the whole experiment); 50→150→300 adds only +8 *total* across a 6×
concentration increase. The Debye length at 50 mM + 12.5 mM Mg already screens most
of the inter-helix repulsion; more salt is wasted. (Within-band points 40/44/48 are
single-run, ~2.4%/pair granularity — the monotonic creep is within noise; the
saturation and the 0→50 jump are not.)

**Conclusion — the melt is TWO global contributors, ~half each:**
1. **Electrostatic (~half) — solved, cheap.** ~50 mM monovalent captures it; lifts
   k=0 from 20→40. One-line config (`ion_conc_mM` default 0→~50), no build change.
   50 mM is also far more physically defensible than 150–300 (closer to a real
   origami buffer; avoids heavy Mg–Na competition).
2. **Non-electrostatic global (~half) — UNSOLVED, the new frontier.** The residual
   ~45→90 gap is untouched by *any* salt. This is the global build-geometry /
   bundle-twist strain (hypothesis 2): the forced ligation imposing a bundle-wide
   linking/twist mismatch, and/or the ENM pinning a template B-DNA geometry the
   forcefield disagrees with. **No ionic condition reaches it.**

**Lever scoreboard (k=0 C1', 2hb baseline recipe):**

| lever | k=0 C1' | net |
|-------|---------|-----|
| baseline (0 salt) | 20 | — |
| +10% expansion | 12 | hurts |
| +50 mM NaCl | 40 | **+20 (screening, saturates here)** |
| +150 mM NaCl | 44 | +24 (diminishing) |
| +300 mM NaCl | 48 | +28 (diminishing) |
| MD-release schedule (Cycles 1–3) | 17–49 | no durable gain |

**Next (Cycle 5) — isolate & attack the non-electrostatic residual.** Cheapest
discriminator first: run a **non-strained control** design (no forced ligation, no
2xT) through the same ladder at 50 mM. If it clears 0.90 → the residual is
*specific to the strain sources* → attack the forced-ligation/2xT build geometry
(global bundle relaxation, not the local junction min — localization killed that).
If it *also* plateaus → the residual is generic ENM-template-vs-CHARMM36 mismatch →
rebuild the ENM reference from a forcefield-relaxed geometry. Either way: bake in
~50 mM salt as the settled electrostatic fix, then confirm the whole picture on 6hb.

### Cycle 5 — control discriminator + 6hb "based on learnings"

Two runs at 50 mM NaCl (the settled electrostatic fix), baseline recipe:
**`control_50mM`** = non-strained `2hb_control.nadoc` (0 forced ligations, no 2xT —
the strain sources removed, junction replaced by a normal crossover); **`6hb_salt50_min24k`**
= the real strained `6hb_2xT` with all learnings folded in (50 mM salt, min 24k,
declash auto, NO expansion). Ran at **+p16** (16 physical cores; see below).

| @ 50 mM, baseline recipe | k0.5 | k0.1 | k0.01 | **k0 C1'** |
|---|---|---|---|---|
| **2hb_control** (no strain) | 100 | 100 | 78 | **40.5** |
| 2hb_2xT (strained) | 88 | 83 | 74 | **40.0** |
| **6hb_2xT** (strained) | 91 | 88 | 78 | **56.0** |
| 2hb_2xT, 0 salt (reference) | 90 | 85 | 76 | 20.0 |

**Finding 1 — the residual melt is GENERIC, not strain-specific (the big reframe).**
The non-strained control melts at k=0 to **40.5%** — *statistically identical* to the
strained 2hb_2xT (40.0%). **Removing the forced ligation + 2xT changes the k=0
endpoint by ~nothing.** The strain sources that motivated all of exp29 are **not** the
k=0 melt driver. (Note the control is actually *cleaner* at high restraint — k0.5/k0.1
C1' = 100 — but converges to the same melted endpoint, ruling out strain as the
endpoint cause even more sharply.)

**Finding 2 — bundle SIZE is the lever the control implicated.** 6hb_2xT holds k=0 at
**56%** vs 2hb's 40% (+16). More helices = more cooperative base-pairing = better
survival at true-zero restraint. This **confirms the long-standing 2hb-proxy-harshness
caveat**: the 2-helix bundle has too few WC pairs to stay paired unrestrained,
independent of strain. The melt we've chased in the 2hb harness was **substantially a
small-bundle artifact**, not the forced-ligation pathology.

**Finding 3 — the electrostatic fix transfers to 6hb.** 50 mM salt + 6 helices reaches
k=0 C1' 56, climbing the ladder: baseline 2hb 0-salt 20 → +salt 40 → +bundle-size 56.
Each lever is additive. **But still short of the 0.90 gate at true k=0** even for
6hb+salt in this fast (0.3 ns/stage) harness — the final 0.01→0 removal still costs
~22 pts (78→56). The original 6hb production failure that motivated exp29 was a *WC*
gate failure at **k=0.1** (a different, earlier event than this k=0 C1' melt); a
clean cross-protocol comparison needs the full 4.8 ns/stage production run.

**Revised driver decomposition of the k=0 melt (2hb→6hb, fast harness):**
1. **Electrostatic** (~+20, 2hb 20→40): screening, solved cheap (~50 mM).
2. **Small-bundle instability** (~+16, 2hb→6hb 40→56): NOT a fixable build defect —
   an artifact of the 2-helix proxy; real designs are larger.
3. **Residual to gate** (~56→90): the final-removal transient + whatever keeps even a
   6-helix bundle from holding true-zero restraint in 0.3 ns. Open.
4. **Forced-ligation / 2xT strain: NOT a measurable contributor to the k=0 endpoint**
   (Finding 1). [The earlier-cycle hypotheses 1/2 about junction/bundle strain are
   downgraded for the *endpoint*; the strain may still matter for the k=0.1 WC event
   that was the original production symptom — that is a separate question.]

**Open / next:**
- The k=0 gate may be the wrong target. 6hb holds k=0.01 at 78% C1'; if production
  hands off to long-equilibration MD (or CG) at low-but-nonzero k rather than true
  zero, the "melt" is moot. Worth deciding before more prep tuning. (Domain call.)
- Definitive test of the fix = 6hb_2xT at 50 mM through the **full 4.8 ns/stage
  production protocol** (slow at ~24 ns/day: ~4–5 h/stage; an overnight run).
- Salt is saturated (Cycle 4c); do not re-ladder it on 6hb expecting more.

**Performance / 16-core note.** `run_cycle.py` `--threads` default raised 8→16 (Ryzen
9 9950X, 16C/32T; `+p16 +setcpuaffinity` = one thread/physical core, no SMT
contention). The 6hb arm here was (re)launched at **+p16** (verified live flag) and
ran at **~24–26 ns/day** for the ~80k-atom 6hb system. A clean 8→16 speedup number
was *not* measured (no controlled same-system benchmark); for single-GPU NAMD3
GPU-resident the CPU gain is often modest, but 16 physical cores is the right ceiling
and costs nothing. All future harness runs inherit the new default.

<!-- Append one subsection per cycle: what was varied, the per-stage C1'/WC curve,
     where it first failed, and the takeaway. Keep the "real lever" diagnosis
     updated as evidence accumulates. -->
