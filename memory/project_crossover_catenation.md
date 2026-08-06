---
name: crossover-catenation
description: "Crossover extra bases can be built topologically CATENATED (Gauss Lk = ±1) at reciprocal pairs. Detector + hard build GATE. The repair and the joint solve were DELETED 2026-08-05 — a linked phase is now refused, not fixed."
metadata:
  node_type: memory
  type: project
---

# Catenated crossover junctions — detector and gate

> **⚠ SUPERSEDED IN PART, 2026-08-05.** Everything below about the *joint solve* and the
> *verify-and-repair ladder* describes code that **no longer exists**. Extra-base positions are now
> a straight read of the CG representation and nothing modifies them afterwards
> (`extra_base_repair.py`, `_minimize_{1,2,3}_extra_base` and `solve_extra_base_pose` are deleted —
> see [[extra-base-spacing]]).
>
> **What still holds:** the detector, the Gauss-Lk measurement, the reciprocal-pair analysis, and
> the **build gate** (`gate_seed_topology`), which is now the only protection. **What changed:** a
> linked junction is **REFUSED** rather than repaired. Measured after the purge: 3 of 14 phases on
> the reciprocal fixture link (T bp16, T bp18, TT bp16), and TT/bp8 threads 2 covalent bonds through
> rings. Those designs cannot be packaged until their crossover phase changes.
>
> Read the rest as history — it is why the gate exists and how the defect behaves, not a
> description of the current builder.

**Status 2026-07-28: catenation FIXED and gated.** Every design screened is clean, including
24hb_2xT (170 reciprocal pairs). MD-validated on 2hb (see the archive); 6hb in progress
(`experiments/exp45_extra_base_catenation/`).

**Status 2026-07-31: a SECOND permanent defect of the same family — a covalent bond built
through a nucleotide RING — was found, and the catenation repair itself was manufacturing it.**
Detector + ranking term + gate shipped; every design in the workspace now builds with 0 of both.
See the ⭐ section below; that is the one to read if you are here about extra-base geometry.

## What was wrong

At an antiparallel **reciprocal** crossover pair — two crossovers at adjacent bp between the
same two helices, 3′ exits on OPPOSITE helices — a pair carrying inserted extra bases was
built with its two backbones **wound around each other**: Gauss linking number `Lk = ±1`
(occasionally ±2) instead of 0.

Both chain ends are covalently pinned into the origami network, so the entanglement is not
something relaxation undoes. Measured on the archived pre-fix 2hb_1xT run: `Lk = +1` at the
seed and **unchanged through minimisation and every ENM stage**. It is invisible to the
health checks — that same run reported `c1_paired_fraction = 1.0`, `wc_ref_relative ≈ 0.97`.

Prevalence in the geometric build, before any MD:

| design | reciprocal pairs | catenated |
|---|---|---|
| any `*noT` | 28 | **0** |
| 6hbx100_1xT | 28 | 15 |
| 6hbx100_2xT | 28 | 26 |
| 6hb_2xT | 10 | 10 |
| 24hb_1xT / 24hb_2xT | 170 | (clean after fix) |

**Consequence for past results: any stiffness/twist/curvature measured from an extra-base
design before 2026-07-28 is suspect.** A topologically pinned junction mimics a soft
rotational hinge. The `extra_base_co` numbers in `snupi_params.json` were extracted from
24hb_2xT and should be re-derived on a verified-unlinked ensemble.

## Root cause — the joint solve, NOT the pose

The decisive measurement: building with `fast_bridges=True` (which skips the L-BFGS-B joint
solve and closes the linkers with the cheap bridge) gives **zero catenation at every helical
phase**. So the Bezier arc placement and the `_align_glycosidic` swing are *not* the cause —
`_minimize_{1,2,3}_extra_base` is. Its objective is bond lengths + angles + glycosidic
alignment + a repulsion term acting only on `C1'/C3'/C4'` against a **static** `repel_pos`
snapshotted before the solve, which never contains the partner crossover's inserts. So it
freely routes the O3′/P/O5′ linker through the partner strand.

