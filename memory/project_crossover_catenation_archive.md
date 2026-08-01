---
name: crossover-catenation-archive
description: "History for [[crossover-catenation]] — the exp45 MD validation of the catenation fix and the exp46 200 ns insert-pose measurement. Never read in a routine loop; mine it for a specific past decision."
metadata:
  node_type: memory
  type: project
---

# Crossover catenation — archive

History split out of [[crossover-catenation]] on 2026-07-31 when the head passed the
~200-line budget. The head keeps the current state, the fix, the detection rules and the
open items; everything below is completed work, kept for the measurements it records.

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

