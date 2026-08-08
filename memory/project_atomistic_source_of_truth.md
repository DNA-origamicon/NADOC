---
name: atomistic-source-of-truth
description: "The dependency inversion, DONE 2026-08-07: the atomistic stamp no longer reads the display bead, the CG bead is a projection of the helical site, and 4 of the 11 live CG couplings are closed. Carries the RE-VERIFIED audit table of what is still coupled."
metadata:
  node_type: memory
  type: project
---

# The atomistic rep becomes the source of truth

**Status: the inversion is DONE (2026-08-07), together with helical-site Phases 0-6
([[project_helical_site]]).  Suite 6865 passed, 0 failed.  Three couplings remain and each is
out of scope by construction — read the audit table below, it is re-verified against live code.**
Written 2026-08-06 for a fresh session.

## What shipped, in one place

Detail and every justifying measurement: [[project_atomistic_source_of_truth_archive]] and
[[project_helical_site_archive]].

- **Display junction-balance roll** — square's full rep drew one arc of every DX pair at
  1.126 nm and the other at 0.286; `FULL_REP_BALANCE_ROLL_SQUARE_DEG = 30 − ½·33.75 = 13.125°`
  fixes it on the render feeds only. Honeycomb 0.
- **Atomistic junction-balance roll** — the same defect where it is exported: honeycomb linkers
  0.586/1.086 nm → 0.7241/0.7242. One constant, `_ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG = 14.6`,
  because the offset is a template-convention property, not a lattice one.
- **The inversion** — `NucleotidePosition` carries the phase (`radial_hat` / `axis_point` /
  `azimuth_rad`); the CG bead is a projection of it, exactly; the stamp reads the phase, not the
  bead. Byte-identical. Then helical-site Phases 1–10 ([[project_helical_site]]).

## Why — the one-paragraph version

Today the dependency runs **backwards**. `build_atomistic_model` reads
`geometry.nucleotide_positions` — the CG bead layer — and builds each nucleotide's stamping frame
from a bead. Worse, `_ATOMISTIC_PHASE_OFFSET_RAD = −32°` is documented as *"calibrated by overlaying
the atomistic model on the NADOC bead/slab representation"*: the display rep is literally dictating
where atoms go. And the CG rep feeds oxDNA, LAMMPS and (by an inline copy of the same formula)
mrDNA. So a change made to make a figure look better today can move a simulation.

## Target

```
Topology (strands, crossovers)            ← ground truth, edits only here
      ↓
Helix axes + phase (axis_start/end, phase_offset, twist, direction)   ← lattice, LOCKED
      ↓
ATOMISTIC  ← THE geometric source of truth.
             Measured templates stamped on frames computed DIRECTLY from
             (axis point, axis tangent, azimuth, axial offset). No CG input.
      ↓                                        ↓
SIMULATION CG  (one adapter per engine)   DISPLAY CG  (the "full" rep)
  atoms → that engine's own landmark        atoms → legible beads/slabs
  · oxDNA:  CM + a1 + a3                    · tuned for figures; may deviate
  · mrDNA:  bead/bp + 3×3 orientation         from a literal atom projection
  · FEM:    axis nodes (C1'–C1' midpoint)   · A LEAF. Nothing reads from it
  · NAMD/GROMACS: already atoms, no change     except renderers.
```

**The invariant to enforce:** display CG is a leaf. If anything other than a renderer reads it, that
is the bug.

## What is already true (verified, don't re-derive)

- **The atomistic build's CG dependency is NARROW.** `_atom_frame` extracts only two things from the
  CG bead: the **azimuth** (direction of `radial_perp`) and the **axial offset**
  (`dot(radial, axis_tangent)`). **The radius is discarded** — `HELIX_RADIUS` 1.0 is overwritten by
  `_ATOMISTIC_P_RADIUS` 0.886. `base_position` is never read. `base_normal` is read only on the
  `nuc_frame_override` branch. `axis_point` is already computed independently from
  `helix.axis_start/bp_start/BDNA_RISE_PER_BP`. **So the bead is a carrier, not a source** — the
  azimuth it carries is just `phase_offset + local_bp·twist + groove_offset_rad(direction)`.
