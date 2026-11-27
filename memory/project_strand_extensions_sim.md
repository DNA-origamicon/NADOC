# Strand extensions → oxDNA + NAMD (terminal ssDNA tails)

**November 23 — Full extension base slabs:** extension DNA now renders the
standard measured-ring slab (centroid, fitted plane, named in-plane ring span)
from the current cached atomistic model via `extension_slabs.py`. Coarse extension
backbone/base frames, atom coordinates and simulation placement stay unchanged;
chemical modification markers remain slabless. Full rendering, incremental pose
transport, cluster motion, unfold and extension visibility include the slabs.
Atomic construction requests host-only display geometry to avoid a projection
cycle. First-time Full geometry for designs with extensions now requires an
atomistic build and its existing memory admission; a large legacy app check was
refused for insufficient available RAM. No guard was weakened.
Validation: 147 focused backend tests passed (2 optional tests skipped), 139
frontend tests passed; the isolated app checks all 16 A/C/G/T tail bases across
both termini/directions, with face/edge visual inspection. Run
`just validate-safe uv run python -m scripts.check_extension_slabs_app` to recreate
the five-command, independently replayed specimen and overlay check. The runner
removes the specimen/workspace afterward; compact evidence goes under
`.development-artifacts/extension-slabs/app/`. This verifies display alignment,
not general long-tail stereochemistry (ISSUE-164).

**November 22 — real Alpine startup confirmed:**
Gerling WITH_EXTRA_T native job `3ec95fb07c6b`, Slurm `36129263`, node
`c3gpu-e7-u13`, RTX Pro 6000 MIG `2g.48gb`, 16 CPUs/48 GiB RAM/4 h.
Prepared 7,561,135 atoms with the literature 2 fs relaxation preset; zero seed
piercings without override and neutral final charge. Desktop RAM admission refused;
the unchanged API preparation operation ran on an Alpine CPU node instead, then
all 46 input hashes/source/request were verified before adoption into the native
job. GPU wait was 28 s. Actual log reached step 559 of initial minimization with
finite decreasing energy and no fatal engine error. Conjugate-gradient restarts
are present: startup is confirmed, not convergence or later dynamics. Run left
active; no automatic resubmission/production. The 6 nm bbox passed fixed-pose
clearance but needs separate review for long freely rotating production.
Evidence: `.development-artifacts/gerling_alpine_relax_20261122/findings.txt`.

