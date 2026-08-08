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

## SHIPPED 2026-08-07 — the display CG carries its own junction-balance roll

The first concrete instance of *"the full rep is derived and tuned for figures"*.  A DX junction is
two staple crossovers between one helix pair at bp i and i+1; the full rep draws each as a
bead-to-bead arc and they must be equal.  **Honeycomb was; square was not** — 1.1262 vs 0.2860 nm
(Δ −0.8402), i.e. one arc of every pair drawn stretched to the far side of the neighbour and the
other collapsed onto it.

`constants.FULL_REP_BALANCE_ROLL_{SQUARE,HONEYCOMB}_DEG` rolls every helix about its own axis on
the **display path only**, behind `design_geometry._geometry_for_helices(junction_balance=True)`,
which the render feeds pass and nothing else does.  Square: **+13.125° = 30.000° − ½·33.75°**,
exact and design-independent (`2x3x100_Sq_test` 21 junctions, `3x6Sq_oxDNA` 110, `3x6_Sq_full` 297
→ Δ = −0.000000, and all 610 staple crossovers collapse onto ONE 0.6708 nm arc against
honeycomb's own 0.680).  Honeycomb: 0.0.  Also balanced under Help ▸ New Positioning (uniform
0.8742 nm).  `_lattice_phase_offset`'s "+½ bp of twist" Holliday correction is right for honeycomb
(17.143° balances it) and wrong for square, which wants a round 30°.

**What this says about the plan:** `_PHASE_*` and `_lattice_phase_offset` were NOT touched, the
atomistic build and every seed writer are byte-identical (pinned), and the display roll enters at
the serialiser — the same boundary the measured bead re-placement uses.  Pins:
`tests/test_junction_balance.py` (7), including the two firewalls and the square-without-the-roll
bug itself so a silent revert cannot pass as "no change".

**Known gap:** the assembly ds-linker bridge feed (`assembly.py:2521`) builds a synthetic design
hardcoded `lattice_type="HONEYCOMB"`, so its roll is 0 — a square design's bridge would draw
unrolled beside rolled part beads.  Unexercised: no fixture in `Examples/` or `workspace/` has a
ds linker.

**Consequence to know:** on a square design the CG beads are now 13.125° off the atoms.  Displaying
the full rep and the atomistic rep together shows that offset — deliberate under this plan's
doctrine, and the reason the roll must never leak past the render feeds.

## The atomistic junctions were NOT balanced on either lattice — measured, then fixed (2026-08-07)

Same metric, on the minimiser-independent quantity: the **C3′(src)→C5′(dst) anchor gap** the
phosphodiester bridge has to span (canonical ≈ 0.394 nm).  Do NOT use the O3′→P bond for this —
`_minimize_backbone_bridge` places O3′/P/O5′ between fixed C3′/C5′ anchors, so it distributes the
error and reports a junction as nearly balanced (square 0.204/0.217) when the anchors are 0.694/0.746.

| lattice | gap(i) / gap(i+1) at roll 0 | roll that balances the atomistic | balanced gap |
|---|---|---|---|
| honeycomb | 0.586 / 1.086 (Δ +0.500) | **−14.60° / −14.75°** (2 designs) | 0.724 |
| square | 0.694 / 0.746 (Δ +0.052) | **−1.33 / −1.53 / −1.45°** (3 designs) | 0.719 |

Both lattices land on the *same* balanced gap, and the CG-vs-atomistic balance points differ by a
constant **≈14.5°** on both — that offset is the measured template's 130.2° C3′–C3′ separation
against the CG lattice groove (±150°), i.e. the 2026-08-06 re-registration.  So the two reps cannot
both be balanced at one helix roll while those conventions differ.

**Owner decision 2026-08-07: fix both lattices' atomistic balance too.** Rolling the SHARED phase
to do it is blocked, and the blocker is measured, not guessed: the shared CG layer moves with it and
**half of every design's crossover bonds go over the FENE cliff** (honeycomb 114/228, square
305/610; site max 1.41–1.44 u) — the "half of all crossovers" symptom returning, which clears only
once the seeds stop reading display CG (**steps 3–4 below gate that**).

### SHIPPED instead 2026-08-07 — the roll lives INSIDE the atomistic build

`atomistic.atomistic_phase_offset_rad(design)` adds the balance to `_ATOMISTIC_PHASE_OFFSET_RAD`,
which is already a rigid roll of every nucleotide about its helix axis, so the atoms move and the CG
layer does not.  oxDNA / mrDNA / LAMMPS seeds and every pose fitter are byte-identical; the all-atom
display, the PDB/PSF exports and the NAMD/GROMACS seeds shift, which is the point.

Written as ONE measured constant, `_ATOMISTIC_TEMPLATE_BALANCE_OFFSET_DEG = 14.6`, because the
atomistic balance sits that far off the full rep's on **both** lattices (honeycomb 14.60/14.75,
square 14.45/14.65/14.57) — it is the template convention (130.2° C3'-C3') against the CG lattice
groove (±150°), not a lattice property.  So `atomistic_roll = FULL_REP_BALANCE_ROLL[lattice] − 14.6`
and the two reps' constants can never drift apart.

