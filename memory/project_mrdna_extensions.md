# Strand extensions → mrDNA (5′/3′ ssDNA tails)

**Status: DONE (2026-07-14).** mrDNA was the last engine ignoring `design.extensions`; it now
materializes every extension base as a real CG bead. VoltronCoreScad: **+334 beads**, matching
oxDNA's +334 particles and the atomistic model's +334 residues.

Sibling (read for the engine-independent traps):
[project_strand_extensions_sim](project_strand_extensions_sim.md). Reference pattern that was
copied, not rebuilt: crossover extra bases (`tests/test_mrdna_extra_bases.py`).

## What was built

All of it funnels through **`_build_nt_arrays`** (`backend/core/mrdna_bridge.py`), the per-strand
walk the SegmentModel is built from. An extra base bridges TWO anchors (chord-lerp); a tail hangs
off ONE and its far end is free — so instead of the `pending_xb` state machine, each strand records
its FIRST and LAST emitted real nucleotide (`first_anchor` / `last_anchor` = idx, position, radial,
axis_hat, direction) and materializes its tails after the domain walk.

- **Key:** `("__ext_<ext_id>", bead_index, direction, 0)` in `nt_key` — the SAME key the geometry
  layer, oxDNA and the atomistic model emit. Extra bases carry no key; tails need one, because
  `_ssdna_runs` maps indices back through `nt_key` and the display addresses that key.
- **Order (load-bearing):** bead `i` is the geometry layer's distance-rank from the anchor (i=0
  nearest the duplex). A 5′ tail is therefore walked **outermost-first** (i = n-1 … 0 — the
  outermost bead IS the 5′ terminus) and spliced onto the FRONT of `strand_indices`; a 3′ tail
  innermost-first, appended. `ordinal` indexes `ext.sequence` directly (scadnano stores it 5′→3′).
- **Sequence:** tail bases come from `ext.sequence` and never advance the strand's sequence cursor.
- **Geometry:** `_extension_bead_positions()` re-lays the display's outward quadratic Bézier in the
  UNDEFORMED helix frame `_build_nt_arrays` works in — arc length `n_total · 0.68 nm`
  (`SSDNA_CONTOUR_PER_NT_NM`), bead i at `t=(i+1)/n_total`, bow ⟂ radial **in the anchor's own
  frame**. Measured on VoltronCore: every tail bond is 0.680 nm. `n_total` counts a modification
  bead (it owns the outermost slot in the geometry layer) though it never becomes a bead here — so
  all three engines put the DNA beads at the same fractions of the same arc.
- **Free for real, as the plan predicted (verified, not assumed):** `bp_arr` (unpaired),
  `three_prime_arr` (chain bonding from `strand_indices`), and `_ssdna_runs` → the tails surface as
  ss runs with the right root and `root_side`, so `nuc_pos_override_ssdna_from_arbd` places them on
  the relaxed structure with no new machinery.
- **Stacking:** `extension_chains` threads anchor↔tail after the domain walk (so a 3′ tail beats the
  across-the-nick intrahelical stack its anchor may have been given).
- **Display:** `mrdna_runner._display_positions` emits the `__ext_`-keyed relaxed positions straight
  from the ss override (`_DISPLAY_VERSION` 7→**8**, so cached `display.json` regenerates).
  **Zero frontend changes** — `toFemUpdates` is a pass-through and `design_renderer` already
  addresses `${helix_id}:${bp_index}:${direction}` (pinned in `mrdna_display.test.js`).

## The `__ext_` guard — and the ONE way it differs from oxDNA

The carried-over trap held: a tail key's `bp_index` is an ordinary `int >= 0`, so it passes every
`isinstance(k[1], int)` filter written to catch `__xb__` (string bp_index). Guarded:
`_build_nt_arrays` pass 2 (pairing), `mrdna_shape_source._rmsf_profile` (a floppy tail would have
leaked into the rigid dsDNA-core RMSF column), `mrdna_anchors._anchor_nt_positions` (a `strand`
anchor scope DOES select tail beads — a floppy tail is not a rigid tether point).

**NEW, mrDNA-specific:** the guard must test **`startswith("__ext_")`, NOT `startswith("__")`.**
mrDNA's `nt_key` also holds **`__lnk__` virtual linker helices, which are real WC-paired duplex** —
the broad `__` test unpaired them and turned `test_mrdna_linkers.py::test_ds_bridge_is_a_duplex_in_
the_arrays` red. oxDNA never hit this (no `__lnk__` in its walk). `_EXT_PREFIX` now lives in
`mrdna_bridge` (mirrors `oxdna_interface._EXT_PREFIX`).

## Tests

`tests/test_mrdna_extensions.py` — 15 fast + 1 `slow[mrdna]`. Mirrors the extra-base twin: bead
count (+8 on the 6hb; +334 on VoltronCoreScad), modification-only extension adds 0, unpaired,
3′/5′ chain threading in both directions, 5′ walked outermost-first with bases 5′→3′, sequence
cursor untouched, 0.68 nm arc spacing, beads march radially outward, tails surface in `_ssdna_runs`
with the right `root_side`, and the two leak guards (shape column + anchors).

- **`test_real_arbd_runs_with_extensions` (slow[mrdna]) has NOT been run** — needs a test-dedicated
  session. It is the only remaining proof: ARBD has finite bonded potentials and a steric blow-up
  mode, so "mrDNA is forgiving" is still an assumption. Everything else is pinned and green.

## State

- **DONE:** all four engines now simulate extensions — oxDNA, NAMD/atomistic, mrDNA.
- **STILL OUT OF SCOPE:** CanDo/SNUPI (`fem_solver`) — see
  [project_snupi_ssdna](project_snupi_ssdna.md) (`snupi_tails.py` already models free ssDNA tails
  via `classify_ssdna_runs`; surfacing extensions to it is likely most of the work).
