---
name: project_strand_sequence_edit
description: Hand-edit a strand's sequence from the right-click menu in 3D / cadnano / either spreadsheet, with the paired scaffold shown above the field and mismatches flagged. Shipped 2026-07-27.
metadata:
  node_type: memory
  type: project
---

# Edit strand sequences by hand (2026-07-27)

User ask: no path existed to type a strand's sequence anywhere. Add "Edit sequence…"
to the strand right-click menu in BOTH editors; for a staple whose scaffold is
sequenced, show the paired scaffold bases above the input and highlight incorrect
base pairing — but still allow any bases.

## Strand-specific insertion loops (2026-11-25)

Current production (November 26, explicit user promotion): loops of **6–39 bases**
use `strand-loop-ellipse-v4-ring-priority`: the previous bond optimum, additional
rigid +1nm outward translation, then fixed-center ring-priority rotations with
up to0.10nm linker growth versus the translated baseline. Atom-overlap counts
and depth cannot increase per group; no new piercing identities are accepted.
Shorter loops retain v2; loops>=40 retain v3. No hard editor limit is imposed.
User accepted residual edge cases and deferred further refinement until demand.
`strand_loop_ring_fit.py` shares the atom-aware placement with Full and all
atomistic representations; context-local recursion control and an input-keyed
bounded cache keep rebuilds consistent. Atom cache version advanced and v4 is
registered in frontend placement validation. Six portable approved coordinate
fixtures guard the selected result; complete84-case production comparison is
under `.development-artifacts/loop-ring-production-20261126/`.


Earlier production (November 26): user explicitly selected **Bond optimum only**
on the demonstrated 0.50 nm outward ellipse. `strand-loop-ellipse-v3-bond-optimum`
uses smooth fixed-root shoulders and contour refitting, then the global 5°-grid
O3′–P length optimum about each fixed bead-to-slab-center axis. It never lengthens
an individual modeled linker; it does not optimize clashes/piercings. Native
attachment landmarks use the actual strand sequence and the measured template
registration. Slab centers and beads stay fixed during fitting; path tangents
remain geometric. Insertions below six bases retain v2 (the reviewed 0.50 nm
offset exceeds a one-base contour budget). Atomistic cache version is advanced.

Production reevaluation: 126 cases match the reviewed `bond_only` atoms within
7.2e-15 nm, with exact independent replay. Relative to the unrotated 0.50 nm
baseline, mean O3′–P is 0.576→0.306 nm; loop-self atom overlaps 1281→31647;
parent overlaps 8295→8358; neighbor overlaps 14210→14131. Ring piercings 103→130,
including 123 newly introduced identities. Full parent/self intersections stay
zero; neighbor intersections 193→204. These are unassigned/T-placeholder display
fixtures, not physically relaxed structures. Export/simulation remains guarded.
Evidence: `.development-artifacts/loop-bond-production-20261126/`; executable audit:
`experiments/loop_bond_production_review.py`. Focused regressions: 64 passed,
including approved-pose, sequence-specific endpoint and no-linker-growth checks.
Renderer/codec regressions: 32 passed; Full and all four atomistic modes verified
in the isolated app, with its workspace removed afterward. The new source tag
is explicitly registered in `native_placement.js`; the initial missing-tag
incident was preserved and reviewed through the standard placement journal.
The guarded alternatives below were **not** selected for production.

Radial A/B diagnostic (November 26, production unchanged): user authorized bases
outward from the ellipse center, farther offsets, then guarded rotation fitting.
`experiments/loop_radial_comparison.py` compares 126 recorded 2HB fixtures;
`.development-artifacts/loop-radial-20261126/` retains inputs, frozen source,
ordered process, stage evidence and shared-frame review (localhost:8772).
Offsets selected per case by self contacts, helix contacts, piercings, then offset:
0.75 nm for 6 nt, 3 nm for 30 nt, 4 nm for 80 nt. Versus current production,
final parent/neighbor/self atomic overlaps: 8358/14131/31647 → 3015/6346/2183;
piercings 130→28, all 28 remaining identities newly introduced versus current.
Mean O3′–P worsens 0.306→0.501 nm (maximum 0.775→0.876 nm). The rotation
stage improves its radial starting pose (mean 0.633→0.501; piercings 47→28),
with no individual linker growth, increased per-group overlap count/depth,
or new piercing identity at that stage. Both centers and radial direction stay
fixed during fitting. Full parent contacts increase 0→21. This candidate is
not physically resolved and has not been selected for production.