- **Three engines already bypass CG.** NAMD and GROMACS build from `build_atomistic_model`;
  CanDo/SNUPI place FEM nodes inline on the helix axis. The engine-side blast radius is really
  **oxDNA + LAMMPS + mrDNA**.
- **mrDNA does not call the CG layer** — `mrdna_bridge._build_nt_arrays` re-implements the formula
  inline (its own comment says *"same formula as geometry.py nucleotide_positions()"*). It is a
  third copy, not a consumer.
- The honeycomb twist is now commensurate (TD-29), so crossover geometry no longer drifts along a
  helix and is identical across designs of one lattice type. Do not re-open that.

## Assets that already exist for the inversion

Do not write these from scratch:

| need | existing code |
|---|---|
| atoms → CG beads | `backend/core/atomistic_to_nadoc.py` — `extract_from_pdb` maps **P atoms → NADOC bead positions**; built for MD read-back, structurally the derivation we want |
| CG derived from the atomistic template | `measured_positioning._from_atomistic_template()` — **a partial prototype of the inversion**, already deriving bead sites from the measured template |
| oxDNA CM ↔ backbone | `oxdna_interface.oxdna_backbone_site()` — the exact conversion, written in the reverse direction; invert it |
| all-atom frame → oxDNA frame | `atomistic._rigid_frame_calibration()` `(Q, c)` per (strand, cell) bucket — **inverted, this IS "atoms → oxDNA particle"**. The single most valuable asset here |
| display→sim adapter precedent | `oxdna_interface._oxdna_cm_radius_map()` — an explicit boundary converter, already in place, no-op on legacy geometry |
| atoms → helix axes | `pdb_to_design.py:521`, `pdb_import.py:843` — two independent fitters already exist; reconcile rather than add a third |

## Audit — every CG coupling, RE-VERIFIED against live code after helical-site Phases 1-6

Suite: **6865 passed, 0 failed.**  Phase detail in [[project_helical_site]].

| # | Coupling | State | Evidence |
|---|---|---|---|
| 1 | atomistic stamp phase | **INVERTED** | reads `radial_hat`; corrupting the bead to r=3.7 nm moves 0 atoms |
| 2 | CG backbone bead | **DERIVED** | `position == axis_point + HELIX_RADIUS·radial_hat`, exact |
| 3 | surface point cloud | **INVERTED** | `surface_atom_cloud` passes `radial_hat=` |
| 4 | override paths | **NAMED PRODUCER** | `geometry.site_from_bead`; was an unnamed fallback |
| 5 | oxDNA seed | **CORRECT, misleadingly named** | `nuc_conf_line:1405` still writes `backbone_position` into the CM slot, but `oxdna_native_seed_map` converts it and all 3 production call sites pass `oxdna_native_seed=True`. Phase 4 replaced its fitted 0.37 nm with the published `HYDR_R0` |
| 6 | LAMMPS | **CORRECT** | same writer + native seed |
| 7 | mrDNA | **FIXED** | inline formula gone (0 hits); reads the site. Fixed a live bug: stale stored pose, pre-TD-29 twist, `6hb_test` 175° out of phase |
| 8 | extra-base positions | **NOT A DISPLAY COUPLING** — row was wrong | reads `nucleotide_positions` (the GEOMETRIC layer), not `_geometry_for_design`; the chord endpoints are the site at `HELIX_RADIUS`. No display tweak can reach an exported atom here |
| 9 | extension tails | **NOT A DISPLAY COUPLING** — row was wrong | same cache; its docstring mentions `_strand_extension_geometry` but does not call it |
| 10 | `_rigid_frame_calibration` | **FIXED** | frames from `nucleotide_positions`; no conf round trip, no display dependency (only a comment mentions `_geometry_for_design`) |
| 11 | periodic seam solver | **FIXED** | no `np.linalg.solve` left; reads the axis. Fixed a live bug on base pairs split across two domain-level clusters |
| 12 | pose fitters | **HAZARD CLOSED**, re-target still open | all 8 sites now call `design_geometry.fitting_geometry`, which states `measured_positioning=False, junction_balance=False` instead of inheriting defaults TD-27 intends to flip. Re-targeting bead→site still wants the migration decision |
| 13 | `_ATOMISTIC_PHASE_OFFSET_RAD = −32°` | **DECOUPLED** (value unchanged) | re-justified against MD, not the bead rep: on 18hb it sits 1.6° from the free-NAMD crossover azimuth (+5.72 vs +7.30). Exposed an OPEN question — the shipping total (−46.6°, with the junction-balance roll) is 8.5° the other side of MD |
| 14 | FEM (CanDo/SNUPI) | not a coupling | places nodes on the helix axis inline |
| 15 | display junction-balance roll | display-only | `junction_balance=` on render feeds only |

