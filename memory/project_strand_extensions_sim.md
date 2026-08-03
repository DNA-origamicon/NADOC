# Strand extensions → oxDNA + NAMD (terminal ssDNA tails)

`StrandExtension` (a 5′/3′ terminal tail, e.g. the single T on every staple end of a
scadnano import) used to be **display-only**: model, CRUD, validation, 3D geometry — and
zero hits in *every* simulation exporter. A relaxation of `workspace/VoltronCoreScad.nadoc`
(334 single-T extensions) was byte-identical to one without them. Now they are real
nucleotides in the oxDNA topology + configuration and real residues in the all-atom model.

Sibling feature, same pattern, read it first: [project_oxdna_extra_bases](project_oxdna_extra_bases.md).
Extensions differ in one way that drives every design decision below: an extra base
**bridges two anchors**; a tail hangs off **one**, and its far end is free.

## Key choice: tails reuse the GEOMETRY key, not an `__xb__`-style sentinel

Tail beads are keyed `("__ext_<ext_id>", bead_index, direction)` — the key
`design_geometry._strand_extension_geometry` already emits. Consequences, all load-bearing:

- `resolved_nuc_map` pass 1 finds their positions in the geometry list for free.
- **The frontend needed ZERO changes.** `helix_renderer`'s `_keyToEntry` is
  `` `${helix_id}:${bp_index}:${direction}` ``, extension beads already pass the
  `assignedGeometry` filter into `backboneEntries`, and the `/display` emitter already
  writes `key[0]/key[1]/key[2]`. Setting `include_extensions=True` on `_relaxed_full_map`
  was the entire display change.
- **The trap:** a tail key is a 3-tuple whose `bp_index` is an `int >= 0`, so it **passes**
  every `isinstance(k[1], int)` filter written to catch `__xb__`. Use
  `is_synthetic_nuc_key()` / `is_synthetic_pkey()` / `helix_id.startswith("__")`, never the
  isinstance test. Guarded: `oxdna_health._frame_atomistic_overrides`,
  `atomistic_to_nadoc` (`rigid_mask` would have let tails bias the Kabsch fit),
  `oxdna_shape_source`, `namd_shape_source`, `skip_twist_tuning`.

## The three things that make a tail blow up (all measured, all pinned)

FENE diverges at `r0 ± delta` — **a too-SHORT bond kills the run exactly as dead as a
too-long one**, and `backbone_fene_stretch` only reports the long side. Window: 0.506–1.006
units (0.431–0.857 nm), r0 = 0.7564.