User retained the current bond optimum after radial comparison (November 26).
Read-only piercing census: `.development-artifacts/loop-piercing-census-20261126/`.
36/126 current fixtures have 130 events: 109 neighbor-helix, 21 parent, zero
loop-self. Every 80 nt reverse fixture has parent helix P–OP2 at anchor bp+5
piercing loop base 2 sugar; all 21 appear only after bond fitting. Neighbor events
cluster at forward bp32–33/42–43 and reverse bp38/48–49 in this 2HB environment.
Only lengths 6/30/80, ratio3, plane0°, offset0.50 nm were checked; exact length
threshold and other settings remain unknown. Direction and scaffold/staple role
are confounded in these fixtures. Current geometry remains selected.

Rigid-translation A/B (November 26, production unchanged): user clarified that
outward offset should translate the entire existing loop without taper/refitting,
and explicitly authorized stretched attachment connections. Diagnostic script
`experiments/loop_rigid_translation_comparison.py`; evidence/review:
`.development-artifacts/loop-rigid-translation-20261126/`, localhost:8773.
All 126 fixtures independently replay exactly. All loop positions translate
uniformly; rotations, internal O3′–P lengths and 31647 self-overlaps stay fixed.
Additional +0.25 nm removes all 21 parent ring piercings. +0.75 nm is the smallest
tested shift clearing every parent atom overlap (8358→0); attachment lengths
0.507–1.389 nm. Neighbor contacts can worsen: +0.75 nm has 16584 versus14131,
with134 neighbor piercings versus109 current. +3 nm clears all helix atom overlaps,
but leaves one stretched-attachment piercing in 6nt reverse bp38; attachment
lengths2.694–3.559 nm. These offsets are additional to current0.50nm shaped geometry.
User authorized diagnostic stretching only; no new production selection yet.

Latest user selection (November 26): additional **+1.00 nm rigid translation**
is the working candidate for further A/B investigation. Focus on loops **below
40 bases**; longer motifs should use another solution per user. This is a scope
restriction, not an implemented editor hard limit. Production remains unchanged
pending explicit promotion. Selection recorded in rigid-translation evidence
`working-candidate.json`. On existing6/30nt fixtures at+1nm, 13/84 cases contain
58 neighbor-ring piercings. User subsequently granted the per-base rotation comparison at fixed bead/slab
centers; completed results are recorded below.

Neighbor-ring rotation A/B (November 26): user authorized per-base rotations
on the +1nm working candidate, below40 bases. 84 fixtures (6/30nt, both directions,
bp30..50) audited and independently replayed exactly. Strict no-linker-growth
search accepts zero changes (58 piercings remain). Ring-priority local search
allows up to0.10nm extra per linker versus baseline; keeps bead/slab centers and
all helix atoms fixed, guards per-group atom-overlap count/depth and rejects new
piercing identities. Piercings58→32, affected cases13→11; neighbor atom overlaps
6673→6465, self10899→9787, parent stays0. 93 linkers lengthen, max0.090916nm;
mean O3-P0.393709→0.393741nm, max1.619348→1.634093nm. Fully clears6nt forward
bp33 and30nt reverse bp37. Local5degree/four-sweep search, not global optimum;
other sub40 lengths untested. Full/atomistic review verified at localhost:8774.
Evidence `.development-artifacts/loop-neighbor-rings-20261126/`; algorithm
`experiments/loop_neighbor_ring_comparison.py`. The user subsequently authorized production promotion of this rotation candidate;
see the current production state above.