### ⚠ Refinement 2026-08-05 — the joint solve is the DOMINANT cause, not the only one

The `fast_bridges` result above is correct, but it confounds two independent changes: that path
swaps the linker closure **as well as** skipping the solve. Separated, on `_reciprocal_design`
across a full turn (7 phases × {T, TT} = 14 builds, repair disabled so the raw pose is visible):

| insert pose | linker closure | catenated |
|---|---|---|
| joint solve | exact (`_minimize_backbone_bridge`) | **7 / 14** |
| Bezier arc | exact (`_minimize_backbone_bridge`) | **2 / 14** (T bp=12, TT bp=16) |
| Bezier arc | cheap (`_interpolate_backbone_bridge`) | **0 / 14** |

So **`_minimize_backbone_bridge` is a second, smaller catenation source in its own right** — it
routes the *phosphodiester linker* through the partner strand even when the inserts themselves
never left the arc. "Arc pose ⇒ unlinked" is FALSE as a general statement; it holds only when the
cheap interpolated linker is used too, which is the display path, not the MD path.

Consequence, and why the current default is what it is: **the joint solve is now opt-in**
(`build_atomistic_model(..., solve_extra_base_pose=True)`, default False — see
[[extra-base-spacing]]). The MD/seed path places inserts at the arc pose but keeps the **exact**
linker minimiser (NAMD needs those bond angles — a collapsed bridge angle divides by sin θ), so it
sits on the 2/14 row. **That is why the repair below is armed on the arc path too.** With it armed
the full sweep measures 0 catenated at every phase and insert count. Do not "simplify" by skipping
the repair on the grounds that the arc pose is clean — it is not.

Ring piercing tracks the same split: the solve threads 3 covalent bonds through nucleotide rings on
`TT`/bp=8, the arc pose threads none. `tests/test_ring_piercing.py` therefore has to opt INTO the
solve to have a defect to gate on.

**Catenation is helical-phase dependent** (flips sign and on/off with crossover bp) — which is
why ~half a design's pairs were hit, and why a fixture pinned to one bp proves nothing.

## The fix — verify and repair (`backend/core/extra_base_repair.py`)

No single tightening is a guarantee (2 inserts still link at one phase even at
`|Δ| ≤ 0.04 nm`), and no pose is a guaranteed-unlinked fallback either (n ≥ 4 links even
at the pure arc pose). So the builder **measures Lk per reciprocal pair after the solve**
and, when linked, retries through a deterministic ladder.

**The retry knob is the SPIN seed, not a bound.** Each insert's spin DOF rotates about
`target_c1n` — the very axis `_align_glycosidic` aligned C1′→N to — so
`_glycosidic_cost_grad` returns cost 0 and zero gradient for *every* θ. The objective is
indifferent to the seed: re-seeding cannot bias the converged geometry, it only changes
which local basin L-BFGS-B falls into. A translation bound, by contrast, constrains the
optimum and measurably degrades the linker. Measured (clashes, unrepaired → repaired):

| | 2hb_1xT | 2hb_2xT |
|---|---|---|
| bound ladder | 2 → 2 | 6 → **10** |
| **spin seeds** | 2 → **0** | 6 → **5** |

Spin re-seeding leaves the structure with **fewer clashes than the unrepaired build** —
a different basin is often a better minimum of the same objective. Across every design
screened the delta-cap backstop and the arc last-resort never fired; 2–12 of 16 spin
seeds sufficed.

