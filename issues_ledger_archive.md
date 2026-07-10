# Issues & bugs ledger — archive (closed issues)

Split out of `issues_ledger.md` on 2026-07-09 for context economy — closed/shipped issue entries and their historical narrative live here. Read on demand only.

## ISSUE-2 — Cross-tab sync claims saved but doesn't sync (functional, data-integrity)

- **Status:** ✅ FULLY CLOSED 2026-06-05. Propagation fix `[x]`; silent-by-default sync logging `[x]`
  (console mirror in `ui/sync_badge.js` `syncLog` gated on the debug panel being open — Ctrl+Shift+D /
  `__nadocSyncDebug.show()` enables it, close/hide silences; rolling in-panel log still records every
  event); badge co-editing (stale-sibling) indicator `[x]` DONE 2026-06-05.
- **Sub-phase B (badge co-editing indicator) — SHIPPED 2026-06-05.** User-chosen scope (AskUserQuestion):
  trigger = **co-editing PRESENCE** (no content-version counter exists, so flag whenever another tab holds
  the SAME workspace file in a DIFFERENT backend doc — the real save-clobber risk); visual = **distinct
  dot + label** (a blue `coedit` dot + `saved · N tab(s) editing this file`, only at the resting green
  "saved" state — an active save/error keeps its own colour). Implementation: `ui/sync_badge.js` composes
  base status + a sibling count via a new `setSiblingCoediting(count)` + `_render()`, plus a pure exported
  `countCoeditingSiblings(myPath, myDocId, others)` (excludes same-docId child windows = genuinely in-sync).
  main.js wiring: `doc-presence` broadcast now carries `workspacePath` (+ stores sibling `docId`);
  `_refreshCoediting()` recomputes the count on presence/goodbye/own-path-change; new `doc-goodbye` emit on
  `beforeunload` keeps the count honest when a sibling closes; `_setWorkspacePath` re-announces + refreshes.
  Pinned by 13 vitest tests (`ui/sync_badge.test.js`: 7 badge-render + 6 detector). App-validation =
  two-real-tab USER TODO (BroadcastChannel can't cross Playwright contexts — same constraint as the
  propagation fix). main.js LOC Δ +~22 (thin wiring across existing blocks, not a new cohesive subsystem).
- **ROOT CAUSE (confirmed by code trace, 2026-06-05):** two independently-opened tabs get
  *different* sticky doc ids (`doc_id.js` mints one per tab in `sessionStorage`). So the fast path
  (`design-changed` BroadcastChannel) is doc-scoped out (`isSameDoc` false → `main.js` ignores it),
  AND the fallback (SSE `file-changed` → reload) was suppressed because `main.js`'s `file-saved`
  broadcast handler added the path to `selfSavedPaths` **regardless of doc**. Each save re-armed the
  5 s self-echo window just before its own SSE, so a sibling's genuine edit was swallowed for minutes.
  The `markSameDocActivity` 10 s window is NOT the culprit (only set on a same-doc `design-changed`).
- **FIX (decision: auto-sync B→A ~1s):** doc-scoped the echo guard. New
  `initAutosaveSync.registerSiblingSave(path, sameDoc)` in `app/lifecycle.js` suppresses ONLY a
  same-doc sibling's save (stale echo we already sync via design-changed); a different-doc sibling's
  `file-saved` is left un-suppressed so the SSE `file-changed` reloads it. `main.js` `file-saved`
  handler now calls it with `nadocBroadcast.isSameDoc(data)` (−4 main.js LOC). Pinned by 3 vitest
  tests in `app/lifecycle.test.js` (same-doc suppresses; different-doc reloads = the repro; 5 s clear).
- **User decisions banked (2026-06-05 AskUserQuestion):** (1) same-file tabs auto-sync ~1s [DONE];
  (2) the "saved" badge SHOULD distinguish disk-saved from siblings-in-sync (flag stale siblings)
  [sub-phase, not built]; (3) sync console logging silent by default, verbose only behind
  Ctrl+Shift+D / `__nadocSyncDebug` [sub-phase, not built].
- **Symptom (user):** multiple tabs with the same part open both show "saved" but don't actually sync to
  each other for several minutes. Console debug clutter makes it hard to diagnose.
- **Repro (to pin):** open the same workspace-backed part in two tabs (the app spawns a new tab per
  doc — see `shared/doc_id.js`). Edit in tab A; time how long until tab B reflects it. Expected: ~1 s;
  observed: minutes. Capture the console noise. A Playwright two-context spec can drive this
  deterministically (two `browser.newContext()` on the same `?doc`), asserting tab B's design version
  updates within N seconds — that spec is the acceptance test.
- **Suspected locations (verify):** `app/lifecycle.js` `initAutosaveSync` owns the autosave debounce +
  the Library-SSE handler + the cross-tab suppression. Note `_RELOAD_SUPPRESS_MS = 10000` (a 10 s
  same-doc activity window that suppresses reloads) and the design-save debounce (`setTimeout … 900ms`)
  + the `_selfSavedPaths` 5 s self-echo clear. The SSE handler refreshes the **library file list**
  (`libraryPanel.refresh()`), not necessarily the **open design** — cross-tab *design* propagation rides
  the `BroadcastChannel('nadoc-design')` path (`shared/broadcast.js`). **Hypothesis (unproven):** the
  10 s suppression window + the broadcast/SSE split means a sibling tab's edit is suppressed-then-not-
  re-fetched until some later unrelated event. Verify before believing.
