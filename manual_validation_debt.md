# Manual Validation Debt — shift register

**What this is.** A queue of features that were shipped with the *accepted caveat*
that their **live gesture / visual appearance was never hand-checked in the running
app** — only verbatim-moved + unit-tested + smoke-gated. Sources: the "regression
caught by" / final caveat column of `main_js_extraction_log.md` (the `NOT
hand-exercised` / `NOT hand-driven` / `not visually confirmed` rows) and the USER
TODO column of `issues_fix_log.md`. These are real validation debt: a silent
behavior break would pass every automated gate we have.

**Intake (push, not just mining).** The initial PENDING queue was *mined* from those
two logs, but new items should be **pushed here directly** by the loop that creates
the debt: a carve-up extraction session (`main_js_carveup.md` step 6b) or a fix
session (`issues_ledger.md`) that ships a stateful/gesture region without hand-checking
its live gesture/visual appends a PENDING `MV-N` row itself — manual op + which
extractions/fixes it discharges + a fixture hint. Don't wait for a future re-mine.

**Why a shift register.** The debt is large and each item needs its own
context-dig (exact menu path, element ids, fixture, edge cases) to turn into
runnable manual steps. Doing them all at once is expensive and produces a wall of
instructions nobody executes. Instead we process **one item per loop**: a loop
pulls the head of the PENDING queue, generates an explicit USER TODO block for it,
and shifts the head off so the next loop starts on the next item.

Items are **deduped by manual operation, not by extraction number** — one live
gesture (e.g. the design-mode cluster Move/Rotate commit) validates several
extractions at once (#71/#78/#79/#80/#81). Each entry lists every extraction / fix
it discharges.

---

## The loop protocol (what each `/loop` iteration does)

1. **Read this file.** The next item is the one marked `▶ HEAD` in the PENDING
   queue below (top of the list).
2. **Dig the context** for that one item: grep the codebase for its real UI entry
   points — menu labels, button/element ids, keyboard shortcuts, the fixture that
   exercises it. **Verify the fixture actually exists** (`ls workspace/` /
   `Examples/`); if none does, say so in the block and either name the closest one
   or flag that a fixture must be built first.
3. **Write the USER TODO block** into the GENERATED section (append, newest at the
   bottom). Structure every block as: **SETUP** (which file to load, how to reach
   the feature) → **MAIN CASES** (numbered, the happy paths) → **EDGE CASES**
   (numbered, the things likely to silently break — boundary inputs, cancel/revert,
   re-edit, cross-layer effects) → **PASS CRITERIA** (what "it works" looks like,
   precise enough to catch a regression) → **WATCH FOR** (known-suspect behaviors,
   e.g. a flagged latent bug to confirm/deny).
4. **Shift the register:** move the processed item's PENDING line into the DONE-
   GENERATING list (it stays in the queue conceptually, just past the head), move
   the `▶ HEAD` marker to the new top PENDING item, and update the counts + the
   `## Next loop` pointer at the bottom.
5. **Commit:** `docs(manual-debt): generate manual ops for <item-id>`.
6. **When the user later runs a block and reports back,** move that item from
   GENERATED → **VALIDATED** (pass) or **REGRESSION FOUND** (fail, with a one-line
   note + open a fix). That transition can happen in any loop, out of band.

**Loop ends** when PENDING is empty (every item has a generated block). A second
pass over GENERATED → VALIDATED happens as the user actually executes them.

---

## Register state

