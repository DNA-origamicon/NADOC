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
   note + open a fix). That transition can happen in any loop, out of band. When an
   item is VALIDATED, its runnable GENERATED block is **deleted** (the VALIDATED
   summary replaces it) to keep this file lean.

**Loop ends** when PENDING is empty (every item has a generated block). A second
pass over GENERATED → VALIDATED happens as the user actually executes them.

---

## Register state

- Total items: **22** (19 mined MV-1..MV-19 + MV-LNK + MV-RSZ + MV-SCAF, scaffold routing pushed 2026-06-09)
- PENDING (no manual ops yet): **14** (12 mined + MV-RSZ + MV-SCAF)
- GENERATED (ready to run): **1** — MV-5
- VALIDATED: **7** — MV-1 (cluster Move/Rotate, 2026-06-07), MV-2 (overhang orientation, 2026-06-07), MV-3 (selection-rules UX, 2026-06-07), MV-4 (parts/groups multi-select box, 2026-06-07), MV-LNK (assembly linker completion, 2026-06-07), MV-6 (belt polymerize, 2026-06-07), MV-7 (coalesced part-refresh, 2026-06-07)
- REGRESSION FOUND: **0** (MV-1 + MV-2 + MV-3 + MV-LNK enhancements/bugs found during validation were shipped same session)

---

## PENDING queue (ordered; `▶ HEAD` = next loop processes this)

Priority = (user-facing value) × (risk a silent break slips every automated gate).
Core editing + default-selection UX first; niche/visual last.