**November 22 — shared native viewport/export/NAMD starting geometry:**
User explicitly authorized removing the implicit slower NAMD rebuild. Native
`build_atomistic_model` and its cache now default to the same interpolation used
by the viewport. Physical overrides retain the old reconstruction defaults;
explicit `fast_bridges=False` remains a historical diagnostic option. Multi-base
extension linkers retain their existing physical solver in both native display
and preparation (interpolation compressed their O3'-P bonds below 1 Å); this is
not a new long-extension conformer or polymerization implementation.
Fresh Gerling default rebuild: 45/45 approved plane placements, zero physical
and display piercings. Actual default CHARMM/psfgen preparation preserves all
349,181 common heavy atoms exactly at PDB precision; rounded physical geometry
also has zero piercings. Source unchanged. Existing contacts/angle strain remain;
no production MD readiness claim. Evidence and replay:
`.development-artifacts/shared_native_seed_20261122/check.py` and `result.json`.
This supersedes the normal-NAMD mode limitation in the historical entry below.

**November 22 — approved plane placements implemented in normal NADOC rebuilds:**
User authorized promotion and a Gerling rebuild. `extension_plane_motifs.py` now
runs after forced-TT placement and before manual poses. A packaged 45-context
geometry/connectivity lookup (no design IDs) transfers the reviewed final poses;
no online search/minimization. The cache includes `terminal-plane-v1`.
Fresh workspace Gerling display/export (`fast_bridges=True`) rebuild: all 45
placements match the reviewed candidate within 4.5e-16 nm; both physical and raw
native-display ring detectors report ZERO piercings. 14 selected contacts and 11
ordinary severe overlaps remain; roots/planes/chirality pass, known angle strain
remains. Workspace source/history unchanged; no authored document produced.
Important mode boundary: the slower bridge-minimization path changes attachment
anchors. It does not match this reviewed bank and still has 20 piercings. A probe
reusing only approved poses cannot satisfy the plane at site029 in that mode;
no root stretching, new conformer or unrelated host-atom changes were introduced.
Thus zero piercings is confirmed for normal display/PDB export, NOT all NAMD
preparation paths. Existing physical overrides and unsupported motifs bypass this
placement. 12 focused tests, 10 geometry locks, FAST 21,046 pass / 90 skip; FULL
suite deferred under the session guard. Evidence:
`.development-artifacts/extension_plane_default_20261122/findings.txt`.
The experiment below records the pre-promotion state and persistent chemistry
limitations; it is superseded only for the explicitly supported rebuild mode.

**November 21 — isolated extension/midpoint-plane experiment (not promoted):**
User constrained every extension atom, including sugar/phosphate/H, to its own
side of the midpoint plane across the nick. Tested 41 defect extensions + 4 nick
partners. Eight phase/end families; canonical correction of inherited 5′ O3′
geometry repairs 21 wrong C3 centers, then rigid donor search, joint adjustment,
three constrained native pilots and a finite bank. Final: whole piercings 20→0,
severe nonbonded overlaps 66→11 (all 55 extension overlaps removed), selected
<2 Å contacts 944→14 at 9/45 extensions, including four new 1.948–1.996 Å contacts.
All 135 sugar centers correct, exact 1.600 Å roots, all mobile atoms behind planes,
all outside-selection coordinates fixed. 36/45 extensions completely clear.
Not accepted geometry: worst fixed-host OP2–P–extension O3′ angle is 30.5° vs
111.6° at published_131_five_prime (H14 BP146); root length alone is insufficient.
Pair073 native donor passed Reference-force comparison and exact replay; site099
passed/replayed but rejected for 2.089 Å P–O5′ stretching; pair029 failed force
parity and was excluded. Geometric search/transfer/joint/audit independently replay.
32 selected finite templates; no online minimization or production/default changes.
Next question: attachment-angle constraints/local host phosphate accommodation.
Evidence: `.development-artifacts/gerling_extension_plane_ab_20261121/findings.txt`.

**November 21 — refined source O3′/TT bank promoted for manual evaluation:**
User explicitly requested implementation of the refined positions. Native atomistic
rebuilds now apply `forced_tt_motifs.py` after terminal-T placement, before manual
residue poses; packaged bank `forced-tt-o3-v1` participates in the cache key.
Matches reverse forced TT topology, phase and two-helix separation, excluding
extension anchors and loops/skips within ±2 bp. Source O3′ and both Ts move;
paired sugars/bases and neighboring phosphates remain fixed. Physical coordinate
overrides bypass the placement. Five stored templates are ranked by contacts,
penetration and bond strain; no runtime minimization (~0.8–0.9 s Gerling pass).
Exact and display builds reproduce the approved combined candidate within
3.6e-15 nm at all 75 sites, with identical template selections. All 75 are
piercing-free; 64 completely clear; 11 O3′–OP1 contacts remain, and the whole
design retains 20 other piercings. Bond/angle strain still prevents claiming
NAMD readiness. This supersedes the non-promotion status below, not its scientific
limitations. No authored design files changed. Reload/reopen the design to refresh
in-memory atomistic display caches. Evidence, native rebuild audit and same-frame
views: `.development-artifacts/forced_tt_default_20261121/findings.txt`.

**November 21 — source O3′ refinement (experiment before promotion above):** source O3′ plus
both Ts mobile (65 atoms), all paired sugars/bases and neighbor phosphates fixed.
Five local candidates and a finite template bank improve the expanded O3′+TT
selection from 241 contacts <2 Å to 11; 64/75 motifs completely clear, all 75
remain piercing-free, whole Gerling remains at 20 other piercings. O3′ moves
~1.49–1.58 Å; C3′–O3′ held at 1.433 Å and both O3′–P attachments at 1.600 Å.
All 525 checked chiral centers and outside-selection coordinates preserved.
The 11 remaining NEW O3′/OP1 contacts (1.896–1.993 Å) involve exit phosphates of
adjacent FORWARD forced TT crossovers. Next coupled target is those phosphate
atoms, not further movement of paired sugars/bases. Residual bond error ~0.235 Å
and source C3′–O3′–P angles ~159–160° mean this is not simulation-ready.
Native/shell/seed/minimization/transfer replay succeeded. One intermediate CUDA
force-parity check failed narrowly; final donor0173 uses independently replayed
Reference minimization and finite-difference validation; tolerances unchanged.
Evidence: `.development-artifacts/gerling_source_o3_ab_20261121/findings.txt`.

**November 21 follow-up — isolated reverse forced TT experiment:** three 64-atom
(two inserted T) minimizations with every neighbor fixed independently replayed
exactly. All three two-anchor/frame transfers remove all 58 piercings across 75
no-near-extension reverse forced sites (55/71 directly 31/32-bp); whole Gerling
78→20, no new piercings. Best by contact count/bond error: donor003, contacts <2 Å
3,557→91 (16 new), overlaps <0.8 Å 29→0. Residual P–O5′ up to 1.903 Å versus
1.600 Å and donor phosphate-angle error 59.2° prevent production acceptance.
All fixed source O3′/C4′ distances are only 0.385–0.471 Å; at 32/75 sites this
mathematically forces incoming P/C4′ <2 Å with a 1.60 Å root bond. Standard reverse
Gerling sites also have folded source attachments (0.421–0.464 Å), despite no
piercing; forward sites are 2.357–2.426 Å. Next diagnostic target: source attachment
O3′ and exit phosphate closure, keeping paired sugars/bases fixed initially.
No production change or crossover-length cap; TT-only evidence cannot justify a
cap. Evidence: `.development-artifacts/gerling_forced_tt_ab_20261121/findings.txt`.

**November 21, 2026 — approved native atomistic default:** `terminal_t_motifs.py`
now transfers the demonstrated single-T/TT-junction templates in a proper two-helix
frame, after deformation and before manual residue poses. Matches topology, phase
and axis separation, not design IDs; three phase families, 29 stored conformers.
No runtime minimization. Physical coordinate overrides and legacy TT audit mode
bypass it; long tails, other insert sequences/phases and nearby loops stay outside
its scope. Atomistic cache identity includes the template version.
Gerling: 58 matching motifs / 116 extensions clear of <2 Å nonbonded contacts and
ring piercings; whole-design piercings remain 78. This is clearance acceptance,
not NAMD readiness: accepted templates retain internal bond strain (worst reported
C4′–C3′ 2.742 Å). Coarse-grained extension geometry is a separate path.
TT without extension anchors within ±2 bp: Gerling 58/382 pierced, existing 21-bp
6hb 0/60 and 24hb 0/338. All 58 are reverse forced junctions near 0° source radial
phase: destination P–O5′ threads the last inserted T sugar. Standard Gerling
31/32-bp sites are clear. Spacing, phase and junction kind are confounded; this is
an observational comparison, not a spacing-only intervention. Evidence and replay:
`.development-artifacts/extension_default_20261121/`. Source designs unchanged;
legacy source construction history is not certified by diagnostic replay.

**November 2, 2026 scope correction:** polymerization strands must not be converted
to these ordinary extensions (ISSUE-163). Long-extension molecular geometry was
not fully developed and belongs to separate follow-on work after the feature-log/
dependency overhaul (ISSUE-164). Existing spacing/export checks below do not
establish general long-tail stereochemistry or clash freedom. Full representation
must attach the host to the nearest extension bead (›1), independently of host
helix direction (ISSUE-162). See [the user decision](feedback_polymerization_extension_scope.md).

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
