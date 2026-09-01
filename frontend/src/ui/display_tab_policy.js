// Which left-hand tabs may keep a simulation display painted into the scene.
//
// Every engine panel (oxDNA, NAMD/MD, mrDNA, CanDo, SNUPI) writes its relaxed /
// trajectory-frame / RMSF positions into the SHARED bead overlay via
// designRenderer.applyFemPositions() — there is no separate sim scene graph. So
// "stop the display" literally means "revert the model the user is looking at to
// equilibrium geometry". Each panel used to do that on leaving Dynamics, which is
// right for the editing tabs (a deformed model must not linger where you edit
// topology) but wrong for view-only tabs: they must show the result the user is
// currently looking at without silently restoring equilibrium geometry.
//
// The rule lives here, not in six copies, because all the panels must agree — a
// single panel that still tears down turns a photo of an oxDNA frame into a photo
// of the un-simulated design.

/** The tab that OWNS the engine panels; displays start and resume here. */
export const DISPLAY_HOME_TAB = 'dynamics'

/** Tabs that must not disturb a display already painted into the scene.
 *
 *  - `photo` — renders what is on screen, which includes an oxDNA/NAMD frame.
 *  - `plates` — view/order UI only. Selecting wells may highlight strands, but the
 *    tab does not edit molecular geometry and therefore has no authority to reset it.
 *  - `scene` (the ANIMATIONS tab) — a trajectory keyframe paints its frames through
 *    the very same `oxdnaDisplay` / `mdViz` controller (see
 *    `scene/trajectory_keyframes.js`). Tearing displays down on arrival here would
 *    stop the animation's own playback. It did exactly that: Animations → Photo →
 *    Animations reverted the model to native positions, because the return trip fired
 *    `left-tab-change` with `activeTab: 'scene'` and `_allDisplaysOff()` called
 *    `stopAndRestore()` on the controller the animation was driving. Before trajectory
 *    keyframes shared that controller, `isActive()` was false here and the teardown
 *    was a silent no-op — which is why this only became reachable in 2026-08.
 */
export const DISPLAY_PRESERVING_TABS = Object.freeze(['photo', 'scene', 'plates'])

/** Tabs a LIVE (streaming) session may keep running on. Stricter than the painted
 *  set: a painted overlay is static and can sit on the Animations tab, but a live
 *  stream keeps WRITING bead positions every frame and would fight animation playback
 *  for the same beads. Photo only, exactly as before. */
export const LIVE_PRESERVING_TABS = Object.freeze(['photo'])

/** True if `tabId` may keep a running simulation display on screen. */
export function preservesDisplays(tabId) {
  return DISPLAY_PRESERVING_TABS.includes(tabId)
}

/**
 * True if a tab change to `activeTab` must revert the model to equilibrium.
 * False for Dynamics (displays live there) and for the display-preserving tabs.
 */
export function shouldTearDownDisplays(activeTab) {
  return activeTab !== DISPLAY_HOME_TAB && !preservesDisplays(activeTab)
}

/**
 * True if a LIVE streaming session (oxDNA live field, "Display MD" over the job
 * WebSocket) must stop on arriving at `activeTab`.
 *
 * Separate from `shouldTearDownDisplays` because the two answers now differ on the
 * Animations tab: a painted trajectory frame belongs there, a stream that keeps
 * overwriting the same beads does not.
 */
export function shouldStopLiveSession(activeTab) {
  return activeTab !== DISPLAY_HOME_TAB && !LIVE_PRESERVING_TABS.includes(activeTab)
}

/** True if arriving on `activeTab` should resume polling / re-open the panels. */
export function shouldResumeDisplays(activeTab) {
  return activeTab === DISPLAY_HOME_TAB
}

/** Every tab on which a display is allowed to be on screen. */
export function displayTabIds() {
  return [DISPLAY_HOME_TAB, ...DISPLAY_PRESERVING_TABS]
}

/** Every tab on which a LIVE streaming session may keep running. */
export function liveTabIds() {
  return [DISPLAY_HOME_TAB, ...LIVE_PRESERVING_TABS]
}
