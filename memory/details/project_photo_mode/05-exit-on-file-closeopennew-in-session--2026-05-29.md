# Exit on file close/open/new (in-session) — 2026-05-29 — supporting detail

[Topic head](../../project_photo_mode.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Exit on file close/open/new (in-session) — 2026-05-29

Photo mode is in-memory only, so a *page reload* is already safe (renderer
reconstructed with `_active=false`, see "Reload behaviour"). But an **in-session**
close → new/open left photo mode running: `_photoModeExit()` was only wired to the
Photo tab button (photo mode is entered/exited **only** via the left-sidebar Photo
tab — there is NO keyboard shortcut; the old `p` binding was removed and `P` is now
Physics), so nothing dropped it when the design/assembly was torn down. Symptom: in
photo mode → Close Session → New Part came up "in photo mode" (the render override
stayed installed).

Fix ([main.js](../../../frontend/src/main.js)):
- `_photoModeExit()` is now **idempotent** — early-returns if `!photoRenderer.isActive()`,
  so it's safe to call from any teardown path.
- Called at the **top of `_resetForNewDesign()`** (the choke point for new/open/import/
  load/close of a part — runs first so `deactivate()` restores live materials while
  meshes still exist) and at the **top of `_enterAssemblyMode()`** (open/new assembly).
- Together these cover: Close Session, New/Open Part, New/Open Assembly, import
  cadnano/scadnano/PDB. **Not** wired to the SSE external-edit in-place reload of the
  *same* open file — that's not a context switch and the renderer adopts rebuilt
  meshes on the fly.

### No design ⇒ no open sidebar (Close Session) — 2026-08-02

**The bug was CSS specificity, and it is not photo-specific.**
[sidebar_resize.js:45](../../../frontend/src/ui/sidebar_resize.js#L45) persists a dragged
sidebar width as an **inline** `style.width`, which outranks
`#left-panel.hidden { width: 0 }` from the stylesheet. So for any user who had ever
resized the sidebar, `.hidden` stopped collapsing it — and Close Session fires
`nadoc:workspace-path-change` with a null path, whose handler RE-APPLIES the saved
global width, inline, onto the panel it just hid. Symptom: close the session and the
sidebar is still there, showing an empty pane. A fresh browser profile never
reproduces it (no saved width) — that is why the first repro of this looked clean.

Three parts, all in the "shut" direction:
1. `#left-panel.hidden { width: 0 !important; min-width: 0 }` — an author
   `!important` beats a non-important inline style. Load-bearing; don't drop it
   while `sidebar_resize` writes inline widths.
2. `_render()` derives `shut = collapsed || locked` and drives the tab highlight and
   the toggle arrow off it, not off `collapsed` alone — a lit tab and a "Hide
   sidebar" arrow over a shut panel were most of what read as "still open".
3. `_showWelcome()` calls `__leftSidebar.collapseForTeardown()` (via `window.`, NOT
   the closure const — `_showWelcome` runs at boot, thousands of lines before that
   `let` initialises → TDZ). It drops a RENDER_OVERRIDE tab (`_photoMode.exit()`,
   activeTab → feature-log) so the override is off and the pane can't flash back.
   It does **not** touch `collapsed` and persists nothing: that is the user's
   preference, replayed by `_setLeftPanelEnabled(true)` on the next design open.

Also: `_setLeftPanelEnabled(false)` now disables the Photo tab button with the rest.
Its exemption ("works on any scene, even empty") had been dead for a long time —
`setActiveTab`/`toggleCollapsed` both early-return while `locked-hidden` is set, so
the button was clickable and inert.

Verified with a saved global width, closing from Photo AND from Feature Log:
`{inlineWidth: '420px', width: 1, enabledTabs: []}` — inline width back, panel shut
anyway — and re-opening a design restores both the 420 px width and Feature Log.

## Exit on sidebar-tab switch + feature-log default on load — 2026-06-20

Two related sidebar behaviours:
- **Switching to any non-Photo left-sidebar tab now exits photo mode.** The tab
  strip's `setActiveTab(tabId)` (main.js sidebar controller) calls
  `_photoMode.exit({ skipTabRestore: true })` whenever `tabId !== 'photo'`.
  `_photoModeExit` ([photo_mode.js](../../../frontend/src/scene/photo_mode.js)) gained a
  `{ skipTabRestore }` option so the exit doesn't yank the user back to
  feature-log — the strip switch lands them on the tab they clicked. (Entering
  via the Photo tab is unchanged; clicking Photo while active still just
  collapses.) Supersedes the old "exit is ONLY wired to the Photo tab button"
  claim in the in-session-exit note below.
- **A freshly loaded part defaults to the Feature Log tab.** `_hideWelcome()`
  (the universal funnel for every open/new/import path) calls a new
  `__leftSidebar.selectTab('feature-log')` — a non-toggling tab setter
  (preserves the user's collapsed/expanded pref; unlike `setActiveTab`, it never
  collapses when re-selecting the active tab) that overrides whatever tab was
  persisted in `localStorage`.

Verified in-app (temp Playwright spec, since deleted): persisted `plates` →
load part → active tab is `feature-log`; enter photo → switch Dynamics/Plates →
`__photoRenderer.isActive()` false + clicked tab active, no console errors.