Previous loop orientation (November 25): `strand-loop-ellipse-v2` rotates
all inserted bases 180° from the original v1 frame, except the two major-axis
tip turning regions, which rotate +90° (net from v1, about local backbone
tangents). A tip region includes bases within one ssDNA contour step (0.68 nm)
axially from either extremum. Single extremal-base exceptions left short-loop
neighbor collisions; the turning regions remove those in the checked fixtures.
On a six-base loop the two regions cover all six bases. Backbones, roots and
nonloop geometry are unchanged. Both editors consume the same geometry authority.

`experiments/loop_orientation_v2_review.py` rebuilds and independently audits the
126 recorded 2HB cases (6/30/80 nt, 21 phases, both directions). Zero loop-self
display intersections remain; total base-display contacts fall 646→314, with
parent/neighbor-helix and fixed-backbone contacts still present. These are default
Full solid checks, not atomic clash/piercing validation. Evidence, frozen source,
independent replay and viewer: `.development-artifacts/loop-orientation-v2-20261125/`.
The earlier orientation search remains isolated in
`.development-artifacts/loop-clearance-20261125/ab/`; it was not promoted.

The shared Add/Edit Loop popup uses NADOC modal/input/button classes and theme
tokens, aligned numeric fields, a primary save action and destructive remove action.

Both editors offer **Add loop here** on scaffold/staple bases, then **Edit loop…**
for count, aspect ratio, rotation around the helix, and removal. `Strand.loops`
records unpaired nucleotides after the selected base in 5′→3′ traversal, before
its existing next nucleotide. The complementary strand and duplex bp register
stay unchanged. Existing helix-wide `LoopSkip` marks retain their old semantics.
The D009 reference crop shows a compact counted loop (30 nt); cadnano uses one
counted glyph on the owning track. Full/Beads use an arc-length-sampled ellipse,
long axis parallel to the helix, with both attachment nucleotides fixed.

Scaffold assignment consumes loop bases in order. New staple loop bases are N;
Edit sequence changes them, and later scaffold assignment preserves those manual
loop bases. The native `strand-loop-set` operation records all inputs, supports
undo, and independently replays after save/reopen. Nick/ligation preserve loop
ownership and sequence; edits that would orphan/drop a surviving loop are refused.
A 3′ terminus cannot anchor an internal loop because it has no next nucleotide.

Atomistic display now includes loops in Ball & Stick, VDW, Stick, and Detail
Surface. Rigid measured nucleotide templates anchor O5′ to each loop backbone
bead and follow the Full view's ring orientation (including the tip quarter
turns). Sequence register, copy identities, and anchor→loop→next bonds are
preserved; existing helix atoms stay fixed. Unassigned N uses the standard
thymine display placeholder with a warning. Inter-residue linkers are unrelaxed:
the explicit `strand_loop_display` build/cache path is display-only, and default
atomistic export/simulation, oxDNA, and cadnano/scadnano interchange still refuse
loops. Native NADOC persistence and sequence CSV remain available. Legacy
multi-base duplex insertions are not automatically converted.

Atomistic checks: `tests/test_strand_loop_atoms.py` (12 passing); focused related
regressions (111 passed, 1 skipped before the final two guard tests); real-browser
four-mode review `frontend/e2e/strand_loop_atoms.spec.js` (passed). Screenshots:
`.development-artifacts/strand-loop-atomistic-20261125/`. Isolated review workspace
is removed after evidence collection.

Outward-offset investigation (2026-11-26): user explicitly authorized A/B testing
for outward ellipse offsets. `experiments/loop_offset_comparison.py` is isolated
from production; evidence/replay/viewer live in
`.development-artifacts/loop-offset-20261126/`. Across 126 recorded 2HB cases,
0.50 nm smooth outward body offsets with fixed roots and refitted contour remove
all parent Full intersections (147→0), but leave atom overlaps (17976→8295) and
increase neighbor overlaps (11752→14210). Some short-loop unrelaxed O3′–P linkers
worsen. These are T-placeholder display models, not physically relaxed models.
All evidence independently regenerated exactly; production geometry was unchanged
at that investigation stage. The later explicit selection is documented above.

