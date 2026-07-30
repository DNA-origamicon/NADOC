---
name: crossover-catenation
description: "Crossover extra bases were built topologically CATENATED (Gauss Lk = ±1) at reciprocal pairs. Detector + hard build gate + verify-and-repair in the bridge minimiser. Read before touching extra-base placement or the joint solve."
metadata:
  node_type: memory
  type: project
---

# Catenated crossover junctions — detector, gate, repair

**Status 2026-07-28: FIXED and gated.** Every design screened is clean, including 24hb_2xT
(170 reciprocal pairs). MD-validated on 2hb (see below); 6hb in progress (`experiments/exp45_extra_base_catenation/`).

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

## MD validation (exp45, 2026-07-28)

Two arms per design, identical but for the seed: **fixed** (repaired) vs **catenated**
(repair off + `allow_catenated_seed=True`). Local RTX 3080 Ti, equilibrium-aware ladder,
4 fs with Fix B applied explicitly.

| arm | seed | through minimisation + k=0.5 + k=0.1 |
|---|---|---|
| 2hb_1xT fixed | unlinked, G = −0.19 | unlinked, \|ΔG\| ≤ 0.02 |
| 2hb_1xT catenated | linked, G = +0.67 | linked, \|ΔG\| ≤ 0.08 |
| 2hb_2xT fixed | unlinked, G = −0.16 | unlinked, \|ΔG\| ≤ 0.04 |
| 2hb_2xT catenated | linked, G = +0.58 | linked, \|ΔG\| ≤ 0.09 |

No strand passage in any arm. The control never unlinks, the repaired arm never links —
the topological-invariance argument confirmed in simulation, not just asserted.

### The closed Lk is NOT trustworthy on a thermalised frame

`2hb_2xT/catenated` read Lk = +1 → 0 → −1 across three stages. That is **a closure
artefact, not strand passage**: these are open backbone arcs closed by an artificial
straight chord, and once MD jiggles the structure the chord can sweep across the partner,
flipping Lk by exactly ±1 — with **zero integrality residual**, so the `lk_residual`
ambiguity check does not catch it.

The fix is `g_open`, the same Gauss double integral over the *unclosed* arcs. It is a
continuous function of the coordinates, so it cannot jump without atoms moving: a real
passage shifts it by ~1, thermal motion by ~0.05. It also separates the arms cleanly
(≈ −0.17 unlinked vs ≈ +0.6 linked).

**So: the SEED measurement establishes whether a pair is catenated (the build closure is
well conditioned — every noT design returns 0); the TRAJECTORY measurement establishes
whether that ever CHANGED.** `catenation_in_frame(..., reference=<seed gauss_open>)`
reports `delta_g` and a `changed` flag for exactly this.

Two harness traps worth remembering: segment names sort **alphabetically**, so
`..._p100` precedes `..._p50` — chronological ordering must be explicit; and running heavy
Python builds alongside NAMD starves its `+p16` threads badly enough to halve throughput.

## 2026-07-29 — the 200 ns 1xT ensemble measures where an insert BELONGS (exp46)

`experiments/exp46_xb_placement/` (full write-up in its `REPORT.md`) measured the
equilibrium insert pose from job `29c5b267380f` (2hb_1xT, **200 ns free k=0**, 4 fs+HMR,
20 000 frames; 2hb_1xT = ONE reciprocal pair, one T on each crossover). Reported in the
builder's own chord frame but with the bow referenced to the **chemical hop** (3′ exit →
5′ entry) instead of `half_a → half_b`, C1′ equilibrates at

| | t along C3′(src)→C5′(dst) | bow | ax |
|---|---|---|---|
| **MD 20–180 ns, pooled** | **+0.57 ± 0.05** | **−0.31 ± 0.11** | \|ax\| 0.27, sign not transferable |
| pure arc seed | 0.72 / 0.79 | **+0.65 / −0.67** | −0.20 / +0.19 |
| full build (after the joint solve) | 0.65 / 0.63 | −0.28 / −0.23 | −0.27 / +0.26 |

(units = fractions of the chord L ≈ 9.1 Å. P sits at t 0.17, bow −0.17.)

**Why this belongs in this file: it explains the frustration the repair ladder is
cleaning up.** `bow_dir = cross(half_a → half_b, avg_axis)`, and `half_a` is only the
order the record stores its halves in — so the seed side is arbitrary, and **the builder
seeds both inserts of every reciprocal pair on the SAME physical side** (verified 28/28
pairs in 6hbx100_1xT, and on 2hb_1xT/2hb_2xT/6hb_2xT/6hbS42_1xT/6hbx100_2xT; `half_a` is
not the 3′ exit for exactly half of all extra-base crossovers). MD puts them on
**opposite** sides — bow < 0 in **100 %** of frames for both inserts, in every sub-window
(20–100 / 20–180 / 100–180 ns all give pooled bow −0.30…−0.31). The `ax` coordinate the
arc rule already gets right; `t` is 0.15–0.22 L too far toward the 5′ entry; the bow is
~2× too far out *and* wrong-signed on half the crossovers.

