/**
 * ui/md_display_state.js — pure decision helpers for the MD display controller.
 *
 * Extracted from md_panel.js so the state-machine logic that decides *whether to
 * open a new WebSocket, reuse the open one, or wait for an in-flight load* can be
 * unit-tested without a DOM, a WebSocket, or a Three.js scene.
 *
 * These functions are pure: same inputs → same output, no side effects.
 */

// WebSocket.readyState values (kept local so tests don't need the WebSocket global).
export const WS = Object.freeze({ CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 })

/**
 * Pick the trajectory stream mode for the current scene representation.
 *   atomistic scene reprs (vdw / ballstick) → 'ballstick'
 *   everything else (full / beads / cylinders / hull / surface) → 'nadoc'
 */
export function targetStreamMode(sceneRepr) {
  return sceneRepr === 'vdw' || sceneRepr === 'ballstick' ? 'ballstick' : 'nadoc'
}

export function sceneUsesAtomistic(sceneRepr) {
  return sceneRepr === 'vdw' || sceneRepr === 'ballstick'
}

export function sceneUsesNativeCg(sceneRepr) {
  return sceneRepr === 'full' || sceneRepr === 'beads' || sceneRepr === 'cylinders'
}

/**
 * Decide what the display controller should do when asked to show `requestedConfig`.
 *
 * Returns one of:
 *   'open'           — open a fresh WebSocket and send a load (no usable connection,
 *                      or a forced reload, or the target config/mode changed).
 *   'reuse-open'     — a ready WebSocket already serves this exact target; reuse it
 *                      (re-arm live / re-apply the cached frame / poll).
 *   'wait-in-flight' — a load for this exact target is already in flight; do nothing
 *                      and let the pending 'ready' apply the frame. Crucially this
 *                      avoids tearing down a mid-handshake socket (NS_BINDING_ABORTED).
 *
 * @param {object} p
 * @param {number|null} p.wsState        WebSocket.readyState, or null when no socket
 * @param {boolean}     p.loadInFlight   true between sending 'load' and receiving 'ready'/'error'
 * @param {string|null} p.loadConfigPath config path of the in-flight load
 * @param {string|null} p.currentConfig  config path the controller last targeted
 * @param {string}      p.requestedConfig config path now requested
 * @param {boolean}     p.modeChanged    true when the stream mode (nadoc/ballstick) differs
 * @param {boolean}     p.forceReload    caller insists on a fresh load
 */
export function decideReload({
  wsState = null,
  loadInFlight = false,
  loadConfigPath = null,
  currentConfig = null,
  requestedConfig,
  modeChanged = false,
  forceReload = false,
}) {
  if (forceReload) return 'open'

  const wsActive = wsState === WS.CONNECTING || wsState === WS.OPEN
  const loadingSameTarget =
    loadInFlight && wsActive && loadConfigPath === requestedConfig && !modeChanged
  if (loadingSameTarget) return 'wait-in-flight'

  const reuseOpen =
    wsState === WS.OPEN && currentConfig === requestedConfig && !modeChanged
  if (reuseOpen) return 'reuse-open'

  return 'open'
}

/**
 * Frame-apply gating: a cached frame may only be re-applied to the scene when the
 * stream mode still matches the current scene representation. A 'nadoc' frame is
 * meaningless once the scene switched to an atomistic representation, and vice
 * versa — re-applying it would paint stale/garbage positions.
 */
export function canReapplyFrame(repr, sceneRepr) {
  if (repr === 'nadoc' && !sceneUsesNativeCg(sceneRepr)) return false
  if (repr === 'ballstick' && !sceneUsesAtomistic(sceneRepr)) return false
  return true
}