Rotation-only follow-up (2026-11-26): user authorized A/B and selected the 0.50 nm
outward candidate as the sole positional baseline. Isolated
`experiments/loop_bond_rotation_comparison.py` rotates rigid loop residues about
each fixed bead-to-slab-center axis. Evidence:
`.development-artifacts/loop-bond-rotation-20261126/`. The final contact/ring-guarded
search reduces mean O3′–P length 0.576→0.453 nm across 126 cases, with no individual
linker lengthening, no increase in atom-contact counts/depth by group, and no new
ring-piercing identities. Existing piercings remain (103→56); Full neighbor display
intersections increase 193→202. Attachment bond lengths have analytic rigid-rotation
minima 0.296–0.774 nm, above the 0.160 nm target. Both displayed centers and all
nonloop atoms stay fixed. Physical ring centroid is not identical to slab center.
These guarded alternatives were not selected for production; the later user
selected the bond-only optimum described above. Internal-torsion fitting and
simulation remain outside this work. See the evidence's replay and invariant reports.

Tests: `tests/test_strand_loops.py`; shared dialog/glyph/sequence tests; real
right-click flows in `frontend/e2e/strand_loops.spec.js` on an isolated server.

## Scoped scaffold assignment (2026-11-05)

Assign Scaffold Sequence now offers Default, cluster, and scaffold-strand targets
in both 3D and cadnano. The 3D menu initializes from the selected scaffold/domain
or cluster; explicit strand context-menu targets take precedence. Cadnano uses
its selected strand and also offers cluster targets in the dialog. No selection
keeps the first editable scaffold behavior.

Cluster scope includes whole non-reference scaffolds only. A scaffold crossing
the cluster boundary requires an explicit whole-strand target; domain-scoped
cluster membership uses the same bp coverage rules as native reconciliation.
Multiple targets prompt “Multiple scaffolds detected, assign sequence to all?”
with Yes/No. No keeps the assignment dialog open. Yes restarts the chosen sequence
at each scaffold's existing 5′ end; it does not route/connect separate scaffolds.
The native assign-scaffold-sequence command records `cluster_id` or `strand_id`
and shares the scope resolver with independent replay. Assignment is atomic;
other scaffold/staple sequences are unchanged. Short sequences retain N padding.

Scope validation: 5 focused backend tests pass, including guarded saved/reopened
replay. Full frontend: 10,148 passed, 1 skipped (879 files). Both editor flows and
24 smoke tests pass; browser scratch cleanup verified. FAST: 20,666 passed,
19 skipped, known CPD failure plus aptamer capture-budget failure (exact retry
passed in 0.37 s call time); FULL deferred, no per-test timing violators.
The user's existing `test.nadoc` accepts scoped assignment in isolated memory and
preserves other strands, but its saved input already has an independent replay
mismatch in loadout fields. No derived user file was published or saved.
Evidence: `.development-artifacts/scaffold-sequence-scope-validation.json`.

## Staple temperature view (2026-11-05)

The Tm button beside Length cycles off/domain Tm/total staple Tfold in Full/Beads
part views and the standalone cadnano path editor. Both editors share the model,
Celsius palette and legend, with lower/upper numeric bounds, draggable handles and
full-data-range reset (shared flex-map range math). Bounds persist across modes
within each editor session and only recolor cached estimates. Cadnano caches estimates across pan/zoom and refreshes
them on sequence/routing changes. Read-only calculation uses assigned sequences and the existing
loop/skip projection; no structure or feature-history mutation. Domain mode uses
SantaLucia–Owczarzy; total uses the user-selected PNAS 2024 model with a circular
scaffold for every active scaffold molecule (including secondary scaffolds).
Each staple uses its own scaffold’s contour length; inter-scaffold staples remain
unavailable rather than being treated as intramolecular loops. Both assume 10 mM free Mg²⁺ and excess 200 nM staples. Missing
or unsupported cases are gray. See [model, sources and limits](../docs/staple_temperature.md).

