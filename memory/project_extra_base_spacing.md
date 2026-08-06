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

## Extra-base positions are a READ of the CG representation (2026-08-05 purge)

**Everything that modified an extra base's 3D position after placement has been deleted**, and so
has the prose that described how one ought to sit. The gap between what was intended and what came
out kept widening with each attempt to specify it, so the specification was removed instead.

What the builder does now: stamp each insert's atoms on the quadratic Bezier between its two
junction nucleotides' **CG backbone positions** — same endpoints, same bow as
`crossover_connections.js` — and minimise only the phosphodiester linker. Nothing moves the residue
afterwards. Verified on 6hbx100_2xT: all 120 insert origins sit on the CG chord to **0.000000 Å**
(rigid-body fit of the ribose template; `test_extra_bases_are_placed_from_the_cg_representation`).

Deleted: `extra_base_repair.py` (the catenation re-placement ladder), `_minimize_{1,2,3}_extra_base`
and their rigid-body machinery, the `_XB_CACHE`, the `z_sign`/`target_c1n` glycosidic swing and its
static repulsion snapshot, `solve_extra_base_pose`, `GET /design/extra-base-seed`,
`designRenderer.setSeedExtraBases` and the CG insert pinning. −1735 lines.

**One thing deliberately NOT routed through CG:** the oxDNA/trajectory override path still takes its
chain direction from the real C3′/C5′ **atoms** (`chain_p0`/`chain_p1`). It orients a nucleotide
from measured `a1` against its bonded neighbours — a fact about atoms, not about where a bead is
drawn. Routing it through CG silently broke
`test_heavy_rep_extra_base_uses_full_simulated_orientation`; that test is the guard.

### ⚠ Consequence: a linked junction is now REFUSED, not repaired

With nothing adjusting positions, **3 of 14 phases on the reciprocal fixture catenate** (T bp16,
T bp18, TT bp16) and the build threads 2 covalent bonds through rings on TT/bp8. The repair that
used to drive both to zero is gone. `gate_seed_topology` still detects them, so such a design now
**raises instead of building a seed** — the defect cannot reach a trajectory silently, but the
design cannot be packaged either until its phase changes.

Tests were rewritten around the property that survives: a linked phase must be refused
(`test_a_linked_phase_is_refused_rather_than_re_placed`, `test_a_catenating_phase_cannot_reach_a_seed`).
The old "the repair guarantees Lk = 0" contract is deleted — it was a promise the code no longer
makes. `_WOUND_BP`/`_CLEAN_BP` in `test_junction_winding` exist because a wound build and a clean
one are now two different PHASES, not two settings.

## Opt-in seed pre-expansion (`seed_lattice_nm`) — still live

`POST /md/jobs` takes `seed_lattice_nm`: `null` (default, build as designed), `"auto"`, or a float
in nm. It scales a **copy** of the design's helix axes laterally about the bundle centroid before
anything reads geometry (`lattice.scale_helix_spacing`), so the topology gate, atomistic model, box
sizer and every exported map describe one structure. Saved `.nadoc` and `HONEYCOMB_LATTICE_RADIUS`
are untouched. Recorded in `manifest.json` — a trajectory from a pre-expanded seed is **not**
comparable to one that swelled into its spacing.

**Measured effect** (6hbx100; bonded-excluded insert contacts < 3 Å, O3′–P bridge p99):

| design | spacing | insert contacts | bridge p99 |
|---|---|---|---|
| noT | 2.25 → 2.45 | 0 → 0 | 2.67 → 3.09 Å ✗ |
| 1xT | 2.25 → 2.53 | 3428 → 2586 (−25%) | 1.93 → 3.18 Å ✗ |
| 2xT | 2.25 → 2.55 | 14283 → **6058** (−58%) | 2.37 → **1.80 Å** ✓ |

The benefit scales with insert count and the bridge cost **inverts**: two inserts carry enough
contour to span 2.55 nm so the bridges actually relax; one insert is stretched by 2.53; with none
there is nothing to relieve and the backbone only stretches. **That is why `"auto"` declines an
insert-free design.** Not default-on: at 1xT it is a genuine trade, so the caller picks.

(These contact numbers predate the CG-placement purge and were measured against the then-current
arc pose. The *direction* of each effect is a lattice property and still holds; re-measure before
quoting an absolute.)

## The ATOMISTIC reps show the MD seed — still live

`GET /design/atomistic?seed_lattice_nm=auto` returns the **t=0 pre-minimisation** coordinates for
the whole model. Absent the param it is the old display build, unchanged. Seed mode differs by:
exact L-BFGS-B linkers instead of `fast_bridges`' cheap interpolation (which moves the ~1.5%
phosphodiester atoms by up to 2.4 Å at junctions); no flexible-display frame override; and optional
lattice pre-expansion. Measured on 6hbx100_2xT: same 29 629 atoms, **mean 3.17 Å per-atom shift**
display → seed. ~26 s then `build_atomistic_model_cached` serves it in 0.07 s.