| # | id | feature / manual operation | discharges | fixture hint | why deferred |
|---|----|----------------------------|-----------|--------------|--------------|
| — | **MV-1** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — design-mode cluster **Move / Rotate** tool: right-click cluster → gizmo/panel → ✓ commit | #71 #78 #79 #80 #81 | a cluster-bearing design (e.g. `Examples/26hb_platform_v3.nadoc`) | 3D pointer-pick on a cluster + gizmo-handle drag not drivable at pixel precision (LESSONS H7) |
| — | **MV-2** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — **Overhang Orientation** panel: right-click a rendered overhang → Edit Orientation → step/apply/reset/auto-close; also the migrated context menu | #64, fix #7 | `Examples/NS_trans_fix.nadoc` (51 overhangs) ✓ + `workspace/OH6hb_test.nadoc` (2) ✓ | WebGL raycast on 1 of N overhang beads not drivable |
| — | **MV-3** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — **selection-rules UX** (drill levels, crossover tube, yellow hover+snap, Ctrl+click, cluster Tab removal) | fixes #10 #11 #12 #14 #15 | `Examples/6hb_test.nadoc` ✓ + `Examples/2hb_xover_val.nadoc` ✓ | — |
| — | **MV-4** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — Assembly **multi-select purple union BoxHelper** (parts + groups selection): Ctrl-lasso ≥2 instances → purple box around the union; white at 1; drops to 0 → clears | #34 | `workspace/Belt_test1.nass` (parts+groups) or any ≥2-part `.nass` | needs a built ≥2-part assembly + Ctrl-lasso multi-select |
| — | **MV-5** | *(generated — see GENERATED)* Assembly **right-click context menu**: right-click a part → linker-relax (enabled/disabled), attach-to-belt, select; pan-suppress | #69 | `workspace/Linker_Assem_test.nass` / `Belt_test1.nass` | assembly + linker/belt multi-step setup; right-click router |
| — | **MV-6** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — **Belt polymerize**: built belt assembly → Polymerize along belt → evenly-spaced copies | #32 | `workspace/Belt_test1.nass` / `belt_test.nass` | needs a built belt assembly |
| — | **MV-7** | ✅ **VALIDATED 2026-06-07** (see VALIDATED) — **Coalesced assembly part-refresh**: edit a part in part-context + save burst → shared instances refresh once (not per-instance) | #38 | a multi-part assembly with ≥2 instances of one source part | needs multi-part assembly + part-editor save burst |
| | **MV-RSZ** | **3D overhang-resize through the scaffold boundary**: select a staple end whose tail extends past the scaffold (an inline overhang) → grab the cyan extrude arrow → drag the tip *inward past the scaffold end* → the overhang shrinks away and the strand becomes flush (or shorter), matching the cadnano editor (no hard stop at the boundary) | (new, this session) | a design with an inline overhang on a staple end (e.g. `Examples/NS_trans_fix.nadoc`, or extrude one) | live pixel-precise 3D arrow-drag past the boundary; `terminalRunLength` + backend merge unit-pinned, gesture human-eye only |
| | **MV-SCAF** | **Section-router scaffold routing of irregular multi-section designs (teeth / dumbbell), seamed AND seamless** — now default-on for any multi-section design via both `auto_scaffold_seamed` and `auto_scaffold_seamless` (decompose trunk+windows → route each → 2-opt splice → buried nick). Programmatically pinned (1 strand, full coverage, inter-tooth gap clearance, buried single-helix nick, matched/polymerizable seamed trunk, fully-seamless cycle trunk) but the **live 3D weave is NOT hand-validated across designs**: trace one continuous strand through all teeth, gaps visibly open, buried nick mid-bundle, seamed far ends puzzle-fit for polymerization, seamless teeth show NO trunk seams (HC dumbbell still falls back to a seamed trunk). ALSO re-run idempotency (ISSUE-9: running autoscaffold twice corrupts faces). | ISSUE-8, this session | `tests/fixtures/teeth.nadoc` + `10-6-10hb_seamed.nadoc`; pre-baked `workspace/teeth_{section,seamless}_routed.nadoc` + `dumbbell_*_routed.nadoc` | **"tests-pass-but-visually-wrong" area** — already burned multiple sessions on a corrupt fixture; gap/nick/seam math can all pass while the rendered route is wrong. Needs an eyeball across teeth + dumbbell + other multi-section designs, both modes, + a double-run idempotency check |
| ▶ HEAD | **MV-8** | Assembly **config animation**: assembly with a saved feature-log configuration → "animate to configuration" tweens instances | #68 | an assembly that has ≥1 saved configuration (may need to create one) | needs assembly WITH a saved configuration |
| | **MV-9** | **Assembly open from library**: open a `.nass` from a library row → enters assembly mode cleanly | #59 | any `workspace/*.nass` | part-open exercised live; assembly-open path verbatim-only |
| | **MV-10** | **Autosave write-back + server-restart recovery**: workspace-backed file + edit burst → debounced save; kill+restart backend → silent recovery badge | #53 #55 | any workspace-backed `.nadoc` | needs workspace file + edit burst + a real backend restart |
| | **MV-11** | **Two-real-tab cross-doc sync** + co-editing "saved" badge sibling indicator | fixes #2 #4 | same file opened in two browser tabs | BroadcastChannel can't cross Playwright contexts |
| | **MV-12** | **Overhang-binding context menu**: right-click an overhang-binding line → Bind/Unbind/Delete | fix #6 | a design with non-empty `overhang_bindings` (none known — may need to build) | no fixture has bindings; WebGL right-click |
| | **MV-13** | **FRET / fluorescence glow**: fluorophore-labeled design → View menu Fluorescence / FRET toggles → emitters glow, FRET quench scaling | #24 | a design with fluorophore-modified strands (none known — may need to build) | scaffold-only parts have no fluorophores; glow logic unit-tested only |
| | **MV-14** | **Representation option sliders** real mouse-drag (not JS-dispatch): expand the Representation sidebar section, drag each slider | #83 (partial) | any scaffolded part | panel section collapsed by default → `.fill()` needed visibility; drove via JS-dispatch instead |
| | **MV-15** | **Properties panel for an overhang-/assembly-anchored protein**: select a protein attached to an overhang (and one in an assembly) → panel shows the overhang id + attach-end / part-instance anchor, not just the free case | fix #18 (ISSUE-5) | needs a design with a protein attached to an overhang (none known — build via `/design/protein/attachments`) + an assembly with a protein | only the FREE-anchor branch was eyeballed live; overhang/assembly anchor branches are unit-tested only (no fixture) |
| | **MV-17** | **File-load progress overlay**: open this tab as a part editor (`?part-instance=<id>&assembly-doc=<docId>` — i.e. dive into a part from a live assembly) → the `#file-load-progress` overlay appears ("Opening Part"), the progress bar fills, the log lines append, "▸/▾ Details" toggles the log pane, and it auto-hides green on success (or turns red + shows the actions row + main-menu button on failure) | #87 | a live assembly with ≥1 part instance (e.g. `workspace/Belt_test1.nass`), then dive into a part | only fires on the `?part-instance=` part-editor boot path — needs a spawned part tab off a live assembly; boot console-error gate constructs the factory but never SHOWS the overlay |
| | **MV-18** | **Blunt-end (domain-end) menus**: load a design → left-click a rendered blunt/domain-end ring → the right-sidebar action panel appears ("helix N bp M") → Extrude opens the continuation slice plane (amber ghost), Bend/Twist start the deform tool at that end; ALSO right-click the ring → context menu at cursor → same Extrude/Bend/Twist; outside-click dismisses the ctx menu | #88 | a design with exposed blunt ends (e.g. `Examples/26hb_platform_v3.nadoc`) | panel/ctx appear only on a 3D domain-end ring pick (WebGL raycast at pixel precision); the action paths' store/slicePlane/deform effects are unit-pinned, the teardown `hidePanel` is smoke-covered, but the live click→panel→action gesture is human-eye only |
| | **MV-19** | **Force-Crossover tool (3D forced ligation) live gesture/visual**: load a design → click the `fxover` toolbar button (teal active state, End filter button lights, mode line "FORCE CROSSOVER…") → hover a 5′/3′ end (standard yellow snap glow) → click it (locks GREEN anchor) → only OPPOSITE-polarity ends on OTHER strands now hover-highlight, and hovering one shows the yellow crossover **arc preview** → click it → the two strands merge into one (arc renders, cadnano editor + sidebars update) → tool resets to step 1. Esc in step 2 drops the anchor; Esc in step 1 exits (restores prior selection level + mode line). Confirm lasso/Ctrl-multi-select are inert while active. | (new) | `Examples/26hb_platform_v3.nadoc` (52 staple ends) | topology (2 strands→1, ForcedLigation record, clean deactivate) verified end-to-end via the `__nadocForceXover` dev hook; the pixel-level raycast snap, glow COLORS, arc-preview appearance, and button/mode-line visuals are Tier-3 human-eye only |
| | **MV-16** | **Atomistic / surface representation VISUAL**: load a design → F6 VDW (space-fill atoms render, CG hidden) / F7 Ball & Stick (bonds render) / F5 Surface (molecular SES/VdW *mesh* appears, correct shape, opacity + probe-radius sliders + strand/uniform colour buttons affect it) / per-region overlay (pin a strand→VDW/surface while base stays full — overlay coexists with CG, no z-fight); F4 restores. Confirm the actual rendered geometry *looks right*, not just the panel toggles. | #86 | a representative `.nadoc` (e.g. `Examples/26hb_platform_v3.nadoc`); per-region needs a design with `representation_overrides` (mixed_representation work) | Tier-3 golden-image "does it look right" check (deliberately NOT automated — needs a pinned rasterizer); the F6/F5/F4 panel-toggle + zero-console path IS covered by the #86 exercise, but the mesh/atom *appearance* is human-eye only |

