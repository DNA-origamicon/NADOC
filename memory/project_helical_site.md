---
name: helical-site
description: "ALL phases 0-10 closed 2026-08-07 (history in [[project_helical_site_archive]]): one HelicalSite abstraction — axis point + tangent + radial + labels — that every representation (CG bead, atomistic stamp, oxDNA particle, mrDNA bead, FEM node) derives from cheaply, replacing four independent re-derivations of the same helix formula."
metadata:
  node_type: memory
  type: project
---

# One helical site, many cheap representations

**Status: CLOSED. All phases 0–10 resolved 2026-08-07** — 7 as a false premise, 8 by the owner's
"leave saved poses as-is", 9 by re-justification, 10 has no consumer. The 14.6° between junction
symmetry and MD azimuth is SETTLED in favour of symmetry (see below). **No open questions.**
Per-phase detail and every justifying measurement: [[project_helical_site_archive]].

Owner instruction: *"why not have a unified abstraction then?
From which all representations and models can be built from cheaply"* — yes, and this is what
that costs. Companion to [[project_atomistic_source_of_truth]] (whose audit table this is the
remedy for) and TD-27 in [[project_tech_debt]].

## The idea in one paragraph

A designed nucleotide's geometry is seven numbers: the point on the helix axis it belongs to,
the axis tangent there, the outward radial direction at its helical phase, and its labels
(bp index, strand, loop copy). Every representation is that site projected at some radius,
after some rotation, into some frame. Nothing needs to be built from anything else, and no
projection costs more than a few arithmetic ops per nucleotide — which is the answer to *"is
deriving CG from atomistic expensive?"*: it would be, and it is also unnecessary.

## What a site is

```
HelicalSite: helix_id, bp_index, direction, copy_k,
             axis_point (3,), axis_tangent (3,), radial_hat (3,), azimuth_rad
```

`radial_hat` is redundant with `azimuth_rad` + the helix frame, and is carried anyway: it is
what every consumer actually multiplies by a radius, and carrying it is what makes each
derivation **byte-exact** rather than ULP-close. That matters more than it sounds — see Risks.

## Every representation, as a projection

| Representation | Radius | Rotation off the site | Frame |
|---|---|---|---|
| CG backbone bead (legacy) | `HELIX_RADIUS` 1.000 | 0 (FWD) / ±150° by lattice cell (REV) | — |
| CG bead, measured mode | 0.804 | groove-registered | — |
| CG base bead | 1.000 − `BASE_DISPLACEMENT` | along the cross-strand direction | — |
| Atomistic P | `_ATOMISTIC_P_RADIUS` 0.886 | +58.2°/−1.8° by cell, then `atomistic_phase_offset_rad` | template stamp |
| oxDNA particle | CM radius | the same, plus the a1/a3 convention | (CM, a1, a3) |
| mrDNA bead | 0 (bp midpoint) | — | 3×3 orientation from (radial, tangent) |
| FEM node | 0 (on the axis) | — | — |

## Two producers, one site type

- **P1 — lattice (analytic).** DONE on both paths: `geometry.nucleotide_positions` carries
  `radial_hat` / `axis_point` / `azimuth_rad`, and `nucleotide_positions_arrays` (plus both
  `_extended` variants and the loop/skip fallback) carries `radial_hats` / `axis_points` /
  `azimuths`. It survives cluster transforms and bends — see Phase 1.
- **P2 — measured (from a position + an axis).** DONE as `geometry.site_from_bead` /
  `site_from_beads_arrays`. The AXIS is an input, not fitted: every caller has one. A
  standalone atoms→sites converter (fitting the axis too) still does not exist —
  `atomistic_to_nadoc.extract_from_pdb` reads P atoms → bead positions and nothing else, and
  the two axis fitters to reconcile are `pdb_to_design.py:521` / `pdb_import.py:843`.

P2 is what makes this a unification rather than a tidy-up: with it, a relaxed oxDNA frame, an
MD trajectory frame and an imported PDB all become sites, every representation derives from a
site regardless of provenance, and the `atomistic._phase_invalidated` special case (added
2026-08-07 — "this nucleotide moved, throw the analytic phase away") disappears, because a
moved nucleotide simply has a measured site.

## Phases 0-10 — all closed 2026-08-07

Per-phase detail, measurements and the three scope corrections: [[project_helical_site_archive]].