**The joint solve already recovers ALL of it.** Distance of the delivered (post-solve,
post-repair) C1′ from the MD mean: **1.18 Å / 0.97 Å**, versus the ensemble's own thermal
spread of 1.51 Å / 1.99 Å (the raw arc seed is 8.77 Å / 3.85 Å away). So the *shipped*
geometry is already indistinguishable from equilibrium; only the *seed* is wrong.

### ⭐ The MD side is also the side that stops the solve catenating

The bow side can be selected with no source change, by which half is stored as `half_a`
(`half_a = dst` ⇒ `bow = −cross(hop,axis)` = the MD side; `half_a = src` ⇒ `+cross(hop,axis)`).
Screened with the repair ladder DISABLED — raw builds, catenated reciprocal insert pairs:

| design | inserts/xover | today | **−cross(hop,axis) [MD]** | +cross(hop,axis) |
|---|---|---|---|---|
| 2hb_1xT | 1 | 1/1 | **0/1** | 1/1 |
| 6hbS42_1xT | 1 | 1/3 | **0/3** | 3/3 |
| 6hbx100_1xT | 1 | 15/28 | **2/28** | 22/28 |
| 24hb_1xT | 1 | 65/159 | **5/159** | 89/159 |
| 2hb_2xT | 2 | 1/1 | 1/1 | **0/1** |
| 6hb_2xT | 2 | 10/10 | 8/10 | **0/10** |
| 6hbx100_2xT | 2 | 26/28 | 17/28 | **0/28** |

**For ONE insert, seeding on the MD side cuts raw catenation ~93 % (24hb_1xT 65→5).** Two
independent criteria — 200 ns equilibrium and Gauss linking of the L-BFGS-B linker solve —
pick the same side. **The correct side FLIPS with insert count**: for 2 inserts the other
side is clean (37→0 pairs), which is a solver observation only (no 2xT MD exists).

**Not shippable as-is:** with the MD-side seed the *post-solve* pose moves away from
equilibrium (1.18→4.88 Å, 0.97→3.05 Å) — the solve objective and the repair ranking are
tuned around today's seed. The seed also still lands at ~2× the equilibrium radius, and
`_BOW_FRAC_3D` alone cannot fix that (≈0.5 L of the arc C1′ offset comes from the template
ORIENTATION via `_extra_base_frame`'s `e_n = bow_dir`; only 0.15 L from the control point),
so the placement would have to be respecified as a pose. Trade-off: side fix ⇒ far fewer
catenated builds; pose fix ⇒ solve needs re-tuning.
**Nothing was changed — `feedback_crossover_no_reasoning` names "swap half_a/half_b by bow
direction" as a known-bad move, so this needs the user's sign-off. The in-memory half swap
in `hop_bow_experiment.py` is a MEASUREMENT device, not a proposal.**

Also from the same run: **base orientation is not a transferable constant** — the two
inserts' whole-nucleotide orientations differ by **103°** (per-insert spread 18°/26°). A
lone unpaired base at a junction is soft and multi-modal; don't bake one in.

Open from exp46: no design and no MD for **an insert on only ONE crossover of a pair**
(every 2hb variant is symmetric) — next experiment is an asymmetric 2hb through the same
protocol. And no free-MD 2-insert numbers on a verified-unlinked build.

⚠ **The 200 ns box is smaller than the solute.** NPT collapsed the carved-shell cell to
37.6 × 56.7 × 96.7 Å while the DNA spans 45–55 Å in x; DNA-to-own-periodic-image minimum
distance averages 7.0 Å, is under 3 Å in 26 % of frames and **2.2 Å throughout the last
25 ns**. The local insert pose is window-insensitive, but the global splay (helix-axis
angle 16–18°, → 33° late) and the late fraying (designed bp intact 98.7 % over 20–180 ns,
90.5 % after) are suspect. See [[project_water_shell_carve]].

⚠ Analysis trap worth keeping: with `wrapAll on` a single-atom minimum-image fix is NOT
enough here (the true solute span exceeds half the box in every dimension). Use
bond-based `unwrap(compound='fragments')` then shift each fragment by the **modal**
box offset over the base pairs it shares with an already-placed fragment —
`exp46_xb_placement/xb_map.py:FrameJoiner`. Verified by the two phosphodiester bonds each
insert bridges measuring 1.57 ± 0.03 Å across all 4 000 frames.

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

- All six geometry-lock hashes are **byte-unchanged** by the fix (verified). The repair only
  touches geometry where a pair was actually linked, and no `Examples/` design has one. If a
  golden moves, the change leaked into the shared bridge minimiser.
- The build must stay **byte-reproducible** — the ladder is a fixed, ordered search.
- The gate must never fire on the display path (`fast_bridges=True`) or the oxDNA-override
  paths; it lives in the packaging functions only.

## Where things are

- `backend/core/junction_topology.py` — connectors, reciprocal pairs, vectorised Gauss `Lk`,
  `catenation_report`, `gate_seed_topology`, plus `package_connector_rows` /
  `catenation_in_frame` for measuring a NAMD trajectory.
- `backend/core/extra_base_repair.py` — the repair ladder.
- `scripts/check_catenation.py` — Screen 0, build-only, run before spending GPU time.
- Gate sites: `md_protocols.prepare_mgh_slow_release`, `namd_package.build_namd_package`,
  `routes_md` (`allow_catenated_seed`). Recorded in every manifest as `topology_check`.
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