---

## GENERATED (manual ops ready — run these, then report pass/fail)

### MV-5 — Assembly right-click context menu (part / linker / belt)
*Discharges fix #69 — the assembly right-click router moved onto the shared
`createContextMenu` primitive. The router (`assembly_pointer.js`
`onAssemblyContextMenu`, line 575) and the part menu builder
(`ui/assembly_context_menu.js`) have unit coverage for the item set and gating, but
the **live WebGL right-click that decides part vs linker vs belt, the right-drag pan-
suppress, and the enabled/disabled linker-relax state** are the never-hand-driven
parts.*

**Why this needs a human.** The unit tests pin which items the part menu builds and
the multi-select/group gating, but they cannot touch: the **raycast priority chain**
that decides whether your right-click resolves to a *linker*, a *belt path*, or a
*part instance* (and routes to a different menu for each), the **5-pixel pan-suppress**
that must let a right-*drag* orbit/pan without ever popping a menu, and the
**linker-relax enabled-vs-disabled** state that depends on a backend availability
call. A break in any of those passes every automated gate.

**Routing facts (so you know where to click) — `assembly_pointer.js:575-620`:**
- Right-click fires `onAssemblyContextMenu`. It first reads the right-button-down
  position: if the pointer moved **> 5 px** (squared dist > 25) since right-button-
  down, it treats the gesture as a **right-drag pan** and **suppresses the menu
  entirely** (line 584-586). No browser menu appears either (`preventDefault`).