| # | What it did | Outcome |
|---|---|---|
| 0 | stamp reads the carried phase, not the display bead | byte-identical; bead at r=3.7 nm moves 0 atoms |
| 1 | vectorised path carries the site, survives transforms | 3220 arrays byte-identical; identity exact on 151,386 nucleotides |
| 2 | mrDNA reads the site | **bug fix**: pre-TD-29 twist on every honeycomb design, 19.99 A phase error on `6hb_test` |
| 3 | seam solver reads the axis | **bug fix**: 35 of 5549 frames were garbage on cluster-split base pairs |
| 4 | oxDNA seed HB separation | fitted 0.37 nm → published `HYDR_R0`; CM-CM error 0.0287 → 0.0005 nm |
| 5 | measured producer (`site_from_bead`) | two named producers, 1 ULP apart; `_phase_invalidated` KEPT deliberately |
| 6 | `_rigid_frame_calibration` off sites | conf round trip gone; constant moved ≤1.1e-7 nm |
| 7 | the placers | **retracted**: they read the geometric layer, not the display. No change needed |
| 8 | pose fitters | hazard closed by `fitting_geometry`; re-target dropped (saved poses stay as-is) |
| 9 | `_ATOMISTIC_PHASE_OFFSET_RAD` | decoupled by re-justification against MD; value unmoved |
| 10 | standalone atoms→sites converter | not built — no consumer. Entry point: `site_from_bead`'s axis arg |

## Explicitly out of scope

The first three items here were promoted to **Phases 7–9** above once the round-2 audit had
scoped them; they are out of scope for Phases 0–6, not out of scope for the plan. What stays
permanently out:
- Making the CG bead a literal function of atom positions. It would move the full rep by 15–46°
  (the correction chain) and cost an atom build per geometry request. The owner has ruled the
  current reps correct; siblings off one site is the design.

## ⚠ Known red: TD-30 (added 2026-08-07)

The first full-suite run since 2026-07-20 is **43 failed / 7248 passed**, 41 of them one root:
extra-base inserts thread nucleotide rings at 17 of 22 swept helical phases. **Pre-existing** —
identical on a worktree at `6076989` — and parked by owner decision for a dedicated session, so a
red slow suite here is expected, not a surprise. Full attribution in [[project_tech_debt]] TD-30.

One item there IS from this plan: the atomistic junction-balance roll took catenating phases on
the synthetic reciprocal fixture from **7/33 to 11/33**. It causes none of the failures, but it
means Phase 7's "no change needed" was right only about DISPLAY leakage — moving the duplex atoms
does move inserts relative to their neighbours' rings.

## Risks, each with its countermeasure

1. **ULP drift is not cosmetic here.** The scalar path uses `math.cos`, the array path
   `np.cos`, and they differ at the last ULP — `_strand_beads`' docstring says so. Downstream,
   the backbone-bridge L-BFGS-B solve amplifies a last-ULP change into 0.1–1.3 Å at junctions
   (LESSONS H15/H19). **Countermeasure:** each path carries the radial *it* computed; never
   share one path's value with the other, and never accept a regenerated golden as proof —
   measure the atom displacement directly, as Phase 0 did (0.000e+00 nm).
2. **The skip fallback splits the paths.** `nucleotide_positions_arrays` delegates
   loop/skip-bearing helices to the scalar path (`geometry.py:382`). A site added to only one
   producer makes skip-bearing designs disagree with everything else. Phase 1 must cover it,
   and its acceptance fixture set must include one.
3. **A phase that quietly changes numbers.** Only Phase 4 is allowed to. For 1, 2, 3 and 6 the
   bar is `np.array_equal` / byte-identical output, and anything else is a bug in the phase.
4. **Deformation and cluster transforms.** Sites are straight-lattice quantities; deformation is
   applied downstream. Do not let a consumer read a site and skip the deformation pass — that is
   how `mrdna_bridge` ended up re-deriving from the straight helix in the first place.

## The 14.6° — SETTLED 2026-08-07: symmetry-first stays

The atomistic roll cannot satisfy both measured criteria at once, and the owner's call is the
**status quo**: the shipping total of **−46.6°** (−32° + the −14.6° DX-junction balance), which
equalises the junction linkers and leaves the crossover azimuth 8.5° from the MD mean.

Rejected: MD-first at ≈−38.1°, which would put the azimuth mean on +7.3° and give back roughly
half the original 0.500 nm junction-gap asymmetry.

Rationale to preserve: the two criteria measure different things — a built structure's local
linker strain versus where relaxed DNA settles — and the balanced build is the one the owner has
actually inspected in the app on both lattices. **This is now a decision, not an accident: do not
"fix" the 8.5° against MD.** `test_the_atomistic_crossover_azimuth_stays_in_the_md_envelope`
stays deliberately loose so it guards the physical range without re-litigating this.

## Earlier open question — ANSWERED 2026-08-07

Phase 4's CM definition was a false dichotomy: neither the atomistic mass centroid nor the
inverted `oxdna_backbone_site`, but oxDNA's own published HB equilibrium (`HYDR_R0`), applied by
the a1 slide that was already there. See Phase 4. Everything else is a refactor with an equality test.