Result (mean over junctions): honeycomb Δ **+0.500 → +0.0002 nm**, square **+0.485 → −0.0057**;
worst single linker 1.126 → 0.761; per-junction spread 0.561 → 0.060 (the residual is sequence —
per-residue templates, so a junction's two linkers see different bases).  On `VoltronCoreScad`
(566 inserts, 263 junctions) mean Δ 0.0591 → 0.0010 and the worst gap 0.786 → 0.755.

**Collateral, measured — all of it favourable.** Extra-base bonds improve (`2hb_xover_atoms_test`
max 0.2111 → 0.1835; VoltronCoreScad 0.2322 → 0.2298) because `_extra_base_frame` interpolates
between the C3'(src)/C5'(dst) **atomistic** anchors, so inserts follow the roll — the CG-chord
coupling of blocker 2 does not bite here.  Extension tails are untouched (they translate rigidly
with their anchor).  `_rigid_frame_calibration`'s `m_res < 1e-6` tripwire still passes; a uniform
roll is rigid, so it absorbs exactly.  21 bonds crossed a 0.32 nm over-stretch line on
VoltronCoreScad and 2 left, all of them 0.321–0.327 — threshold jitter, not a regression.

**Three tests changed premise, not correctness** — worth knowing because two are load-bearing
elsewhere: `test_the_bead_lands_on_the_ribose_c3_prime` (the balanced atoms now sit CLOSER to the
legacy lattice-groove bead than to the measured one — 0.4612 → 0.2887 vs 0.5589 → 0.5448 on
`6hb_test`; a consistency signal for the roll and an open question for the measured CG bead, i.e.
TD-27's), `test_dedicated_overhang_phase_shared_by_cg_and_atomistic` (its oracle built its own frame
and had to be given the same total phase), and
`test_gate_uses_the_supplied_model_not_a_fresh_build` (it collapsed inserts onto the **world
origin**, which `make_bundle_design` puts inside the first base pair, so its O3'-P bond ran out
through the middle of the bundle and began clipping a ring when atoms moved 0.2 nm — now collapsed
outside the bounding box).  The 5 `test_atomistic_geometry_lock` goldens were regenerated
deliberately via the documented `--update`; the change they record is real (Con4's worst junction
O3'-P 3.00 → 2.17 Å).

**Still open:** −14.6° descends from the cross-strand azimuth flagged **provisional** in
[[project_measured_atomistic]], the DOF `exp52_groove_seed_sweep` was meant to settle (its jobs are
not on this machine).  If that number moves, this one must be re-measured — as must the display roll
if the shared lattice phase ever changes.  `tests/test_junction_balance.py` asserts the property,
not the constant, so both fail rather than drifting.
Owner decision, stated directly: *"We want one source of truth which is the atomistic
representation. We want the full rep to be purely derived from the atomistic rep and tuned to look
nicer for figures and visualization. The NADOC full rep should never inform or impact any
simulation in any way."*

Read this before touching `atomistic.py`, `geometry.py`, `design_geometry.py`, or any simulation
seed path. Companion to [[project_measured_atomistic]] (the templates) and TD-27 / TD-29 in
[[project_tech_debt]] (the correction stack and the twist fix).

## SHIPPED 2026-08-07 — step 1 done: the stamp no longer reads the display bead

`geometry.NucleotidePosition` now carries the helical phase as a quantity —
`radial_hat`, `axis_point`, `azimuth_rad` — and **the CG bead is a projection of it**:
`position == axis_point + HELIX_RADIUS * radial_hat`, exactly (`np.array_equal`).
`atomistic._atom_frame` and `_atom_frames_batch` read `radial_hat` directly and place the P
at `_ATOMISTIC_P_RADIUS`; they no longer recover the phase by subtracting an axis point from
the r=1.0 display bead and re-normalising.

**Byte-identical**: 0.000e+00 nm max atom displacement on `6hb_test`, `Con4`,
`2x3x100_Sq_test`; the 5 geometry-lock goldens pass unchanged. It is exact rather than
ULP-close because `HELIX_RADIUS` is exactly 1.0, so the old reconstruction divided by a norm
of exactly 1.0 — a dependency nobody had written down.

Pinned by `test_the_stamp_ignores_the_bead_and_reads_the_phase`: move every bead to r=3.7 nm
and **zero atoms move**. That assertion is the inversion; the docstrings are commentary.

**The one real bug this introduced, and the rule it produced.** `nuc_pos_override` (relaxed
oxDNA/mrDNA display, folded ssDNA seeds) and `axis_override` (bent centreline) move a
nucleotide, which invalidates the carried lattice phase — the stamp kept trusting it and
applied only the override's AXIAL component. Five tests caught it
(`test_displaced_nucleotide_flags_backbone_and_hidden`, `test_overlapping_nucleotides_clash`,
`test_wc_helix_imbalance_detector`, `test_ssdna_fold_does_not_collapse_seed_atoms`,
`test_deformed_axis_slashes_clashes_on_a_displaced_helix`). **Any code path that moves a
nucleotide must call `atomistic._phase_invalidated`** — the phase fields describe LATTICE
geometry only, and dropping them is what returns that nucleotide to the bead-derived frame.

**What this does NOT do:** the CG bead is not computed *from atoms*. A literal
atoms→beads projection would move the full rep by the correction chain (−32° − balance
+ the per-cell REV delta, i.e. 15–46°) — the owner has ruled the current reps correct — and
it would cost an atom build per geometry request on the hot path. So atoms and beads are
siblings off one owned phase, with the bead the derived one. Treat the remaining audit table
below as the real backlog.

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

*2026-08-07:* it is no longer read directly by the build — `atomistic_phase_offset_rad(design)` is,
and it adds the measured DX-junction balance on top. The −32° itself is still the unjustified CG
overlay this item describes; retiring it now means re-deriving that sum, not just this constant.

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
   *Partially done out of order, 2026-08-07:* the junction-balance roll (top of this file) is a
   display-only tune that landed early because it needed no seed change. It does NOT make display
   CG a leaf — the seeds still read the unrolled layer, which is exactly why it was safe.

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