- The hit is resolved in a **priority chain**, first match wins:
  1. **Overhang arrow** (only if the overhang tool's locations are visible) → handled
     by `selection_manager`, the part menu is skipped (line 591-595).
  2. **Linker** (`pickLinker` — complement/bridge beads or the connector arc) →
     **Linker menu** (line 598-599).
  3. **Belt path** (`pickBeltAt`) → **Belt menu** (line 603-609).
  4. **Part instance** (`pickInstance`) → selects it (`activeInstanceId = inst.id`,
     line 618) **and** opens the **part context menu** (line 619).
- **Linker menu** (`showAssemblyLinkerMenu`, line 548): header `Linker · {name}`, one
  item **"Relax linker"**. It is **disabled** when the backend
  `getAssemblyOverhangConnectionRelaxStatus(connId)` returns `available === false`
  (ds-only; needs a movable free part); when disabled, a second header line shows the
  **reason** (line 570).
- **Belt menu** (line 605): header `Belt path`, one item **"Attach part to belt"**.
- **Part menu** (`ui/assembly_context_menu.js`): header = part name; a **Repr**
  dropdown (Full/Beads/Cylinders/Hull Prism/VDW/Ball+Stick); **Move / Rotate**;
  **Define Connector**; **Fixed (anchored)** toggle; **Allow Part Joints** toggle;
  conditional **Show/Hide**, **Edit Part…**, **Duplicate**, **Polymerize…**;
  **Group (N parts)** *only when a multi-select exists*; **Ungroup** *only when the
  part is in a group*; danger-styled **Delete**.
- **Dismiss:** outside `pointerdown` or **Escape** → `hide()`; the dismiss listeners
  are bound on a `setTimeout(…,0)` so the originating right-click doesn't instantly
  close the menu. Exiting the assembly calls `hide()`.

**SETUP**
1. Start both servers (`just dev` + `just frontend`), open `http://localhost:5173`,
   keep devtools console open. This is an **assembly-mode** block.
2. For the **linker-relax** cases: File → Open → **`workspace/Linker_Assem_test.nass`**
   (verified present — a cross-part linker assembly). For the **attach-to-belt** case:
   File → Open → **`workspace/Belt_test1.nass`** (verified — 62 instances + 2 groups +
   1 belt). You'll do the part-menu + pan-suppress cases on either.
3. Wait for parts to render; zoom/orbit so an individual part, the linker beads/arc,
   and (in Belt_test1) the belt tube are each comfortably clickable.

**MAIN CASES**
1. **Right-click a bare part → part menu + selects it.** Right-click a part instance
   that is *not* on a linker or belt. Expect: the part is **selected** (its white
   per-instance outline appears) AND a `.context-menu` opens at the cursor with the
   header = the part's name and the item set listed in routing facts (Repr dropdown,
   Move / Rotate, Define Connector, Fixed, Allow Part Joints, … Delete).
