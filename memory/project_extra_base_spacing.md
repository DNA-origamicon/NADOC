---
name: extra-base-spacing
description: "MD-measured interhelical spacing vs crossover extra-base count (0/1/2), and the View ▸ Adjust for Extra Bases display toggle built on it. The 2.25 nm caDNAno lattice is ~2 A tighter than equilibrium even with NO inserts."
metadata:
  node_type: memory
  type: project
---

# Extra bases widen the lattice — measured, and wired to a view toggle

**The headline, and it is bigger than the extra-base effect: a relaxed origami sits ~2 Å wider
than the 2.25 nm caDNAno lattice it is BUILT on, even with zero extra bases.** Every design in
NADOC is therefore displayed ~9 % denser than it actually equilibrates. Extra bases add a further,
strongly **sub-linear** expansion on top. This is the frame to read any clash/declash result in:
a large part of what reads as "clashing" is the built lattice being tighter than B-DNA equilibrium,
not the inserts.

## The measurement (2026-08-05)

Archived unrestrained NAMD production trajectories, two **matched-control** series — designs
identical apart from their crossover inserts:

| series | helices | crossovers | carrying inserts |
|---|---|---|---|
| `24hb_{0,1,2}xT` | 24 | 384 | 338 |
| `6hbx100_{noT,1xT,2xT}` | 6 | 66 | 60 |

Mean nearest-neighbour interhelical distance, **matched MGHH-only stage** (the only apples-to-apples
comparison — see the equilibration trap below):

| extra bases | 6hbx100 | 24hb | Δ vs 0 |
|---|---|---|---|
| 0 | 24.02 Å | 23.58 Å | — |
| 1 (T) | 24.95 Å | 24.14 Å | +0.93 / +0.56 |
| 2 (TT) | 25.34 Å | 24.32 Å | +1.32 / +0.74 |

**Sub-linear**: the second inserted base adds roughly a third of what the first does. The slack
absorbs into the loop conformation rather than pushing helices apart. Do NOT extrapolate linearly
past 2 — the shipped table clamps instead.

**The small bundle expands ~1.7× more than the large one** (+0.93 vs +0.56 for one base). A
6-helix tube is laterally soft; a 24-helix block's interior helices are pinned by neighbours on
every side. So the "per extra base" number is not a universal constant — it is bundle-stiffness
dependent. The shipped table averages the two; per-lattice-size deltas were considered and
rejected as making the display depend on helix count.

## Method (`scripts/measure_interhelical_spacing.py`)

```bash
uv run python scripts/measure_interhelical_spacing.py \
  --psf <pkg>/<stem>.psf --pdb <pkg>/<stem>.pdb --dcd <pkg>/output/<stem>_..._k0.dcd \
  --n-helices 24 --label 24hb_2xT
```
Archived job packages live under `/media/jojo/Archive/nadoc_jobs/<job>/package/<stem>_namd_solvated/`.
Use a **free** stage only — `_k0` production or `MGHH_only`; anything with `ENM` in the name is
restrained to the built geometry and will just report the lattice back at you.


C1′ atoms only. Reference = the NADOC-built DNA-only PDB in the package. **Cluster the MIDDLE
axial slab into helices, then propagate that labelling outward slab by slab**, seeding each slab's
k-means from its solved neighbour. A single global 2-D projection is NOT enough — over a 400–500 Å
bundle even mild bending smears adjacent helices together, and the first attempt silently merged
helix pairs and split others (the tell: "neighbour" pairs at 8 Å in a 22.5 Å lattice).

Two more things that were load-bearing:

- **Refine each slab-helix centroid from its duplex core only** (atoms within `r_cut` of the
  centroid), then re-assign. Inserts sit *between* helices and otherwise drag the k-means centroid
  off-axis — worse at 2 inserts than 1, which would have manufactured exactly the trend being
  looked for. A starved-cluster repair (retire the starved centre, split the fattest) is what
  finally made `24hb_2xT` converge.
- **Minimum-image every slab-helix before averaging.** `wrapAll on` in these runs, and the box
  cross-section (83 × 89 Å) barely exceeds the bundle, so the DNA is genuinely split across the
  periodic boundary.

Every run self-validates (balanced occupancy, no sub-15 Å reference "neighbours") and reports
failure rather than averaging garbage.

## Trap: most of these trajectories are NOT equilibrated

Quintile drift over each run:

| run | drift | verdict |
|---|---|---|
| `24hb_0xT` 50 ns k0 | 24.02 → 25.09 (+1.07) | **still expanding at 50 ns** |
| `24hb_2xT` 2 ns k0 | 24.20 → 24.63 (+0.44) | still expanding |
| `6hbx100_noT` 20 ns k0 | 24.33 → 24.68 (+0.35) | near plateau |
| `24hb_1xT` 5 ns k0 | flat at 26.49 | converged |
| `6hbx100_1xT` 0.5 ns k0 ×3 | flat at 25.0–25.2 | converged |