- Total items: **18**
- PENDING (no manual ops yet): **14**
- GENERATED (ready to run): **3** — MV-1, MV-2, MV-4
- VALIDATED: **1** — MV-3 (selection-rules UX, 2026-06-07)
- REGRESSION FOUND: **0** (MV-3's two regressions were fixed + re-validated same session)

---

## PENDING queue (ordered; `▶ HEAD` = next loop processes this)

Priority = (user-facing value) × (risk a silent break slips every automated gate).
Core editing + default-selection UX first; niche/visual last.

| # | id | feature / manual operation | discharges | fixture hint | why deferred |
|---|----|----------------------------|-----------|--------------|--------------|
| — | **MV-1** | *(processing — see GENERATED)* design-mode cluster **Move / Rotate** tool: right-click cluster → gizmo/panel → ✓ commit | #71 #78 #79 #80 #81 | a cluster-bearing design (e.g. `Examples/26hb_platform_v3.nadoc`) | 3D pointer-pick on a cluster + gizmo-handle drag not drivable at pixel precision (LESSONS H7) |
| — | **MV-2** | *(generated — see GENERATED)* **Overhang Orientation** panel: right-click a rendered overhang → Edit Orientation → step/apply/reset/auto-close; also the migrated context menu | #64, fix #7 | `Examples/NS_trans_fix.nadoc` (51 overhangs) ✓ + `workspace/OH6hb_test.nadoc` (2) ✓ | WebGL raycast on 1 of N overhang beads not drivable |
| — | **MV-3** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — **selection-rules UX** (drill levels, crossover tube, yellow hover+snap, Ctrl+click, cluster Tab removal) | fixes #10 #11 #12 #14 #15 | `Examples/6hb_test.nadoc` ✓ + `Examples/2hb_xover_val.nadoc` ✓ | — |
| — | **MV-4** | *(generated — see GENERATED)* Assembly **multi-select purple union BoxHelper**: Ctrl-lasso ≥2 instances → purple box around the union; drops below 2 → clears | #34 | `workspace/Belt_test1.nass` (parts+groups) or any ≥2-part `.nass` | needs a built ≥2-part assembly + Ctrl-lasso multi-select |
| ▶ HEAD | **MV-5** | Assembly **right-click context menu**: right-click a part → linker-relax (enabled/disabled), attach-to-belt, select; pan-suppress | #69 | `workspace/Linker_Assem_test.nass` / `Belt_test1.nass` | assembly + linker/belt multi-step setup; right-click router |
| | **MV-6** | **Belt polymerize**: built belt assembly → Polymerize along belt → evenly-spaced copies | #32 | `workspace/Belt_test1.nass` / `belt_test.nass` | needs a built belt assembly |
| | **MV-7** | **Coalesced assembly part-refresh**: edit a part in part-context + save burst → shared instances refresh once (not per-instance) | #38 | a multi-part assembly with ≥2 instances of one source part | needs multi-part assembly + part-editor save burst |
| | **MV-8** | Assembly **config animation**: assembly with a saved feature-log configuration → "animate to configuration" tweens instances | #68 | an assembly that has ≥1 saved configuration (may need to create one) | needs assembly WITH a saved configuration |
| | **MV-9** | **Assembly open from library**: open a `.nass` from a library row → enters assembly mode cleanly | #59 | any `workspace/*.nass` | part-open exercised live; assembly-open path verbatim-only |
| | **MV-10** | **Autosave write-back + server-restart recovery**: workspace-backed file + edit burst → debounced save; kill+restart backend → silent recovery badge | #53 #55 | any workspace-backed `.nadoc` | needs workspace file + edit burst + a real backend restart |
| | **MV-11** | **Two-real-tab cross-doc sync** + co-editing "saved" badge sibling indicator | fixes #2 #4 | same file opened in two browser tabs | BroadcastChannel can't cross Playwright contexts |
| | **MV-12** | **Overhang-binding context menu**: right-click an overhang-binding line → Bind/Unbind/Delete | fix #6 | a design with non-empty `overhang_bindings` (none known — may need to build) | no fixture has bindings; WebGL right-click |
| | **MV-13** | **FRET / fluorescence glow**: fluorophore-labeled design → View menu Fluorescence / FRET toggles → emitters glow, FRET quench scaling | #24 | a design with fluorophore-modified strands (none known — may need to build) | scaffold-only parts have no fluorophores; glow logic unit-tested only |
| | **MV-14** | **Representation option sliders** real mouse-drag (not JS-dispatch): expand the Representation sidebar section, drag each slider | #83 (partial) | any scaffolded part | panel section collapsed by default → `.fill()` needed visibility; drove via JS-dispatch instead |
| | **MV-15** | **Properties panel for an overhang-/assembly-anchored protein**: select a protein attached to an overhang (and one in an assembly) → panel shows the overhang id + attach-end / part-instance anchor, not just the free case | fix #18 (ISSUE-5) | needs a design with a protein attached to an overhang (none known — build via `/design/protein/attachments`) + an assembly with a protein | only the FREE-anchor branch was eyeballed live; overhang/assembly anchor branches are unit-tested only (no fixture) |
| | **MV-17** | **File-load progress overlay**: open this tab as a part editor (`?part-instance=<id>&assembly-doc=<docId>` — i.e. dive into a part from a live assembly) → the `#file-load-progress` overlay appears ("Opening Part"), the progress bar fills, the log lines append, "▸/▾ Details" toggles the log pane, and it auto-hides green on success (or turns red + shows the actions row + main-menu button on failure) | #87 | a live assembly with ≥1 part instance (e.g. `workspace/Belt_test1.nass`), then dive into a part | only fires on the `?part-instance=` part-editor boot path — needs a spawned part tab off a live assembly; boot console-error gate constructs the factory but never SHOWS the overlay |
| | **MV-18** | **Blunt-end (domain-end) menus**: load a design → left-click a rendered blunt/domain-end ring → the right-sidebar action panel appears ("helix N bp M") → Extrude opens the continuation slice plane (amber ghost), Bend/Twist start the deform tool at that end; ALSO right-click the ring → context menu at cursor → same Extrude/Bend/Twist; outside-click dismisses the ctx menu | #88 | a design with exposed blunt ends (e.g. `Examples/26hb_platform_v3.nadoc`) | panel/ctx appear only on a 3D domain-end ring pick (WebGL raycast at pixel precision); the action paths' store/slicePlane/deform effects are unit-pinned, the teardown `hidePanel` is smoke-covered, but the live click→panel→action gesture is human-eye only |
| | **MV-16** | **Atomistic / surface representation VISUAL**: load a design → F6 VDW (space-fill atoms render, CG hidden) / F7 Ball & Stick (bonds render) / F5 Surface (molecular SES/VdW *mesh* appears, correct shape, opacity + probe-radius sliders + strand/uniform colour buttons affect it) / per-region overlay (pin a strand→VDW/surface while base stays full — overlay coexists with CG, no z-fight); F4 restores. Confirm the actual rendered geometry *looks right*, not just the panel toggles. | #86 | a representative `.nadoc` (e.g. `Examples/26hb_platform_v3.nadoc`); per-region needs a design with `representation_overrides` (mixed_representation work) | Tier-3 golden-image "does it look right" check (deliberately NOT automated — needs a pinned rasterizer); the F6/F5/F4 panel-toggle + zero-console path IS covered by the #86 exercise, but the mesh/atom *appearance* is human-eye only |

---

## GENERATED (manual ops ready — run these, then report pass/fail)

### MV-1 — Design-mode cluster Move / Rotate tool
*Discharges extractions #71 (flex-relax sub-block), #78 (Move/Rotate panel shell),
#79 + #80 (flex bridge re-emit dedup), #81 (tool gesture core). LESSONS H7 — the
standing "design-mode cluster-gizmo 3D-drag commit not hand-driven" caveat for the
whole Translate/Rotate band.*

**Why this is the head item.** Five extractions all rest on one live gesture that no
automated gate touches: activating the Move/Rotate tool on a real cluster, dragging
it, and committing. The assembly path *is* covered by `assembly_move_tool.spec.js`
(real raycast) — it's the **design-mode** path that's pure verbatim-move + jsdom
factory tests. A break here corrupts edits silently.

**SETUP**
1. Start both servers (`just dev` + `just frontend`), open `http://localhost:5173`.
2. Load a design that has clusters — `Examples/26hb_platform_v3.nadoc` is the
   canonical multi-cluster geometry fixture. (If clusters aren't visible, open the
   **Clusters** panel / confirm cluster auto-detect is on so a cluster is
   selectable.)
3. Enter cluster-selection (drill to the **cluster** level — Tab cycles selection
   levels; the engaged level shows in the selection-filter row). Left-click a
   cluster so it's the active/drilled cluster.

**MAIN CASES**
1. **Activate via right-click.** Right-click the selected cluster → context menu →
   **"Move / Rotate"**. Expect: a transform gizmo attaches at the cluster, the
   **Move/Rotate** right-sidebar panel opens with numeric translate/rotate fields,
   and a floating green **✓** button appears bottom-left.
2. **Translate by gizmo drag.** Drag a gizmo translate handle. Expect: the cluster's
   beads move live (preview), the panel's translate fields update to match.
3. **Rotate by gizmo drag.** Drag a rotation ring. Expect: live rotation about the
   pivot; panel rotate fields update.
4. **Commit.** Click **✓**. Expect: the transform sticks, the gizmo/panel close, and
   a **`cluster_op` (Move/Rotate) entry appears in the Feature Log**. Geometry should
   look identical to the previewed pose (no snap-back, no jump).
5. **Commit via panel inputs (no drag).** Re-select the cluster → Move/Rotate, type a
   value into a translate field (press Enter / blur), then ✓. Expect: same commit
   path as the drag — this is the input that drives `_mrCommitInputs` (the path the
   automated assembly test uses).

**EDGE CASES**
1. **Cancel reverts.** Activate, drag to a clearly different pose, then press
   **Escape**. Expect: the cluster snaps **back** to its pre-tool pose and **no**
   Feature Log entry is added.
2. **Pivot selection.** In the panel, switch the pivot dropdown (centroid / joint /
   ssDNA, whichever the cluster offers) and rotate. Expect: rotation pivots about the
   chosen point, not always the centroid.
3. **Re-edit an existing op.** From the Feature Log, edit the `cluster_op` you just
   committed. Expect: the tool reopens **prepopulated** with that op's values;
   changing + ✓ edits the existing entry **in place** (does not append a new one).
4. **Stale-op guard.** Commit two Move/Rotate ops on the *same* cluster, then try to
   edit the *earlier* one. Expect: a toast "Edit blocked: a later move/rotate exists
   for this cluster. Edit the latest one." (no silent corruption).
5. **Three-Layer Law spot-check.** After a commit, the move must have written to the
   **topological** cluster pose and the geometry rederived — switch representations
   (F1–F7) and confirm the new pose holds in every rep (it's not a display-only
   shimmer that a rebuild would lose).

**PASS CRITERIA**
- Activate → drag/type → ✓ leaves the cluster in the dragged/typed pose, persisted,
  with exactly one Feature Log `cluster_op` per commit.
- Escape always reverts with no log entry.
- Re-edit modifies in place; the stale-op guard fires.
- No console errors at any step (keep devtools open).

**WATCH FOR (flagged latent bug — confirm or deny)**
- **ssDNA flexible-arc rebuild on commit.** If the moved cluster has *anchored ssDNA
  flexible arcs* between it and another cluster: the tool's two commit paths pass
  `_refreshClusterOverlays({ withFlexibleArcs: false })`, whereas the response-delta
  (undo/redo) paths pass `true`. So after a **tool** commit the flexible arcs may
  **not** rebuild to follow the new pose, while an undo/redo would. Set up a cluster
  with an ssDNA flexible arc to a neighbor, move it, and report whether the arc
  visually follows. If it lags/stales → that's the flagged bug (do **not** fix
  blind; report so the user can decide — verbatim-rule region).