## Scaffold target layout and Pointer sequence (2026-11-23)

The shared `scaffold_sequence_target` control constrains its select to the
dialog width and stacks its label, so long imported scaffold identifiers do not
force horizontal overflow in either editor. Scoped CSS lives beside the module.
The Pointer's 7,249-nt M13mp18 assignment at offset 0 matches all 161 published
staple cores in Praetorius 2017 Supplementary Table 2, including their 740
unpaired T bases. The saved part records the scaffold assignment; staple
sequences remain unassigned. See `docs/dietz_pointer_reconstruction.md`.

## Selection latency (2026-11-05)

Open spreadsheets must not rebuild the full crossover/ligation index per strand.
`strandLength` and `strandSequenceDisplay` accept a caller-owned junction index;
both table builders and the selected-sequence projection share it within each
operation. The temperature estimator also reuses its existing index. No index
is cached across edits. Whole-strand highlights use each rendered row’s strand ID
without re-sorting or recomputing all lengths. Contiguous unselected sequence
uses one text node per run while selected bases keep their precise marks. Cadnano rows now carry the same
stable `data-strand-id` identity as the 3D sheet.

Regression: both spreadsheet tests bound junction reads independently of strand
count, preserve exact section highlights, and verify subsequent edits. The
read-only `e2e/staple_selection_latency.spec.js` exercises both open spreadsheets,
all temperature modes, and real cadnano canvas clicks. It defaults to U6hb;
`NADOC_TEMPERATURE_DESIGN` selects a local large design without copying it.
On VoltronCoreArmV2, 12 cadnano canvas clicks fell from 1,497–1,579 ms to
265–341 ms through redraw with the spreadsheet open (all three thermal modes).
A subsequent sub-200 ms pass updates only the changed sequence/overhang cells,
preserving rows and unrelated editors; unchanged base selections do no rebuilding.
The cadnano grid is cached in screen pixels per canvas context, with size,
transform, row-layout, grid-toggle and stroke-state invalidation. Translucent
periodic mirror passes paint directly. The opaque base layer preserves exact
pixels, including after wheel zoom and grid toggles. Four distinct staples per
thermal mode measured **143–198 ms** through redraw on VoltronCoreArmV2;
the browser regression now enforces <200 ms for every measured click. A later
color-scale validation measured one 216 ms outlier with the overlay off (other
clicks 129–193 ms), so a consistent sub-200 ms guarantee remains unverified.

## Sequence preservation during topology edits (2026-09-19)

`make_nick` slices an assigned sequence at the loop/skip-aware length of its first
fragment. `_ligate` concatenates ordinary assigned strand sequences as well as
native residues; a missing half is filled with unknown bases, while two unassigned
ordinary strands remain unassigned. Fourteen focused regressions pass for both
strand directions, loop/skip offsets, round trips and partial assignments.

## What shipped

### Exact scaffold availability (2026-10-10)

Readiness now includes `scaffold_length`: every active scaffold must exactly equal
7249, 7560 or 8064 nt, or its explicitly declared custom source length. It is not
a maximum-budget check, and assigned/truncated `Strand.sequence` never declares
an available source. `scaffold_length_checks` counts native loop/skip-aware domain
DNA, extra bases on realized crossover/forced-ligation transitions, and terminal
DNA sequences; terminal modifications contribute no nucleotides. The shared
readiness path supplies the same per-scaffold verdict and owning-instance targets
in assemblies, with reference/native-oligo exclusions unchanged.

