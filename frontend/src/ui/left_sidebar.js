/** Persistent left-sidebar tab state and render-mode transition policy. */
import { preservesDisplays } from './display_tab_policy.js'

export function initLeftSidebar({
  store,
  animPlayer,
  trajectoryKeyframes,
  seekFeaturesWithDelta,
  photoMode,
  animPanel,
}) {
  const _seekFeaturesWithDelta = seekFeaturesWithDelta
  const _photoMode = photoMode
  const TABS = ['feature-log', 'dynamics', 'scene', 'photo', 'plates']
  // Tabs that install a render override and must be torn down when you leave.
  const RENDER_OVERRIDE_TABS = ['photo']
  const STORAGE_KEY = 'nadoc.leftSidebar.v1'
  const leftPanel = document.getElementById('left-panel')
  const tabStrip  = document.getElementById('left-tab-strip')
  const toggleBtn = document.getElementById('left-tab-toggle')
  if (leftPanel && tabStrip) {
    const btns  = Object.fromEntries(TABS.map(id => [id, tabStrip.querySelector(`[data-tab="${id}"]`)]))
    const panes = Object.fromEntries(TABS.map(id => [id, document.getElementById(`tab-content-${id}`)]))

    let activeTab = 'feature-log'
    let collapsed = true

    // Restore persisted state.
    // Special case: if the saved active tab was 'photo', fall back to
    // 'feature-log'. Photo mode is in-memory only and isn't auto-restored on
    // reload, so we don't want to leave the sidebar parked on the Photo tab
    // (which won't actually be in photo mode and just shows stale controls).
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
      if (saved) {
        if (TABS.includes(saved.activeTab) && !RENDER_OVERRIDE_TABS.includes(saved.activeTab)) {
          activeTab = saved.activeTab
        }
        if (typeof saved.collapsed === 'boolean') collapsed = saved.collapsed
      }
    } catch { /* ignore corrupt state */ }

    function _persist() {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ activeTab, collapsed })) } catch {}
    }

    function _render() {
      // While locked (welcome screen / part-context), force visual hidden
      // regardless of the controller's internal `collapsed` state, so the
      // persisted "expanded" state doesn't leak through and pop the panel
      // open at the welcome screen. `locked` also drives the tab highlight
      // and the toggle arrow: a lit tab and a "Hide sidebar" arrow over a
      // panel that is shut read as a bug, and they were what made a closed
      // session still look like it had the sidebar open.
      const locked = leftPanel.classList.contains('locked-hidden')
      const shut   = collapsed || locked
      const simulationTabActive = !shut && activeTab === 'dynamics'
      if (store.getState().simulationTabActive !== simulationTabActive) {
        store.setState({ simulationTabActive })
      }
      for (const id of TABS) {
        if (btns[id])  btns[id].classList.toggle('active', id === activeTab && !shut)
        if (panes[id]) panes[id].hidden = (id !== activeTab)
      }
      leftPanel.classList.toggle('hidden', shut)
      if (toggleBtn) {
        toggleBtn.textContent = shut ? '▶' : '◀'
        toggleBtn.title       = shut ? 'Show sidebar' : 'Hide sidebar'
      }
    }

    // Called whenever the visible state of the Animations (formerly Scene)
    // tab changes from "active + expanded" → anything else. Stops any
    // in-flight playback (frees baked geometry) and re-seeks the design
    // to the feature-log slider's current cursor so the live model
    // matches what the slider says rather than the last lerped frame.
    function _leaveAnimationsTab() {
      try {
        animPlayer?.stop?.()
        animPlayer?.setDisablePoses?.(false)
        // An authoring PREVIEW survives the tab change (the panel still shows
        // "■ Stop" at frame N, and the trajectory is loaded and paid for). The
        // re-seek below rebuilds the design from topology, which would overwrite
        // the previewed frame with design coordinates and leave the panel's
        // needle lying about what is on screen. `animPlayer.stop()` above no
        // longer releases a hold it doesn't own, so the preview really is alive.
        if (trajectoryKeyframes?.isPreviewing?.()) return
        const d = store.getState().currentDesign
        const cursor = d?.feature_log_cursor ?? -1
        const subCursor = d?.feature_log_sub_cursor ?? null
        // Re-issue a seek with the same cursor so the backend rebuilds the
        // design at exactly that index and the renderer subscribes pick up
        // the canonical state. -1 (no features) and -2 (pre-F0) both round-trip
        // through seekFeatures correctly.
        _seekFeaturesWithDelta(cursor, subCursor)
      } catch (err) {
        console.warn('[left-tabs] reset on tab leave failed:', err)
      }
    }

    // Animations → Photo defers the re-seek above instead of running it: the
    // re-seek rebuilds the design from topology, which would drop whatever the
    // user is trying to photograph (an oxDNA/NAMD frame, an animation pose).
    // We owe it on the way OUT of Photo — that's what this flag remembers.
    let _animLeaveDeferred = false

    function _leaveAnimationsTabUnlessPhoto(tabId) {
      if (preservesDisplays(tabId)) { _animLeaveDeferred = true; return }
      _leaveAnimationsTab()
    }

    // Arriving on Animations: put a surviving authoring preview back on screen. No-op
    // unless the user actually left one running. Fire-and-forget — the only async path
    // is re-taking a hold the Feature Log policy dropped, and that resolves
    // out of the still-resident cache.
    function _enterAnimationsTab() {
      animPanel?.resumePreview?.()?.catch?.(() => {})
    }

    function setActiveTab(tabId) {
      if (leftPanel.classList.contains('locked-hidden')) return
      if (!TABS.includes(tabId)) return
      // Switching to any tab other than Photo leaves photo mode (the render
      // override is in-memory only and otherwise stays installed). Pass
      // skipTabRestore so the exit doesn't yank us back to feature-log — the
      // switch below lands us on the tab the user actually clicked.
      if (tabId !== 'photo') {
        _photoMode.exit()
        // Pay off a re-seek we skipped on the way into Photo. Going back to
        // Animations cancels it instead — we never really left.
        if (_animLeaveDeferred) {
          _animLeaveDeferred = false
          if (tabId !== 'scene') _leaveAnimationsTab()
        }
      }
      const wasOnAnimations = !collapsed && activeTab === 'scene'
      if (collapsed) {
        collapsed = false
        activeTab = tabId
      } else if (tabId === activeTab) {
        collapsed = true
      } else {
        activeTab = tabId
      }
      const nowOnAnimations = !collapsed && activeTab === 'scene'
      if (wasOnAnimations && !nowOnAnimations) {
        _leaveAnimationsTabUnlessPhoto(collapsed ? null : activeTab)
      } else if (!wasOnAnimations && nowOnAnimations) {
        _enterAnimationsTab()
      }
      _render()
      // Idempotent — a second click on an active render-override tab only
      // collapses the sidebar, deliberately leaving the render mode running
      // so the user gets the full viewport.
      if (activeTab === 'photo') _photoMode.enter()
      window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
        detail: { activeTab, collapsed },
      }))
      _persist()
    }

    // Make `tabId` the active tab WITHOUT the click-toggle semantics
    // (clicking the active tab collapses; this never collapses). Preserves
    // the user's collapsed/expanded preference. Used to default a freshly
    // loaded part to the Feature Log tab regardless of which tab was last
    // persisted.
    function selectTab(tabId) {
      if (!TABS.includes(tabId)) return
      if (activeTab === tabId) { _render(); return }
      if (tabId !== 'photo') _photoMode.exit()
      const wasOnAnimations = !collapsed && activeTab === 'scene'
      activeTab = tabId
      // Same photo/preview exemption as the click path — this used to leave
      // unconditionally, so even selectTab('photo') tore the preview down.
      if (wasOnAnimations) _leaveAnimationsTabUnlessPhoto(collapsed ? null : tabId)
      else if (!collapsed && tabId === 'scene') _enterAnimationsTab()
      _render()
      window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
        detail: { activeTab, collapsed },
      }))
      _persist()
    }

    function toggleCollapsed() {
      if (leftPanel.classList.contains('locked-hidden')) return
      const wasOnAnimations = !collapsed && activeTab === 'scene'
      collapsed = !collapsed
      if (wasOnAnimations && collapsed) _leaveAnimationsTab()
      else if (!collapsed && activeTab === 'scene') _enterAnimationsTab()
      _render()
      _persist()
    }

    // Session teardown (`_showWelcome`). The `locked-hidden` lock + `_render`
    // above do the collapsing for EVERY tab; what this adds is dropping a
    // render-override tab, so the override is off (idempotent — the usual
    // close path already exited via `_resetForNewDesign`, but Close Session
    // with no design loaded never goes there, and photo mode runs on an empty
    // scene) and the pane isn't armed to flash back on the next design open.
    //
    // `collapsed` itself is deliberately NOT touched and nothing is persisted:
    // it is the user's expanded/collapsed PREFERENCE, and `_setLeftPanelEnabled(true)`
    // replays it when a design opens. Teardown overrides the view, not the choice.
    function collapseForTeardown() {
      if (RENDER_OVERRIDE_TABS.includes(activeTab)) {
        _photoMode.exit()
        activeTab = 'feature-log'
      }
      _render()
    }

    for (const id of TABS) {
      if (btns[id]) btns[id].addEventListener('click', () => setActiveTab(id))
    }
    if (toggleBtn) toggleBtn.addEventListener('click', toggleCollapsed)

    // Apply initial state without firing persistence.
    _render()
    window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
      detail: { activeTab, collapsed },
    }))

    // Expose the controller for assembly-mode entry/exit handlers and tests.
    const controller = {
      setActiveTab,
      selectTab,
      toggleCollapsed,
      collapseForTeardown,
      getActiveTab: () => activeTab,
      isCollapsed:  () => collapsed,
      // Re-applies visual state from internal `collapsed` + `locked-hidden`.
      // Used by `_setLeftPanelEnabled` so unlocking the panel restores the
      // user's persisted expanded/collapsed preference.
      refresh: _render,
    }
    window.__leftSidebar = controller
    return controller
  }
  return null
}