---

### MV-2 — Overhang Orientation panel + migrated context menu
*Discharges extraction #64 (the orientation panel lifted out of main.js —
`ui/overhang_orientation_panel.js`, factory `initOverhangOrientationPanel`) and fix
#7 (the right-click menu migrated onto the shared `createContextMenu` primitive —
`ui/overhang_orientation_menu.js`). Both have jsdom/vitest coverage
(`overhang_orientation_panel.test.js`, `overhang_orientation_menu.test.js`) but the
**live WebGL raycast onto 1 overhang of N + the gizmo drag + the instant client-side
preview** are the never-hand-driven parts.*

**Why this needs a human.** The unit tests pin the menu item set, the single-vs-multi
gating, and `buildOverhangRotationOps` (the delta-compose math). What they cannot
touch: the raycast that decides *which* overhang you right-clicked (domain bead, cone
over an overhang domain, or a Ctrl-lasso union), the rotate-only TransformControls
gizmo, and the no-server preview that only commits on **Apply**. A break in any of
those passes every automated gate.

**Routing facts (so you know where to click):** the right-click menu fires via
`selection_manager.js` → `onOverhangRightClick` → `_orientMenu.show` (main.js:857).
A **single** overhang menu is reached by right-clicking an overhang in **domain**
selection level (or a strand cone that sits on an overhang domain). A **multi**
overhang menu is reached by **Ctrl-lasso** over ≥2 overhang domains, then right-click.
Selection level is set by the `#select-filter` row buttons or **Tab**; **Esc** → default.