2. **Right-click a part in a group → Ungroup appears.** In Belt_test1, right-click a
   part that belongs to a group. Expect the menu to include **Ungroup** (it is omitted
   for an ungrouped part).
3. **Multi-select then right-click → Group (N parts).** Ctrl-lasso ≥2 instances (the
   MV-4 gesture), then right-click one of them. Expect the menu to include
   **Group (N parts)** with N = the multi-selected count.
4. **Right-click the linker → Relax menu (ENABLED).** In Linker_Assem_test, right-click
   directly on the linker (a complement/bridge bead or the connector arc between the two
   parts). Expect a small menu: header **`Linker · {name}`** + an **enabled**
   **"Relax linker"** item. Click it → a toast "Relaxed linker — free part moved into a
   coaxial native-length duplex." and the free part rigid-translates into a coaxial
   duplex.
5. **Right-click the belt → Attach menu.** In Belt_test1, right-click on the **belt
   tube**. Expect a menu: header **`Belt path`** + **"Attach part to belt"**. (You can
   stop at confirming the menu + that clicking it begins the attach flow; the full
   attach pick is a separate feature.)
6. **Pan-suppress: right-DRAG never opens a menu.** Press right mouse button on a part
   and **drag** (> a few px) to pan/orbit the camera, then release. Expect: the camera
   pans/orbits and **NO context menu appears** on release.

**EDGE CASES**
1. **Linker-relax DISABLED state.** If the linker in the fixture is **not** relax-
   eligible (not ds, or no movable free part), the **"Relax linker"** item must be
   **greyed/disabled** and a second header line shows the **reason** (e.g. "Relax
   unavailable"). Confirm a disabled item does nothing when clicked. *(If
   Linker_Assem_test's linker is eligible and always enabled, note that and flag that a
   disabled-case fixture is missing.)*