`assign_custom_scaffold_sequence` persists the full cleaned input length on
`Strand.custom_scaffold_length`; preset assignment clears it. The declaration
survives normal native save/reload and assembly strand projection, is independent
of sequence completeness, and is excluded from simulation fingerprints. Older
custom designs without this declaration need their original custom source
reassigned; readiness reports that remedy rather than guessing from sequence or
feature-history ownership. No route, molecular placement or simulation is changed
by the readiness check. Regression files: `test_scaffold_length.py`,
`test_design_readiness.py`, `test_design_readiness_api.py`, and
`test_readiness_routing_workflow.py`.

**Backend**
- `PATCH /design/strand/{id}` now **accepts a real sequence string**. It previously
  declared a `sequence` field but honoured only `null` — a client sending
  `{"sequence":"ACGT"}` got HTTP 200 and no change (silent-success trap).
  Normalizes (strip whitespace, uppercase), 422 on non-ACGTN or wrong length.
  Recorded as a **`strand-sequence` feature-log** step (new `SnapshotOpKind`), not a
  minor log — a sequence is a build-fingerprint field, so a seek must reproduce it
  or an oxDNA job's stale ⚠ never clears (same reasoning as `overhang-sequence`).
- **Overhang write-back**: bases falling in an `overhang_id` domain are sliced out
  and written to that `OverhangSpec.sequence` **directly** (`model_copy`), NOT via
  `_build_overhang_patch` — that helper resizes the overhang domain to
  `len(sequence)`. Skipped for an overhang carrying sub-domain `sequence_override`s
  (those bases are owned per sub-domain; the UI marks the span read-only).
- **NEW `GET /design/strand/{id}/sequence-context`** (`routes_assign_sequences.py`) →
  `{length, sequence, derived, partner, segments}`, all index-aligned.
- **`sequences.strand_partner_bases(design, strand)`** — the pairing walk extracted
  out of `assign_staple_sequences`, which now consumes it. **ONE implementation** of
  "what does position i pair with": antiparallel scaffold base for a duplex domain,
  overhang base for a binder domain, `None` for an ssDNA overhang tip.
  Proven byte-identical to the old inline walk across 44 real designs + synthetic
  binder / loop-under-overhang / skip-under-overhang cases.
- `strand_sequence_length` + `_domain_seq_span`: the length `strand.sequence` must
  have. Differs from `strand_nucleotide_count` **only** when a loop/skip sits under
  an overhang or binder domain (those use the raw bp span, as the derivation always
  has). **Sequence editors must validate against `strand_sequence_length`**, or a
  hand-typed sequence could be rejected at exactly the length the derivation emits.

**Frontend**
- `ui/strand_sequence_pairing.js` — pure core (mismatch flags with N-as-wildcard,
  validation, overhang splice, run-length decoration, read-only-span preservation).
- `ui/strand_sequence_dialog.js` — `initStrandSequenceDialog({api, showToast})`.
  Three monospace rows in one scroll-synced track: partner / editable field / ruler.
  **api is INJECTED** because the two editors have different api modules
  (`api/client.js` vs `cadnano-editor/api.js`), each already refreshing its own store.
- Item added on **all four surfaces**: 3D `_showColorMenu`, cadnano
  `_showStrandCtxMenu`, and both spreadsheets' Sequence-cell menus. The scaffold
  item was renamed "Assign sequence…" → **"Edit sequence…"** in both editors
  (behaviour unchanged — it still opens the preset/custom scaffold modal).
- `main.js` Δ **+6 lines** (1 import, 1 factory init, 2 one-line handlers): pure wiring.

## Invariants / gotchas

- **The partner row reads 3'→5' left-to-right** — it is laid out in the edited
  strand's 5'→3' index order and pairs antiparallel to it. The row label says so;
  don't "fix" it.
- **Mismatches never block Apply.** Only bad characters and wrong length do. `N` on
  either side is a wildcard (matches backend `is_watson_crick_complement(allow_n=True)`).
- Mismatch colouring lands on the **partner row**, not the input — a `<textarea>`
  cannot colour individual characters.
