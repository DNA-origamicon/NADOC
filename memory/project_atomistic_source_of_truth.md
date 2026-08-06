---
name: atomistic-source-of-truth
description: "PLAN (not yet started): invert the geometry dependency so the ATOMISTIC representation is the single source of truth, the coarse-grained 'full' rep becomes purely derived + tuned for figures, and the display rep can never reach a simulation."
metadata:
  node_type: memory
  type: project
---

# The atomistic rep becomes the source of truth

**Status: PLAN ONLY, nothing implemented.** Written 2026-08-06 for a fresh session.
Owner decision, stated directly: *"We want one source of truth which is the atomistic
representation. We want the full rep to be purely derived from the atomistic rep and tuned to look
nicer for figures and visualization. The NADOC full rep should never inform or impact any
simulation in any way."*

Read this before touching `atomistic.py`, `geometry.py`, `design_geometry.py`, or any simulation
seed path. Companion to [[project_measured_atomistic]] (the templates) and TD-27 / TD-29 in
[[project_tech_debt]] (the correction stack and the twist fix).

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

## The blockers, in order of difficulty

### 1. HARD — pose fitters write SAVED `cluster_transforms` fitted against CG beads

`direct_relax.py`, `linker_relax.py`, `duplex_cluster.py` all read `_geometry_for_design`, fit a
pose, and write `design.model_copy(update={"cluster_transforms": ...})` — a **persisted** Design
field. So a display retune silently moves every previously-saved cluster pose. This is the real
three-layer coupling and it is exactly why TD-27's `measured_positioning` default is still `False`
(measured: 24 fast-suite failures, 14 of them in this family).

**Consequence: display CG cannot be freely tuned until these fit against the atomistic model
instead.** This is the gate on the whole plan. It is also already scoped as **TD-28** (deferred
linker/relax audit) — that audit and this plan should merge.

### 2. HARD — extra-base and extension-tail placers require the CG chord

`atomistic.py:2960` / `:3322`. Their docstring is explicit: *"Nothing here decides where an extra
base belongs — the CG view does, and this follows it."* Swapping the template under them moved an
insert 0.41 nm off the chord and stretched a tail bond to 3.5 Å. Under the inversion these must be
re-derived to place from atoms. Out of scope for a first pass; keep them on the current path and
**mark the two placers as the last CG consumers**.

### 3. MEDIUM — `_ATOMISTIC_PHASE_OFFSET_RAD = −32°` is calibrated to the CG rep

Once atoms are the source, a constant whose stated purpose is to align atoms *to the beads* is
meaningless. It must be removed and the frame re-derived, or re-justified against MD. Note this sits
inside the TD-27 correction stack; retiring it interacts with `_FRAME_ROT_RAD` (locked, listed in
`atomistic_minimisers.py`).

### 4. MEDIUM — `_rigid_frame_calibration` bakes a CG→atomistic round trip into a cached constant

It builds a synthetic design, writes an oxDNA conf **from CG geometry**, reads it back, and Kabsch-
fits against `build_atomistic_model`. Under the inversion its input must become the atomistic model.

### 5. MEDIUM — `periodic_polymer._section_frame_from_arrs` analytically inverts the CG convention

It solves for a helix axis assuming beads sit at exactly `HELIX_RADIUS` at the ideal groove. Pinned
by `test_the_periodic_seam_solver_still_gets_a_valid_axis`. Under the inversion it should read the
axis directly instead of inverting beads.

### 6. LOW — oxDNA writes the CG backbone bead into the CM slot

`nuc_conf_line` puts `backbone_position` in the conf's first three floats, which **are the centre of
mass**. These are different landmarks. `_oxdna_cm_radius_map` already exists as the boundary
adapter; it becomes the place where atoms → CM happens properly.

## Suggested sequence

Each step should leave the suite green and be independently shippable.

1. **Make the atomistic frame self-sufficient.** Replace `_atom_frame`'s bead input with a direct
   azimuth/axial computation from `(phase_offset, local_bp, twist, direction, loop_skip map)`.
   Acceptance: `test_atomistic_geometry_lock` byte-identical, because the azimuth is arithmetically
   the same quantity. **If the goldens move, the replacement is not equivalent — stop and find out
   why** rather than regenerating.
2. **Assert the new direction.** Invert `test_the_atomistic_build_is_immune_to_the_cg_measured_flag`
   into its opposite: the atomistic model must be unchanged by *any* CG-layer change, and CG must
   follow atoms. This test currently states the old architecture as an invariant.
3. **Build the oxDNA adapter**: atoms → (CM, a1, a3), using the inverted `_rigid_frame_calibration`
   and `oxdna_backbone_site`. Route `write_configuration` through it. Verify with the site-based FENE
   metric (`oxdna_health`, `FENE_RMAX_UNITS = 1.0064`) — not a CM-based one, which mis-reports.
   LAMMPS inherits this for free.
4. **Build the mrDNA adapter**: atoms → bead + orientation, replacing `_build_nt_arrays`' inline
   re-derivation. No existing code; the reverse direction (`nuc_pos_override_from_mrdna*`) exists and
   shows the conventions.
5. **Point FEM at atoms** for `_bp_cross_strand_map` (C1'–C1' comes straight from atoms) and, if
   desired, axis nodes as the C1'–C1' midpoint. `cando_cylinders.py` already documents the
   axis-node preference.
6. **Re-fit the pose fitters against atoms** (blocker 1 / TD-28). Decide the migration story for
   designs with `cluster_transforms` already saved.
7. **Only then** cut display CG loose as a leaf and tune it for figures.

## Open questions for the owner — ask, do not guess

1. **Saved `cluster_transforms` migration.** Existing designs carry poses fitted against the old CG
   beads. Re-fit on load, leave them, or version the field?
2. **What "tuned for figures" is allowed to do.** Purely a projection of atoms (bead = C3′), or free
   to deviate for legibility? The 2026-08-06 groove restoration (CG beads re-registered onto the
   lattice groove so Holliday junctions render symmetrically — see [[project_measured_atomistic]])
   is exactly such a deviation and would be *sanctioned* by the second reading, *rejected* by the
   first. It is currently shipped and the owner approved it.
3. **oxDNA CM definition.** Derive from the atomistic nucleotide's mass centroid, or from the
   inverted `oxdna_backbone_site` off the phosphorus? These differ.
4. **Does the display CG keep the lattice groove or follow the atoms?** They disagree by 19.8° on
   FORWARD cells and 79.75° on REVERSE (measured). This is question 2 in concrete form.

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