**SETUP**
1. Start both servers (`just dev` + `just frontend`), open `http://localhost:5173`,
   keep devtools console open.
2. Load `Examples/NS_trans_fix.nadoc` (51 overhangs — dense, the canonical overhang
   fixture). For the single-vs-multi gating checks, `workspace/OH6hb_test.nadoc`
   (exactly 2 overhangs) is smaller and easier to aim at — use whichever lets you
   land a clean right-click.
3. Make overhangs visible/selectable: zoom in past cylinder-LOD so individual beads
   render; set the selection level to **domain** (Tab or the `#select-filter` row) so
   a right-click resolves to an overhang domain rather than a whole strand.

**MAIN CASES**
1. **Open the context menu on one overhang.** Right-click directly on a rendered
   overhang (its domain bead or terminal cone). Expect a `.context-menu` with exactly:
   **Edit Orientation · Reset Orientation · Set Label… · Generate OH binding strand ·
   Open Overhangs Manager… · Clear All Overhangs** (last one red/danger), plus a
   **Representation** flyout. Set Label / Generate appear **only** for a single
   overhang.
2. **Edit Orientation opens the panel + gizmo.** Click **Edit Orientation**. Expect:
   the right-sidebar **Overhang Orientation** section (`#overhang-orient-panel`)
   un-hides showing the overhang's label/id, three axis rows each with **−45 / value /
   +45** controls (`oo-rx/ry/rz`), and **Reset / Cancel / Apply** buttons; a
   **rotate-only** TransformControls gizmo attaches at the overhang's junction
   (root-bead) pivot — three rotation rings, no translate arrows.
3. **Step buttons preview live.** Click **+45** on X (`oo-rx-inc`). Expect: the
   overhang visibly rotates 45° about its junction *instantly* (no server round-trip /
   no spinner), and the X field reads `45`. Click it again → `90`, etc. (accumulates).
4. **Gizmo drag previews live.** Drag a rotation ring. Expect: the overhang follows
   the drag in real time and the angle fields update to match the accumulated delta.
5. **Typed absolute angle previews.** Type a value into the X field and press
   **Enter**. Expect: the overhang snaps to that absolute angle (delta computed from
   the current accumulated rotation), previewed client-side.
6. **Apply commits.** Click **Apply**. Expect: the rotation persists (the panel closes,
   gizmo detaches), an **`overhang_rotation` entry appears in the Feature Log**, and
   the geometry stays exactly where it was previewed — no snap-back, no jump. The
   committed rotation is the *delta composed onto the existing* rotation
   (`patchOverhangRotationsBatch`), so applying twice stacks.

**EDGE CASES**
1. **Cancel reverts the preview.** Edit Orientation → step/drag to a clearly different
   pose → click **Cancel**. Expect: the overhang snaps **back** to its pre-edit pose
   (panel re-fetches server geometry) and **no** Feature Log entry is added.
2. **Reset zeroes the orientation.** With an overhang that already carries a rotation,
   Edit Orientation → **Reset**. Expect: the overhang returns to identity orientation
   `[0,0,0,1]` (this *does* hit the server — `patchOverhangRotationsBatch` with
   identity) and the gizmo re-attaches at zero. (Note: the **Reset Orientation** menu
   item — without opening the panel — does the same identity-batch for every clicked
   overhang. Verify both the menu item and the in-panel button.)
3. **Multi-overhang selection gates the menu.** Ctrl-lasso ≥2 overhang domains →
   right-click. Expect: the menu **omits** Set Label… and Generate OH binding strand
   (single-only), still shows Edit Orientation / Reset / Open Manager / Clear All.
   Edit Orientation on the multi-selection rotates **all** selected overhangs about
   **each one's own** junction pivot (the gizmo centers on the right-clicked anchor).
4. **Auto-close on structural change.** With the panel open on an overhang, trigger a
   change to the overhang *set* — e.g. **Clear All Overhangs**, or delete/add an
   overhang elsewhere. Expect: the panel **auto-closes** (the subscriber fires only
   when the overhang id-set changes, not on a rotation patch). A plain rotation Apply
   must **not** close it via this path (it closes via its own Apply→close).
5. **Set Label round-trips.** Single overhang → **Set Label…** → type a label → it
   shows on the overhang / in the panel header; **Cancel** at the prompt must not patch.
