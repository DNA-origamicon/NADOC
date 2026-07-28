// Which left-hand tabs may keep a simulation display painted into the scene.
//
// Every engine panel (oxDNA, NAMD/MD, mrDNA, CanDo, SNUPI) writes its relaxed /
// trajectory-frame / RMSF positions into the SHARED bead overlay via
// designRenderer.applyFemPositions() — there is no separate sim scene graph. So
// "stop the display" literally means "revert the model the user is looking at to
// equilibrium geometry". Each panel used to do that on leaving Dynamics, which is
// right for the editing tabs (a deformed model must not linger where you edit
// topology) but wrong for Photo: the whole point of the Photo tab is to render the
// simulated result the user is currently looking at.
//
// The rule lives here, not in six copies, because all the panels must agree — a
// single panel that still tears down turns a photo of an oxDNA frame into a photo
// of the un-simulated design.

/** The tab that OWNS the engine panels; displays start and resume here. */
export const DISPLAY_HOME_TAB = 'dynamics'

/** View-only tabs that render the scene as-is and must not disturb a display.
 *  `photo-exp` is the experimental render testbed — same rationale as `photo`:
 *  you photograph what is on screen, including a simulated frame. */
export const DISPLAY_PRESERVING_TABS = Object.freeze(['photo', 'photo-exp'])

/** True if `tabId` may keep a running simulation display on screen. */
export function preservesDisplays(tabId) {
  return DISPLAY_PRESERVING_TABS.includes(tabId)
}

/**
 * True if a tab change to `activeTab` must revert the model to equilibrium.
 * False for Dynamics (displays live there) and for the view-only tabs.
 */
export function shouldTearDownDisplays(activeTab) {
  return activeTab !== DISPLAY_HOME_TAB && !preservesDisplays(activeTab)
}

/** True if arriving on `activeTab` should resume polling / re-open the panels. */
export function shouldResumeDisplays(activeTab) {
  return activeTab === DISPLAY_HOME_TAB
}

/** Every tab on which a display is allowed to be on screen. */
export function displayTabIds() {
  return [DISPLAY_HOME_TAB, ...DISPLAY_PRESERVING_TABS]
}