- **Console clutter:** there's a `__nadocSyncDebug` helper + a Ctrl+Shift+D debug panel (`ui/sync_badge.js`).
  Part of this issue is gating/quieting the default-on sync logging so the real signal is visible — likely
  a sub-phase.
- **Decomposition into phases (proposal):**
  - **Phase 1 — instrument + repro.** Two-context Playwright repro that measures sync latency; quiet the
    console noise behind the existing debug flag so the trace is readable. ASK the user what the target
    sync latency + console verbosity should be.
  - **Phase 2 — fix propagation.** Based on the confirmed root cause (suppression window? missing design
    re-fetch on broadcast? badge lies about "saved"?), fix in `app/lifecycle.js` + a passing two-context
    spec.
- **UX research:** none needed (functional). The only UX call is "saved" badge honesty — the badge should
  not claim saved+synced if siblings are stale.
- **Open questions (ask in Phase 1):** acceptable sync latency? Should the "saved" badge distinguish
  "saved to disk" from "siblings in sync"? Default console verbosity (silent unless Ctrl+Shift+D)?

## ISSUE-3 — Assembly Ctrl-click multi-select feedback (functional bug)

- **Status:** `[x]` DONE 2026-06-05 (single phase). Fix in `scene/assembly_lasso.js`
  (`toggleInstanceSelection`) + `scene/assembly_multi_box.js` (white-for-1 / purple-for-2+);
  main.js `onClick` re-wired to the pure helper (+1 LOC: a dev-only test oracle). See the fix-log
  row. **User-chosen semantics:** (1) Ctrl+click a 2nd part while one is plain-selected → ADD both
  (the active pick folds into the set); (2) Ctrl+click an already-selected part → deselect just it;
  (3) a single Ctrl-selection draws a WHITE box, purple only at 2+.
- **Symptom (user):** in assembly mode, Ctrl+click on a part shows **no visual change** until a *second*
  part is also selected. And the sequence "click part A, then Ctrl+click part A again" *clears* the first
  selection instead of toggling/keeping it.
