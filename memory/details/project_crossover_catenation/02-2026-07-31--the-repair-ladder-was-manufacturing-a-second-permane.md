# ⭐ 2026-07-31 — the repair ladder was manufacturing a SECOND permanent defect: THREADED RINGS — supporting detail

[Topic head](../../project_crossover_catenation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

Two large blocks of finished work live in [project_crossover_catenation_archive.md](../../project_crossover_catenation_archive.md) —
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