Order: 16 spin seeds (seed 0 = today's behaviour exactly, so clean pairs and unpaired
crossovers stay bit-identical) → bounded translation → pure arc pose. Among unlinked
attempts the ranking prefers sound linker geometry, then fewest surrounding clashes, then
attempt order. Only a **fatally** degenerate linker is excluded (collapsed bridge angle:
NAMD's angle force divides by sin θ).

Three design errors found and corrected by measurement while building this — all worth
remembering:
- taking the FIRST unlinking rung doubled 2hb_2xT's clashes (6 → 13);
- ranking purely on inter-connector separation pushed inserts into neighbouring helices
  (2hb_1xT 2 → 6). Separation is the wrong objective: at a reciprocal crossover the two
  backbones *belong* in contact, and unlinked pairs are measurably **closer** than linked
  ones, so proximity is anti-correlated with the defect;
- making linker geometry a **filter** let it veto the only unlinking rung, leaving the
  pair catenated and the whole build refused. It must rank, not exclude — strain relaxes
  out, a linking number never does.

## ⭐ 2026-07-31 — the repair ladder was manufacturing a SECOND permanent defect: THREADED RINGS

**Symptom:** on the `2hb_2xT` relaxation (job `c8c4a87e2033`, archived) a phosphate bond visibly
runs through the ribose ring of another extra crossover base. **Root cause: the repair ladder
above.** Measured on that exact design.json:

| build | catenated | ring-pierced |
|---|---|---|
| raw (repair OFF) | **1/1** | 0 |
| shipped (repair ON) | 0 | **1** |
| display path (`fast_bridges=True`) | 0 | 0 |

The ladder took rung 11 — the FIRST rung that unlinks (spin `(π, 3π/2)`; reported as
`attempts: 12`, which is 1-based) — and stopped there because `penalty == 0` and
`clashes 17 ≤ baseline 34`. The early exit never reached rung 15 (spin `(3π/2, 3π/2)`), which is
**strictly better on every axis**: unlinked, unpierced, 11 clashes, `separation_nm` 0.136 vs
0.072. That is the rung the fixed ladder now picks (`attempts: 16`).
The bond threaded is the inter-insert phosphodiester `O3'(xb0) – P(xb1)` of one crossover,
through the **sugar of the partner crossover's insert**.

The full rung table for this pair (mid-build, both measures) is worth keeping — it shows the
defect is not rare among rungs and that the ladder had a clean one available all along:

| rung | 0–10 | 11 | 12–14 | **15** | 16–18 (Δ0.12) | 19–20 (Δ0.06/0.03) | 21,23 (arc a) | 22 (arc b) |
|---|---|---|---|---|---|---|---|---|
| catenated | yes | no | no | **no** | no | no | no | no |
| pierced | 0 | **1** | 2 | **0** | 2–4 | 0 | 1 | 0 |
| separation nm | — | 0.072 | 0.02–0.06 | **0.136** | 0.02–0.04 | 0.013–0.037 | 0.010 | 0.043 |

**Why nothing caught it.**
- **Gauss `Lk` provably cannot see it.** The connector polyline is `P, O5', C5', C4', C3', O3'`
  — the direct C4'→C3' step. The sugar ring closes through the *other* path
  (C4'-O4'-C1'-C2'-C3'), so it is entirely off-curve and threading it changes no linking number.
  The two measures are complementary, not redundant — see the table above.
- **The clash counters cannot either.** A sugar ring is ~4.6 Å across, so a bond through its
  centre keeps every ring atom 2.2–2.6 Å away — above `extra_base_repair._CLASH_NM` (0.30 nm)
  for part of the ring and far above `atomistic_validation.CLASH_NM` (0.08 nm) for all of it.
  In the ladder's own score the pierced rung looked like an *improvement* (34 → 17 clashes).

**What relaxation does to it (why it is not "just strain").** In the raw seed the bond is a
correct 1.60 Å with a ring atom 1.32 Å away. The 10 000-step declash minimisation cannot pull
the bond out of the ring, so it relieves the overlap the only way left — by **stretching the
covalent bond to 3.08 Å** (~250 kcal/mol, CHARMM36). It was still 2.98 Å after the full ladder
to unrestrained MGHH, the **longest heavy-atom bond in the DNA** in the final frame, and the
ring atom never moved past 2.21 Å. Note 2.98 Å slips *under*
`atomistic_validation.BACKBONE_STRETCH_NM` (0.30 nm) — and `audit_bonds` is not called on the
NAMD path anyway (only from `routes_oxdna`), so nothing downstream flagged it either.

**Prevalence, before the fix** (raw build → shipped build, whole workspace):

| design | pairs | cat raw | pierce raw | cat shipped | **pierce shipped** |
|---|---|---|---|---|---|
| 2hb_1xT | 1 | 1 | 0 | 0 | 0 |
| 2hb_2xT | 1 | 1 | 0 | 0 | **1** |
| 6hb_2xT | 10 | 10 | 0 | 0 | **5** |
| 6hbS21_2xT / 6hbS42_2xT | 1 / 3 | 1 / 3 | 0 | 0 | 0 |
| 6hbx100_1xT | 28 | 15 | 0 | 0 | 0 |
| 6hbx100_2xT | 28 | 26 | 3 | 0 | **18** |
| 24hb_1xT | 159 | 65 | 6 | 0 | **6** |
| **24hb_2xT** | 159 | 138 | 51 | 0 | **131** |

Two things to take from it: the defect is overwhelmingly a **2xT** phenomenon (two inserts give
the solve a second rigid body *and* an inter-insert bond to route through something), and the
repair pass **multiplies** it (24hb_2xT 51 → 131). 24hb_1xT shows the raw build can pierce on
its own at scale, so this is not purely a repair artefact.
**Consequence: any ensemble built from a 2xT design before 2026-07-31 may carry threaded rings.**
Screened directly on the shipped packages with `scripts/check_ring_piercing_frame.py` (measures
the PSF + coordinates a job actually ran, not a rebuild):

| archived job | package seed | threaded rings |
|---|---|---|
| `336a067ba241` — 24hb_2xT, the "validated 2xT" package | `24hb_2xT_build.pdb` | **51** |
| `83a8ed8ded0e` — 24hb_1xT, the validated 1xT package | `24hb_1xT_build.pdb` | **6** |
| `c8c4a87e2033` — 2hb_2xT, 2026-07-31 | `2hb_2xT_build.pdb` | **1** |

So the `extra_base_co` parameters were extracted from an ensemble with **51 permanently threaded
rings** — a second, independent reason those numbers need re-deriving (the first is in the header
of this file). The 2hb_2xT run is unusable for junction observables outright: it has exactly one
reciprocal pair and that pair is the one that was pierced.

### The fix

- **`backend/core/ring_piercing.py`** (new) — segment/ring Möller-Trumbore over a fan
  triangulation of every sugar and base ring. `model_piercings` / `piercing_report` /
  `assert_not_pierced` for a whole model; `PierceScope` is the cheap re-measurable
  neighbourhood scope the ladder uses per rung (indexes rings + name-derived bonds once,
  re-reads coordinates per call; radius 1.2 nm, so a rung that shoves a linker into a
  *neighbouring duplex* residue is seen too — 6hbx100_2xT had exactly that).
- **`extra_base_repair.repair_catenated_pairs`** — a pair is now "defective" if it is linked
  **or** pierced, and the rung score is `(pierced, penalty, clashes, n_try)`. Piercing is
  RANKED, not excluded, for the same reason the geometry penalty is: if every rung pierces,
  ship the least-bad one and let the gate refuse it rather than silently leave it catenated.
  The early exit now requires `pierced == 0` as well as `penalty == 0` — that alone is what
  would have taken rung 16 instead of rung 12 on `2hb_2xT`.
- **`gate_seed_topology`** — refuses a pierced seed exactly as it refuses a catenated one, at
  the same single choke point (`md_protocols`, `namd_package`, `namd_vacuum`), and records
  `n_ring_pierced` + `ring_pierced` in `manifest.json → topology_check`.
  `allow_catenated_seed=True` overrides both.
- **`scripts/check_catenation.py`** — screens a *design* for both defects off one build (the
  pre-GPU gate). **`scripts/check_ring_piercing_frame.py`** (new) screens an already-built
  structure — a job's packaged PSF + seed PDB, a `.coor`, or a whole DCD — which is how the
  archived runs above were audited and how to decide whether an existing run's data is usable.

After the fix, every design in the table above builds with **0 catenated and 0 pierced**, and
the synthetic reciprocal fixture is clean at **every phase** of a full helical turn for both
insert counts (pre-fix: TT pierced at 6 of 11 phases, T at 1). On `2hb_2xT` the chosen rung is
better than the pre-fix one on all three axes at once (clashes 17 → 11, separation 0.072 →
0.136 nm, pierced 1 → 0), so this is not a quality trade.
Tests: `tests/test_ring_piercing.py` (geometry primitive, hand-built model, gate, and a
`_piercing_check_disabled()` positive control that reproduces the pre-fix ranking on demand).

### ⚠ Two traps in inferring connectivity mid-build — both produced silent wrong answers

The ladder measures *before any bond list exists*, so `PierceScope` derives connectivity from
atom names + geometry. Two ways that went wrong, each caught only by cross-checking the scoped
detector against `model_piercings` on **identical final coordinates**:

1. **Chain adjacency is not connectivity at an extra-base crossover.** Linking `O3'(seq i)` to
   `P(seq i+1)` invents an ~0.8 nm bond straight across the junction — the inserts sit between
   those two duplex residues, and mid-build the inserts are not yet numbered into the chain at
   all (they are appended at the end: chain A duplex 1–14, inserts 15–16, vs 8–9 in the final
   model). That phantom "pierced" every ring near the crossover and made three sound rungs —
   **including the winner** — look defective, pushing the ladder onto a Δ-cap rung with 10× less
   backbone separation. Infer the phosphodiester as *nearest P within 0.40 nm of each O3'*.
2. **Connectivity cannot be frozen at index time.** A rung moves whole inserts, so which P an
   O3' bonds to changes with the rung. Caching the bond list when the scope was built dropped
   the bond a later rung created, and one threaded junction in `6hb_2xT` went unseen by the
   ladder while the whole-model gate still refused the build. Only the *intra-residue* half is
   geometry-independent; re-derive the links on every measurement.

Both bugs are pinned by named regression tests. **If the ladder and the gate ever disagree
again, this is where to look first** — the gate uses the real `model.bonds` and is the authority.

## Completed history → archive

Two large blocks of finished work live in [project_crossover_catenation_archive.md](project_crossover_catenation_archive.md) —
**don't open them in a routine loop**:

- **exp45 (2026-07-28) — MD validation of the catenation fix.** Two arms per design (repaired vs deliberately catenated) through minimisation + ENM; no strand passage in any arm, the control never unlinks and the repaired arm never links. Also records why the **closed** Lk is untrustworthy on a thermalised frame (a closure artefact flips it ±1 with zero integrality residual) and that `g_open` is the measure to use on a trajectory.
- **exp46 (2026-07-29) — where an insert BELONGS, from the 200 ns 1xT ensemble.** The equilibrium insert pose, the finding that the builder seeds both inserts of a pair on the SAME physical side while MD puts them on opposite sides, that the joint solve already recovers all of it (delivered C1' within 1.2 A of the MD mean), and that the MD-side seed would cut raw catenation ~93% for ONE insert but is **not shippable** without re-tuning the solve. Includes the ⚠ that that run's NPT box collapsed below the solute width.

## Detection: use f_hi, never the modal crossing number

The closure-free channel (PCS) projects the two arcs along 64 directions and counts signed
crossings per view. **The verdict statistic is `f_hi`** — the fraction of views showing two
or more crossings — **not the modal crossing number.** Measured on a real wound junction,
the crossing distribution straddles 1 and 2 (`{0:1, 1:29, 2:34}` over 64 views), so the
mode flips with orientation: `2, 2, 1, 1, 1, 2` across six rotations. A rule of
`|n_mode| >= 2` therefore scores a wound junction **clean in half of all orientations** —
a false negative on the primary channel. `f_hi` over the same rotations stayed in
0.453-0.562 (wound) vs 0.000-0.016 (clean), so the threshold sits at 0.15 in the empty
middle. `n_mode` is still reported, as a diagnostic only.

Symptom that this is wrong again: spurious `ambiguous` verdicts. While the rule used
`n_mode`, 6hbS42_1xT and 6hbS42_2xT each reported one ambiguous pair — that was the two
channels disagreeing because of the mode instability, not real ambiguity. Switching to
`f_hi` removed them and made the unrepaired counts match ground truth exactly
(6hbx100_1xT 15/28).

## Invariants to preserve

- All six geometry-lock hashes are **byte-unchanged** by the fix (verified, and re-verified
  2026-07-31 by rebuilding at `e810dd8` and `e810dd8^` — identical). The repair only touches
  geometry where a pair was actually linked, and no `Examples/` design has one. If a golden
  moves, the change leaked into the shared bridge minimiser.
  - **This fix was twice blamed for a failure it did not cause.** `3093b83` regenerated two
    goldens "after the catenation fix" and `ce1ef35` reverted them; the real cause was BLAS
    kernel dispatch differing between the two dev computers, not any commit. See
    [[LESSONS]] H19. `test_atomistic_geometry_lock.py` no longer hashes solver-placed atoms
    at all, so it can no longer implicate this fix that way — but the invariant above still
    holds and is still the right thing to check.
- The build must stay **byte-reproducible** — the ladder is a fixed, ordered search.
- The gate must never fire on the display path (`fast_bridges=True`) or the oxDNA-override
  paths; it lives in the packaging functions only.

## Where things are

- `backend/core/junction_topology.py` — connectors, reciprocal pairs, vectorised Gauss `Lk`,
  `catenation_report`, `gate_seed_topology`, plus `package_connector_rows` /
  `catenation_in_frame` for measuring a NAMD trajectory.
- `backend/core/extra_base_repair.py` — the repair ladder (scores BOTH defects).
- `backend/core/ring_piercing.py` — the threaded-ring detector: `model_piercings` /
  `piercing_report` / `assert_not_pierced` on a model, `PierceScope` for the ladder.
- `scripts/check_catenation.py` — Screen 0, build-only, run before spending GPU time; reports
  catenation AND piercings off one build.
- `scripts/check_ring_piercing_frame.py` — screens an already-built structure (a job's PSF +
  seed PDB / `.coor` / DCD), for deciding whether an existing run's data is usable.
- Gate sites: `md_protocols.prepare_mgh_slow_release`, `namd_package.build_namd_package`,
  `namd_vacuum`, `routes_md` (`allow_catenated_seed` overrides BOTH defects). Recorded in every
  manifest as `topology_check`, now with `n_ring_pierced` + `ring_pierced`.
- `audit_bonds` gained `catenation` + `ok_including_topology` (its `ok` is unchanged).

## Open / adjacent

- **`n ≥ 4` inserts are NOT repaired** — there is no joint solve to bound, so the ladder has no
  lever. Rare (real designs use 1–2), and the gate refuses it rather than shipping it.
- **Fix B is not applied by the normal prep path.** `md_protocols` calls `write_hmr_psf` without
  `heavy_residues`, so an extra-base design prepped through the UI gets standard HMR, which
  *lightens* the dangling bases — the failure mode `project_extra_base_4fs_geometric_fixb`
  documents. Only `prep_24hb_seeded.py` (and now the exp45 harness) does it correctly.
- **`audit_bonds` crashes on 6hb_2xT** — `h.direction` is `None` at
  `atomistic_validation.py:166`. Pre-existing, unrelated.
- The oxDNA seed (`_resolve_extra_base_geometry`, straight chord lerp) has **not** been measured
  for catenation yet; unifying both engines on one placer is still open.
- **The pierced runs have not been re-run.** `2hb_2xT` (job `c8c4a87e2033`) needs rebuilding and
  relaxing from scratch — it has one reciprocal pair and that pair was the pierced one, so no
  junction observable from it is usable. `24hb_2xT` (`336a067ba241`, 51 piercings) is the source
  of `extra_base_co`.
- **The `n_ring_pierced_after` in the ladder summary is a scoped, per-pair count** taken at the
  winning rung, not a whole-model measurement — a pair cleared as a side effect of repairing its
  neighbour can read high. The manifest's `topology_check` is the authority.
- **`PierceScope` covers the reciprocal pair's neighbourhood, not the whole model.** A piercing
  between two crossovers that are not a registered reciprocal pair would be caught by the gate
  (build refused) but has no repair lever. Not observed on any design screened.