6. **Single-overhang special: Generate OH binding strand.** Fire it on one overhang;
   expect a binder strand generated for that overhang id (no error). (Lower priority —
   binder generation is separately covered; just confirm the menu wiring fires the
   right call.)

**PASS CRITERIA**
- Right-click resolves to the *correct* overhang (the one under the cursor), with the
  expected item set + single/multi gating.
- Edit → step/drag/type previews instantly with **no server round-trip**; angle fields
  always mirror the current accumulated delta.
- **Apply** persists exactly one `overhang_rotation` Feature Log entry per commit, in
  the previewed pose; **Cancel** reverts with no entry; **Reset** returns to identity.
- Panel auto-closes when the overhang set changes; stays open across a rotation patch.
- No console errors at any step.

**WATCH FOR (suspect behaviors — confirm or deny)**
- **Pivot correctness on multi-select.** The gizmo centers on the right-clicked
  anchor's pivot, but each overhang rotates about **its own** junction
  (`_ooPivotPositions[id]`). On a Ctrl-lasso of overhangs that are far apart, confirm
  each one pivots about its *own* root bead — not all about the anchor's pivot (that
  would be a regression and would visibly fling distant overhangs).
- **Preview-vs-commit drift.** Because Apply commits the *delta* composed onto the
  existing rotation, watch for a one-step double-apply or off-by-one (e.g. the pose
  jumping further than previewed the instant you click Apply). The preview should be
  pixel-identical to the committed result.
- **Stale gizmo after Apply.** After Apply the panel closes and the gizmo detaches;
  confirm no orphaned rotation rings linger in the scene, and re-opening Edit
  Orientation on the same overhang starts from a fresh zero delta (fields read 0),
  not the previously-applied angle.
- **Extrude overhangs.** `NS_trans_fix` may contain extrude-type overhangs
  (independent helix). For those the preview also re-poses the helix axes +
  overhang-location sprites (`isExtrudeOverhang` branch). Right-click an extrude
  overhang and confirm the whole stub (axis + label sprite) rotates coherently, not
  just the beads.

---

### MV-3 — Drill-v2 selection on a multi-helix design (with crossovers)
*Discharges fixes #10 #11 #12 #14 #15 — the unified `selectionLevel` model that
replaced the legacy auto-drill ladder / manual filter pins / Tab drill-lock (those
were physically deleted 2026-06-06). Pure model in `scene/selection_level.js`; click
paths are `_v2HandleBead` / `_v2HandleCone` / `_v2HandleArc` in `selection_manager.js`.*

**Why this needs a human.** Every automated test runs against a **single-helix**
harness fixture — so it has **no crossovers**, and the three things that only exist
on a real multi-helix design with inter-helix crossovers are entirely un-exercised:
(1) the thin crossover **arc** as a pick target (its cone is hidden, so the arc is
picked by 18-px screen proximity, not raycast), (2) the **red hover tube → green
selection tube** colour transition on that arc, and (3) a multi-element **Ctrl-lasso
that respects the engaged level** across more than one helix. The pure model is
unit-pinned (`selection_level.test.js`); the live gesture is not.

**FIXTURE** — you need a multi-helix design that *actually has crossover arcs*.
Verified counts (probed from the files):
- **`Examples/6hb_test.nadoc`** ✓ — **6 helices, 2 crossovers**. **Primary** — true
  multi-helix, and it has arcs to hover/click.
- `Examples/2hb_xover_val.nadoc` ✓ — 2 helices, **4 crossovers** (denser arcs, easier
  to land an arc click) but only 2 helices — use as the **arc-specific backup**.