The flat ones are flat because they *continue* an already-equilibrated predecessor; the fresh ones
are still swelling. **This is why the free-production column cannot be compared across variants**
(24hb reads 0xT 25.01 / 1xT 26.48 / 2xT 24.57 — non-monotonic, purely a run-length artefact) and
why the matched MGHH stage is the number of record despite being under-relaxed in absolute terms.
Both matched-stage series agree on sign and rough magnitude, which is the real evidence.

Honest uncertainty on a Δ is **~±0.3 Å** — from the replica spread (3 × `6hbx100_1xT`: 25.01 /
25.21 / 25.09) and the stage-to-stage spread within one design — not the ±0.01–0.05 Å block SEM,
which only measures within-trajectory noise.

## What shipped — View ▸ Adjust for Extra Bases

Display-only. Toggle OFF = the as-built 2.25 nm lattice (unchanged default); ON = the relaxed
table below, chosen by the design's **largest** extra-base count (a design mixing T and TT is
adjusted as if every crossover carried TT — the lattice is one rigid frame, so the widest junction
sets the pitch).

| extra bases | spacing |
|---|---|
| 0 | 2.45 nm |
| 1 | 2.53 nm |
| 2 | 2.55 nm |

- `scene/extra_base_spacing.js` — pure table + `maxExtraBaseCount` / `adjustedSpacingForDesign`.
  15 vitest tests. **The provenance comment in that file is the primary record; keep it in sync.**
- `scene/expanded_spacing.js` — grew a `_mode` (`'manual'` = the Q slider, `'extra-base'` = this).
  **One offset channel, one writer**: reusing the existing `applyUnfoldOffsets` fan-out rather than
  adding a parallel position writer is deliberate — see `.claude/rules/unfold.md`, which calls this
  module the second implementation of that contract. A third writer would race both.
- `_desiredOn` (synchronous) vs `_active` (settles when the 300 ms animation lands): the menu pill
  and the next toggle's direction read `_desiredOn`, or a second click inside the animation window
  expands twice instead of collapsing. `_active`'s meaning was left alone — `isActive()` has other
  consumers.
- `e2e/extra_base_spacing.spec.js` asserts the resolved spacing off the module's own `[EXPAND]` log
  (noT → 2.45, 2xT → 2.55) plus real bead movement. It copies its fixtures because **the library
  hides `__`-prefixed files**, so the usual `__e2e__` convention is unclickable here.

## Also shipped — the Bezier arc is now the built insert pose

`build_atomistic_model(..., solve_extra_base_pose=False)` is the new default. Inserts stay exactly
where the bowing quadratic Bezier put them — the same arc `crossover_connections.js` draws — and
only the phosphodiester linker is minimised to close O3′→P. The per-insert rigid-body L-BFGS-B
joint solve (`_minimize_{1,2,3}_extra_base`) that used to drag them off that arc is opt-in.

Why the default flipped: that solve optimises against a **static** repulsion snapshot that never
contains the partner crossover's inserts, so it is the dominant source of catenated junctions and
ring-threaded bonds. Measured across a full helical turn on the reciprocal fixture, raw (repair
disabled): joint solve **7/14** phases catenated, arc pose **2/14**, and the solve additionally
threads 3 covalent bonds through nucleotide rings where the arc pose threads none.

**The catenation repair is still armed on the arc path — this is load-bearing.** The arc pose is
*not* unconditionally unlinked (2/14 above; the residual comes from the exact linker minimiser
routing the phosphodiester through the partner strand, not from the insert pose). With the repair
armed the sweep measures 0 at every phase and insert count. See [[crossover-catenation]] for the
full pose × linker table.

Pinned by 4 tests in `tests/test_atomistic.py`; the arc-pose oracle is the independent
`fast_bridges` branch, which has always used the arc, with the solved pose as a live control.

## Open

- **The 2-base value rests on one matched comparison per design, both under-relaxed.** A longer
  `24hb_2xT` run and a k0 production for `6hbx100_2xT` would pin it. Deferred by choice.
- Whether the 0-base baseline (2.45 nm) should become the *build* lattice rather than a view
  toggle is untouched — that would change every design's geometry, not just its display, and
  `HONEYCOMB_LATTICE_RADIUS` is a locked constant.

## Related

[[crossover-catenation]] (extra-base placement + the joint solve) · [[extra-base-4fs-geometric-fixb]]
(seeding these same designs for NAMD) · [[clash-detector]]
