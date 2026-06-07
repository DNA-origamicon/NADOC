# Manual Validation Debt — shift register

**What this is.** A queue of features that were shipped with the *accepted caveat*
that their **live gesture / visual appearance was never hand-checked in the running
app** — only verbatim-moved + unit-tested + smoke-gated. Sources: the "regression
caught by" / final caveat column of `main_js_extraction_log.md` (the `NOT
hand-exercised` / `NOT hand-driven` / `not visually confirmed` rows) and the USER
TODO column of `issues_fix_log.md`. These are real validation debt: a silent
behavior break would pass every automated gate we have.

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

- Total items: **14**
- PENDING (no manual ops yet): **13**
- GENERATED (ready to run): **1** — MV-1
- VALIDATED: **0**
- REGRESSION FOUND: **0**

---

## PENDING queue (ordered; `▶ HEAD` = next loop processes this)

Priority = (user-facing value) × (risk a silent break slips every automated gate).
Core editing + default-selection UX first; niche/visual last.

| # | id | feature / manual operation | discharges | fixture hint | why deferred |
|---|----|----------------------------|-----------|--------------|--------------|
| — | **MV-1** | *(processing — see GENERATED)* design-mode cluster **Move / Rotate** tool: right-click cluster → gizmo/panel → ✓ commit | #71 #78 #79 #80 #81 | a cluster-bearing design (e.g. `Examples/26hb_platform_v3.nadoc`) | 3D pointer-pick on a cluster + gizmo-handle drag not drivable at pixel precision (LESSONS H7) |
| ▶ HEAD | **MV-2** | **Overhang Orientation** panel: right-click a rendered overhang → Edit Orientation → step/apply/reset/auto-close; also the migrated context menu | #64, fix #7 | a design with overhangs (mem: `NS_trans_fix` ≈ 50 overhangs — verify it exists) | WebGL raycast on 1 of N overhang beads not drivable |
| | **MV-3** | **Drill-v2 selection** on a multi-helix design: strand level, Tab cycle, crossover-arc hover(red)/click(green) tube, no red sf-pinned box, multi-element lasso respects engaged level | fixes #10 #11 #12 #14 #15 | a multi-helix design WITH crossovers (harness fixture is single-helix → no xovers) | thin-arc gesture + Tier-3 colour + multi-element lasso need a real multi-helix design |
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

## VALIDATED (user-confirmed pass)

_(none yet)_

## REGRESSION FOUND (user-confirmed fail → fix opened)

_(none yet)_

---

## Next loop

**▶ Process MV-2 — Overhang Orientation panel.** Dig: exact right-click→"Edit
Orientation" entry, the `#overhang-orient-panel` field ids + step/apply/reset
buttons, the rotate-only TransformControls gizmo, and the structural-change
auto-close subscriber (extraction #64) + the migrated context menu (fix #7). Verify
the overhang fixture exists (`NS_trans_fix` ≈ 50 overhangs per memory — `ls
workspace/`); if absent, name the closest design with runtime overhangs or flag that
one must be built. Edge cases to cover: single vs multi-overhang selection (Set
Label / Generate gating), Apply composing delta ops, Reset zeroing, step-button
accumulation, Delete/Escape, and auto-close when the structure changes underneath.