- **Repro (to pin):** load a ≥2-part assembly (`workspace/Belt_test1.nass`). (a) Ctrl+click one part →
  assert a selection box/highlight appears immediately (currently does not until #2). (b) Click A, then
  Ctrl+click A → assert A stays selected or toggles predictably (currently clears). Drive via
  `e2e/helpers/scene_harness.js` (`selectAssemblyInstance` / assembly select helpers already exist) +
  `getSelectedObject`-style state assertions — extend `e2e/assembly_select.spec.js`.
- **Suspected locations (verify):** `scene/assembly_pointer.js` (`initAssemblyPointer` → `onAssemblyClick`,
  carve-up #29) handles the click/select; `scene/assembly_multi_box.js` (#34) draws the purple union box
  only at **≥2** selections (that's the "no change until a second part" symptom — single-select feedback is
  suppressed by design there). `scene/assembly_lasso.js` handles Ctrl-modified selection. The
  single-select-no-feedback and the re-click-clears behaviors are likely two distinct bugs in the
  click-handler's selection state machine.
- **Decomposition:** likely a **single phase** (bounded). If the two symptoms have separate causes, split
  into 1a (immediate single-select feedback) + 1b (re-click toggle semantics).
- **UX research:** none — this is standard multi-select semantics (Ctrl/Cmd toggles membership; single
  selection shows feedback immediately). The "ask" is just confirming the desired toggle rule (Ctrl+click
  an already-selected part → deselect just it? no-op? ).
- **Open questions (ask after repro):** should single-part selection show the same purple box as multi, or
  a distinct single-select highlight? Ctrl+click on an already-selected part — deselect it, or keep it?

## ISSUE-4 — Drill selection UX overhaul (UX redesign)

- **Status:** Phase 1 `[x]` DONE 2026-06-05 (current-state map + friction catalogue + target interaction
  spec; NO code — survey + AskUserQuestion). Phase 2 `[x]` DONE 2026-06-05 (state-machine rebuild, behind the
  `NADOC_DRILL_V2` flag). Phase 3 `[~]` polish — **3-preview `[x]`** (red hover-preview glow) + **3-xover `[x]`
  DONE 2026-06-05** (crossover ARCS now hoverable=red / clickable=green crossover in drill-v2 — the thin
  inter-helix arc was never in the bead/cone pick set; `_arcHitPx` 12→18; `_v2HandleArc`/`_selectCrossoverV2`
  in `selection_manager.js` + `hoverPreviewTarget` 'arc' kind); **3-filter-audit-lasso `[x]` DONE 2026-06-06**
  (lasso v2-aware). **v2-eyeball feedback batch `[x]` DONE 2026-06-06** — user verified v2 then directed:
  (A) default 2nd-click KEEPS the leaf (no toggle-clear); (B) crossover selection highlight unified to a green
  glow TUBE; (C) **drill-v2 flipped to DEFAULT** + filter-row gutted (no button = drill ladder, button = fixed
  level, `strand` a distinct level, Tab cycle cluster→strand→domain→end→xover→none, red `sf-pinned` removed).
  **+ level-persistence `[x]` DONE 2026-06-06** — an engaged level now survives an empty-space/toggle-off click
  (lit filter button stays lit until Tab/re-click; `_clearAll` emits the persisted `_selLevel`).
  **+ legacy-deletion `[x]` DONE 2026-06-06** — the 87 dead legacy sites (auto-drill ladder / manual pins / Tab
  drill-lock) + the `NADOC_DRILL_V2` flag plumbing PHYSICALLY DELETED across `selection_level.js` /
  `selection_manager.js` (3853→3477 LOC) / `selection_filter.js` / `keyboard_shortcuts.js` + main.js wiring (−5)
  + the dead `.sf-pinned` CSS. selection-level is now the ONLY model, no opt-out. User chose "drop the opt-out
  entirely" (gated on a confirmed multi-helix v2 eyeball — both AskUserQuestion'd this session). ~715 net lines
  removed; vitest 984 (legacy-path tests deleted with the code), smoke 23/23, drill-v2 + bead_select e2e green.
  **STILL OPEN (optional, low-priority):** assembly-unification `[ ]` (decision G), text level-breadcrumb (decision E).

### Phase 3-filter-audit — lasso `[x]` DONE 2026-06-06; per-mechanism decisions banked (flip+delete pending v2 eyeball)

**RESOLVED 2026-06-06 (AskUserQuestion, per-mechanism keep/clean/delete):**
- **#8 lasso — KEEP-but-FIXED `[x]`.** `_finalizeLasso` now derives capture from pure
  `lassoCaptureType({drillV2, selLevel, drillType, selectableTypes})` in `scene/selection_level.js`. In
  drill-v2 the engaged `_selLevel` is the single truth (default→strand, cluster→cluster, domain→domain,
  end→**5′/3′ termini only** — user decision, NOT every nucleotide — xover→crossover). Legacy branch
  byte-for-byte unchanged. 11 vitest (the 5 v2 cases were the failing repro). Commit `28cfacd`.
- **#7 visibility gates — KEEP** as a separate "what's pickable" concern (decision F confirmed); they do
  NOT drive lasso capture in v2.
- **#9 other multi-selects (overhang/loop/skip/multi-arc lasso) — DEFER.** In v2 the lasso captures ONLY
  the engaged level; overhang/loop/skip are not lasso-capturable in v2 — revisit as a separate phase.
- **#4/#5/#6 legacy pins + drill-lock + auto-drill — DELETE, but DEFERRED.** User first chose "flip ON +
  delete legacy"; then, given new info (87 entangled reference sites across the 3 selection modules +
  drill-v2 NEVER human-eyeballed + Tier-3 WebGL visual check not automatable here), chose **"eyeball v2
  first, then flip+delete."** So the flip-default + 87-site deletion is the NEXT phase, gated on the v2
  eyeball USER TODO in the handoff below. Flip + deletion as SEPARATE commits.

**Original directive (2026-06-05):** "Get rid of the selection-filter PINNING system — it interferes with
UX. If the user Tabs to `ends` then lassos, the lasso selects a CLUSTER (wrong). Set the next loop to ask about
EACH selection-filter changing process and clarify if it should be KEPT, CLEANED UP, or DELETED." So the next
session's protocol is: present the inventory below, AskUserQuestion **keep / clean-up / delete for each
mechanism**, THEN implement one phase. Do NOT bulk-delete without the per-mechanism ask.

**ROOT CAUSE (verified by code read 2026-06-05) — two parallel "what am I selecting" truths:** drill-v2 unified
the **click** paths under `_selLevel` (`setSelectionLevel`), but **lasso + the other multi-selects never learned
about it.** `_finalizeLasso` (selection_manager.js ~2740) decides what to capture from `_currentDrillType()`
(which returns `_drillSeq[_drillLevel]` from the LEGACY auto-drill state, and is `null` unless `_autoDrill()`)
falling back to `selectableTypes`. Neither consults `_selLevel`. So in v2, Tab→`end` sets `_selLevel='end'` but
the lasso reads the stale `selectableTypes`/legacy-drillType → captures strands/clusters. **The lasso is not
v2-aware** — that IS the bug.

**INVENTORY — every selection-filter / selection-level changing mechanism (verified, ask keep/clean/delete each):**
| # | Mechanism | Where | Drives | v2-aware? |
|---|-----------|-------|--------|-----------|
| 1 | v2 level buttons (clust/strand/line/ends/xover) | `selection_filter.js` attachFilterButtons | `setSelectionLevel` (`_selLevel`) | yes |
| 2 | v2 Tab cycle (cluster→domain→end→xover) | `keyboard_shortcuts.js` | `setSelectionLevel` | yes |
| 3 | v2 Esc → default | `keyboard_shortcuts.js` | `setSelectionLevel('default')` | yes |
| 4 | ~~Legacy manual filter PINS (`_manualFilters` Set + red `sf-pinned`)~~ DELETED 2026-06-06 | `selection_filter.js` | — | gone |
| 5 | ~~Legacy Tab DRILL-LOCK (`_drillLock`/`_TAB_LOCKS`)~~ DELETED 2026-06-06 | `selection_manager.js`+`keyboard_shortcuts.js` | — | gone |
| 6 | ~~Legacy AUTO-DRILL ladder (`_drillSeq`/`_drillLevel`/`_autoDrill`)~~ DELETED 2026-06-06 | `selection_manager.js` | — | gone |
| 7 | Visibility gates (scaf/stap/loop/skip/ovhangs) | `selection_filter.js` | plain-toggle `selectableTypes` ("what's pickable/visible") | shared |
| 8 | The LASSO (`_finalizeLasso`) | `selection_manager.js` | `lassoCaptureType({selLevel})` — engaged level is the single truth (legacy `drillType` branch DELETED 2026-06-06) | yes (fixed) |
| 9 | Multi-crossover-arc / multi-domain / multi-overhang selects | `selection_manager.js` | engaged level (Shift/Ctrl additive paths) | yes |

**Decisions the next-session ask must resolve (per the user's keep/clean/delete framing):**
- **#8 lasso (the motivating bug):** should multi-select respect `_selLevel` in v2 (Tab→ends → lasso captures
  ENDS)? Almost certainly KEEP-but-FIX: teach the lasso (`_currentDrillType`/the `useStrands/useEnds/...` block)
  to read `_selLevel` when `_drillV2`. Testable kernel: extract a pure `lassoCaptureType({drillV2, selLevel,
  drillType, selectableTypes})`.
- **#4/#5/#6 legacy pinning + drill-lock + auto-drill:** DELETE (this also discharges the planned "flip flag
  default ON → delete legacy" Phase-3 step). Confirm the flag flip happens first / together.
- **#7 visibility gates:** KEEP as a separate "what's pickable" concern (decision F) — confirm.
- **#9 other multi-selects:** keep/clean — make them v2-aware alongside the lasso, or defer.

**Repro to pin next session:** drillv2 on, load a multi-helix design, Tab to `end` (or `cluster`), Ctrl-drag a
lasso → assert it captures the engaged level's element type (today: captures the legacy `selectableTypes` type).
Gesture e2e OR unit-test the extracted `lassoCaptureType`. (BANKED gotcha: the single-helix `loadScaffoldedPart`
fixture has no crossovers and limited clusters — may need a richer fixture or the unit-kernel route.)

### Phase 3-preview OUTPUT — red hover-preview glow (shipped 2026-06-05, flag-gated)

**⚠ "Breadcrumb" was a naming mismatch.** The handoff's decision-E "breadcrumb" meant a TEXT level-trail
(`Strand ▸ End`). When asked the form, the user clarified they did NOT want a text widget — they meant the
**hover-preview affordance**: with a strand selected (default level), the leaf a further click WOULD select
(bead → end/nucleotide | cone → crossover) gets a **RED glow**, distinct from the GREEN selection glow;
clicking it selects it (green). Phase 2 had shipped this as an un-eyeballed *scale-pop*; this sub-phase
replaces the scale-pop with the red glow the user actually wanted.

**What shipped (route: 3 modules, main.js LOC Δ = 0):**
- **`scene/selection_level.js`:** new pure `hoverPreviewTarget({drillV2,selLevel,mode,strandId,hit})` — the
  gate: preview ONLY in default level + mode 'strand' + hit on the selected strand; returns `{kind,entry|cone}`
  or null. 7 vitest.
- **`scene/glow_layer.js`:** `createGlowLayer` gained an optional `name` (tags the InstancedMesh) + a
  `count()` accessor — so the gesture e2e can find/measure a specific glow layer.
- **`scene/design_renderer.js`:** new red `_previewGlowLayer = createGlowLayer(scene, 0xff2a2a, 4.2,
  'previewGlow')` (larger than the green 2.8 so its halo reads red over a green-glowing strand) +
  `setPreviewGlow`/`clearPreviewGlow`; cleared on rebuild + refreshed in `refreshAllGlow`.
- **`scene/selection_manager.js`:** `_updateHoverPreview`/`_clearHoverPreview` rewritten — scale-pop →
  `setPreviewGlow([{pos}])` (bead `entry.pos` / cone `midPos`) via the pure gate; `_restoreStrand` now also
  `clearPreviewGlow()` (separate layer the scale-reset missed).

**Pinned by:** 7 vitest (`selection_level.test.js` hoverPreviewTarget) + e2e `drill_v2_select.spec.js` new
test (real raycast: select strand → hover → named `previewGlow` layer count goes 0 → >0; discriminates the
glow from the old scale-pop). vitest 987 green, smoke 23/23, both drill e2e green.

**NOT eyeballed (carry):** the RED-over-GREEN *colour* is a Tier-3 aesthetic check (golden-image, not
automated). Additive blend means the hovered bead's centre composites green+red → yellowish; the larger red
halo is meant to read red. If it looks muddy, tune `_previewGlowLayer` scale/opacity, or exclude the hovered
bead from the green selection glow for a pure red. USER TODO below. Crossover *arc* preview not added — the
click path reaches beads + cones only; arc-raycast is a possible follow-up.

### Phase 2 OUTPUT — unified selectionLevel state machine (shipped 2026-06-05, flag-gated)

**User scope decision (AskUserQuestion 2026-06-05):** "Full Phase 2 now" — the entire banked spec
(default-click + level merge + hover preview + rep caveat) in one batch, behind a flag. (NOT the cheaper
slices.) Breadcrumb UI + flipping the flag default + assembly unification stay Phase 3.

**Flag:** `NADOC_DRILL_V2` — `localStorage.setItem('NADOC_DRILL_V2','true')` OR `?drillv2=1`. OFF by default,
so the legacy auto-drill / manual-pin / Tab-lock paths are 100% untouched (smoke confirms the off-path).

**What shipped (route: 3 modules + 1 new, main.js LOC Δ = 0):**
- **`scene/selection_level.js` (NEW, pure):** the model — `LEVELS {default,cluster,domain,end,xover}`,
  `TAB_CYCLE [cluster,domain,end,xover]`, `BTN_LEVEL`/`LEVEL_BTN` (strand button ↔ default), `isDrillV2()`,
  `normalizeLevel`, `nextTabLevel`, `toggleLevel`. 14 vitest.
- **`scene/selection_manager.js`:** `_drillV2`+`_selLevel` state; `_v2HandleBead`/`_v2HandleCone` gate ahead
  of the legacy `_autoDrill*` calls; reusable `_select{Strand,Cluster,Domain,Bead,Cone}V2` primitives;
  hover-preview (`_updateHoverPreview`/`_clearHoverPreview`/`_pickNearestBeadCone`) on pointermove (default
  level + strand selected only); rep caveat (cylinders/surface 2nd-click → domain, no bead); public
  `setSelectionLevel`/`getSelectionLevel`/`isDrillV2`. Default ladder: 1st click→STRAND, 2nd→leaf-under-cursor
  (bead→nucleotide | cone→xover), 3rd same leaf→clear.
- **`ui/selection_filter.js`:** in v2 the 5 level buttons (clust/strand/line/ends/xover) drive
  `setSelectionLevel` (toggle off→default) instead of pinning `selectableTypes`; the visibility gates
  (scaf/stap/loop/skip/ovhangs) keep plain-toggle. `reflectDrillLevel` paints active+sf-pinned on the
  engaged level (default→strand). 6 vitest.
- **`ui/keyboard_shortcuts.js`:** in v2 Tab cycles `nextTabLevel` via `setSelectionLevel` (NOT the legacy
  drill-lock); Escape → `setSelectionLevel('default')` (inserted ahead of the drill-lock branch). 4 vitest.

**Pinned by:** 24 vitest (14+6+4) + `e2e/drill_v2_select.spec.js` (real-raycast: 1st→strand, 2nd→nucleotide,
3rd→clear, discriminating vs legacy). App-exercised via that e2e (flag on, real scaffolded part).

**NOT eyeballed (cosmetic / unit-covered, carry to Phase 3):** hover-preview pop and the filter-row pinned
paint weren't visually inspected; Tab toast + level switching are unit-tested but not human-verified.

**Phase 3 leads:** (1) breadcrumb UI (decision E) replacing the invisible level state; (2) flip the flag
default to ON + delete the legacy auto-drill/manual-pin/Tab-lock code once v2 is trusted; (3) assembly
adopts the same shape (decision G — net-new, no assembly drill exists). Confirm the exact
visibility-gate ↔ level split (decision F) with the user when wiring the breadcrumb.

### Phase 1 OUTPUT — current-state map + target interaction spec (banked 2026-06-05)

**Scope of the drill (verified by code read):** the drill is **design-editor ONLY**. `scene/assembly_pointer.js`
/ `scene/assembly_lasso.js` contain NO drill code — assembly selection is flat part-pick (the thing ISSUE-3
fixed). Three modules own the design drill: `scene/selection_manager.js` (auto-drill state machine
`_drillAnchor`/`_drillLevel`/`_drillSeq`/`_drillLock` + `setDrillLock`/`getDrillLock`/`_resetDrill`, the
`_autoDrillBead`/`_autoDrillCone` ladders ~1649–1771), `ui/selection_filter.js` (manual pins +
`reflectDrillLevel`/`reflectLockOnButtons`/`resetToAutoBaseline`, carve-up #61), `ui/keyboard_shortcuts.js`
(Tab cycle-lock ~247 + Escape pop ~574).

**Current model = three overlapping mechanisms on one `#select-filter` button row** (the root problem):
1. **Auto-drill** — repeat-click descends a rep-aware ladder keyed PER-STRAND (`${strandId}:bead|cone`):
   full/vdw/ballstick `cluster→strand→domain→bead`, cylinders `→domain`, surface `→strand`; a cone gives
   `cluster→strand→xover`. Cycles back to cluster one click past the leaf. Matching sf-btn `.active`-lights.
2. **Manual filter pins** — clicking an sf-btn pins it (red `sf-pinned`), switches to `selectableTypes`
   gating, and DISABLES drilling. Un-pinning the last restores auto-drill.
3. **Tab drill-lock** — Tab cycles `null→cluster→strand→domain→bead→xover→null`, pins clicks to a fixed
   level, and paints the SAME red `sf-pinned` border as a manual pin (but means something different).

**Friction (the confirmed repro — survey-style, USER TODO walkthrough):** red border means two different
things (selectability gate vs drill-depth lock); no persistent "what level am I on" signal in plain
auto-drill; clicking a different strand resets depth to cluster (per-strand anchor); the ladder cycles
back to the whole cluster one click past the leaf; three different exit paths (Esc / un-pin / click-other);
hidden modal state (`_drillLevel`/`_drillLock`/`_manualFilters` invisible).

**TARGET SPEC (user AskUserQuestion decisions, 2026-06-05 — these gate Phases 2–3):**

A. **Collapse to ONE concept: an active `selectionLevel` ∈ `{ default, cluster, domain, end, xover }`.**
   Merge the manual-pin and Tab-lock mechanisms into a single level state. Kills the "red means two things"
   ambiguity — there is exactly one engaged level at a time.

B. **Default click behavior (`selectionLevel = default`) — the common case (user: "almost always trying to
   select a strand, an end, or a crossover"):**
   - 1st click on any part element → select the **STRAND**.
   - 2nd click on the already-selected strand → select the **leaf UNDER THE CURSOR**: a **bead/end** if
     hovering a bead, a **crossover** if hovering a cone. Leaf is hover-determined, NOT a fixed sequence slot.
   - **Hover-preview affordance:** while a strand is selected, the element under the cursor (bead or xover)
     is highlighted *distinctly* to preview what a further click would select.
   - Strand is the ONLY thing reachable by plain click; **cluster & domain are NOT in the click path**.

C. **Cluster + domain levels reachable ONLY via the selection filters (or Tab)** — never via click-drill.
   When a level is engaged, every click selects at that fixed level.

D. **Tab cycles `<anywhere> → cluster → domain → end → xover → cluster → …`** (user-specified). NOTE this
   DIFFERS from today: strand and the `null`/auto state are NOT in the cycle — only the 4 filter levels.
   **Escape → return to `default`** (strand-default click). Tab and the filter buttons drive the SAME
   `selectionLevel`.

E. **Persistent breadcrumb** of the current level (e.g. `Strand ▸ End` in default mode with a leaf hovered,
   or the engaged level highlighted), clickable to change level. Replaces the invisible internal state.

F. **Filter row redesigned together** (decision "redesign together"): the cluster/strand/domain/ends/xover
   buttons become the `selectionLevel` selector (one coherent surface, no overloaded red). The orthogonal
   type-visibility gates (scaffold/staples/loops/skips/overhangs) stay a separate "what's pickable" concern
   — confirm the exact split in Phase 2.

G. **Unify assembly** (decision "design drill + unify assembly"): assembly adopts the same shape — 1st click
   = part (the strand-analog), 2nd click = sub-element under hover, breadcrumb `Part ▸ …`. Exact assembly
   sub-levels are a Phase-2 design detail (no assembly drill exists yet — it's net-new there).

**Target state machine:**
```
selectionLevel ∈ { default, cluster, domain, end, xover }

[default]                              (Esc lands here; the common case)
  click empty             → clear
  click element           → SELECT STRAND
  click selected strand   → SELECT leaf-under-cursor   (bead → end | cone → xover)
  hover (strand selected) → preview-highlight the would-be leaf
  Tab                     → [cluster]

[cluster | domain | end | xover]       (engaged via filter button or Tab)
  click element           → SELECT at this fixed level
  Tab                     → next in  cluster → domain → end → xover → cluster
  Esc  /  filter-off      → [default]
  click matching filter   → toggle (on = engage, re-click = off → default)
```

**Rep-awareness caveat (carry to Phase 2):** in `cylinders`/`surface` columns there is no pickable bead, so
the default-mode 2nd-click leaf may be unavailable — decide whether the 2nd click is a no-op or falls back to
domain/strand. `designRenderer.columnRepAt(helix_id, bp_index)` already exposes the per-column rep (the old
ladder used it to cap depth).

### Original dossier (pre-Phase-1 leads — superseded by the spec above)
- **Symptom (user):** the drill-down selection (click into nested levels: assembly → part → cluster →
  strand → bead, or the design-side filter drill) has become a "terrible UX." Needs a from-scratch
  redesign, not a patch.
- **Repro (to pin):** demonstrate the current drill flow end-to-end and catalogue the friction points
  (what's unpredictable, what loses selection, what level you land on, how you escape). A narrated USER
  TODO walkthrough + the user's pain points IS the repro; promote specific broken transitions to e2e
  assertions once the target model is agreed.
- **Suspected locations (verify):** `ui/selection_filter.js` (`initSelectionFilter` + the drill-lock
  state machine `reflectDrillLevel`/`reflectLockOnButtons`/`resetToAutoBaseline`, carve-up #61) +
  `scene/selection_manager.js` (which CALLS the filter's `reflectDrillLevel` from the bead-click drill) +
  `state/store.js` (selectableTypes / drill state). The drill-lock machine was just extracted (#61) — read
  that dossier + the extraction log row first.
- **Decomposition into phases (proposal — confirm):**
  - **Phase 1 — current-state map + target model.** Map every drill transition + the state it mutates.
    Research + propose 2-3 candidate interaction models (see below). ASK the user to pick. Output: an
    interaction spec + a state-machine diagram. No code.
  - **Phase 2 — rebuild the state machine** to the agreed model in `ui/selection_filter.js` /
    `selection_manager.js`, behind a flag if risky, with the e2e repro suite passing.
  - **Phase 3 — polish** (visual affordances for "what level am I on", escape/up-level, keyboard).
- **UX research (needed — this is the most research-dependent issue):** standard hierarchical-selection
  models to compare: (a) **double-click to drill in / Esc to pop out** (Figma groups, Blender object→edit);
  (b) **persistent breadcrumb** of the current drill level with click-to-jump; (c) **modifier-scoped**
  (Alt = drill one level under cursor). The current design is a "drill-lock" toggle model that the user
  finds terrible — the research should articulate *why* (mode confusion? hidden state? no escape?) and what
  replaces it. Produce a short written comparison before Phase 1's ask. Park it in this dossier.
- **Open questions (ask in Phase 1):** what does "drill" need to reach (which levels, in which editor)?
  Is the current *filter* UI (pin a type) part of the problem or separate? Preferred mental model from the
  three above?

---

## ISSUE-5 — Selecting an imported protein threw in the properties panel (functional bug)

- **Status:** `[x]` DONE 2026-06-06 (single phase). **Pushed in from the carve-up loop** — found while
  extracting the protein subsystem (`scene/protein_subsystem.js`, extraction #85) and fixed the same
  session. Fix in `ui/properties_panel.js` (new `_renderProtein` + `protein` dispatch branch). See
  `issues_fix_log.md` row + the carve-up difficulties-ledger entry. Commit `c119e32`.
- **Symptom (user-facing):** clicking/selecting an imported protein in the 3D view threw a console error
  (`Cannot read properties of undefined`) and rendered no panel — the right-panel "Properties" tab broke.
- **Root cause:** `selection_manager.js` sets `selectedObject = {type:'protein', id, data:{attachment_id}}`,
  but `properties_panel.js` `_render` had no `protein` branch → fell through the final `else` to
  `_renderNucleotide`, which reads nucleotide-shaped fields (`nuc.data.helix_id`, `_fmt(nuc.<pos>.map…)`).
  Confirmed byte-identical on master (pre-existing, unrelated to the extraction).
- **Repro (pinned):** `ui/properties_panel.test.js` (first test for that file; 5 cases incl. the
  no-throw regression + free/overhang anchors + missing-attachment fallback + hidden flag) + a live
  exercise (import `mini_protein.pdb` via `/design/import/pdb-auto` → select → panel renders, zero
  console errors).
- **Fix behavior:** `_renderProtein` shows asset name/source, anchor (free / overhang+attach-end /
  assembly instance), atom/residue/chain counts, conjugation atom, handle duplex, hidden flag — all from
  `design.protein_attachments`/`protein_assets`; graceful fallback when the attachment isn't in the
  design. Built to extend as more PDB-import paths land (user: "we want to eventually handle any PDB
  import"). **Follow-up validation debt:** the overhang/assembly anchor branches are unit-tested only,
  not eyeballed (no overhang-protein / assembly-protein fixture) → logged as `MV-15` in
  `manual_validation_debt.md`.

---

## ISSUE-6 — `test_teeth_closing_zig` flaky (hash-seed-dependent scaffold-strand count)

- **Status:** `[x]` DONE 2026-06-08 (single phase). **Pushed in from the backend router carve-up loop**
  (Refactor #2, 2026-06-08); also the long-standing `KNOWN_FLAKES` entry carried across every REFACTOR_AUDIT
  pass. Fix in `backend/core/seamed_router.py` (`_hamiltonian_path` tiebreaker) + `tests/test_seamless_router.py`
  (re-pinned `test_teeth_closing_zig` to the topological event, not a strand count).
- **The ledger's original diagnosis was WRONG.** It is **not** a cross-test state leak. The test fails/passes
  in a *single fresh process with no other tests running* — pin/fail tracks `PYTHONHASHSEED` (deterministic
  within a fixed seed, varies across seeds; ~30% of seeds gave 4 strands, ~70% gave 5). A reset fixture would
  not have touched it.
- **Root cause (5-Whys):** `test_teeth_closing_zig` asserted `len(scaf_strands) == 4` → the strand count varied
  → because the seamless router's Hamiltonian path varied → because the shared `_hamiltonian_path` (in
  `seamed_router.py`, used by both the seamless and advanced-seamed routers) sorted candidate helices by
  **degree only with no tiebreaker** → so equal-degree helices came out in `set`-iteration (hash-seed) order.
  A 2026-06-01 refactor routed teeth through this shared search and lost the `(len(adj[n]), n)` tiebreaker that
  `seamless_router._ham_path_ending` already had. A standing FIXME at the spot named the exact bug.
- **Fix part 1 — determinism (root cause):** added the `(len(adj[n]), n)` lexicographic tiebreaker to BOTH the
  starter sort and the neighbor key in `_hamiltonian_path`. Verified deterministic across 13 hash seeds.
- **Fix part 2 — re-pin the test to its real intent:** with the user's framing that *a fully-routed scaffold is
  1 strand and `auto_scaffold_seamless` is only an INTERMEDIATE stage* (it places crossovers, doesn't ligate to
  one loop), the absolute count of leftover scaffold pieces (4 vs 5) is a meaningless artifact of path ordering,
  NOT an invariant. The test is named for the **closing-zig event**, which I confirmed **fires reliably in both
  the 4- and 5-piece orderings** (crossover `h_XY_2_2 ↔ h_XY_2_3` is present). So the assertion now checks the
  topological events — `bridge_xovers == 6`, no warnings, and the closing-zig crossover exists — matching the
  process-count style of every other test in the file. Order-independent green across 13 seeds + 2× full `just
  test` (1753 passed, was 1752/1-fail).
- **Failed hypothesis chased first:** the FIXME's prescribed "add the tiebreaker" alone made it deterministic but
  locked onto **5** strands (the wrong target if you believe the old `== 4`); the resolution was to recognize the
  count itself was never the right assertion, not to hunt for the tiebreak direction that yields 4.
- **Knock-on:** this kills the `KNOWN_FLAKES` entry referenced throughout `REFACTOR_AUDIT.md`,
  `backend_router_carveup.md`, and `backend_router_extraction_log.md`.

## ISSUE-7 — Negative-bp scaffold segments undeletable in the 2D editor (functional bug)

- **Status:** `[x]` DONE 2026-06-08 (single phase). **Direct triage** — user reported on `workspace/teeth.nadoc`:
  "I cannot delete the scaffold segments on helices 0–7 starting at bp −17; nothing happens." Fix routes ALL
  cadnano-editor element-key parsing through a new tested module `cadnano-editor/element_keys.js` (negative-bp
  safe). Commit pending.
- **Symptom (user-facing):** selecting a scaffold stub that lives entirely in the negative-bp region
  (helices 0–7 of teeth: bp −17..−6/−12) and pressing Delete does NOTHING — no error, the strand stays.
- **ROOT CAUSE (multi-factor, confirmed by code read + Node repro + e2e):**
  1. **Primary — the delete path's key parsers used `(\d+)`, which can't match a negative bp.** The 2D
     editor's `erase` tool is dead UI (no toolbar button / keybinding); the real delete gesture is
     **select-tool → Delete key → `onDeleteElements`** (`cadnano-editor/main.js`). That function (and 4
     sibling parsers) parse element keys like `line:h_XY_0_0_-17_-6_FORWARD` / `end:…_-17_…` / `xo:…_-5_…` /
     `ls:…_-17_…` with `(\d+)` regexes → `null` on any negative-bp key → the domain-selector set stays empty
     → no API call fires → "nothing happens." (Builders in `pathview.js` correctly EMIT negative bp; only the
     parsers were blind. Two drag-handler parsers already used the correct `-?\d+` — the rest never did.)
  2. **Secondary (visibility) — `_fitToContent` drew the negative-bp cells off the left edge.** `_bpToX(bp)
     = GUTTER + bp*BP_W` places bp −17 at world-x −130, but the fit positioned content as if it began at
     world-x 0 (panX clamped ≥ 0), so on a fresh open the entirely-negative stubs rendered ~43 px off-screen
     left while blank EXTEND space sat on the right. Fixed by offsetting panX by the true left edge
     (`worldLeft = min(0, _bpToX(bp0))`). Proven on/off-screen by a throwaway Playwright probe
     (bp −17: screen-x −37 → 0 after fix). This was a real bug but NOT why Delete no-ops — fixing it alone
     didn't let the user delete (the reopen that surfaced factor 1).
- **FIX (user chose "sweep all bp-key parsers"):** new `cadnano-editor/element_keys.js` owns BOTH the build
  and the parse of every element key (single source of truth; `-?\d+` everywhere). `pathview.js` imports the
  5 builders (aliased to the old `_`-names → no call-site churn) + routes its 2 parse sites through the
  module; `main.js` routes its 5 broken parse sites (delete path ×4 + extra-bases menu) through it. Plus the
  `_fitToContent` panX offset.
- **Repro pinned by:** `cadnano-editor/element_keys.test.js` ×19 (the exact teeth stub keys parse to the
  right object + build↔parse round-trips for negative / zero-crossing / positive / reversed cases; old `\d+`
  proven red via a standalone Node eval). App-validated: a throwaway gesture e2e drove the REAL select →
  Delete path on teeth and confirmed the stub is removed (factor 1) and lands on-screen (factor 2); removed
  after verification along with the temp debug hooks.
- **Class of bug → LESSONS.md F5** (bp is signed; never parse it with `(\d+)`). Cross-refs C6 (the cadnano
  editor has its own API client / code — this bug lived entirely in editor-local parsers).

## ISSUE-10 — Dead MD-load REST routes superseded by the WebSocket path (tech debt / dead code)

- **Status:** `[x]` DONE 2026-06-16 — both dead handlers + their request models deleted from `routes_md.py`
  in the same session they were discovered (user approved). `/md/browse` (live) kept. 2130 passed, 0 failed;
  ruff clean. Discovered during the crud.py carve-up (Refactor #42, MD-load fold-in).
- **Symptom:** `POST /md/resolve-config` and `POST /md/load` have **no caller** — not in `frontend/src/`,
  not in `tests/`. The live MD-playback load path is the `/ws/md-run` WebSocket (`backend/api/ws.py`,
  `action:'load'`), which calls `backend.core.md_import.resolve_md_config` directly and does the trajectory
  load itself. The REST twins are leftovers from before the WS path. (`GET /md/browse`, by contrast, IS
  live — `frontend/src/ui/md_panel.js` uses it for the file picker.)
- **Where:** both routes now live in `backend/api/routes_md.py` (folded out of crud.py in #42, moved verbatim
  rather than deleted because deletion is a risky action needing user sign-off). `md_resolve_config` /
  `md_load`, just below the `# ── Molecular Dynamics load` banner.
- **Desired behavior (to confirm with user):** if truly dead, delete both handlers + their request models
  (`MdResolveConfigRequest` / `MdLoadRequest`) from `routes_md.py`. Before deleting, double-check no external
  tooling / notebook / curl-based workflow depends on them (the carve-up only proved no *in-repo* caller).
- **Scope:** tiny, mechanical deletion. No behavior change (nothing calls them). Low priority.

