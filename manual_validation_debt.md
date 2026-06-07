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

- Total items: **17**
- PENDING (no manual ops yet): **15**
- GENERATED (ready to run): **2** — MV-1, MV-2
- VALIDATED: **0**
- REGRESSION FOUND: **0**

---

## PENDING queue (ordered; `▶ HEAD` = next loop processes this)

Priority = (user-facing value) × (risk a silent break slips every automated gate).
Core editing + default-selection UX first; niche/visual last.

| # | id | feature / manual operation | discharges | fixture hint | why deferred |
|---|----|----------------------------|-----------|--------------|--------------|
| — | **MV-1** | *(processing — see GENERATED)* design-mode cluster **Move / Rotate** tool: right-click cluster → gizmo/panel → ✓ commit | #71 #78 #79 #80 #81 | a cluster-bearing design (e.g. `Examples/26hb_platform_v3.nadoc`) | 3D pointer-pick on a cluster + gizmo-handle drag not drivable at pixel precision (LESSONS H7) |
| — | **MV-2** | *(generated — see GENERATED)* **Overhang Orientation** panel: right-click a rendered overhang → Edit Orientation → step/apply/reset/auto-close; also the migrated context menu | #64, fix #7 | `Examples/NS_trans_fix.nadoc` (51 overhangs) ✓ + `workspace/OH6hb_test.nadoc` (2) ✓ | WebGL raycast on 1 of N overhang beads not drivable |
| ▶ HEAD | **MV-3** | **Drill-v2 selection** on a multi-helix design: strand level, Tab cycle, crossover-arc hover(red)/click(green) tube, no red sf-pinned box, multi-element lasso respects engaged level | fixes #10 #11 #12 #14 #15 | a multi-helix design WITH crossovers (harness fixture is single-helix → no xovers) | thin-arc gesture + Tier-3 colour + multi-element lasso need a real multi-helix design |
| | **MV-4** | Assembly **multi-select purple union BoxHelper**: Ctrl-lasso ≥2 instances → purple box around the union; drops below 2 → clears | #34 | `workspace/Belt_test1.nass` (parts+groups) or any ≥2-part `.nass` | needs a built ≥2-part assembly + Ctrl-lasso multi-select |
| | **MV-5** | Assembly **right-click context menu**: right-click a part → linker-relax (enabled/disabled), attach-to-belt, select; pan-suppress | #69 | `workspace/Linker_Assem_test.nass` / `Belt_test1.nass` | assembly + linker/belt multi-step setup; right-click router |
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

## VALIDATED (user-confirmed pass)

_(none yet)_

## REGRESSION FOUND (user-confirmed fail → fix opened)

_(none yet)_

---

## Next loop

**▶ Process MV-3 — Drill-v2 selection on a multi-helix design** (discharges fixes
#10 #11 #12 #14 #15). Dig: the selection-level model (`scene/selection_level.js` +
the `_v2Handle{Bead,Cone,Arc}` paths in `selection_manager.js`), the `#select-filter`
level buttons + **Tab** cycle + **Esc**→default, the crossover-arc hover(red)/click
→ green tube rendering, the absence of the legacy red sf-pinned BoxHelper, and that a
multi-element Ctrl-lasso respects the engaged level + an engaged level survives an
empty-space click. **Fixture caveat from the table:** the harness fixture is
single-helix (no crossovers) — you need a **multi-helix design WITH crossovers**;
candidates: `Examples/26hb_platform_v3.nadoc`, `Examples/multi_domain_test*.nadoc`,
`Examples/2hb_xover_val.nadoc` — verify one actually has crossover arcs before
writing the block (per the selection.md rule the click descriptions there predate
the v2 model, so trust `selection_level.js` + `_v2Handle*` for current behavior).