`atom_surface_display.setSeedLattice(nm|null)` swaps the URL and drops `_atomDataCache`;
`expanded_spacing` drives it from the toggle. **`_applyAll` must NOT also call `applyUnfoldOffsets`
on the atomistic renderer while seed mode is live** — those atoms were BUILT at the expanded
lattice and offsetting them again doubles the expansion. `isSeedLatticeActive()` guards it.
**Refused for a PDB-imported design** (409): measured coordinates that no lattice scale applies to.

### ⚠ Pre-existing: returning to t=0 FLATTENS the insert chain (0.168 nm)

`unfold_view._updateArcPositions` places the extra-base beads on the arc LINE's control point —
`dist * MAX_BOW_FRAC * t`, i.e. **straight at t=0** — while `buildCrossoverConnections` built them
at their own `BOW_FRAC_3D = 0.3`. Any return to t=0 collapses the bow. Measured **0.168 nm,
identical via the Q expand toggle**, which predates this work; unfold has it too. Not fixed: the
two modules use different bow-direction conventions and guessing is how this area goes wrong.

### The CG bead / atomistic ~5 Å register gap — DIAGNOSED 2026-08-05

CG backbone bead → atomistic P atom is **5.02 Å mean** at the design lattice (5.05 Å scaled, so the
lattice is not the cause). The bead's *nearest* atom is not consistently a backbone atom: C3′ for
632 residues (2.9 Å), O5′ for 272 (2.8 Å), but for ~350 residues it is a **base** atom — N7 at
6.1 Å, N4 at 4.6 Å, C7 at 4.4 Å.

The dedicated audit session ran. **Two independent defects**, both now measured — full write-up +
numbers + provenance in `backend/core/measured_positioning.py`, pinned by
`tests/test_measured_positioning.py`:

1. `geometry.py` flips the groove sign with the helix's lattice cell, so FORWARD cells build at
   150° and REVERSE at 210°. Both stay right-handed, so these are **not enantiomers** — they are
   two right-handed helices with the minor groove on opposite sides, one marking the major groove
   as the minor. A wrong-side-marker defect, not a wrong-molecule one, and it is confined to the
   CG bead layer (atomistic's per-cell correction equalises both). On a mixed design the P–P
   separation reads **180° ± 30°**, the ±30 being purely the cell-type split.
2. `atomistic.py`'s 208.2° correction is applied to the template **frame origin**, but the
   template's P sits 0.1887 nm off that origin and the two strands' frames are z-mirrored → the
   two phosphates rotate *toward* each other. Realised separation **183.84°**, exactly
   208.2 − 2×12.182, identical at every bp in both cell types.

Together: ~0.1 nm radial + 26–34° azimuth at r ≈ 0.93 = the 5 Å.

**Measured truth** (`scripts/measure_cg_registration.py`, free `MGHH_only` stage of job
`dbd8ad3b7d4f`, phosphate-cylinder axis fit; estimator reproduces 1ZEW at 208.5°/0.881 nm):
P **0.925 nm**, C1′ 0.566, base-ring centroid **0.324**, C1′–C1′ 1.074, rise 0.347, twist 34.21°.
The CG base bead sits at **0.714 nm** against a measured 0.324 — the largest single error found.

**The atomistic rep cannot be fixed by re-placement.** Built vs measured: P −0.023, C1′ −0.073,
base centroid +0.027 — mutually inconsistent under every whole-body transform (a rigid move onto
the P cylinder opens WC 0.309→0.355 nm; a radial affine fit to P+C1′ throws the base centroid to
0.442). It is a **template** defect → re-extraction, the never-executed recipe in
[[project_o3prime_investigation]].

Shipped: **Help ▸ New Positioning** (display-only, default OFF) re-places the *full* rep onto the
measured geometry. ⚠ `pp_separation_deg = 183.9` is **PROVISIONAL** — every trajectory in this repo
was seeded at 183.84°, so the MD cannot arbitrate it. `experiments/exp52_groove_seed_sweep`
(4 arms seeded 150/184/208/232°, solvated and queued, not yet run) is the test that settles it.

## Open

- **The 2-base value rests on one matched comparison per design, both under-relaxed.** A longer
  `24hb_2xT` run and a k0 production for `6hbx100_2xT` would pin it. Deferred by choice.
- Whether the 0-base baseline (2.45 nm) should become the *build* lattice rather than a view
  toggle is untouched — that would change every design's geometry, not just its display, and
  `HONEYCOMB_LATTICE_RADIUS` is a locked constant.

## Related

[[crossover-catenation]] (extra-base placement + the joint solve) · [[extra-base-4fs-geometric-fixb]]
(seeding these same designs for NAMD) · [[clash-detector]]
