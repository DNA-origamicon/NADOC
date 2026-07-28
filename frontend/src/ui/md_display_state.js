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
 * Stamp each streamed ball-and-stick atom with its design identity, IN PLACE.
 *
 * MD frames carry coordinates only; the identity the colour resolver keys on
 * (strand_id / helix_id / bp_index / direction) is static across frames, so the backend
 * sends it once at load as interned parallel arrays (`ws.py` → 'ready' → `atom_ident`).
 * Without it every MD atom misses the strand lookup and is stuck on CPK, deaf to the
 * strand/base/cluster colouring buttons.
 *
 * Mutates rather than maps: a frame is up to hundreds of thousands of atoms, and the
 * objects are freshly parsed per frame and owned by the caller.
 *
 * Leaves the atoms untouched when there is no identity or the counts disagree — a
 * mismatched map would paint atoms with some OTHER atom's strand, which is worse than
 * the CPK fallback.
 *
 * @param {Array<object>|null|undefined} atoms
 * @param {{strands:string[],helices:string[],dirs:string[],strand_idx:number[],
 *          helix_idx:number[],dir_idx:number[],bp:number[]}|null} ident
 * @returns {Array<object>|null|undefined} the same `atoms` reference
 */
export function zipAtomIdentity(atoms, ident) {
  if (!atoms || !ident || ident.strand_idx?.length !== atoms.length) return atoms
  const { strands, helices, dirs, strand_idx, helix_idx, dir_idx, bp } = ident
  for (let i = 0; i < atoms.length; i++) {
    const a = atoms[i]
    a.strand_id = strands[strand_idx[i]] ?? ''
    a.helix_id  = helices[helix_idx[i]] ?? ''
    a.direction = dirs[dir_idx[i]] ?? ''
    a.bp_index  = bp[i]
  }
  return atoms
}

/**
 * Is the scene drawn by a HEAVY renderer (atomistic or molecular surface) rather
 * than the design's own CG geometry?  The heavy set is exactly {vdw, ballstick,
 * surface}; every other repr (full / beads / cylinders / hull-prism) is drawn by
 * the design renderer.  Note this is the complement of "design-renderer CG" — it is
 * NOT `!sceneUsesNativeCg`, because hull-prism is a design-renderer CG repr that
 * `sceneUsesNativeCg` deliberately excludes.
 */
export function sceneUsesHeavy(sceneRepr) {
  return sceneUsesAtomistic(sceneRepr) || sceneRepr === 'surface'
}

/**
 * What `_restoreDesign` should do when a live / flex / trajectory MD view is stopped,
 * GIVEN the scene representation the user has chosen.  The chosen representation must
 * PERSIST across toggling any MD view — stopping a display must never revert an
 * atomistic/surface scene back to the CG bead-and-slab model.
 *
 *   CG design reprs (full / beads / cylinders / hull-prism)
 *     → showNativeCg: show the design renderer's own CG geometry at the equilibrium
 *       pose (atomistic renderer off).
 *   Heavy reprs (vdw / ballstick / surface)
 *     → rebuildHeavy: keep the heavy renderer, rebuilt from the design at equilibrium;
 *       the native CG design renderer stays hidden.
 */
export function restorePlan(sceneRepr) {
  return sceneUsesHeavy(sceneRepr)
    ? { showNativeCg: false, rebuildHeavy: true }
    : { showNativeCg: true, rebuildHeavy: false }
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
 * Toggle-on reload decision for the MD jobs panel.
 *
 * While the Display-MD toggle is OFF, a background prewarm keeps a warm display
 * socket + cached latest frame for the selected job/segment (its `prewarmKey`).
 * When the user toggles ON we want to REUSE that warm socket and paint the cached
 * frame instantly — a fresh load re-parses the PSF (seconds for big systems),
 * which is exactly the wait the prewarm exists to hide.
 *
 * `key` encodes `config_path|trajectory_path|segment_name`; config_path is the
 * job's resolved manifest path, so a key match implies the same job and segment.
 * Force a reload only when this exact key is neither already displayed nor already
 * prewarmed.
 *
 * @param {object} p
 * @param {string}      p.key         current display key (config|traj|segment)
 * @param {string|null} p.displayKey  key the display path last loaded
 * @param {string|null} p.displayJobId job id the display path last loaded
 * @param {string}      p.jobId       job id now being displayed
 * @param {string|null} p.prewarmKey  key the background prewarm last warmed
 */
export function shouldForceDisplayReload({ key, displayKey, displayJobId, jobId, prewarmKey }) {
  if (prewarmKey === key) return false   // prewarm already warmed this exact target
  return key !== displayKey || jobId !== displayJobId
}

/**
 * Live-poll pacing decision, evaluated once per live interval tick.
 *
 * `get_latest` is fire-and-forget: without pacing the fixed 5 s interval keeps
 * firing even when the previous poll hasn't returned, so a slow load (GROMACS XTC
 * still does load_new per poll) backs the requests up on the server; and if a poll
 * NEVER returns (backend error mid-refresh) the "Fetching…" bar pulses forever with
 * no user-visible failure. This gates both:
 *
 *   'send'    — no poll outstanding → send the next get_latest.
 *   'skip'    — a poll is outstanding and hasn't waited past the timeout → wait,
 *               don't stack another request.
 *   'timeout' — a poll has been outstanding longer than timeoutMs → surface it and
 *               re-poll (clear the stuck pending state).
 *
 * @param {object} p
 * @param {boolean} p.pending   a get_latest is outstanding (sent, no frame back yet)
 * @param {number}  p.waitedMs  ms since that outstanding poll was sent
 * @param {number}  p.timeoutMs how long to wait before declaring the poll stuck
 */
export function nextLivePollAction({ pending, waitedMs, timeoutMs }) {
  if (!pending) return 'send'
  if (waitedMs >= timeoutMs) return 'timeout'
  return 'skip'
}

/**
 * Map an MD-display readiness state to the toggle indicator's visual spec.
 *
 * `color` is a palette KEY (resolved to a hex by the panel), so this stays pure and
 * DOM/theme-free.  States:
 *   'warming' — the display socket is loading (parse PSF + build model) in the
 *               background; toggling now would wait for that load.
 *   'ready'   — the socket load finished (Universe + model parsed); toggling paints
 *               the latest frame near-instantly.
 *   'error'   — the last load/stream failed.
 *   anything else (incl. 'off'/undefined) — hidden (no job to warm / idle).
 */
export function mdReadinessIndicator(state) {
  switch (state) {
    case 'warming': return { show: true, color: 'warn', text: 'warming…' }
    case 'ready':   return { show: true, color: 'ok',   text: 'ready' }
    case 'error':   return { show: true, color: 'err',  text: 'error' }
    default:        return { show: false, color: 'dim', text: '' }
  }
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
