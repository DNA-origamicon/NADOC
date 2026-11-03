# What was wrong — supporting detail

[Topic head](../../project_crossover_catenation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