1. **The display arc was 0.34 nm/bead with a phantom slot** (`t=(i+1)/(n+1)`), so a lone T
   sat **0.177 nm** from its anchor — 2.4× under the lower cliff, and deep inside the
   neighbouring nucleotide. Now `arc_len = n * SSDNA_CONTOUR_PER_NT_NM` (0.68 nm,
   `core/constants.py`, shared with SNUPI's `SS_CONTOUR_PER_NT`) and `t=(i+1)/n`, so the
   last bead lands ON the arc end. Also: the bow is now taken in the anchor's **local**
   frame, not world +Z — a world bow degenerates when a cluster rotation lines the radial
   up with it. Consecutive spacing is provably in [0.680, 0.793] nm for every n.
2. **`oxdna_native_seed_map` shifts every CM along its OWN a1** by a design-derived delta
   (measured **0.4402 nm** on VoltronCore — 65 % of the 0.68 nm bond). A tail bead's a1 is
   ⟂ to its anchor's, so the bond's two ends move in *different directions*: 163/334 tails
   past the upper cliff. Exempting tails is worse (334/334 — the anchor still moves away).
   **A tail is translated rigidly with its anchor, by `delta · a1_anchor`.** 0/334.
3. **A 5′ tail must be solved ANCHOR-OUTWARD, not in chain order.** Its chain runs
   tip → … → bead0 → anchor, so the anchor is the *successor*. Solving in chain order makes
   bead0's frame answer to bead1 and leaves the bead0→anchor bond unconstrained — it
   collapsed to 0.476 units, under the short cliff. Anchor-outward, every bond is solved
   once, by whichever bead is further from the duplex.

## a1 is SOLVED, not picked

A free ssDNA base has no WC partner, so a1 is only constrained to be ⟂ a3 — but it is not
free of *consequence*: the FENE spring acts between BACKBONE SITES, and the site sits at a
~0.48-unit lever arm off the CM whose direction a1 sets. Rotating a1 about a3 swings the
bond over **0.399…0.978 units**. `_resolve_extension_geometry` solves it in closed form
(the site distance is a sinusoid in the rotation angle) and places the site at **r0**, so
the tail starts relaxed rather than merely legal. Of the two roots it picks the one that
keeps the *next* bond reachable — a greedy chain otherwise fights itself (one bond crept to
1.005, a hair under the cliff).

**Consequence for testing:** because the lever arm can reach r0 even when the beads are on
top of each other, the FENE oracle does **not** catch a bad arc. The arc has its own pin
(`test_extension_arc_spacing_is_ssdna_contour`). Don't collapse the two.

## Gotchas that bit

- **`effective_a3(nuc)`** — the a3 `nuc_conf_line` actually writes is the axis tangent
  **negated for REVERSE**. Anything reconstructing a backbone site from a resolved dict
  must use it; reading `axis_tangent` raw silently gives the wrong site for every REVERSE
  nucleotide (it put 171/334 tails at 0.424 units).
- **`count_undefined_bases` had its own copy of the sequence logic**, keyed on
  `is_extra_base`. Extension bases fell through to `seq[seq_idx]` and *advanced the cursor*
  — counted undefined AND shifting every real base after them, so the relaxation's
  "undefined bases" gate **rejected any fully-sequenced design with tails**. Both sequence
  sites now key off `step.base_override is not None`.
- **Modification-only extensions** (a cy3/biotin with no `sequence`) are not DNA: filtered
  at `strand_extension_tails()`, so they contribute zero particles and zero residues. They
  still render (a separate `is_modification` bead).
- **THE TRAJECTORY SEED FRAME (fixed 2026-08-02).** `_aligned_downsampled_frames` PREPENDS
  the design-reference conf as composite frame 0 — but read it with `include_extensions` /
  `include_extra_bases` OFF, so every `__ext_` / `__xb__` key was *missing* from that dict.
  `_flatten_cg_frame` fills a missing key with six zeros ⇒ **View-trajectory opened on every
  tail and extra base at the world origin**, a starburst that snapped into place at frame 1.
  Frames ≥ 1 never had this (`_parse_trajectory_frame_lines` has no drop filter). Fix: a
  SECOND read, `ref_display`, with both flags on, used only for the seed frame — the plain
  `ref` stays synthetic-free because it is also the **Kabsch alignment reference**, and
  floppy tails must not join that fit. The prior spot-fix backfilled `cap*` keys only.
  Pinned by `test_oxdna_extensions.py::test_trajectory_first_frame_places_tails_not_the_origin`.
- **STALE JOBS.** The walk GREW, so a job run before this has fewer `.dat` lines than the
  order now expects — and `_protein_lead_offset` clamps the deficit, silently handing every
  nucleotide after the first extension the WRONG particle line.
  `assert_topology_matches_design()` (called from `_relaxed_full_map`) now 409s instead.
  `oxdna_staleness` could not catch this: the *design* didn't change, the *walk* did.

## NAMD / atomistic

`_build_extension_atoms` reuses the same arc but roots it on the anchor's real C3′ (3′) /
C5′ (5′) atom. It does **not** use `_minimize_{1,2,3}_extra_base` — those solve a linker
pinned at *both* ends. Each consecutive pair gets `_minimize_backbone_bridge`; the free tip
gets none (a dangling O3′/P is what a chain terminus *is*). Seeded O3′–P lands at 1.6–2.8 Å
vs the shipping extra-base seed's 2.6–3.2 Å; `declash` (auto-on via `design_has_extensions`)
finishes the job.

`_thread_extra_bases_inline` → **`_thread_inserts_inline(atoms, design)`**, ordering each
chain `[5′ tail, outermost first] + [real + its inserts] + [3′ tail]`. The existing
contiguous renumber then makes the outermost 5′ base `resid 1` and the 3′ tip `resid N`, so
psfgen's `5TER`/`DEO5`/`3TER` — which key purely off residue ORDER — land on the tails
automatically. No negative seq_num, no patch-list change. The anchor correctly stops being
a terminus and becomes an internal DEOX.

## State / open items

- **DONE:** oxDNA (topology, config, seed, health, read-back, display) + NAMD/atomistic +
  **mrDNA** (2026-07-14 — +334 beads on VoltronCore, matching oxDNA/atomistic;
  [project_mrdna_extensions](project_mrdna_extensions.md)). The real-ARBD slow test still owes a
  test-dedicated session.
  - mrDNA added ONE new trap to the list below: the `__` prefix guard must be `__ext_`
    specifically, because mrDNA's `nt_key` also carries `__lnk__` virtual linker helices, which
    are real WC-paired duplex.
- **OUT OF SCOPE this pass:** CanDo/SNUPI (`fem_solver`) still ignores `design.extensions`.
  It already handles crossover `extra_bases`, so the pattern is there; `snupi_tails.py` already
  models free ssDNA tails via `classify_ssdna_runs` — surfacing extensions to it may be most of
  the work. See [project_snupi_ssdna](project_snupi_ssdna.md).
- **DONE (2026-07-24) — deform toggle repositions tails.** Two gaps closed so the deform
  (straight↔deformed) toggle moves 5′/3′ extension beads with their anchor strand:
  - **Backend:** the *compact* straight-geometry path `_positions_for_design`
    (`design_geometry.py`) emitted real helices + ss-loop overflow + ds-linker bridges but
    NOT `_strand_extension_geometry`, so the auto-embedded `straight_positions_by_helix` (the
    deform toggle's t=0 anchor, and the `positions_only` diff payload) carried zero `__ext_`
    beads. With no straight anchor, `helix_renderer.applyDeformLerp` fell to its `else if (dp)`
    branch and pinned each tail bead at its *deformed* position for all t → tails detached from
    the now-straight strand when the toggle went OFF. Fixed: `_positions_for_design` now folds
    `_strand_extension_geometry` beads into `positions` (anchor map built from the compact
    buckets), matching the full per-nuc path bead-for-bead. Pinned by
    `test_positions_for_design_includes_extension_tail_beads` +
    `..._extension_survives_deformation_strip` (both go red without the fix).
  - **Frontend:** modification/fluorophore tip beads live in `fluoroEntries` (not
    `backboneEntries`), and `applyDeformLerp` had no loop over them → the tip bead never lerped.
    Added a fluoro loop mirroring the backbone one (same `__ext_{id}:bp:dir` key).
- Fluorophore beads still don't follow the mrDNA-**relax** overlay (`iFluoros` is a separate
  mesh `applyFemPositions` never touches) — that is a DIFFERENT overlay from the deform lerp
  (now fixed above); cosmetic, only visible on a modification extension.
- `orderStrandNucleotides` (helix_renderer) sorts 5′-tail beads ascending when the chain
  order is descending — invisible at n=1 (all of VoltronCore), would mis-order a cone chain
  at n≥2.

## Tests

`tests/test_oxdna_extensions.py` (27 fast + 1 `slow[oxdna]` VoltronCore scale check) and
`tests/test_namd_extensions.py` (10). **Verified can-go-red against all four failure modes**
(old arc, world bow, naive own-a1 seed shift, 5′ chain-order solve).
`test_headless_oxdna_build.py::test_display_route_surfaces_extension_tails` is the
end-to-end pin: relax → `/display` payload carries `__ext_` keys.