- ⚠️ **Do NOT use `Examples/26hb_platform_v3.nadoc` for the arc steps** — it has 26
  helices but **0 explicit crossovers**, so there are no arcs to pick. (Fine only for
  the level-button / Tab / lasso steps that don't need an arc.)

**SETUP**
1. Start both servers (`just dev` + `just frontend`), open `http://localhost:5173`,
   keep devtools console open.
2. Load **`Examples/6hb_test.nadoc`**. Zoom in past cylinder-LOD so individual beads,
   cones, and the thin crossover arcs between helices render.
3. The selection level is driven by the **`#select-filter`** button row (buttons:
   **clust / strand / line(=domain) / ends / xover**) and by **Tab**; **Esc** → default.
   "No button lit" = the **default** drill level.

**MAIN CASES**
1. **Default drill ladder.** With no filter button lit: 1st click on a strand →
   the whole **strand** highlights green. 2nd click *on that same strand*, **on a
   backbone bead** → drills to the **end/nucleotide under the cursor**; 2nd click **on
   a cone** → the **crossover**. A repeat click keeps the leaf. Clicking a *different*
   strand restarts at strand level.
2. **`strand` fixed level.** Click the **strand** filter button (or Tab to it). Now
   *every* click selects the whole clicked strand — no leaf drill on a 2nd click.
3. **`domain` (line) fixed level.** Click **line**. Every click → the clicked
   **domain** only (not the whole strand, not a single bead).
4. **`end` fixed level.** Click **ends**. Clicking a terminus selects the **5'/3' end
   bead** (gold measurement-bead style), not the strand.
5. **`xover` fixed level — arc click → GREEN TUBE.** Click **xover**, then click
   directly on a thin **crossover arc** between two helices. Expect: a **green glow
   tube traced along the arc polyline** (not an endpoint sphere), and the Properties/
   selection reads a **crossover** object. Click the **same** arc again → it **toggles
   off** (deselects). (Use `2hb_xover_val.nadoc` if the 6hb arcs are hard to hit.)
6. **Default-level arc hover preview → RED TUBE.** Back at **default** level, select a
   strand that *carries* a crossover (so `mode = strand`). Hover the cursor over that
   strand's crossover arc **without clicking**. Expect: a **red glow tube** along the
   arc (the "a click here would select this crossover" preview). Click it → the red
   preview becomes the **green** selection tube (case 5's result).
7. **Tab cycles the level.** Press **Tab** repeatedly with the canvas focused. Expect
   the engaged filter button to advance **cluster → strand → domain(line) → end(ends)
   → xover → none(default) → cluster …**, the lit button mirroring each step.
8. **Esc → default.** From any engaged level press **Esc**. Expect: all filter buttons
   unlight (back to the drill ladder) and the current selection clears.

**EDGE CASES**
1. **Engaged level survives an empty-space click.** Engage e.g. **domain**, click empty
   background (deselects the object). The **domain** button must **stay lit** — an
   empty click clears the *selection*, not the *level*. (This is the ISSUE-4 fix: the
   old model would silently drop back to a different level.)
2. **Multi-element Ctrl-lasso respects the engaged level.** This is the core
   `lassoCaptureType` fix (#14/#15). Ctrl-drag a rectangle over a region spanning
   **≥2 helices** and check WHAT it captures at each level:
   - default / **strand** → whole **strands** in the rect.
   - **domain (line)** → **domains** in the rect (white domain highlight), not strands.
   - **end** → only the **5'/3' termini** beads in the rect (not every bead).
   - **xover** → the **crossovers** whose arcs fall in the rect.
   The old "Tab to ends, lasso grabs a cluster" bug is the regression to watch for.
3. **No legacy red sf-pinned BoxHelper.** Through ALL of the above, confirm there is
   **never** a stray **red wireframe selection box** drawn around a strand/region.
   That red "selection-filter-pinned" BoxHelper was part of the deleted legacy model;
   the only red you should ever see now is the **arc hover tube** (case 6). Green =
   selection (glow / arc tube), red = hover-preview arc only.
4. **Filter button toggles off to default.** Click an already-lit level button (e.g.
   **xover** when xover is lit). Expect it to turn off → back to **default** (not stay
   stuck lit).
5. **Hover preview is scoped.** The red arc/bead hover preview should appear **only**
   at default level **with a strand already selected**, and **only** for elements on
   *that* strand — hovering a different strand's arc shows nothing. Also: it must
   **not** appear when the cursor is over the right ~300 px (the sidebar panel zone).

**PASS CRITERIA**
- Each level (default ladder / strand / domain / end / xover) selects exactly the
  element type described; the `#select-filter` lit button always matches the engaged
  level, and Tab/Esc move it as specified.
- Crossover **arc**: hover = red tube, click = green tube + crossover selected, 2nd
  click toggles off. (At least on `2hb_xover_val.nadoc` if 6hb arcs are too thin.)
- Ctrl-lasso captures the SAME element type the engaged level's click would — verified
  across ≥2 helices for at least strand / domain / end.
- An empty-space click clears the selection but **keeps** the engaged level lit.
- **No red wireframe selection BoxHelper appears anywhere.**
- No console errors at any step.

**WATCH FOR (suspect behaviors — confirm or deny)**
- **Arc pickability at distance / odd camera angles.** The arc is picked by 18-px
  *screen-space proximity* to its projected polyline (`_findStrandArcAt`), not by a
  3D raycast. On a steeply foreshortened arc or when two arcs overlap on screen,
  confirm the *intended* arc is the one that lights — a wrong-arc pick or a dead zone
  is the likely silent break.
- **Tab swallowed by a gizmo.** Tab is owned by `cluster_gizmo` / `instance_gizmo`
  while a Move/Rotate gizmo is active. Confirm Tab cycles selection levels **only**
  when no transform gizmo is up (it should be skipped, not double-fire, when one is).
- **xover toggle vs. unresolvable arc.** When you click an arc whose crossover can't be
  resolved (forced-ligation edge case) **at xover level**, the handler now **selects
  nothing** (keeps the current selection) — the old strand fallback was removed
  2026-06-07 (see REGRESSION FOUND below). Confirm it does NOT select the strand.

---

## VALIDATED (user-confirmed pass)

### MV-3 — Drill-v2 selection, part-3D editor ✅ VALIDATED 2026-06-07
Discharges fixes #10 #11 #12 #14 #15. Confirmed live by the user across an extended
selection-rules UX session (the original block + a large follow-on overhaul). **The
part-3D-editor selection-rules UX is now validated & finished.** What's in place:

- **Fixed levels select only their own type** — domain/end/xover/cluster no longer
  soft-fall to a whole-strand selection; a mismatched click is a no-op. End level
  selects only 5′/3′ termini.
- **Crossovers are arc-only, rendered as a glow TUBE** — single-click, lasso/additive
  multi-select, and Ctrl+click toggle all use the same green tube (full, double-sided,
  12 radial segments, depthTest-off, r = 0.147 nm). Cones never participate in crossover
  selection; the invisible cross-helix "cones" that FEED the arc pipeline are excluded
  from picking so they can't be selected or flash visible.
- **Ctrl+click** toggles a crossover in/out of the multi-set; **plain click** single-
  selects; lasso respects the engaged level.
- **Generic yellow hover preview** at every filter level (cluster/strand/domain/end/
  xover): hovering shows — in yellow — exactly what a click will select (same FORM as
  the green selection), with snap-to-nearest within 80 px. The already-selected element
  stays green (no yellow on it); other elements preview yellow.
- **Cluster** removed from the Tab cycle (button-only) and its button moved to the gate
  group (skip/loop/ovhg) — a late-stage, occasional tool.
- No legacy red sf-pinned BoxHelper anywhere.

1087 frontend tests green; served `dist/` rebuilt. Tube geometry pinned by
`frontend/src/scene/arc_tube_geometry.test.js` (never NaNs). The earlier MV-3
REGRESSION-FOUND items (below) are resolved by the above.

### MV-4 — Assembly multi-select purple union BoxHelper
*Discharges extraction #34 (the multi-select union box lifted out of main.js →
`scene/assembly_multi_box.js`, factory `initAssemblyMultiBox`). The pure union math
(`selection_bbox.js` `instanceUnionBox`) is unit-pinned and the factory has jsdom
coverage, but the **live Ctrl-lasso over real instances → purple box around the
union → clears when the set empties** gesture is the never-hand-driven part. #34 is
also the extraction that caused the assembly-exit `const`-reassignment TypeError the
smoke teardown gate was added for, so a teardown spot-check belongs here too.*

**Why this needs a human.** Every automated gate runs the *math* (union of N centers)
and the *factory* (does it add/remove a `Box3Helper`), but nothing exercises the real
chain: a Ctrl-drag rectangle in the assembly viewport → `assembly_lasso` projects each
instance center → `multiSelectedInstanceIds` → the RAF-coalesced subscriber calls
`_assemblyMultiBox.update()` → a `Box3Helper` appears at the right extent. The colour
rule (1 part = WHITE, ≥2 parts or any group = PURPLE) and the live re-fit during a
group-gizmo drag are also human-eye-only.

**Routing facts (so you know where to click):**
- Ctrl(or ⌘)-**drag** a rectangle = lasso → instances whose projected center falls in
  the rect populate `multiSelectedInstanceIds` (`main.js:5304` `initAssemblyLasso`
  `onSelect`). A plain (non-additive) lasso *replaces* the set; lasso while already
  multi-selected is **additive** (unions in the new hits).
- Ctrl-**click** (no drag) on a part = toggles that one instance in/out of the set
  (`onClick` → `toggleInstanceSelection`, `main.js:5314`).
- **Plain** (non-Ctrl) click anywhere collapses the whole multi-select back to a single
  select / empty (`assembly_pointer.js:456-465`).
- Colour: `MULTI_BOX_COLOR = 0x8b5cf6` (violet) when `size ≥ 2` OR a group is active;
  `SINGLE_BOX_COLOR = 0xffffff` (white) for exactly one Ctrl-selected part
  (`assembly_multi_box.js:26,62`). The box reads ONLY `multiSelectedInstanceIds` +
  `activeGroupId`, never `activeInstanceId`, so a plain single-click (which the renderer
  already outlines white per-instance) does **not** draw a second box here.
- A **group select** (first click on a grouped part → `selectGroup`) folds every
  transitive group member into the union and draws it PURPLE
  (`assembly_multi_box.js:50-54`).

**SETUP**
1. Start both servers (`just dev` + `just frontend`), open `http://localhost:5173`,
   keep devtools console open.
2. **Open an assembly** (this is an assembly-mode block, not the design editor): File →
   Open → `workspace/Belt_test1.nass`. *(Verified: 62 part instances + 2 groups + 1
   belt — plenty of selectable instances.)* Wait for the parts to render; zoom/orbit so
   a cluster of ≥3 distinct instances is comfortably in view.

**MAIN CASES**
1. **Ctrl-lasso ≥2 instances → PURPLE union box.** Hold Ctrl (⌘ on macOS) and drag a
   rectangle enclosing **≥2** part instances. Expect: on pointer-up, a single **violet
   (purple) wireframe box** appears tightly enclosing the *union* of all captured
   instances (not one box per part). The box should sit on top of the geometry
   (depthTest off — visible even through parts).
2. **Ctrl-lasso exactly 1 instance → WHITE box.** Ctrl-drag a rectangle that catches
   **exactly one** instance. Expect: the box is **white**, not purple (single-part
   case, ISSUE-3a immediate-feedback).
3. **Additive lasso grows the union.** With ≥2 already selected (purple box up),
   Ctrl-drag a *second* rectangle over a different instance. Expect: the new instance is
   **added** (not replaced) and the purple box **grows** to enclose the larger union.
4. **Ctrl-click toggles one in/out.** Ctrl-click an unselected part → it joins the set
   and the box re-fits. Ctrl-click an already-selected part → it leaves the set and the
   box shrinks. When the count crosses 2→1 the box should turn **white**; 1→0 it should
   **vanish**.
5. **Group select draws a purple union.** Click a part that belongs to a **group**
   (Belt_test1 has 2 groups). Expect: the whole group selects (group gizmo at centroid)
   AND a **purple** union box wraps every member of the group.
6. **Plain click clears it.** With a multi-select (or group) active, do a plain
   (non-Ctrl) **left-click on a single part** or on empty space. Expect: the purple/white
   union box **disappears**; you get a fresh single-select (click on a part) or nothing
   (click on empty space).

**EDGE CASES**
1. **Drops below 2 → colour/clear transition.** From a 3-part purple selection, Ctrl-
   click to remove parts one at a time. Expect the exact ladder: 3→2 stays **purple**,
   2→1 turns **white**, 1→0 the box is **removed entirely** (not a zero-size box, not a
   lingering purple frame).
2. **Live re-fit during a group-gizmo drag.** Select a group (purple box up), grab the
   group gizmo and **drag/rotate** it. Expect: the purple box **re-fits every frame** to
   follow the moving members (RAF-coalesced; `group_gizmo.js:389-395`) — it must not lag
   a full gesture behind or stay frozen at the start pose.
3. **Box survives a member move/rotate commit.** After moving the group (case 2), release
   and confirm the box is still correctly fitted to the *new* extent (the subscriber re-
   runs on `assemblyChanged`, `main.js:5143-5148`).
4. **Empty-rect lasso is a no-op.** Ctrl-drag a rectangle over **empty space** (no
   instances). Expect: no box, no error, existing selection cleared/replaced per the
   non-additive rule (empty replace → empty set → no box).
5. **Assembly-exit teardown (the #34 smoke-gate bug).** With a multi-select box up, exit
   the assembly (close the doc / return to main menu / open a design). Expect: **no
   console error** (the original #34 bug was a `const`-reassignment TypeError on assembly
   exit) and no orphaned box left in the next scene.

**PASS CRITERIA**
- Ctrl-lasso of ≥2 instances draws exactly **one** violet union box tightly enclosing
  the union; exactly 1 instance draws a **white** box; 0 draws none.
- Additive lasso + Ctrl-click toggle grow/shrink the box; the 2→1 (purple→white) and
  1→0 (→removed) transitions are crisp.
- A group select draws a purple box around all members; plain click clears any box.
- The box re-fits live during a group drag and stays correct after the commit.
- Exiting the assembly with a box up throws **no console error** and leaves no orphan.
- No console errors at any step.

**WATCH FOR (suspect behaviors — confirm or deny)**
- **The "drops below 2 → clears" phrasing is imprecise — confirm the real rule.** The
  ledger one-liner says the box "clears when the selection drops below 2," but the code
  draws a **white** box at exactly 1 and only removes it at **0**. Confirm you see
  white-at-1 (not a disappearance at 1). If the box vanishes at 1, *that* would be the
  regression.
- **Double box.** Because the union box ignores `activeInstanceId`, a *plain* single-
  click (renderer's own white per-instance outline) must NOT also spawn a union box —
  watch for two overlapping white boxes on a plain single select.
- **Stale box after group move.** Confirm the box doesn't lag one full drag behind the
  members or freeze at the pre-drag pose (the RAF coalescing in `group_gizmo.js` is the
  suspect — it batches re-fits to one per frame).
- **Lasso vs. orbit.** A Ctrl-drag must lasso, not orbit the camera. Confirm OrbitControls
  doesn't also spin during the rectangle drag (the lasso should suppress it).

---

## REGRESSION FOUND (user-confirmed fail → fix opened)

### MV-3 (2026-06-07) — two issues found running the block → **FIXED + re-validated same session** (see VALIDATED)
1. **Fixed levels still let a single click select a strand.** In domain / end / xover
   (and cluster) level, a click on an element that wasn't that type "soft-fell" to
   selecting the whole strand. Fixed: each fixed level now selects ONLY its own type;
   a mismatched click is a **no-op** (current selection kept). `selection_manager.js`
   `_v2HandleBead` / `_v2HandleCone` / `_v2HandleArc` — removed every `_selectStrandV2`
   fallback (cluster/domain/end/xover). `strand` level still selects the strand (its job).
2. **Lasso crossover highlight ≠ single-click highlight.** Lasso/additive multi-select
   drew a cyan arc-line recolor + green glow spheres; single-click draws a green glow
   tube. Fixed: multi-select now renders the **same green glow tubes**
   (`design_renderer.setSelectionArcs` / `clearSelectionArcs`, a pooled mirror of
   `setSelectionArc`); `_applyMultiCrossoverHighlight` + the shift-click arc toggle both
   route through it. The old `unfold_view.updateArcGlow` + `_arcGlow*` path is now
   unused (harmless early-out).
   - *Re-test:* lasso ≥2 crossovers at xover level → each is a green tube identical to a
     single-click selection; shift-click toggles individual arcs in/out as green tubes.

## RE-TEST NEEDED (fix shipped, user not yet re-confirmed)

_(none — MV-3 re-validated 2026-06-07; see VALIDATED)_

---

## Next loop

**▶ Process MV-5 — Assembly right-click context menu** (discharges #69).
Dig: the assembly right-click router (`assembly_pointer.js` right-click handler →
context-menu builder), the menu items (linker-relax enabled/disabled, attach-to-belt,
select) and the pan-suppress behavior (right-drag must orbit/pan, not fire the menu).
**Fixture:** `workspace/Linker_Assem_test.nass` (cross-part linker, for the relax
enabled/disabled gating) and/or `workspace/Belt_test1.nass` (belt, for attach-to-belt);
verify each has the relevant feature. This is an **assembly-mode** block — SETUP opens
the `.nass`. Right-click on a part on a WebGL canvas is the never-driven gesture.