2. **Outside-click dismiss.** Open any of the three menus, then left-click elsewhere
   (empty space or another part). Expect: the menu **closes** cleanly (and an
   outside-click that lands on a part also performs that part's normal selection).
3. **Escape dismiss.** Open a menu, press **Escape**. Expect: the menu closes.
4. **Originating click doesn't self-dismiss.** Confirm the menu actually **stays open**
   after the right-click that spawned it (the deferred-listener fix) — it must not flash
   open-and-immediately-closed.
5. **Right-click empty space → nothing.** Right-click on empty background (no part,
   linker, or belt under the cursor). Expect: **no menu**, no error (`pickInstance`
   returns null → early return).
6. **Pending-edit commit on re-target.** With a Move/Rotate (or other) edit pending on
   part A, right-click part **B**. Expect: the pending edit on A **commits** first
   (`commitAssemblyPending`), B becomes active, B's menu opens — no lost edit, no error.
7. **Assembly-exit teardown.** Open a menu, then exit the assembly (close doc / main
   menu / open a design). Expect: the menu is hidden, **no console error**, no orphaned
   `.context-menu` node left in the DOM.

**PASS CRITERIA**
- A right-click resolves to the **correct** target under the cursor: linker → Linker
  menu, belt → Belt menu, bare part → part menu (and selects the part). The priority
  chain never shows the wrong menu (e.g. a part menu on top of a linker).
- "Relax linker" is **enabled** when relax-eligible and **disabled with a reason** when
  not; clicking the enabled item relaxes (toast + free part moves).
- "Attach part to belt" appears on a belt right-click.
- The part menu's **Group / Ungroup** items obey the multi-select / in-a-group gating.
- A right-**drag** pans/orbits and **never** opens a menu (5 px threshold).
- Outside-click and Escape both dismiss; the spawning click does not self-dismiss;
  exiting the assembly leaves no orphan node and throws no error.
- No console errors at any step.

**WATCH FOR (suspect behaviors — confirm or deny)**
- **Pan-suppress threshold feel.** The cutoff is a fixed **5 px**. A *deliberate*
  micro-nudge right-click (< 5 px jitter) should still open the menu; a real pan should
  not. Confirm a normal "I didn't mean to drag" hand-tremor right-click still pops the
  menu (i.e. the threshold isn't so tight that ordinary clicks get eaten).
- **Linker vs part priority on overlap.** Where a linker bead sits directly in front of
  a part, the linker wins the chain (it's checked first). Confirm right-clicking the
  *part body* (away from the linker beads/arc) still gives the **part** menu, not the
  linker menu — i.e. the linker pick isn't grabbing too wide a screen radius.
- **Belt pick precision.** `pickBeltAt` uses the event directly (screen-proximity to the
  belt tube). On a foreshortened belt or where it overlaps a part, confirm the intended
  target wins and you can still reach the part underneath.
- **Relax-status call failure.** The relax-status fetch is wrapped in try/catch and
  *treats a failure as available* (line 552). If the backend is slow/erroring, the
  "Relax linker" item may show **enabled** but then fail on click with an error toast.
  If you see that, note it — it's a known soft-fail, not a crash.
- **Active-instance side effect.** A right-click on a part sets `activeInstanceId`
  *before* the menu opens (line 618), so right-clicking a part **changes the selection**
  even if you dismiss the menu without choosing anything. Confirm that's acceptable (it
  mirrors most apps) and that dismissing doesn't leave a half-state.

---

## VALIDATED (user-confirmed pass)

### MV-6 — Belt polymerize ✅ VALIDATED 2026-06-07
Discharges #32. User manually validated the belt-polymerize gesture: a built belt
assembly → Polymerize along the belt path → evenly-spaced copies render along the tube.
(Marked complete directly by the user; no GENERATED block was required.)

### MV-7 — Coalesced assembly part-refresh ✅ VALIDATED 2026-06-07
Discharges #38. User manually validated that editing a part in part-context with a
save burst refreshes the shared instances **once** (coalesced), not per-instance.
(Marked complete directly by the user; no GENERATED block was required.)

### MV-4 — Assembly multi-select union box (parts + groups) ✅ VALIDATED 2026-06-07
Discharges extraction #34 (`scene/assembly_multi_box.js`, factory `initAssemblyMultiBox`;
pure union math `selection_bbox.js instanceUnionBox`). Confirmed live by the user during
assembly testing: Ctrl-lasso ≥2 instances → one **purple** union box around the union;
exactly 1 → **white**; group select → purple box around all members; plain click clears;
the box re-fits during a group-gizmo drag and survives the commit; assembly-exit teardown
throws no console error (the original #34 `const`-reassignment TypeError is gone). **The
live Ctrl-lasso / group multi-select gesture for parts + groups is now hand-driven.**

### MV-LNK — Assembly cross-part linker completion ✅ VALIDATED 2026-06-07
Pushed + validated same session (was never a mined PENDING row — it's this session's
assembly-linker feature work, shipped with "NOT hand-driven" caveats, then hand-checked
live by the user: "everything appears to work as desired"). Covers, in the **shared
assembly renderer** (default):

- **Indirect (zero-length ss) linkers render** — previously a `length_value==0` linker
  produced NO topology; now a single ss strand `[comp_a, comp_b]` (each overhang's
  binding-domain complement, no bridge) with the `comp_a→comp_b` backbone jump drawn as
  the connector **arc**. ss linker arcs now render in assemblies generally (was ds-only).
  ([[assembly-overhang-bindings]] "Indirect (zero-length) linkers"; pure arc module
  `scene/assembly_connector_arcs.js`.)
- **ss linker relaxation for 0-length (indirect) linkers** — single-translation rigid
  placement that collapses the lone complement↔complement arc (analog of the ds
  two-translation relax). Right-click "Relax linker" + popup Relax button both enabled
  for indirect via relax-status. ([[assembly-linker-relax]] "Indirect (zero-length ss)
  relax".)
- **Linkers follow part moves** — overhang labels follow a moved part (last turn's
  world-space-sprite fix), and after a relax the binding domains + arcs + any OTHER
  linker sharing the moved parts now refresh immediately (no rep-toggle needed): the
  transform-only fast path in `main.js` now calls `rebuildLinkers` when a linker-bearing
  part moved.
- **Delete linker** — right-click a linker → "Delete linker" (red); cascades to the 3D
  view, the strand spreadsheet, and the Overhangs Manager listing.

Backend pins: `test_assembly_overhang_bindings.py` (indirect topology + geometry endpoint),
`test_assembly_linker_relax.py` (3 new indirect-relax tests). Frontend: `assembly_connector_arcs.test.js`.

### MV-1 — Design-mode cluster Move / Rotate tool ✅ VALIDATED 2026-06-07
Discharges extractions #71 #78 #79 #80 #81 (the LESSONS H7 "cluster-gizmo 3D-drag
commit not hand-driven" caveat for the whole design-mode Translate/Rotate band).
Confirmed live by the user across all MAIN + EDGE cases: activate via right-click,
gizmo translate/rotate, ✓ commit (drag and panel-input), Escape-reverts, pivot
selection, re-edit-in-place, stale-op guard, and the Three-Layer spot-check.

Two UX gaps were found *during* validation and shipped the same session:

1. **Unified cluster selection** — clicking a cluster with the cluster selection
   filter active and clicking its row in the **Dynamics → Movable clusters** list now
   drive ONE selected-cluster state: same green glow (`0x3fb950`) + 1.3× bead scale +
   cluster `selectedObject` + sidebar row highlight. selection_manager owns the commit
   (`_applyClusterSelection` + exported `selectCluster`); a thin main.js subscriber
   mirrors the cluster `selectedObject` onto `activeClusterId`. The blue
   `clusterGlowLayer` is now reserved for the Move/Rotate tool's active cluster.
2. **Earlier Move/Rotate ops are independently editable** — the old "Edit blocked: a
   later move/rotate exists" guard (frontend toast + backend 409) was removed. Each
   `cluster_op` stores the cluster's ABSOLUTE pose after that step and the live pose is
   the LAST op for that cluster, so editing an earlier op (A1→A2) rewrites only that
   step's seek/scrub frame while the latest op keeps defining the final pose (B1).
   Backend: `_edit_cluster_op_feature` recomputes the live transform from the last op.

Backend `just test` 1747 passed (2 new cluster_op-edit pins); frontend
`just test-frontend` 1090 passed (2 new tool pins + the selection-unify wiring);
`just smoke` 23/23. Live-exercised: sidebar↔3D selection parity, and edit-earlier-op
→ seek-to-step → cancel → seek-back-to-latest, all zero console errors.

### MV-2 — Overhang Orientation panel + migrated context menu ✅ VALIDATED 2026-06-07
Discharges extraction #64 (`ui/overhang_orientation_panel.js`) and fix #7 (the
right-click menu on the shared `createContextMenu` primitive). Confirmed live by the
user across the GENERATED block: Edit Orientation opens the panel + rotate-only gizmo,
step/drag/typed previews are instant and client-side, Apply commits one
`overhang_rotation` Feature Log entry, single-vs-multi menu gating, and auto-close on
structural change. **The live WebGL raycast → gizmo → preview gesture is now
hand-driven and validated.**

Five bugs were found *during* validation and fixed the same session:

1. **Dual context menu on an overhang bead.** An overhang's free tip is "unpaired", so
   a right-click on its bead opened the short *flexible-segment* menu instead of the
   overhang menu — the unpaired-bead check ran first. Fixed in `selection_manager.js`:
   an overhang-bead right-click (`hitBead.nuc.overhang_id != null`) routes to
   `onOverhangRightClick`, matching the cone-on-overhang dispatch.
2. **Reset jumped the gizmo to the wrong location.** The in-panel **Reset** re-attached
   the gizmo without the cached pivot, falling back to `anchor.pivot` (`[0,0,0]` for
   inline overhangs). Fixed: Reset (and Apply) re-attach with
   `_ooPivotPositions[_ooRightClickedId]`.
3. **Reset → Cancel still left a Feature Log entry.** Reset committed to the server
   immediately. Reworked to a **client-side preview** (per-overhang baseline → identity,
   tracked via `_ooBaseRotations`): Reset→Apply commits identity; Reset→Cancel reverts
   with no entry.
4. **Multi-overhang menu pixel-dependence.** The multi-overhang divert was gated
   `!hitCone`, so a right-click on an overhang's terminal cone fell through to a
   single-id dispatch. Fixed: the divert fires for any overhang hit (cone OR frontmost
   bead) and dispatches the full `_multiOverhangIds` set.
5. **Flexible scaffold run rendered rigid after Generate OH binder → undo.** The binder
   add/remove undo routed `_design_replace_response` through the compact geometry form,
   omitting the per-bead `is_flexible_segment` flag. Fixed in `crud.py`: ship per-nuc
   geometry whenever the diff changed the marks OR the target design has flexible
   connections.

Backend `just test` 1747 passed (+1 new pin `test_topology_change_replace_keeps_flexible_flag`).
Frontend `just test-frontend` 1101 passed (+4 new overhang-panel pins). All five fixes
confirmed live by the user.

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
  selection.
- **Ctrl+click** toggles a crossover in/out of the multi-set; **plain click** single-
  selects; lasso respects the engaged level.
- **Generic yellow hover preview** at every filter level: hovering shows — in yellow —
  exactly what a click will select (same FORM as the green selection), with snap-to-
  nearest within 80 px. The already-selected element stays green.
- **Cluster** removed from the Tab cycle (button-only) and its button moved to the gate
  group — a late-stage, occasional tool.
- No legacy red sf-pinned BoxHelper anywhere.

1087 frontend tests green; served `dist/` rebuilt. Tube geometry pinned by
`frontend/src/scene/arc_tube_geometry.test.js` (never NaNs). The earlier MV-3
REGRESSION-FOUND items (below) are resolved by the above.

---

## REGRESSION FOUND (user-confirmed fail → fix opened)

### MV-3 (2026-06-07) — two issues found running the block → **FIXED + re-validated same session** (see VALIDATED)
1. **Fixed levels still let a single click select a strand.** In domain / end / xover
   (and cluster) level, a click on an element that wasn't that type "soft-fell" to
   selecting the whole strand. Fixed: each fixed level now selects ONLY its own type;
   a mismatched click is a **no-op** (current selection kept). `selection_manager.js`
   `_v2HandleBead` / `_v2HandleCone` / `_v2HandleArc` — removed every `_selectStrandV2`
   fallback (cluster/domain/end/xover). `strand` level still selects the strand.
2. **Lasso crossover highlight ≠ single-click highlight.** Lasso/additive multi-select
   drew a cyan arc-line recolor + green glow spheres; single-click draws a green glow
   tube. Fixed: multi-select now renders the **same green glow tubes**
   (`design_renderer.setSelectionArcs` / `clearSelectionArcs`, a pooled mirror of
   `setSelectionArc`); `_applyMultiCrossoverHighlight` + the shift-click arc toggle both
   route through it.

## RE-TEST NEEDED (fix shipped, user not yet re-confirmed)

_(none — MV-3 re-validated 2026-06-07; see VALIDATED)_

---

## Next loop

**▶ Process MV-8 — Assembly config animation** (discharges #68).
Dig: the "animate to configuration" entry point (feature-log configuration → tween),
the saved-configuration data model, and how the instance tween is driven. **Fixture:**
an assembly that has ≥1 saved configuration — none is known offhand, so the SETUP may
need to *create* a configuration first (save a pose as a config) before animating to it.
This is an **assembly-mode** block. The live "tween instances between configurations"
gesture + the visual smoothness of the interpolation is the never-driven part.

(MV-6 + MV-7 were validated directly by the user 2026-06-07 without generated blocks;
MV-RSZ, the 3D overhang-resize-through-boundary fix, was pushed PENDING this session.)