**Round 2 (2026-08-07) resolved three more rows, two of them by finding the row itself wrong.**
Rows 8/9 are not display couplings at all — both placers read the geometric layer — so nothing
needs to change and the "a display decision reaches an exported atom" claim is retracted. Row 12's
active hazard is closed by `fitting_geometry`; only the bead→site re-target remains, and it wants
the migration decision. **Row 13 (`_ATOMISTIC_PHASE_OFFSET_RAD`) is now the only untouched
coupling**, and it is no longer gated on the placers — it is gated on re-quoting ~300 1ZEW
coordinates alongside `_FRAME_ROT_RAD`.

## Open questions for the owner — ask, do not guess

1. ~~**Saved `cluster_transforms` migration.**~~ **ANSWERED 2026-08-07: leave them as-is.** No
   re-fit on load, no versioned field. This also settles the pose fitters: re-targeting them from
   the bead onto the site would change what a saved pose means, so it is not happening. The
   default-flip hazard is closed separately by `design_geometry.fitting_geometry`.
2. **What "tuned for figures" is allowed to do.** Purely a projection of atoms (bead = C3′), or free
   to deviate for legibility? The 2026-08-06 groove restoration (CG beads re-registered onto the
   lattice groove so Holliday junctions render symmetrically — see [[project_measured_atomistic]])
   is exactly such a deviation and would be *sanctioned* by the second reading, *rejected* by the
   first. It is currently shipped and the owner approved it.
3. **oxDNA CM definition.** Derive from the atomistic nucleotide's mass centroid, or from the
   inverted `oxdna_backbone_site` off the phosphorus? These differ.
4. **Does the display CG keep the lattice groove or follow the atoms?** They disagree by 19.8° on
   FORWARD cells and 79.75° on REVERSE (measured). This is question 2 in concrete form.
   *Answered in part 2026-08-07:* display CG keeps the lattice groove AND is free to deviate — the
   junction-balance roll is exactly such a deviation and the owner chose it over rolling every rep.
   The unresolved half is whether unifying the two azimuth conventions (making CG follow the
   measured 130.2° separation) is preferable, since that would let ONE roll balance both reps.

## What must NOT move

- `_PHASE_FORWARD` / `_PHASE_REVERSE` / `_SQ_PHASE_*` and `_lattice_phase_offset` — locked
  ([[feedback_phase_constants_locked]]), and now **validated against equilibrated-origami MD**
  (`scripts/measure_interhelix_phase.py`: NADOC legacy crossover azimuth |φ| median 17.1° vs MD
  18.6–19.5°). The phase convention is right; do not "fix" it.
- The commensurate honeycomb twist (`HONEYCOMB_TWIST_PER_BP_DEG = 2*360/21`, TD-29).
- The topological layer. Nothing in this plan edits topology.
- `_FRAME_ROT_RAD` — locked, and retiring it is gated on the extra-base/tail placers (TD-27).

## Tests that will need rewriting, not deleting

`test_the_atomistic_build_is_immune_to_the_cg_measured_flag` (premise reverses) ·
`test_the_periodic_seam_solver_still_gets_a_valid_axis` (bead-inversion assumption) ·
`test_the_oxdna_seed_restores_the_cm_radius_and_is_a_legacy_no_op` (this IS the seed-boundary
contract — rewrite it around the new adapter) · the CG-placement block in
`test_measured_positioning.py` · `test_atomistic_geometry_lock` goldens (only if step 1 genuinely
changes geometry — it should not) · ~30 assertions in `test_geometry.py` that currently *define* the
CG layer and would become the derivation's acceptance criteria.