- A hand-set sequence is deliberately **not** protected from `assign-staple-sequences`
  / `full-autostaple` (user's call: they should override, and both are undoable).
  Only the *implicit* hooks were narrowed — see [[overhang-sequence-display]] §3.

## Menu unification (2nd commit)

`ui/strand_menu_items.js` — pure `buildStrandMenuItems(ctx, handlers)` is now the ONE
definition of the items both editors share (Make Reference/Active, Convert to OH
binding strand, Convert to scaffold, Edit sequence…, Edit extensions…). A handler you
don't pass hides its item, so each editor opts in to what it implements.

- **cadnano** `_showStrandCtxMenu` now renders that list through
  `ui/primitives/context_menu.js` — its bespoke `<div>` + `mkItem` + hand-rolled
  outside-click/Escape listeners are gone.
- **3D** `_showColorMenu` builds the same shared list but still renders it with its own
  `_menuItem`/`_menuSep`, because that menu also carries a colour grid, an RGB input, a
  representation flyout and a `_dismissMenu` singleton shared with six sibling builders
  (`_showNickMenu`, `_showLoopSkipMenu`, …). Swapping its *renderer* is a much larger
  change with no user-visible gain, and the 3D strand right-click **cannot be driven
  headlessly** (LESSONS H7), so it could not be verified. The duplication that actually
  mattered — two copies of the labels/visibility rules, which had already drifted — is gone.
- `placeMenu()` extracted as a pure export from `context_menu.js` (flip-up when it would
  overflow the bottom, cap + scroll when taller than the viewport). The primitive only
  clamped before; the 3D `_placeMenu` had these rules and the primitive didn't.
- **Order change in the 3D menu**: Make Reference/Active now sits above Isolate (it was
  below), matching cadnano.

## Bug found + fixed while verifying

The strand spreadsheet's context menu armed
`document.addEventListener('pointerdown', _removeCtxMenu, {once:true})` with **no
containment check**, so a real pointerdown on an item detached the menu before
mouseup and the item's `click` never fired. **Every item in that menu was dead to a
real mouse** ("Clear sequence", "Set binder sequence…", "Go to strand"). Fixed to
dismiss only on an outside press. See LESSONS for why jsdom can't catch this.

## Tests

- Backend: `tests/test_strand_sequence_edit.py` (24), `tests/test_targeted_reassign.py` (9).
  `just test-smart` → **FAST, 5522 passed**; DEFERRED `FULL` parked in `.nadoc-slow-pending`.
  (2 pre-existing failures in `test_atomistic_geometry_lock.py` — stale goldens, byte-identical
  to HEAD, unrelated.)
- Frontend: `strand_sequence_pairing.test.js` (32), `strand_sequence_dialog.test.js` (27),
  `spreadsheet.test.js` (6), `strand_menu_items.test.js` (17), `context_menu.test.js` (+7
  for `placeMenu`). `just test-frontend` **3335 passed**.
- In-app: verified in a real browser in BOTH editors (dialog renders character-aligned,
  mismatch highlighting, Apply persists + feature-logs, reset-to-derived, overhang
  shading + write-back, no console errors). The throwaway 6hb fixture and its
  Playwright spec were **deleted after verification** per the E2E policy.

Related: [[overhang-sequence-display]], [[overhang_connections]], [[oh_binder]].

## Spreadsheet sectional selection (2026-11-04)

Both spreadsheets now project base/end, domain, overhang, and crossover selections
through `ui/sequence_selection.js`. Junction highlights include their endpoints and
extra bases (including forced ligations); loop copies and skips use the existing
sequence identity projection. Cadnano's element-key adapter supplies exact refs
alongside its existing row-selection IDs. Terminal overhang columns show a marked
readout above the existing editable field. Unassigned selected sequence positions
show `N`; clearing selection removes marks. Cross-window selection transport still
uses the existing whole-strand protocol; section refs are local to each editor.
