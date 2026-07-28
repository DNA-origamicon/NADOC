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
