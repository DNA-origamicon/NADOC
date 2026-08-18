/**
 * API client — typed fetch wrappers for all CRUD endpoints.
 *
 * Every function that mutates the design updates the store with the returned
 * design, geometry, and validation report automatically.
 *
 * All functions return the parsed JSON response body (or null on error).
 * Errors are stored in store.lastError and are NOT thrown, so callers
 * don't need try/catch unless they need the error value directly.
 */

import { store } from '../state/store.js'
import { geometryQuerySuffix, isNewPositioningOn } from '../ui/new_positioning.js'
import { nadocBroadcast } from '../shared/broadcast.js'

// Signal that the active design's content changed: cross-TAB (BroadcastChannel) so
// other browser tabs re-fetch, AND in-PAGE (window event) so the oxDNA/MD job panels
// re-evaluate their out-of-date markers immediately — incl. a feature-log seek, which
// is how a stale job is brought back in sync (the panels' poll is paused off-tab).
function _signalDesignChanged() {
  nadocBroadcast.emit('design-changed')
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('nadoc:design-changed'))
}
import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'
import { notifyRequestFailure, notifyRequestSuccess, pokeProbe } from '../shared/connection_monitor.js'
import { docHeaders, docHeadersFor, docKey, docKeyFor } from '../shared/doc_id.js'
import { activeOperationTiming, beginOperationTiming, finishOperationAfterRender, markOperationTiming, whenOperationIdle } from '../perf/operation_timing.js'

const BASE = '/api'

// localStorage keys are scoped per document (docKey) so independent tabs don't
// overwrite each other's recovery cache.  The default doc keeps the bare legacy
// key, preserving Phase-1 single-document recovery unchanged.
const LS_DESIGN_KEY   = () => docKey('nadoc:design')
const LS_ASSEMBLY_KEY = () => docKey('nadoc:assembly')
const LS_MODE_KEY     = 'nadoc:mode'  // 'assembly' | 'part-edit:{id}' | null (sessionStorage, tab-isolated)

// ── Stale-response guard (rapid-edit race) ───────────────────────────────────
// Rapid fine-routing edits fire concurrent mutations. The backend serializes
// them and stamps each design response with a monotonic `revision`. Network/parse
// jitter can make an EARLIER response arrive after a later one; without this
// guard it would clobber the newer state (freshly-added nicks "disappearing" a
// moment later) and desync the panel's feature-log from the backend (the
// "index N out of range" revert error). We track the newest revision applied and
// drop any design response older than it. Monotonic per tab/document; a page
// reload resets it and the first response re-seeds it.
let _lastAppliedRevision = -1

/** True if this design response is older than the newest already applied (so the
 *  caller should DROP it). Updates the watermark when the response is accepted.
 *  Only consults responses that actually carry a design + numeric revision. */
function _isStaleDesignResponse(json) {
  const rev = json?.revision
  if (typeof rev !== 'number' || !json?.design) return false
  if (rev < _lastAppliedRevision) return true
  _lastAppliedRevision = rev
  return false
}

/** Reset the stale-response watermark. MUST be called when the backend restarts
 *  (its per-session revision resets low, so post-restart responses would
 *  otherwise be dropped as "stale"). Called from the restart-recovery handler. */
export function resetRevisionWatermark() {
  _lastAppliedRevision = -1
}

// ── Recovery-cache quota management ──────────────────────────────────────────
// The full design/assembly JSON is cached per-document for server-restart
// recovery. Each independently-opened tab mints a STICKY doc id (doc_id.js) that
// lives in sessionStorage — so when the tab closes, the id is gone but its
// localStorage snapshot (`nadoc:design:<id>` / `nadoc:assembly:<id>`) leaks. Over
// many sessions these orphans exhaust the ~5 MB quota and every setItem starts
// throwing (the user-visible "exceeded the quota" on opening a part). We don't
// track which other doc ids are still alive, so we only evict UNDER pressure:
// when our own write fails, drop every OTHER document's snapshots and retry once.
// A still-open sibling re-persists on its next edit, so the loss is best-effort.
const _SNAPSHOT_BASES = ['nadoc:design', 'nadoc:assembly']

/** Remove other documents' recovery snapshots (the large per-doc JSON). Returns
 *  the count removed. Keeps THIS tab's own keys (bare default-doc key or the
 *  ':<docId>'-suffixed one). */
export function evictOtherDocRecoverySnapshots() {
  // docKey('') is '' on the default doc, ':<id>' on an explicit doc — exactly the
  // suffix our own snapshot keys carry, so we keep keys whose suffix matches.
  const mySuffix = docKey('')
  const drop = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      for (const base of _SNAPSHOT_BASES) {
        if (key === base) break                       // bare default-doc snapshot
        if (key.startsWith(base + ':')) {
          const suffix = key.slice(base.length)       // ':<id>'
          if (suffix !== mySuffix) drop.push(key)     // a different document's leaked cache
          break
        }
      }
    }
    for (const k of drop) localStorage.removeItem(k)
  } catch { /* private mode / enumeration failure — best effort */ }
  return drop.length
}

/** setItem that, on quota failure, frees space by evicting other docs' snapshots
 *  and retries once. Always swallows the final failure (recovery cache is
 *  best-effort — never let it surface as an exception to the user). */
function _setItemWithEvict(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    if (evictOtherDocRecoverySnapshots() > 0) {
      try { localStorage.setItem(key, value) } catch { /* still full — give up silently */ }
    }
  }
}

/** Persist the current design topology to localStorage for session recovery. */
export function persistDesign() {
  const design = store.getState().currentDesign
  if (!design) return
  _setItemWithEvict(LS_DESIGN_KEY(), JSON.stringify(design))
}

/** Read the persisted design from localStorage (parsed JSON or null). */
export function getPersistedDesign() {
  try {
    const raw = localStorage.getItem(LS_DESIGN_KEY())
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** Remove the persisted design (e.g. when returning to the welcome screen). */
export function clearPersistedDesign() {
  try { localStorage.removeItem(LS_DESIGN_KEY()) } catch { /* ignore */ }
}

export function persistAssembly() {
  const assembly = store.getState().currentAssembly
  if (!assembly) return
  _setItemWithEvict(LS_ASSEMBLY_KEY(), JSON.stringify(assembly))
}

// docId reads ANOTHER doc's cache (e.g. a part-editor tab restoring the assembly
// from the assembly tab's recovery cache after a server restart); omitted → this
// tab's own cache.
export function getPersistedAssembly(docId) {
  try {
    const key = docId !== undefined ? docKeyFor('nadoc:assembly', docId) : LS_ASSEMBLY_KEY()
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function clearPersistedAssembly() {
  try { localStorage.removeItem(LS_ASSEMBLY_KEY()) } catch { /* ignore */ }
}

export function setPersistedMode(mode) {
  try {
    // sessionStorage is tab-isolated: each tab keeps its own mode without
    // clobbering sibling tabs (e.g. a part-edit tab must not overwrite
    // 'assembly' in the assembly tab — they share the same localStorage domain).
    // sessionStorage survives page refresh (F5) but is cleared when the tab closes.
    if (mode) sessionStorage.setItem(LS_MODE_KEY, mode)
    else      sessionStorage.removeItem(LS_MODE_KEY)
  } catch { /* ignore */ }
}

export function getPersistedMode() {
  try { return sessionStorage.getItem(LS_MODE_KEY) } catch { return null }
}

export async function checkAssemblyExists() {
  const json = await _request('GET', '/assembly/exists')
  return json?.exists === true
}

/** List pre-validated primitive building blocks for the "Add Primitive" panel.
 *  Non-critical: returns [] on any failure so the panel falls back to its static catalog. */
export async function listPrimitives() {
  try { return (await _request('GET', '/primitives')) ?? [] }
  catch { return [] }
}

/** Erase the active design on the server and clear all local persistence. */
export async function closeSession() {
  try { await fetch(`${BASE}/design`, { method: 'DELETE' }) } catch { /* ignore if unreachable */ }
  clearPersistedDesign()
}

// ── Recent files ─── (moved to recent_files.js)
export * from './recent_files.js'

/** Slow-call threshold for the perf log; calls under this are silent to keep
 *  the console useful. Set window.__nadocApiTraceAll = true to trace everything. */
const _API_PERF_THRESHOLD_MS = 1000

/** Delay before the "still working…" progress popup appears for a slow API
 *  call. Keeps fast calls (sub-5 s) from flashing the widget so the popup
 *  only appears for truly long ops (large autostaple runs, big bundle
 *  imports, full-design relax, etc.). */
const _BUSY_POPUP_DELAY_MS = 5000

/** Hard ceiling on any single request. Purely an anti-hang backstop for a wedged
 *  backend (so a request can't wait forever) — set well above the slowest real op
 *  (autostaple / big import / bounded MD analysis), since fast wedge DETECTION
 *  comes from pokeProbe(), not from this ceiling. */
const _REQUEST_TIMEOUT_MS = 240000

/** Once the popup actually appears, keep it visible for at least this many
 *  milliseconds even if the response arrives sooner. Avoids one-frame flashes
 *  for ops that finish just after the threshold. */
const _BUSY_POPUP_MIN_VISIBLE_MS = 400
let _diagnosticRequestSeq = 0

function _emitRequestDiagnostic(detail) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('nadoc:api-request', {
    detail: { ...detail, at: performance.now() },
  }))
}

/** Parse a Server-Timing header into a `step=ms` summary string.
 *  Format we emit on the backend: `step;dur=12.3, other_step;dur=4.5`. */
function _formatServerTiming(headerValue) {
  if (!headerValue) return null
  const parts = []
  for (const seg of headerValue.split(',')) {
    const m = seg.trim().match(/^([^;]+);.*?dur=([\d.]+)/)
    if (m) parts.push(`${m[1].trim()}=${Math.round(parseFloat(m[2]))}ms`)
  }
  return parts.length ? parts.join(' ') : null
}

/** Friendlier label for the progress popup based on the request path. Falls
 *  back to a generic "Working…" so unknown endpoints still show *something*
 *  rather than the raw URL. */
function _busyHeaderForPath(method, path) {
  if (path.startsWith('/design/features/seek'))                    return 'Seeking Feature Log'
  if (path.endsWith('/roll-design'))                               return 'Rolling design to job state'
  if (path.startsWith('/design/features/') && path.endsWith('/edit'))   return 'Editing Feature'
  if (path.startsWith('/design/features/') && path.endsWith('/revert')) return 'Reverting Feature'
  if (path.startsWith('/design/features/') && method === 'DELETE')      return 'Deleting Feature'
  if (path === '/design/undo')                                     return 'Undo'
  if (path === '/design/redo')                                     return 'Redo'
  if (path.startsWith('/design/overhang-connections/') && path.endsWith('/relax')) return 'Relaxing Linker'
  if (path.startsWith('/design/cluster/') && method === 'PATCH')   return 'Applying Transform'
  if (path === '/design/auto-scaffold-matched')                    return 'Auto Scaffold (Matched Ends)'
  if (path.startsWith('/design/auto-staple'))                      return 'Auto Staple'
  if (path === '/design/auto-break')                               return 'Auto Break'
  if (path === '/design/full-autostaple')                           return 'Full Autostaple'
  if (path.startsWith('/design/auto-crossover'))                   return 'Auto Crossover'
  if (path.startsWith('/design/bundle'))                           return 'Building Bundle'
  if (path.startsWith('/design/extrude'))                          return 'Extruding'
  if (path.startsWith('/design/load') || path.startsWith('/design/import')) return 'Loading Design'
  if (path.startsWith('/design/geometry'))                       return 'Loading Design Geometry'
  return 'Working…'
}

/** How many validation entries a flattened 422 message spells out before summarising. */
const ERROR_DETAIL_MAX_ITEMS = 3

/**
 * Readable message from a FastAPI error body's `detail`.
 *
 * A hand-raised HTTPException (400/404/409) sends `detail` as a plain string and
 * needs no help. A 422 — pydantic rejecting the REQUEST BODY before the handler
 * runs — sends an ARRAY of `{loc, msg, type, input}` objects instead, and handing
 * that array to `new Error(...)` or a template literal stringifies it to the
 * useless "[object Object]". That is what the MD panel showed for every request
 * that tripped a `Field(ge=…, le=…)` bound, e.g. a production run longer than the
 * step cap: the real reason ("steps: Input should be less than or equal to …")
 * was in the response the whole time and simply never reached the toast.
 *
 * @param {unknown} detail
 * @param {string} fallback used when `detail` is absent or carries no message
 * @returns {string}
 */
export function errorDetailToMessage(detail, fallback = 'Server error') {
  if (typeof detail === 'string') return detail || fallback
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === 'string') return d
      // Drop the leading 'body'/'query' frame — it names the request part, not a field.
      const loc = Array.isArray(d?.loc)
        ? d.loc.filter(p => p !== 'body' && p !== 'query').join('.')
        : ''
      const msg = d?.msg || d?.type || ''
      if (loc && msg) return `${loc}: ${msg}`
      return msg || loc
    }).filter(Boolean)
    if (parts.length) {
      // Cap it: a body that fails ten constraints would otherwise render an
      // unreadable toast, and the first few are enough to act on.
      const shown = parts.slice(0, ERROR_DETAIL_MAX_ITEMS).join('; ')
      const extra = parts.length - ERROR_DETAIL_MAX_ITEMS
      return extra > 0 ? `${shown}; and ${extra} more validation error${extra > 1 ? 's' : ''}` : shown
    }
  }
  // Arrays are handled above; one that yielded no readable part (empty, or all
  // entries blank) must reach the fallback rather than serialise to a bare "[]".
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    if (typeof detail.msg === 'string' && detail.msg) return detail.msg
    try {
      const s = JSON.stringify(detail)
      if (s && s !== '{}') return s
    } catch { /* circular / non-serialisable → fall through to the fallback */ }
  }
  return fallback
}

export async function _request(method, path, body, { signal, suppressBusy = false, docId, timeoutMs = _REQUEST_TIMEOUT_MS, protectedRetry = true } = {}) {
  const diagnosticId = ++_diagnosticRequestSeq
  _emitRequestDiagnostic({ phase: 'start', id: diagnosticId, method, path, suppressBusy })
  const isTimedOperation = method !== 'GET' && (
    path === '/design/load' || path === '/design/import' ||
    path === '/design/bundle' || path === '/design/bundle-segment' ||
    path === '/design/bundle-continuation' || path === '/design/bundle-deformed-continuation' ||
    path === '/design/overhang/extrude' || /\/assembly\/instances\/[^/]+\/overhang\/extrude$/.test(path)
  )
  // An optimistic UI may start the trace immediately before calling the API so
  // click→preview and preview→confirmation live in one measurement. Reuse that
  // trace instead of replacing it at fetch time.
  const activeTrace = activeOperationTiming()
  const operationTrace = isTimedOperation
    ? activeTrace?.details?.optimisticPreview
      ? activeTrace
      : beginOperationTiming(`${method} ${path}`, { body })
    : null
  // Hard timeout so a wedged-but-listening backend (event loop stuck) can't make a
  // request hang forever — without it the welcome screen waited indefinitely and
  // looked dead. On timeout the catch below flags the connection down. Generous by
  // default so it never aborts a legitimately long op; the fast "is the server
  // actually wedged?" signal comes from pokeProbe() below, not from this ceiling.
  const _timeoutCtrl = new AbortController()
  const _timeoutTimer = setTimeout(
    () => _timeoutCtrl.abort(new DOMException('Request timed out', 'TimeoutError')), timeoutMs)
  if (signal) {
    if (signal.aborted) _timeoutCtrl.abort(signal.reason)
    else signal.addEventListener('abort', () => _timeoutCtrl.abort(signal.reason), { once: true })
  }
  const opts = {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      // Mutation responses embed replacement display geometry. Keep its projection
      // identical to GET /geometry so Apply cannot transiently re-register every
      // bead and slab until the next reload.
      'X-NADOC-Measured-Positioning': String(isNewPositioningOn()),
      // X-NADOC-Doc: route to this tab's backend document, OR to an explicitly
      // named doc (docId) for one-off cross-document calls (e.g. a part editor
      // reaching into the assembly's doc). `undefined` keeps the legacy default.
      ...(docId !== undefined ? docHeadersFor(docId) : docHeaders()),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: _timeoutCtrl.signal,
  }
  // Show a centred indeterminate progress popup if the call hasn't returned
  // within _BUSY_POPUP_DELAY_MS. Fast calls clear the timer before it fires
  // and the user never sees the popup. Slow calls (linker seek, autostaple,
  // big imports) get a "still working" indicator so they don't look frozen.
  let _busyShown = false
  let _busyShownAt = 0
  const _busyTimer = suppressBusy ? null : setTimeout(() => {
    _busyShown = true
    _busyShownAt = performance.now()
    showOpProgress(_busyHeaderForPath(method, path), '')
    _emitRequestDiagnostic({ phase: 'busy-show', id: diagnosticId, method, path })
    // A slow request might mean the backend is wedged, not just busy — probe
    // /health now (short timeout, off the event loop) so a true hang surfaces as
    // "reconnecting…" in seconds instead of waiting out the request ceiling.
    pokeProbe()
  }, _BUSY_POPUP_DELAY_MS)
  const t0 = performance.now()
  let r, json, tNetwork = 0
  try {
    r = await fetch(`${BASE}${path}`, opts)
    tNetwork = performance.now() - t0
    markOperationTiming('response-received', {
      serverTiming: r.headers?.get?.('Server-Timing') ?? null, status: r.status,
    }, operationTrace)
    notifyRequestSuccess()   // any HTTP response means the backend is reachable
    json = await r.json().catch(() => null)
    markOperationTiming('response-parsed', undefined, operationTrace)
  } catch (err) {
    _emitRequestDiagnostic({
      phase: 'error', id: diagnosticId, method, path,
      durationMs: performance.now() - t0, message: err?.message ?? String(err),
    })
    markOperationTiming('operation-failed', { message: err?.message ?? String(err) }, operationTrace)
    finishOperationAfterRender(operationTrace)
    notifyRequestFailure()   // network-level failure → flag the connection as down
    throw err
  } finally {
    clearTimeout(_busyTimer)
    clearTimeout(_timeoutTimer)
    if (_busyShown) {
      // Keep the popup up for a minimum visible time so it doesn't flash for
      // calls that finish just a hair past the trigger threshold. Most ops
      // that hit the popup are well above this floor (multi-second seeks),
      // so the floor doesn't add perceived latency.
      const visibleFor = performance.now() - _busyShownAt
      const wait = Math.max(0, _BUSY_POPUP_MIN_VISIBLE_MS - visibleFor)
      const hide = () => {
        hideOpProgress()
        _emitRequestDiagnostic({ phase: 'busy-hide', id: diagnosticId, method, path })
      }
      if (wait > 0) setTimeout(hide, wait)
      else hide()
    }
  }
  const tTotal = performance.now() - t0
  _emitRequestDiagnostic({
    phase: 'complete', id: diagnosticId, method, path,
    durationMs: tTotal, networkMs: tNetwork, status: r?.status ?? null,
  })
  // Cheap perf trace: log slow calls (and all calls when explicitly enabled),
  // including any Server-Timing breakdown the backend attached. Threshold keeps
  // the console quiet for fast calls; raise window.__nadocApiTraceAll = true
  // to trace every request. Uses console.log (not console.debug) so it shows
  // up under DevTools' default level filter.
  if (tTotal >= _API_PERF_THRESHOLD_MS || globalThis.__nadocApiTraceAll) {
    const serverTiming = _formatServerTiming(r.headers.get('Server-Timing'))
    const tag = `[API ${Math.round(tTotal)}ms] ${method} ${path}`
    if (serverTiming) {
      console.log(`${tag} (server: ${serverTiming}, parse: ${Math.round(tTotal - tNetwork)}ms)`)
    } else {
      console.log(`${tag} (parse: ${Math.round(tTotal - tNetwork)}ms)`)
    }
  }
  if (!r.ok) {
    if (r.status === 409 && json?.detail?.code === 'protected_simulation_loadout' && protectedRetry) {
      // Protected simulation branches are immutable. Restore the most recently
      // used editable branch and replay the user's original action there.
      const activated = await _request(
        'POST', '/design/loadouts/activate-editable', undefined,
        { suppressBusy: true, docId, protectedRetry: false })
      if (activated) {
        return _request(method, path, body, {
          signal, suppressBusy, docId, timeoutMs, protectedRetry: false,
        })
      }
    }
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    markOperationTiming('operation-rejected', { status: r.status }, operationTrace)
    finishOperationAfterRender(operationTrace)
    return null
  }
  store.setState({ lastError: null })
  return json
}

/** Sync the store with a mutation response (design + validation + optional geometry).
 *
 * `opts.skipGeometry` (default false) — when true, this function updates only
 * design / validation / metadata (loop strand IDs, unligated crossover IDs,
 * strand colors) and does NOT refetch or update currentGeometry /
 * currentHelixAxes. Used by Plan B's cluster-transform commit path: the
 * gizmo's live-drag has already painted correct positions into the renderer's
 * instance buffers, so the backend geometry refetch is wasted work AND
 * triggers a full rebuild that visually snaps things back to stale geometry.
 * Caller is responsible for invoking helixCtrl.commitClusterPositions() to
 * keep currentGeometry consistent with what's rendered.
 */
// True only while applying a TRANSIENT design mutation — a bend/twist preview,
// live param PATCH, or cancel-revert (the `?preview=true` / PATCH endpoints).
// The design auto-save subscriber reads this synchronously during setState and
// skips: transient changes must NOT propagate to disk (→ SSE) or to the assembly
// (→ part-design-updated). Committed changes (Apply) leave it false → they save.
// Always reset to false by the end of the call, so non-transient paths (undo /
// diff syncs that don't route through here) read the residual false and save.
let _designSyncTransient = false
export function wasLastDesignSyncTransient() { return _designSyncTransient }

/** Restore history bodies omitted from a slim mutation response.
 *
 * Existing entries are immutable history, so their payloads can be reused from
 * the current store by id. The backend retains the new entry in full. This must
 * run before currentDesign is stored/persisted so restart recovery remains
 * complete even though the wire response omitted accumulated old blobs.
 */
export function _mergeFeatureLogPayloads(incoming, previous) {
  if (!incoming?.feature_log || !previous?.feature_log) return incoming
  const prevById = new Map(previous.feature_log.map(e => [e.id, e]))
  const bodyKeys = ['design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64']
  for (const entry of incoming.feature_log) {
    const prev = prevById.get(entry.id)
    if (!prev) continue
    for (const key of bodyKeys) {
      if (!entry[key] && prev[key]) entry[key] = prev[key]
    }
    if (!Array.isArray(entry.children) || !Array.isArray(prev.children)) continue
    const prevChildren = new Map(prev.children.map((c, i) => [c.id ?? i, c]))
    for (let i = 0; i < entry.children.length; i++) {
      const child = entry.children[i]
      const old = prevChildren.get(child.id ?? i)
      if (!old) continue
      for (const key of ['diff_added_b64', 'diff_removed_b64', 'diff_modified_b64']) {
        if (child[key] === '1' && old[key]) child[key] = old[key]
      }
    }
  }
  return incoming
}

export async function _syncFromDesignResponse(json, { skipGeometry = false, transient = false } = {}) {
  if (!json) return null
  if (_isStaleDesignResponse(json)) return json   // superseded by a newer response → skip (rapid-edit race)
  if (json.feature_log_payloads_partial && json.design) {
    json.design = _mergeFeatureLogPayloads(json.design, store.getState().currentDesign)
  }
  _designSyncTransient = transient
  const updates = {}
  if (json.design)     updates.currentDesign     = json.design
  if (json.validation) {
    updates.validationReport = json.validation
    updates.loopStrandIds    = json.validation.loop_strand_ids ?? []
  }
  // unligated_crossover_ids is emitted on every design-bearing response by
  // _design_response (backend chokepoint). The frontend treats it as the
  // canonical set of crossovers to mark with a ⚠ overlay. Always overwrite
  // — recompute every response so the marker auto-clears when topology
  // changes (e.g. user nicks the strand to break the cycle).
  if (Array.isArray(json.unligated_crossover_ids)) {
    updates.unligatedCrossoverIds = new Set(json.unligated_crossover_ids)
  }
  if (Array.isArray(json.placement_warnings) && json.placement_warnings.length) {
    // Surface as a one-shot toast. The warnings live as visual markers on
    // the affected crossovers regardless, so this toast is just a heads-up.
    showToast(json.placement_warnings.join('  •  '), 6000)
  }
  // Sync strandColors with strand.color from the design — respects both
  // color assignments and null resets (palette fallback).
  if (json.design?.strands) {
    const existing = store.getState().strandColors ?? {}
    const fromDesign = {}
    const removals = []
    for (const strand of json.design.strands) {
      if (strand.color) {
        fromDesign[strand.id] = parseInt(strand.color.replace('#', ''), 16)
      } else if (strand.id in existing) {
        removals.push(strand.id)
      }
    }
    if (Object.keys(fromDesign).length > 0 || removals.length > 0) {
      const merged = { ...existing, ...fromDesign }
      for (const id of removals) delete merged[id]
      updates.strandColors = merged
    }
  }
  if (skipGeometry) {
    // Plan B caller (cluster-transform commit) — apply ONLY design +
    // validationReport. Skip loopStrandIds / unligatedCrossoverIds /
    // strandColors even when the response carries them: those slots get
    // a fresh array/Set reference on every PATCH (validation re-runs each
    // call), and any reference change trips design_renderer's
    // `loopChanged` guard (or sibling guards), which bypasses the
    // visual-only-design-change early-return and forces a full _rebuild
    // against stale currentGeometry — exactly the visual snap-back we're
    // trying to avoid. Cluster transforms never affect strand topology,
    // so these slots' contents can't have actually changed.
    const minimalUpdates = {}
    if (json.design)     minimalUpdates.currentDesign     = json.design
    if (json.validation) minimalUpdates.validationReport  = json.validation
    store.setState(minimalUpdates)
    if (json.design) _signalDesignChanged()
    if (json.design) persistDesign()
    _designSyncTransient = false
    return json
  }
  // Backend may ship deformed geometry in COMPACT per-helix-per-direction
  // parallel-arrays form (`nucleotides_compact`) instead of the legacy
  // per-nuc `nucleotides` list. ~50% smaller on the wire and ~50% faster
  // to parse on big designs. Re-materialise into the flat nuc list the
  // renderer expects so downstream code paths don't change.
  if (!json.nucleotides && json.nucleotides_compact) {
    const flat = []
    const compact = json.nucleotides_compact
    for (const helixId of Object.keys(compact)) {
      const byDir = compact[helixId]
      for (const dir of Object.keys(byDir)) {
        const b = byDir[dir]
        if (!b || !Array.isArray(b.bp)) continue
        const M = b.bp.length
        for (let i = 0; i < M; i++) {
          flat.push({
            helix_id:          helixId,
            bp_index:          b.bp[i],
            direction:         dir,
            backbone_position: b.bb[i],
            base_position:     b.bs[i],
            base_normal:       b.bn[i],
            axis_tangent:      b.at[i],
            strand_id:         b.sid?.[i] ?? null,
            strand_type:       b.stype?.[i] ?? null,
            is_five_prime:     !!b.is5?.[i],
            is_three_prime:    !!b.is3?.[i],
            domain_index:      b.did?.[i] ?? 0,
            overhang_id:       b.ohid?.[i] ?? null,
            extension_id:      b.extid?.[i] ?? null,
            is_modification:   !!b.ismod?.[i],
            modification:      b.mod?.[i] ?? null,
            nucleobase:        b.base?.[i] ?? null,
          })
        }
      }
    }
    json.nucleotides = flat
  }
  if (json.nucleotides) {
    // Geometry is embedded in the response — apply design + geometry in one
    // atomic setState so the renderer subscriber fires only once (one rebuild).
    const helixAxesMap = {}
    for (const ax of json.helix_axes ?? []) {
      helixAxesMap[ax.helix_id] = { start: ax.start, end: ax.end, samples: ax.samples ?? null, ovhgAxes: ax.ovhg_axes ?? null, segments: ax.segments ?? null }
    }
    if (json.partial_geometry && json.changed_helix_ids?.length) {
      // ── Fix B merge path ──────────────────────────────────────────────────
      // Server returned only the helices listed in changed_helix_ids.
      // Replace just those helices in the existing geometry array rather than
      // discarding and rebuilding the whole thing.
      const changedSet = new Set(json.changed_helix_ids)
      const existing   = store.getState().currentGeometry ?? []
      updates.currentGeometry = [
        ...existing.filter(n => !changedSet.has(n.helix_id)),
        ...json.nucleotides,
      ]
      if (Object.keys(helixAxesMap).length) {
        const retainedAxes = { ...(store.getState().currentHelixAxes ?? {}) }
        for (const id of changedSet) delete retainedAxes[id]
        updates.currentHelixAxes = { ...retainedAxes, ...helixAxesMap }
      }
      // Signal design_renderer to try the in-place fast path (Fix B part 2).
      updates.lastPartialChangedHelixIds = json.changed_helix_ids
    } else {
      // ── Full replacement (current default) ────────────────────────────────
      updates.currentGeometry             = json.nucleotides
      updates.currentHelixAxes            = Object.keys(helixAxesMap).length ? helixAxesMap : null
      updates.lastPartialChangedHelixIds  = null
    }
    // Backend may also embed straight (un-deformed) geometry alongside the
    // deformed payload (`embed_straight=True` in _design_response_with_geometry).
    // When present, set straightGeometry / straightHelixAxes in the SAME setState
    // batch so deform_view's currentGeometry subscriber sees the fresh straight
    // values atomically and skips its 5+ second `apply_deformations=false`
    // refetch on topology-changing seek/undo/redo/delete-feature.
    //
    // Backend ships straight geometry in COMPACT positions_by_helix form
    // (parallel float arrays per helix per direction). Re-materialise a thin
    // flat nuc-list here so the existing deform_view / unfold_view consumers
    // (which iterate `for (const nuc of straightGeometry)`) keep working
    // unchanged. Each materialised nuc carries only the fields those
    // consumers actually read — backbone_position / base_normal / helix_id /
    // bp_index / direction — same memory footprint as before, but the wire
    // payload is ~3× smaller and parses ~3× faster.
    if (json.straight_positions_by_helix) {
      const straightGeo = []
      const pbh = json.straight_positions_by_helix
      for (const helixId of Object.keys(pbh)) {
        const byDir = pbh[helixId]
        for (const dir of Object.keys(byDir)) {
          const data = byDir[dir]
          if (!data || !Array.isArray(data.bp)) continue
          for (let i = 0; i < data.bp.length; i++) {
            straightGeo.push({
              helix_id:          helixId,
              bp_index:          data.bp[i],
              direction:         dir,
              backbone_position: data.bb[i],
              base_normal:       data.bn?.[i],
            })
          }
        }
      }
      updates.straightGeometry = straightGeo
      const straightAxesMap = {}
      for (const ax of json.straight_helix_axes ?? []) {
        straightAxesMap[ax.helix_id] = {
          start: ax.start, end: ax.end,
          samples:  ax.samples  ?? null,
          ovhgAxes: ax.ovhg_axes ?? null,
          segments: ax.segments ?? null,
        }
      }
      updates.straightHelixAxes = Object.keys(straightAxesMap).length ? straightAxesMap : null
    }
    store.setState(updates)
    markOperationTiming('store-applied')
  } else {
    store.setState(updates)
    markOperationTiming('design-applied')
    if (json.design) {
      const h0 = json.design.helices?.[0]
      console.debug('[NADOC import] design set: first helix axis_start =',
        h0 ? `(${h0.axis_start?.x?.toFixed(3)}, ${h0.axis_start?.y?.toFixed(3)})` : 'none',
        '| debug =', json.debug ?? 'none')
    }
    // Re-fetch full geometry whenever the design changes (getGeometry stores it directly).
    if (json.design) {
      markOperationTiming('geometry-fetch-start')
      await getGeometry()
      markOperationTiming('geometry-fetched')
      const axes0 = Object.values(store.getState().currentHelixAxes ?? {})[0]
      console.debug('[NADOC import] geometry applied: first helix_axes start =',
        axes0 ? `(${axes0.start[0]?.toFixed(3)}, ${axes0.start[1]?.toFixed(3)})` : 'none')
    }
  }
  // Notify other tabs (cadnano editor, second 3D windows) that the design changed.
  if (json.design) _signalDesignChanged()
  // Persist design to localStorage for session recovery on refresh/restart.
  if (json.design) persistDesign()
  if (json.design) _clearStaleSelections()
  _designSyncTransient = false
  return json
}

// ── Wire-format v2 → v1 expansion (Phase 5 migrate-readers, path-to-thousands) ─

/**
 * Default values for PartInstance fields that to_compact_dict omits when they
 * match. Mirrors backend/core/models.py::PartInstance. Kept in sync manually —
 * if PartInstance defaults change, update both sides.
 */
const _PART_INSTANCE_DEFAULTS = Object.freeze({
  name:                        'Part',
  mode:                        'flexible',
  visible:                     true,
  representation:              'full',
  fixed:                       false,
  allow_part_joints:           false,
  base_transform:              null,
  joint_states:                {},
  cluster_transform_overrides: [],
  interface_points:            [],
})

/**
 * Reconstruct a 16-element row-major Mat4x4 ``{values: [...]}`` from the
 * compact 12-float top-3-rows packing. The implicit bottom row is
 * ``[0, 0, 0, 1]``. Throws on malformed input.
 */
function _expandT12(t12) {
  if (!Array.isArray(t12) || t12.length !== 12) {
    throw new Error(`t12 must be a 12-element array, got ${t12?.length ?? typeof t12}`)
  }
  return {
    values: [
      +t12[0], +t12[1], +t12[2],  +t12[3],
      +t12[4], +t12[5], +t12[6],  +t12[7],
      +t12[8], +t12[9], +t12[10], +t12[11],
      0, 0, 0, 1,
    ],
  }
}

/**
 * Expand one ``instances_v2`` entry into a full v1-shaped PartInstance dict.
 * Returns null (and logs a warning) when ``src_key`` can't be resolved.
 */
function _expandV2Instance(entry, sources) {
  let source = null
  if (entry.source) {
    source = entry.source
  } else if (entry.src_key != null) {
    source = sources?.[entry.src_key]
    if (!source) {
      console.warn(
        `[assembly v2] instance ${entry.id}: src_key ${JSON.stringify(entry.src_key)} not in sources map; skipping`,
      )
      return null
    }
  } else {
    console.warn(`[assembly v2] instance ${entry.id}: no source or src_key; skipping`)
    return null
  }

  const out = {
    id:        entry.id,
    source,
    transform: _expandT12(entry.t12),
    ..._PART_INSTANCE_DEFAULTS,
  }
  // Override defaults with any explicitly-present fields from the compact entry.
  for (const k of Object.keys(_PART_INSTANCE_DEFAULTS)) {
    if (k in entry) out[k] = entry[k]
  }
  return out
}

/**
 * Expand the v2 wire format (``format_version: 2`` + ``instances_v2`` +
 * ``sources``) into a v1-shaped assembly dict the rest of the frontend
 * already understands. Returns the input unchanged when v2 fields are
 * absent (legacy payload) — old ``.nass`` files keep working.
 *
 * Strips the v2-only fields after expansion so the store holds a single
 * canonical shape (the v1 shape).
 */
export function _expandV2Assembly(assembly) {
  if (!assembly || typeof assembly !== 'object') return assembly
  const isV2 = (
    assembly.format_version === 2 &&
    Array.isArray(assembly.instances_v2) &&
    assembly.sources && typeof assembly.sources === 'object'
  )
  if (!isV2) return assembly  // v1-only payload — passthrough

  const expanded = []
  for (const entry of assembly.instances_v2) {
    const inst = _expandV2Instance(entry, assembly.sources)
    if (inst) expanded.push(inst)
  }

  // Build a new assembly object with the v1-shaped instances and v2 fields stripped.
  // Spread first so the rest of the assembly (joints, configs, etc.) carries through.
  const { format_version, sources, instances_v2, ...rest } = assembly
  return { ...rest, instances: expanded }
}

/** Sync the store with an assembly mutation response. */
export function _syncFromAssemblyResponse(json) {
  if (!json) return null
  if (json.assembly) {
    store.setState({ currentAssembly: _expandV2Assembly(json.assembly) })
    persistAssembly()
  }
  return json
}

// ── Design ────────────────────────────────────────────────────────────────────

export async function getDesign() {
  const json = await _request('GET', '/design')
  if (!json) return null
  const updates = {
    currentDesign:    json.design,
    validationReport: json.validation,
    loopStrandIds:    json.validation?.loop_strand_ids ?? [],
  }
  // Sync unligated crossover marker set from every design fetch — including
  // passive refetches triggered by cross-tab broadcasts. Without this the
  // 3D view would keep stale ⚠ markers after the cadnano editor (or another
  // tab) mutates the design in a way that resolves a previously-cyclic
  // crossover (e.g. autobreak after autocrossover).
  if (Array.isArray(json.unligated_crossover_ids)) {
    updates.unligatedCrossoverIds = new Set(json.unligated_crossover_ids)
  }
  // Sync strandColors with strand.color from the design — respects both
  // color assignments and null resets (palette fallback).
  if (json.design?.strands) {
    const existing = store.getState().strandColors ?? {}
    const fromDesign = {}
    const removals = []
    for (const strand of json.design.strands) {
      if (strand.color) {
        fromDesign[strand.id] = parseInt(strand.color.replace('#', ''), 16)
      } else if (strand.id in existing) {
        removals.push(strand.id)
      }
    }
    if (Object.keys(fromDesign).length > 0 || removals.length > 0) {
      const merged = { ...existing, ...fromDesign }
      for (const id of removals) delete merged[id]
      updates.strandColors = merged
    }
  }
  store.setState(updates)
  _clearStaleSelections()
  persistDesign()
  return json
}

/**
 * Revert to the previous design state (server-side undo stack, up to 50 steps).
 * Returns null if nothing to undo (404 from server).
 */
export async function undo() {
  const json = await _request('POST', '/design/undo')
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

/**
 * Re-apply the last undone mutation (server-side redo stack, up to 50 steps).
 * Returns null if nothing to redo (404 from server).
 */
export async function redo() {
  const json = await _request('POST', '/design/redo')
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

/**
 * Replace the design's 96-well plate / tube layout (IDT ordering convenience).
 * Display-only metadata persisted in the .nadoc file; does not change geometry.
 * `layout` = { orientation, plate_count, wells:[{strand_id,plate,row,col}], tubes:[{strand_id,reason}] }
 */
export async function savePlateLayout(layout) {
  const json = await _request('PUT', '/design/plate-layout', layout)
  return _syncFromDesignResponse(json)
}

/**
 * Replace the design's per-region representation overrides. Each override pins a
 * render rep ('full' | 'cylinders') onto a selection of strands and/or clusters,
 * so a focal region can show full detail against a coarser background.
 * Display-only metadata persisted in the .nadoc file; does not change geometry.
 * `overrides` = [{ id?, name, representation, strand_ids:[...], cluster_ids:[...] }]
 */
export async function saveRepresentationOverrides(overrides) {
  const json = await _request('PUT', '/design/representation-overrides', { overrides })
  return _syncFromDesignResponse(json)
}

/** Clear all per-region representation overrides. */
export async function clearRepresentationOverrides() {
  const json = await _request('DELETE', '/design/representation-overrides')
  return _syncFromDesignResponse(json)
}

/** Persist display-only nucleotide/cluster visibility in the .nadoc file. */
export async function saveVisibilityState(visibilityState) {
  const json = await _request('PUT', '/design/visibility', visibilityState)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/** Optional handler invoked after store sync for cluster_only / positions_only
 * responses. Set by main.js at init to push the diff through the renderer
 * (helixCtrl + bluntEnds + joint/overhang renderers). Centralising this here
 * means every endpoint that returns a diff_kind response (undo, redo,
 * seek, delete-feature, edit-feature, relaxLinker, …) gets the in-place
 * renderer update without each having its own main.js wrapper.
 *
 * The skipNextResponseDelta flag lets specific call sites opt out of the
 * delta application — used by the cluster_op edit-in-place flow, where the
 * gizmo's live drag has already moved the visual to the post-edit state and
 * applying the (old → new) cluster delta on top would double-move it. */
let _responseDeltaHandler = null
let _skipNextDelta = false
export function registerResponseDeltaHandler(fn) {
  _responseDeltaHandler = fn
}
export function skipNextResponseDelta() {
  _skipNextDelta = true
}

/** Fast-path sync for a response whose only delta is cluster transforms.
 * Mirrors the cluster-commit Plan B path: minimal store update, skip the
 * full design_renderer rebuild. Calls the registered handler so the
 * renderer's bead/slab/cone/axis matrices catch up with the new cluster
 * state in-place. */
async function _syncClusterOnlyDiff(json) {
  if (_isStaleDesignResponse(json)) return json   // superseded by a newer response → skip (rapid-edit race)
  const updates = {}
  if (json.design)     updates.currentDesign     = json.design
  if (json.validation) updates.validationReport  = json.validation
  store.setState(updates)
  if (Array.isArray(json.placement_warnings) && json.placement_warnings.length) {
    showToast(json.placement_warnings.join('  •  '), 6000)
  }
  if (json.design) {
    _signalDesignChanged()
    persistDesign()
  }
  if (_responseDeltaHandler && !_skipNextDelta) await _responseDeltaHandler(json)
  _skipNextDelta = false
  return json
}

/** Fast-path sync for a response with diff_kind='positions_only': topology is
 *  unchanged but positions need updating (e.g. cluster_transform pivot change,
 *  or a deformation seek where structural fields all match). Mutates the
 *  existing currentGeometry array AND currentHelixAxes object IN PLACE so
 *  references don't change — design_renderer's visual-only-design-change
 *  check stays satisfied and skips the full scene rebuild, and deform_view's
 *  topology-skip keeps the cached straightGeometry. The caller is expected
 *  to call helix_renderer.applyPositionsUpdate(positions_by_helix, helix_axes)
 *  to push the new positions into the rendered meshes. */
async function _syncPositionsOnlyDiff(json) {
  if (_isStaleDesignResponse(json)) return json   // superseded by a newer response → skip (rapid-edit race)
  const state = store.getState()
  const positionsByHelix = json.positions_by_helix
  const helixAxesArr     = json.helix_axes

  // 1. Mutate currentGeometry's nuc records in place. The renderer's
  //    backboneEntries entries hold direct references to these objects, so
  //    later applyPositionsUpdate() will see the fresh values.
  if (Array.isArray(state.currentGeometry) && positionsByHelix) {
    // Build a fast lookup keyed by "helix:bp:dir".
    const lookup = new Map()
    for (const helixId of Object.keys(positionsByHelix)) {
      const byDir = positionsByHelix[helixId]
      for (const dir of Object.keys(byDir)) {
        const data = byDir[dir]
        if (!data) continue
        for (let i = 0; i < data.bp.length; i++) {
          lookup.set(`${helixId}:${data.bp[i]}:${dir}`, {
            bb: data.bb?.[i], bs: data.bs?.[i], bn: data.bn?.[i], at: data.at?.[i],
          })
        }
      }
    }
    for (const nuc of state.currentGeometry) {
      const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      const u = lookup.get(key)
      if (!u) continue
      if (u.bb && nuc.backbone_position) {
        nuc.backbone_position[0] = u.bb[0]; nuc.backbone_position[1] = u.bb[1]; nuc.backbone_position[2] = u.bb[2]
      }
      if (u.bs && nuc.base_position) {
        nuc.base_position[0]    = u.bs[0]; nuc.base_position[1]    = u.bs[1]; nuc.base_position[2]    = u.bs[2]
      }
      if (u.bn && nuc.base_normal) {
        nuc.base_normal[0]      = u.bn[0]; nuc.base_normal[1]      = u.bn[1]; nuc.base_normal[2]      = u.bn[2]
      }
      if (u.at && nuc.axis_tangent) {
        nuc.axis_tangent[0]     = u.at[0]; nuc.axis_tangent[1]     = u.at[1]; nuc.axis_tangent[2]     = u.at[2]
      }
    }
  }

  // 2. Mutate currentHelixAxes object's per-helix entries in place. The
  //    outer object reference stays the same, so the renderer subscriber
  //    that watches `currentHelixAxes !== prevState.currentHelixAxes` sees
  //    no change and skips the rebuild.
  if (state.currentHelixAxes && Array.isArray(helixAxesArr)) {
    for (const ax of helixAxesArr) {
      const existing = state.currentHelixAxes[ax.helix_id]
      if (existing) {
        existing.start    = ax.start
        existing.end      = ax.end
        existing.samples  = ax.samples ?? existing.samples ?? null
        existing.ovhgAxes = ax.ovhg_axes ?? existing.ovhgAxes ?? null
        existing.segments = ax.segments ?? existing.segments ?? null
      } else {
        // New helix in axes (shouldn't happen if topology unchanged, but be safe).
        state.currentHelixAxes[ax.helix_id] = {
          start: ax.start, end: ax.end,
          samples:  ax.samples  ?? null,
          ovhgAxes: ax.ovhg_axes ?? null,
          segments: ax.segments ?? null,
        }
      }
    }
  }

  // 3. Update design + validation. design_renderer's visual-only-design-change
  //    check returns early when topology counts match — which they do, since
  //    `_topology_unchanged` (backend) is the precondition for diff_kind here.
  const updates = {}
  if (json.design)     updates.currentDesign     = json.design
  if (json.validation) updates.validationReport  = json.validation
  store.setState(updates)
  if (Array.isArray(json.placement_warnings) && json.placement_warnings.length) {
    showToast(json.placement_warnings.join('  •  '), 6000)
  }
  if (json.design) {
    _signalDesignChanged()
    persistDesign()
  }
  if (_responseDeltaHandler && !_skipNextDelta) await _responseDeltaHandler(json)
  _skipNextDelta = false
  return json
}

/**
 * Trigger a browser download of the active design as a .nadoc file.
 * Uses the GET /design/export endpoint which returns JSON with Content-Disposition.
 */
export async function exportDesign() {
  const r = await fetch(`${BASE}/design/export`)
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  // Extract filename from Content-Disposition header, fall back to 'design.nadoc'
  const disposition = r.headers.get('Content-Disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : 'design.nadoc'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return true
}

export async function createBundle({ cells, lengthBp, name = 'Bundle', plane = 'XY', strandFilter = 'both', latticeType = 'HONEYCOMB', ligateAdjacent = true }) {
  const json = await _request('POST', '/design/bundle', {
    cells,
    length_bp: lengthBp,
    name,
    plane,
    strand_filter: strandFilter,
    lattice_type: latticeType,
    ligate_adjacent: ligateAdjacent,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Append a bundle segment to the active design (slice-plane extrude).
 * lengthBp may be negative to extrude in the -axis direction.
 */
export async function addBundleSegment({ cells, lengthBp, plane = 'XY', offsetNm = 0, strandFilter = 'both', ligateAdjacent = true }) {
  const json = await _request('POST', '/design/bundle-segment', {
    cells,
    length_bp: lengthBp,
    plane,
    offset_nm: offsetNm,
    strand_filter: strandFilter,
    ligate_adjacent: ligateAdjacent,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Place a parametric circle (flat disc) primitive: a row of helices whose per-cell
 * lengths (parallel to `cells`) trace a circular chord profile, each centred on the
 * slice plane. Lengths are pre-computed from the radius (circle_primitive_logic.js).
 */
export async function addCircleSegment({ cells, cellLengths, plane = 'XY', offsetNm = 0, strandFilter = 'both', ligateAdjacent = true }) {
  const json = await _request('POST', '/design/circle-segment', {
    cells,
    cell_lengths: cellLengths,
    plane,
    offset_nm: offsetNm,
    strand_filter: strandFilter,
    ligate_adjacent: ligateAdjacent,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Extrude a continuation segment: cells whose helix ends at offsetNm extend existing strands;
 * fresh cells get new scaffold + staple strands.
 */
export async function addBundleContinuation({ cells, lengthBp, plane = 'XY', offsetNm = 0, strandFilter = 'both', ligateAdjacent = true }) {
  const json = await _request('POST', '/design/bundle-continuation', {
    cells,
    length_bp: lengthBp,
    plane,
    offset_nm: offsetNm,
    strand_filter: strandFilter,
    ligate_adjacent: ligateAdjacent,
  })
  return _syncFromDesignResponse(json)
}

export async function createDesign(name = 'Untitled', latticeType = 'HONEYCOMB') {
  const json = await _request('POST', '/design', { name, lattice_type: latticeType })
  return _syncFromDesignResponse(json)
}

export async function addAutoCrossover() {
  const json = await _request('POST', '/design/crossovers/auto')
  return _syncFromDesignResponse(json)
}

export async function placeCrossover(halfA, halfB, nickBpA, nickBpB) {
  const json = await _request('POST', '/design/crossovers/place', {
    half_a:    { helix_id: halfA.helix_id, index: halfA.index, strand: halfA.strand },
    half_b:    { helix_id: halfB.helix_id, index: halfB.index, strand: halfB.strand },
    nick_bp_a: nickBpA,
    nick_bp_b: nickBpB,
  })
  return _syncFromDesignResponse(json)
}

export async function placeCrossoverBatch(placements) {
  const json = await _request('POST', '/design/crossovers/place-batch', {
    placements: placements.map(p => ({
      half_a:    { helix_id: p.halfA.helix_id, index: p.halfA.index, strand: p.halfA.strand },
      half_b:    { helix_id: p.halfB.helix_id, index: p.halfB.index, strand: p.halfB.strand },
      nick_bp_a: p.nickBpA,
      nick_bp_b: p.nickBpB,
    })),
  })
  return _syncFromDesignResponse(json)
}

/**
 * Remove a crossover RECORD by id (DELETE /design/crossovers/{id}).
 *
 * This is the correct way to delete a placed crossover: the backend both
 * desplices the strand (splits it back into single-helix fragments) AND drops
 * the record.  Nicking alone leaves the record behind, so the arc is redrawn
 * from it — use this whenever a selected crossover carries a real crossover_id.
 */
export async function deleteCrossover(crossoverId) {
  const json = await _request('DELETE', `/design/crossovers/${crossoverId}`)
  return _syncFromDesignResponse(json)
}

/** Remove multiple crossover records atomically (POST /design/crossovers/batch-delete). */
export async function batchDeleteCrossovers(crossoverIds) {
  if (!crossoverIds.length) return null
  const json = await _request('POST', '/design/crossovers/batch-delete', { crossover_ids: crossoverIds })
  return _syncFromDesignResponse(json)
}

export async function patchCrossoverExtraBases(crossoverId, sequence) {
  const json = await _request('PATCH', `/design/crossovers/${crossoverId}/extra-bases`, { sequence })
  // extra_bases never moves real nucleotide geometry (see crud.py); the backend
  // flags this so the beads-only crossover-connections rebuild (which reads
  // design.crossovers directly) doesn't pay for a geometry round-trip.
  return _syncFromDesignResponse(json, { skipGeometry: json?.geometry_unchanged === true })
}

/** Set extra bases on multiple crossovers atomically (PATCH /design/crossovers/extra-bases/batch).
 *  `entries` = [{ crossover_id, sequence }, …]. */
export async function batchCrossoverExtraBases(entries) {
  if (!entries.length) return null
  const json = await _request('PATCH', '/design/crossovers/extra-bases/batch', { entries })
  return _syncFromDesignResponse(json, { skipGeometry: json?.geometry_unchanged === true })
}

export async function patchForcedLigationExtraBases(flId, sequence) {
  const json = await _request('PATCH', `/design/forced-ligations/${flId}/extra-bases`, { sequence })
  return _syncFromDesignResponse(json, { skipGeometry: json?.geometry_unchanged === true })
}

/**
 * Forced ligation: join the 3' end of one strand to the 5' end of another,
 * merging the two strands into one (the 5' strand's domains are appended onto
 * the 3' strand). Drives the 3D Force-Crossover tool — same endpoint the cadnano
 * editor's pencil-tool forced ligation uses. Records a ForcedLigation (not a
 * canonical Crossover). `is_periodic_seam` is false for direct 3D edits.
 */
export async function forcedLigation(threePrimeStrandId, fivePrimeStrandId, isPeriodicSeam = false) {
  const json = await _request('POST', '/design/forced-ligation', {
    three_prime_strand_id: threePrimeStrandId,
    five_prime_strand_id:  fivePrimeStrandId,
    is_periodic_seam:      isPeriodicSeam,
  })
  return _syncFromDesignResponse(json)
}

export async function addAutoBreak(opts = {}) {
  const json = await _request('POST', '/design/auto-break', opts)
  return _syncFromDesignResponse(json)
}

export async function addFullAutostaple(opts = {}) {
  const json = await _request('POST', '/design/full-autostaple', opts)
  return _syncFromDesignResponse(json)
}

export async function addAutoMerge() {
  const json = await _request('POST', '/design/auto-merge')
  return _syncFromDesignResponse(json)
}

export async function autoScaffoldSeamed() {
  const json = await _request('POST', '/design/auto-scaffold-seamed')
  if (json?.warnings?.length) console.warn('[AutoScaffoldSeamed] warnings:', json.warnings)
  return _syncFromDesignResponse(json)
}

export async function routeForPolymerization() {
  const json = await _request('POST', '/design/route-for-polymerization')
  if (!json) return null  // 422 (nothing to route) etc. — store.lastError set by _request
  if (json?.warnings?.length) console.warn('[RouteForPolymerization] warnings:', json.warnings)
  _syncFromDesignResponse(json)
  return json  // caller reads .warnings / .seam_ligation_ids before/after sync
}


// ── Sequence assignment ────────────────────────────────────────────────────

export async function assignScaffoldSequence(scaffoldName = 'M13mp18', opts = {}) {
  const { customSequence = null, strandId = null } = opts
  const json = await _request('POST', '/design/assign-scaffold-sequence', {
    scaffold_name: scaffoldName,
    custom_sequence: customSequence || null,
    strand_id: strandId || null,
  })
  return json  // caller reads json.padded_nt etc. before syncing design state
}

export async function autoScaffoldSeamless(opts = {}) {
  const { nickHelixId = null, nickOffset = 7, minEndMargin = 9 } = opts
  const json = await _request('POST', '/design/auto-scaffold-seamless', {
    nick_helix_id: nickHelixId,
    nick_offset: nickOffset,
    min_end_margin: minEndMargin,
  })
  return _syncFromDesignResponse(json)
}

export async function syncScaffoldSequenceResponse(json) {
  return _syncFromDesignResponse(json)
}

export async function assignStapleSequences() {
  const json = await _request('POST', '/design/assign-staple-sequences')
  return _syncFromDesignResponse(json)
}

export async function exportSequenceCsv() {
  const r = await fetch(`${BASE}/design/export/sequence-csv`, { headers: docHeaders() })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'sequences.csv'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return true
}

/**
 * Export staple sequences as an XLSX file with overhang regions bolded.
 *
 * `strandColors` is a map of strandId → "#RRGGBB" matching the on-screen
 * Sequence panel.  `strandOrder` is an array of strand IDs (staples only)
 * in the order they should appear in the sheet.  Both are optional; the
 * backend falls back to strand.color / palette and id-sorted order.
 */
export async function exportSequenceXlsx(strandColors = {}, strandOrder = []) {
  const r = await fetch(`${BASE}/design/export/sequence-xlsx`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...docHeaders() },
    body: JSON.stringify({ strand_colors: strandColors, strand_order: strandOrder }),
  })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'sequences.xlsx'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return true
}

export async function exportCadnano() {
  const r = await fetch(`${BASE}/design/export/cadnano`, { headers: docHeaders() })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'design.json'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return true
}

/**
 * Stream a backend export URL to a file download, doc-scoped and error-aware.
 *
 * Unlike a raw `<a href>` download, this sends `docHeaders()` so the backend
 * resolves the CALLER'S document session (not DEFAULT_DOC_ID), and it inspects
 * the response: on failure it records `lastError` and returns false so the menu
 * can toast, instead of the browser silently saving the 404 error body as a
 * bogus `<name>.json` file.  Used by the PDB/PSF/NAMD-package exports, whose
 * fixed-width outputs can't be produced client-side.
 */
async function _downloadBinaryExport(path, fallbackName, options = null) {
  const r = await fetch(`${BASE}${path}`, options ?? { headers: docHeaders() })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({
      lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) },
    })
    return false
  }
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return true
}

export function exportPdb(positions = null, visualization = null) {
  if ((!Array.isArray(positions) || !positions.length) && !visualization?.coloring) {
    return _downloadBinaryExport('/design/export/pdb', 'design.pdb')
  }
  return _downloadBinaryExport('/design/export/pdb/visualized', 'design.pdb', {
    method: 'POST',
    headers: { ...docHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({
      positions: Array.isArray(positions) ? positions : [],
      visualization: visualization && Array.isArray(positions) && positions.length ? {
        engine: visualization.engine,
        mode: visualization.mode,
        job_id: visualization.jobId,
        frame: visualization.trajectory?.frame ?? null,
        align: visualization.align ?? true,
      } : null,
      coloring: visualization?.coloring || null,
    }),
  })
}

export function exportPsf() {
  return _downloadBinaryExport('/design/export/psf', 'design.psf')
}

export function exportNamdComplete() {
  return _downloadBinaryExport('/design/export/namd-complete', 'design_namd_complete.zip')
}

export async function exportSurfaceStl({ targetMm = 200, gridSpacing, probeRadius } = {}) {
  const params = new URLSearchParams({ target_mm: String(targetMm) })
  if (gridSpacing != null) params.set('grid_spacing', String(gridSpacing))
  if (probeRadius != null) params.set('probe_radius', String(probeRadius))
  const r = await fetch(`${BASE}/design/export/stl?${params}`, { headers: docHeaders() })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'surface.stl'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return true
}

export async function exportSurface3mf({ targetMm = 200, gridSpacing, probeRadius } = {}) {
  const params = new URLSearchParams({ target_mm: String(targetMm) })
  if (gridSpacing != null) params.set('grid_spacing', String(gridSpacing))
  if (probeRadius != null) params.set('probe_radius', String(probeRadius))
  const r = await fetch(`${BASE}/design/export/3mf?${params}`, { headers: docHeaders() })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const coloring = r.headers.get('X-NADOC-Coloring') || ''
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'surface.3mf'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return { ok: true, coloring }
}

// ── Deformation endpoints ──────────────────────────────────────────────────

export async function addDeformation(type, planeA, planeB, params, helixIds = [], preview = false, clusterIds = []) {
  const body = {
    type,
    plane_a_bp: planeA,
    plane_b_bp: planeB,
    params,
    affected_helix_ids: helixIds,
    cluster_ids: Array.isArray(clusterIds) ? clusterIds : (clusterIds ? [clusterIds] : []),
    preview,
  }
  const json = await _request('POST', '/design/deformation', body)
  // A preview op is transient (no undo, no commit) → must not auto-save/propagate
  // to the assembly. The non-preview add IS the commit → save normally.
  const synced = _syncFromDesignResponse(json, { transient: preview })
  // On commit (not preview), surface any feasibility warning the backend attached.
  if (!preview && json?.deformation_warning) _toastDeformationWarning(json.deformation_warning)
  return synced
}

/** Surface a backend deformation_warning ({status, message}) as a toast. */
function _toastDeformationWarning(w) {
  if (!w?.message) return
  if (w.status === 'block') showToast(w.message, { severity: 'error', duration: 6000 })
  else if (w.status === 'warn') showToast(w.message, { severity: 'warning', duration: 5000 })
}

/**
 * Non-mutating bend/twist feasibility check (live editor feedback).
 * Returns { status, local_bp_per_turn, requested_radius_nm, min_bend_radius_nm,
 * requested_twist_deg, max_twist_deg, message } — never throws on warn/block.
 */
export async function validateDeformation({ type, planeA, planeB, params, helixIds = [], clusterIds = [] }) {
  return _request('POST', '/design/deformation/validate', {
    type,
    plane_a_bp: planeA,
    plane_b_bp: planeB,
    helix_ids: helixIds,
    cluster_ids: Array.isArray(clusterIds) ? clusterIds : (clusterIds ? [clusterIds] : []),
    params,
  })
}

export async function updateDeformation(opId, params) {
  // PATCH is always transient: live preview param tweaks AND the cancel-revert
  // both use it; the real edit commit goes through editFeature, not this.
  const json = await _request('PATCH', `/design/deformation/${opId}`, { params })
  return _syncFromDesignResponse(json, { transient: true })
}

export async function deleteDeformation(opId, preview = false) {
  const url = preview ? `/design/deformation/${opId}?preview=true` : `/design/deformation/${opId}`
  const json = await _request('DELETE', url)
  // Preview-op delete (cancel / drag auto-refresh) is transient; a non-preview
  // delete is a committed removal → save normally.
  return _syncFromDesignResponse(json, { transient: preview })
}


export async function updateMetadata(fields) {
  const json = await _request('PUT', '/design/metadata', fields)
  return _syncFromDesignResponse(json)
}

/**
 * Fetch geometry and update the store.
 *
 * @param {string[]|null} helixIds — when given, fetch only those helices and
 *   merge the result into the existing currentGeometry (Fix B partial path).
 *   Pass null (default) for a full fetch that replaces the whole geometry.
 */
export async function getGeometry(helixIds = null) {
  const base = helixIds?.length
    ? `/design/geometry?helix_ids=${helixIds.join(',')}`
    : '/design/geometry'
  // Measured ("new positioning") placement is a query flag on this endpoint, so a
  // toggle costs one refetch and the legacy request stays byte-identical when off.
  const url  = base + geometryQuerySuffix(base.includes('?'))
  const json = await _request('GET', url)
  if (!json) return null
  // Response format: { nucleotides: [...], helix_axes: [...] }
  // When the design has deformations or cluster_transforms, the backend
  // also auto-embeds straight_positions_by_helix + straight_helix_axes so
  // currentGeometry and straightGeometry update atomically (one setState).
  // Without that, deform_view's currentGeometry subscriber would see the
  // mismatch and trigger a second round-trip via getStraightGeometry().
  const nucleotides  = json.nucleotides ?? json   // backward compat with flat array
  const helixAxesMap = {}
  for (const ax of json.helix_axes ?? []) {
    helixAxesMap[ax.helix_id] = {
      start: ax.start, end: ax.end,
      samples: ax.samples ?? null,
      ovhgAxes: ax.ovhg_axes ?? null,
      segments: ax.segments ?? null,
    }
  }
  // Materialise the embedded straight payload (if any) into the same flat
  // nuc-list shape deform_view / unfold_view consumers read.
  let straightGeo  = null
  let straightAxes = null
  if (json.straight_positions_by_helix) {
    straightGeo = []
    const pbh = json.straight_positions_by_helix
    for (const helixId of Object.keys(pbh)) {
      const byDir = pbh[helixId]
      for (const dir of Object.keys(byDir)) {
        const data = byDir[dir]
        if (!data || !Array.isArray(data.bp)) continue
        for (let i = 0; i < data.bp.length; i++) {
          straightGeo.push({
            helix_id:          helixId,
            bp_index:          data.bp[i],
            direction:         dir,
            backbone_position: data.bb[i],
            base_normal:       data.bn?.[i],
          })
        }
      }
    }
    straightAxes = {}
    for (const ax of json.straight_helix_axes ?? []) {
      straightAxes[ax.helix_id] = {
        start: ax.start, end: ax.end,
        samples:  ax.samples  ?? null,
        ovhgAxes: ax.ovhg_axes ?? null,
        segments: ax.segments ?? null,
      }
    }
    if (Object.keys(straightAxes).length === 0) straightAxes = null
  }
  if (json.partial_geometry && json.changed_helix_ids?.length) {
    // ── Fix B merge path ────────────────────────────────────────────────────
    const changedSet = new Set(json.changed_helix_ids)
    const existing   = store.getState().currentGeometry ?? []
    const retainedAxes = { ...(store.getState().currentHelixAxes ?? {}) }
    for (const id of changedSet) delete retainedAxes[id]
    const updates = {
      currentGeometry: [
        ...existing.filter(n => !changedSet.has(n.helix_id)),
        ...nucleotides,
      ],
      currentHelixAxes: { ...retainedAxes, ...helixAxesMap },
    }
    // Partial responses do not embed straight (axes unchanged on partial
    // mutations), so straightGeo/straightAxes are null here in practice —
    // but include them in the same setState if the backend ever does.
    if (straightGeo !== null)  updates.straightGeometry  = straightGeo
    if (straightAxes !== null) updates.straightHelixAxes = straightAxes
    store.setState(updates)
  } else {
    const updates = {
      currentGeometry:  nucleotides,
      currentHelixAxes: Object.keys(helixAxesMap).length ? helixAxesMap : null,
    }
    if (straightGeo !== null)  updates.straightGeometry  = straightGeo
    if (straightAxes !== null) updates.straightHelixAxes = straightAxes
    store.setState(updates)
  }
  return json
}

/**
 * Fetch deformation-geometry debug data.
 * Returns the raw JSON (not stored in state).
 */
export async function getDeformDebug() {
  return _request('GET', '/design/deformation/debug')
}

/**
 * Fetch the straight (un-deformed) geometry and store it in straightGeometry /
 * straightHelixAxes without touching currentGeometry.
 */
export async function getStraightGeometry() {
  const json = await _request('GET', '/design/geometry?apply_deformations=false')
  if (!json) return null
  const nucleotides = json.nucleotides ?? json
  const helixAxesMap = {}
  for (const ax of json.helix_axes ?? []) {
    helixAxesMap[ax.helix_id] = {
      start: ax.start, end: ax.end,
      samples: ax.samples ?? null,
      ovhgAxes: ax.ovhg_axes ?? null,
      segments: ax.segments ?? null,
    }
  }
  store.setState({
    straightGeometry:  nucleotides,
    straightHelixAxes: Object.keys(helixAxesMap).length ? helixAxesMap : null,
  })
  return json
}

/**
 * Apply all DeformationOps as loop/skip topology modifications.
 * Requires crossovers to be placed first.
 */
export async function applyAllDeformations() {
  const json = await _request('POST', '/design/loop-skip/apply-deformations')
  return _syncFromDesignResponse(json)
}

/**
 * Insert or remove a loop/skip at a specific bp position on a helix.
 * delta: +1 = loop, -1 = skip, 0 = remove existing.
 */
export async function insertLoopSkip(helixId, bpIndex, delta) {
  const json = await _request('POST', '/design/loop-skip/insert', {
    helix_id: helixId,
    bp_index: bpIndex,
    delta,
  })
  return _syncFromDesignResponse(json)
}

export async function loadDesign(path) {
  const json = await _request('POST', '/design/load', { path })
  return _syncFromDesignResponse(json)
}

/**
 * Load a design from raw .nadoc JSON content (browser file open).
 * Replaces the active design and clears undo history.
 */
export async function importDesign(content) {
  const json = await _request('POST', '/design/import', { content })
  return _syncFromDesignResponse(json)
}

export async function importCadnanoDesign(content) {
  const json = await _request('POST', '/design/import/cadnano', { content })
  const result = await _syncFromDesignResponse(json)
  if (result) store.setState({ isCadnanoImport: true })
  return result
}

export async function importScadnanoDesign(content, name) {
  const body = name ? { content, name } : { content }
  const json = await _request('POST', '/design/import/scadnano', body)
  return _syncFromDesignResponse(json)
}

export async function importPdbDesign(content, merge = false) {
  const json = await _request('POST', '/design/import/pdb', { content, merge })
  return _syncFromDesignResponse(json)
}

/**
 * Unified PDB import. Provide `pdbId` (RCSB download) or `content` (file text).
 * Routing is server-side: DNA → design, protein → library. Returns the raw
 * response ({ imported:{dna,protein}, design?, protein?, import_warnings? })
 * WITHOUT syncing — the caller decides reset/sync order via syncDesignResponse.
 */
export async function importPdbAuto({ content = null, pdbId = null, name = '', removeDnaFromProtein = null } = {}) {
  return _request('POST', '/design/import/pdb-auto', {
    content, pdb_id: pdbId, name, remove_dna_from_protein: removeDnaFromProtein,
  })
}

/** Apply a design-response payload to the store (renderer rebuild). */
export function syncDesignResponse(json) {
  return _syncFromDesignResponse(json)
}

// ── Protein library (display-only proteins attached to overhangs) ──────────────

/** Import a protein from PDB text into the session library. Returns metadata. */
export async function importProtein(content, name = '', sourceFilename = '') {
  return _request('POST', '/design/protein/import', {
    content, name, source_filename: sourceFilename,
  })
}

/** List protein assets in the session library (metadata only). */
export async function listProteinLibrary() {
  return _request('GET', '/design/protein/library')
}

/** Surface-accessible azide-oligo conjugation candidate residues for an asset.
 *  Returns { asset_id, candidates:[{res_name,chain_id,res_seq,chemistry,
 *  functional_atom_serial,x,y,z,accessible}] }. */
export async function getConjugationCandidates(assetId) {
  return _request('GET', `/design/protein/conjugation-candidates?asset_id=${encodeURIComponent(assetId)}`)
}

/** Remove a protein asset from the session library. */
export async function deleteProteinAsset(assetId) {
  return _request('DELETE', `/design/protein/${assetId}`)
}

/** Anchor a protein to an overhang in the active design. Syncs the design. */
export async function createProteinAttachment(assetId, overhangId, opts = {}) {
  const json = await _request('POST', '/design/protein/attachments', {
    asset_id: assetId,
    overhang_id: overhangId,
    attach_end: opts.attachEnd ?? 'free_end',
    conjugation_atom_serial: opts.conjugationAtomSerial ?? null,
    handle_complement_bp: opts.handleComplementBp ?? 0,
    handle_spacer_nt: opts.handleSpacerNt ?? 0,
  })
  if (json) _syncFromDesignResponse(json)
  return json   // carries attachment_id
}

/** Commit an azide-oligo conjugation into the design: creates the ssDNA handle
 *  as an OH_BINDER strand bound to the overhang AND attaches the protein so its
 *  conjugation residue sits at the chosen azide terminus. One undo step.
 *  Returns json (carries attachment_id + binder_strand_id). */
export async function conjugateProteinToOverhang({ assetId, overhangId, conjugationAtomSerial = null, azideEnd = '5p' }) {
  const json = await _request('POST', '/design/protein/conjugate', {
    asset_id: assetId,
    overhang_id: overhangId,
    conjugation_atom_serial: conjugationAtomSerial,
    azide_end: azideEnd,
  })
  if (json) _syncFromDesignResponse(json)
  return json
}

/** Update a protein attachment (pose / conjugation / handle / visibility). */
export async function patchProteinAttachment(attachmentId, patch) {
  const json = await _request('PATCH', `/design/protein/attachments/${attachmentId}`, patch)
  return _syncFromDesignResponse(json)
}

/** Detach a protein. */
export async function deleteProteinAttachment(attachmentId) {
  const json = await _request('DELETE', `/design/protein/attachments/${attachmentId}`)
  return _syncFromDesignResponse(json)
}

export async function saveDesign(path) {
  return _request('POST', '/design/save', { path })
}

// ── Helices ───────────────────────────────────────────────────────────────────

export async function addHelix({ axisStart, axisEnd, lengthBp, phaseOffset = 0 }) {
  const json = await _request('POST', '/design/helices', {
    axis_start:   axisStart,
    axis_end:     axisEnd,
    length_bp:    lengthBp,
    phase_offset: phaseOffset,
  })
  return _syncFromDesignResponse(json)
}

export async function updateHelix(helixId, { axisStart, axisEnd, lengthBp, phaseOffset = 0 }) {
  const json = await _request('PUT', `/design/helices/${helixId}`, {
    axis_start:   axisStart,
    axis_end:     axisEnd,
    length_bp:    lengthBp,
    phase_offset: phaseOffset,
  })
  return _syncFromDesignResponse(json)
}

export async function deleteHelix(helixId) {
  const json = await _request('DELETE', `/design/helices/${helixId}`)
  return _syncFromDesignResponse(json)
}

// ── Strands ───────────────────────────────────────────────────────────────────

export async function addStrand({ domains, strandType = 'staple', sequence = null }) {
  const json = await _request('POST', '/design/strands', {
    domains:     domains,
    strand_type: strandType,
    sequence,
  })
  return _syncFromDesignResponse(json)
}

export async function updateStrand(strandId, { domains, strandType, sequence = null }) {
  const json = await _request('PUT', `/design/strands/${strandId}`, {
    domains,
    strand_type: strandType,
    sequence,
  })
  return _syncFromDesignResponse(json)
}

export async function deleteStrand(strandId) {
  const json = await _request('DELETE', `/design/strands/${strandId}`)
  return _syncFromDesignResponse(json)
}

export async function convertStrandToBinder(strandId) {
  const json = await _request('POST', `/design/strands/${strandId}/convert-to-binder`)
  return _syncFromDesignResponse(json)
}

export async function generateBinderForOverhang(overhangId) {
  const json = await _request('POST', `/design/overhang/${overhangId}/generate-binder`)
  return _syncFromDesignResponse(json)
}

export async function convertBinderToScaffold(strandId) {
  const json = await _request('POST', `/design/strands/${strandId}/convert-to-scaffold`)
  return _syncFromDesignResponse(json)
}

export async function deleteStrandsBatch(strandIds) {
  const json = await _request('DELETE', '/design/strands/batch', { strand_ids: strandIds })
  return _syncFromDesignResponse(json)
}

/**
 * Resize one or more strand terminal domains by delta_bp each.
 * entries: Array<{ strand_id, helix_id, end: '5p'|'3p', delta_bp: number }>
 */
export async function resizeStrandEnds(entries) {
  const json = await _request('POST', '/design/strand-end-resize', { entries })
  return _syncFromDesignResponse(json)
}

export async function addDomain(strandId, { helixId, startBp, endBp, direction }) {
  const json = await _request('POST', `/design/strands/${strandId}/domains`, {
    helix_id:  helixId,
    start_bp:  startBp,
    end_bp:    endBp,
    direction,
  })
  return _syncFromDesignResponse(json)
}

export async function deleteDomain(strandId, domainIndex) {
  const json = await _request('DELETE', `/design/strands/${strandId}/domains/${domainIndex}`)
  return _syncFromDesignResponse(json)
}

// ── Nicks ─────────────────────────────────────────────────────────────────────

/**
 * Create a nick (strand break) at the 3′ side of the nucleotide at
 * (helixId, bpIndex, direction).  The strand is split into left (3′ = bpIndex)
 * and right (5′ = next nucleotide) fragments.
 */
export async function addNick({ helixId, bpIndex, direction }) {
  const json = await _request('POST', '/design/nick', {
    helix_id:  helixId,
    bp_index:  bpIndex,
    direction,
  })
  return _syncFromDesignResponse(json)
}

export async function addNickBatch(nicks) {
  const json = await _request('POST', '/design/nick/batch', {
    nicks: nicks.map(n => ({ helix_id: n.helixId, bp_index: n.bpIndex, direction: n.direction })),
  })
  return _syncFromDesignResponse(json)
}

/** Remove a forced ligation by ID — splits the strand back into two fragments. */
export async function deleteForcedLigation(flId) {
  const json = await _request('DELETE', `/design/forced-ligations/${flId}`)
  return _syncFromDesignResponse(json)
}

/** Remove multiple forced ligations in a single atomic request. */
export async function batchDeleteForcedLigations(flIds) {
  if (!flIds.length) return
  const json = await _request('POST', '/design/forced-ligations/batch-delete', { forced_ligation_ids: flIds })
  return _syncFromDesignResponse(json)
}

// ── Overhangs ────────────────────────────────────────────────────────────────
// 9 overhang endpoint helpers extracted to ./overhang_endpoints.js (Refactor 05-A-v2).
// Re-exported from this file via `export * from './overhang_endpoints.js'` below.

export async function clearAllLoopSkips() {
  const json = await _request('POST', '/design/loop-skip/clear-all')
  return _syncFromDesignResponse(json)
}

// TODO(05-A-v2): extract to overhang_endpoints.js once _syncClusterOnlyDiff / _syncPositionsOnlyDiff are factored
export async function relaxLinker(connId, jointIds = null, opts = {}) {
  // Optimizes joint angle(s) so the linker's connector arcs collapse.
  //   jointIds   null / []  → backend auto-picks (1-DOF case)
  //              non-empty  → multi-DOF
  //   opts.binIndex  (ss)   → R_ee histogram bin whose pre-baked shape to render.
  //   opts.rEeMinNm  (ss)   → kinematic R_ee minimum to persist on the connection.
  //   opts.rEeMaxNm  (ss)   → kinematic R_ee maximum.
  // All ss-linker fields are optional; omit them to keep the connection's
  // current bridge_bin_index / bridge_r_ee_min_nm / bridge_r_ee_max_nm.
  const { binIndex = null, rEeMinNm = null, rEeMaxNm = null } = opts
  const body = {}
  if (jointIds && jointIds.length) body.joint_ids   = jointIds
  if (binIndex != null)            body.bin_index   = binIndex
  if (rEeMinNm != null)            body.r_ee_min_nm = rEeMinNm
  if (rEeMaxNm != null)            body.r_ee_max_nm = rEeMaxNm
  const payload = Object.keys(body).length ? body : null
  const json = await _request('POST',
    `/design/overhang-connections/${encodeURIComponent(connId)}/relax`, payload)
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

/**
 * Generic bond relax — closes a stretched backbone bond chord using
 * cluster transforms (rigid translate for 0-DOF; joint rotate / Powell
 * for 1-DOF / N-DOF).
 *
 * `bond` is a typed reference:
 *   { bond_type: 'crossover'|'ligation'|'linker_arc'|'strand_arc',
 *     bond_id: ?string,                // record-id path
 *     linker_side: ?'a'|'b',           // linker_arc only
 *     side_a:  ?{helix_id, bp_index, direction, strand_id?},
 *     side_b:  ?{helix_id, bp_index, direction, strand_id?},
 *   }
 * `opts`:
 *   sideToMove: 'a'|'b'|null  — required in the 0-DOF case
 *   jointIds:   string[]|null — null = auto-pick all joints between the clusters
 *   targetNm:   number|null   — override the type-default chord target
 */
export async function relaxBond(bond, opts = {}) {
  const { sideToMove = null, jointIds = null, targetNm = null } = opts
  const body = {
    bond_type: bond.bond_type,
  }
  if (bond.bond_id != null)     body.bond_id     = bond.bond_id
  if (bond.linker_side != null) body.linker_side = bond.linker_side
  if (bond.side_a != null)      body.side_a      = bond.side_a
  if (bond.side_b != null)      body.side_b      = bond.side_b
  if (sideToMove != null)       body.side_to_move = sideToMove
  if (jointIds && jointIds.length) body.joint_ids = jointIds
  if (targetNm != null)         body.target_nm   = targetNm
  const json = await _request('POST', '/design/relax-bond', body)
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

// ── Flexible ssDNA segments (pose & explore mechanisms) ──────────────────────

/** Mark one unpaired bead as part of a flexible segment + re-derive connections.
 *  bead: {strand_id, domain_index, bp_index, direction}. Full geometry returns
 *  (beads reclassify out of the rigid meshes, arcs appear). */
export async function markFlexibleSegment(bead) {
  const json = await _request('POST', '/design/flexible-segment', bead)
  return _syncFromDesignResponse(json)
}

export async function unmarkFlexibleSegment(markId) {
  const json = await _request('DELETE', `/design/flexible-segment/${encodeURIComponent(markId)}`)
  return _syncFromDesignResponse(json)
}

/** Mark an explicit list of beads flexible (selective). opts: {marks?:[{...}],
 *  replace?:bool}. replace:true with no marks clears all flexible segments. */
export async function batchFlexibleSegment(opts = {}) {
  const json = await _request('POST', '/design/flexible-segment/batch', opts)
  return _syncFromDesignResponse(json)
}

/** Derived flexible connections + per-cluster gate (no mutation). Used to enable
 *  the move/rotate "ssDNA constrained" mode and feed the drag constraint. */
export async function getFlexibleConnections() {
  return _request('GET', '/design/flexible-connections')
}

/** Commit a flexible-segment relax: persist the moved-cluster transforms as ONE
 *  feature-log step (revertable / deletable / single undo). `transforms` =
 *  [{cluster_id, pivot, translation, rotation}]. */
export async function relaxFlexibleSegments(transforms, label) {
  const json = await _request('POST', '/design/flexible-relax', { transforms, label })
  // The backend applies only cluster_transforms, so the response is classified
  // cluster_only / positions_only; fall back to the full sync otherwise. Without
  // one of these, the store's currentDesign (which holds feature_log) never
  // updates → the relax entry wouldn't appear in the panel and wouldn't persist.
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

export async function patchStrand(strandId, { notes, color, sequence } = {}) {
  const body = {}
  if (notes    !== undefined) body.notes    = notes
  if (color    !== undefined) body.color    = color
  if (sequence !== undefined) body.sequence = sequence
  const json = await _request('PATCH', `/design/strand/${encodeURIComponent(strandId)}`, body)
  // notes/color/sequence are pure metadata — no nucleotide moves.
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/**
 * Read everything the "Edit sequence…" dialog needs for one strand:
 * `{length, sequence, derived, partner, segments}` — see the backend route
 * GET /design/strand/{id}/sequence-context. Read-only; never mutates the design.
 */
export async function getStrandSequenceContext(strandId) {
  return _request('GET', `/design/strand/${encodeURIComponent(strandId)}/sequence-context`)
}

/** Apply the same color to multiple strands in one atomic request.
 *  color: '#RRGGBB' hex string, or null to reset to palette.
 */
export async function patchStrandsColor(strandIds, color) {
  const json = await _request('PATCH', '/design/strands/colors', { strand_ids: strandIds, color })
  // Color-only update — no geometry refetch needed.
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/** Mark/clear strands as inactive reference geometry, atomically in one request.
 *  Reference strands are ignored by all auto-features and excluded from exports.
 *  NOTE: NOT skipGeometry — toggling reference changes the bend/twist freeze, so
 *  nucleotide positions move and the response carries fresh geometry.
 */
export async function patchStrandsReference(strandIds, isReference) {
  const json = await _request('PATCH', '/design/strands/reference',
    { strand_ids: strandIds, is_reference: isReference })
  return _syncFromDesignResponse(json, { skipGeometry: json?.geometry_unchanged === true })
}

/**
 * Add a terminal extension to a staple strand's 5′ or 3′ end.
 * @param {string} strandId
 * @param {'five_prime'|'three_prime'} end
 * @param {{sequence?: string, modification?: string, label?: string}} opts
 */
export async function createStrandExtension(strandId, end, opts = {}) {
  const json = await _request('POST', '/design/extensions', { strand_id: strandId, end, ...opts })
  return _syncFromDesignResponse(json)
}

/**
 * Update an existing strand extension.
 * @param {string} extId
 * @param {{sequence?: string, modification?: string, label?: string}} opts
 */
export async function updateStrandExtension(extId, opts) {
  const json = await _request('PUT', `/design/extensions/${extId}`, opts)
  return _syncFromDesignResponse(json)
}

/**
 * Remove a strand extension.
 * @param {string} extId
 */
export async function deleteStrandExtension(extId) {
  const json = await _request('DELETE', `/design/extensions/${extId}`)
  return _syncFromDesignResponse(json)
}

/**
 * Upsert (create or update) multiple strand extensions in one round-trip.
 * Each item with the same (strand_id, end) as an existing extension will update
 * it in-place; otherwise a new extension is created.
 *
 * @param {Array<{strandId, end, sequence?, modification?, label?}>} items
 */
export async function upsertStrandExtensionsBatch(items) {
  const json = await _request('POST', '/design/extensions/batch', {
    items: items.map(({ strandId, end, sequence, modification, label }) => ({
      strand_id:    strandId,
      end,
      sequence:     sequence     ?? null,
      modification: modification ?? null,
      label:        label        ?? null,
    })),
  })
  return _syncFromDesignResponse(json)
}

/**
 * Delete multiple strand extensions by ID in one round-trip.
 *
 * @param {string[]} extIds
 */
export async function deleteStrandExtensionsBatch(extIds) {
  const json = await _request('DELETE', '/design/extensions/batch', { ext_ids: extIds })
  return _syncFromDesignResponse(json)
}

/**
 * Return the deformed cross-section frame at sourceBp on the arm containing refHelixId.
 * Returns { grid_origin, axis_dir, frame_right, frame_up } (lists of 3 floats each).
 */
export async function getDeformedFrame(sourceBp, refHelixId = null) {
  const params = new URLSearchParams({ source_bp: sourceBp })
  if (refHelixId) params.append('ref_helix_id', refHelixId)
  return _request('GET', `/design/deformed-frame?${params}`)
}

/**
 * Extrude a bundle continuation using a deformed cross-section frame.
 * frame must be the object returned by getDeformedFrame().
 */
export async function addBundleDeformedContinuation({ cells, lengthBp, plane = 'XY', frame, refHelixId = null, sourceBp = null }) {
  const json = await _request('POST', '/design/bundle-deformed-continuation', {
    cells,
    length_bp:    lengthBp,
    plane,
    grid_origin:  frame.grid_origin,
    axis_dir:     frame.axis_dir,
    frame_right:  frame.frame_right,
    frame_up:     frame.frame_up,
    ref_helix_id: refHelixId,
    // bp where the frame was sampled — lets the backend recompute the frame live
    // and re-place this segment if an upstream bend/twist is later deleted/edited.
    source_bp:    sourceBp,
  })
  return _syncFromDesignResponse(json)
}

// ── oxDNA ──────────────────────────────────────────────────────────────────────

/**
 * Trigger a browser download of the active design as an oxDNA ZIP archive
 * (topology.top, conf.dat, input.txt, README.txt).
 */
export async function exportOxdna() {
  const r = await fetch(`${BASE}/design/oxdna/export`, { method: 'POST' })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const disposition = r.headers.get('Content-Disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : 'design_oxdna.zip'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return true
}

/**
 * Run an oxDNA energy minimisation on the server (requires oxDNA binary).
 * Returns { available, message, positions } — positions is null if not available.
 */
export async function runOxdna(steps = 10000) {
  return _request('POST', `/design/oxdna/run?steps=${steps}`)
}

// ── oxDNA relaxation jobs (managed 3-stage runner) ─────────────────────────────
// These talk to the oxDNA job manager (routes_oxdna.py), a sibling of the NAMD
// /md/jobs API.  They do NOT mutate the design, so they bypass _request's
// design-sync and just return parsed JSON (or null on error).

// Job panels share several list/status endpoints and can refresh from timers, tab changes,
// SSE, and explicit actions in the same turn. Collapse identical, non-abortable GETs while
// one is in flight; each caller still receives the same parsed result. Requests carrying an
// AbortSignal stay independent because sharing would make one consumer's cancellation
// semantics lie to the others.
const _jobJsonGetInflight = new Map()

async function _oxdnaJSON(method, path, body = undefined, { signal } = {}) {
  if (method !== 'GET' || signal != null) return _oxdnaJSONRequest(method, path, body, { signal })
  const key = `${JSON.stringify(docHeaders())}|${path}`
  const existing = _jobJsonGetInflight.get(key)
  if (existing) {
    _emitRequestDiagnostic({ phase: 'coalesced', method, path, transport: 'job-json' })
    return existing
  }
  const request = _oxdnaJSONRequest(method, path, body, { signal })
  _jobJsonGetInflight.set(key, request)
  try {
    return await request
  } finally {
    if (_jobJsonGetInflight.get(key) === request) _jobJsonGetInflight.delete(key)
  }
}

async function _oxdnaJSONRequest(method, path, body = undefined, { signal } = {}) {
  const diagnosticId = ++_diagnosticRequestSeq
  const diagnosticStarted = performance.now()
  _emitRequestDiagnostic({
    phase: 'start', id: diagnosticId, method, path,
    suppressBusy: true, transport: 'job-json',
  })
  const opts = { method, headers: { ...docHeaders() } }
  // Type-check rather than truthiness-check: a positional arg mix-up used to land a
  // non-signal here (e.g. `signal = true` from an `align` bound to the wrong param).
  // `if (signal)` waved that straight through to fetch, which rejects with an opaque
  // "Expected signal to be an instance of AbortSignal" from deep inside the request —
  // or, worse, the real signal was dropped and the fetch just became un-abortable.
  // Fail here instead, naming the route, so the mistake is obvious at the call site.
  if (signal != null) {
    if (!(signal instanceof AbortSignal)) {
      throw new TypeError(
        `_oxdnaJSON(${method} ${path}): signal must be an AbortSignal, got ${typeof signal}. `
        + 'A positional align/signal mix-up is the usual cause — these APIs take (id, { align, signal }).')
    }
    opts.signal = signal
  }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  let r
  try {
    r = await fetch(`${BASE}${path}`, opts)
  } catch (err) {
    _emitRequestDiagnostic({
      phase: err?.name === 'AbortError' ? 'aborted' : 'error',
      id: diagnosticId, method, path,
      durationMs: performance.now() - diagnosticStarted,
      message: err?.message ?? String(err), transport: 'job-json',
    })
    if (err?.name === 'AbortError') return null
    throw err
  }
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    _emitRequestDiagnostic({
      phase: 'complete', id: diagnosticId, method, path,
      durationMs: performance.now() - diagnosticStarted,
      status: r.status, transport: 'job-json',
    })
    return null
  }
  const json = await r.json().catch(() => null)
  _emitRequestDiagnostic({
    phase: 'complete', id: diagnosticId, method, path,
    durationMs: performance.now() - diagnosticStarted,
    status: r.status, transport: 'job-json',
  })
  return json
}

async function _backgroundJobList(path) {
  await whenOperationIdle()
  return _oxdnaJSON('GET', path)
}

/** Binary sibling of _oxdnaJSON — returns the response as an ArrayBuffer (or null). */
async function _oxdnaBin(method, path, body = undefined) {
  const opts = { method, headers: { ...docHeaders() } }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const r = await fetch(`${BASE}${path}`, opts).catch(() => null)
  if (!r || !r.ok) return null
  return r.arrayBuffer().catch(() => null)
}

/** Last API error message (e.g. the 400 detail from a rejected create). */
export const lastErrorMessage    = ()            => store.getState().lastError?.message ?? null

export const oxdnaAvailable      = ()            => _oxdnaJSON('GET',  '/oxdna/available')
/** Ranked available RunPod GPUs for the active design's relaxation — each with live price,
 *  estimated relax wall-clock, and estimated cost. nAtoms omitted → backend sizes the design. */
export const getRunpodGpuOptions = (nAtoms)      =>
  _oxdnaJSON('POST', '/runpod/gpu-options', nAtoms ? { n_atoms: nAtoms } : {})
/** The Job Wizard's RunPod feed: the WHOLE plan costed (relaxation + production, at their own
 *  timesteps) plus storage, balance, live pods and the pre-flight — in ONE round trip, so the
 *  card does not fetch the same live stock four times. Body is `runpodPlanShape(plan)`. */
export const getRunpodJobPreview = (body)        =>
  _oxdnaJSON('POST', '/runpod/job-preview', body || {})
/** Every network volume on the account (id, name, size_gb, data_center_id). */
export const getRunpodVolumes    = ()            => _oxdnaJSON('GET',  '/runpod/volumes')
/** Point the live session at a network volume. The wizard needs this because, unlike the
 *  setup modal, it does not hold the API key that `/runpod/connect` requires. */
export const setRunpodVolume     = (id)          =>
  _oxdnaJSON('POST', '/runpod/volume', { network_volume_id: id })
/** MD-engine status report (oxDNA/NAMD/GROMACS/… availability + GPU + toolchain). */
export const enginesStatus       = ()            => _oxdnaJSON('GET',  '/engines/status')
/** List a directory for the "pick a downloaded file" navigator ({cwd, parent, entries}).
 *  path omitted → opens at the user's Downloads folder; kind ('arbd'|'namd') highlights matches. */
export const browseFiles         = (path, kind)  => {
  const q = new URLSearchParams()
  if (path) q.set('path', path)
  if (kind) q.set('kind', kind)
  const s = q.toString()
  return _oxdnaJSON('GET', '/engines/browse' + (s ? `?${s}` : ''))
}
export const createOxdnaJob      = (body)        => _oxdnaJSON('POST', '/oxdna/jobs', body)

// ── LAMMPS (CG-DNA / parallel oxDNA) jobs ──────────────────────────────────────
/** Is a CG-DNA-capable LAMMPS installed? → {available, lammps_bin, cgdna_capable}. */
export const lammpsAvailable     = ()            => _oxdnaJSON('GET',  '/lammps/available')
/**
 * Normalize a visualization call's `{ align, signal }` options — and make every legacy
 * positional call fail LOUDLY.
 *
 * These fns were briefly `(id, align = true, signal)`. `align` was inserted BEFORE
 * `signal`, so any caller still on the older `(id, signal)` shape silently bound its
 * AbortSignal to `align`: the request became un-abortable (stale responses then raced the
 * display) and `?align=[object AbortSignal]` went on the wire. Nothing threw at the call
 * site. No positional signature can catch that, so the options object IS the fix, and this
 * guard is the tripwire for anything still on the old shape.
 */
function _vizOpts(opts, fn) {
  // `scope` must be defaulted here too — omitting it put the literal `scope=undefined` on
  // the wire for any no-options call (the backend then fell through to lineage by
  // accident, which is the right answer for the wrong reason).
  if (opts == null) return { align: true, signal: undefined, scope: 'lineage' }
  if (typeof opts === 'boolean' || opts instanceof AbortSignal) {
    throw new TypeError(
      `${fn}(id, opts): expected an options object like { align, signal }, got a positional `
      + `${typeof opts === 'boolean' ? 'boolean (the old (id, align, signal) form)' : 'AbortSignal (the old (id, signal) form)'}. `
      + 'Update the call — the old form silently dropped the AbortSignal.')
  }
  const { align = true, signal, scope = 'lineage' } = opts
  if (typeof align !== 'boolean') {
    throw new TypeError(`${fn}: opts.align must be a boolean, got ${typeof align}.`)
  }
  if (signal != null && !(signal instanceof AbortSignal)) {
    throw new TypeError(`${fn}: opts.signal must be an AbortSignal, got ${typeof signal}.`)
  }
  if (scope !== 'lineage' && scope !== 'job') {
    throw new TypeError(`${fn}: opts.scope must be 'lineage' or 'job', got ${JSON.stringify(scope)}.`)
  }
  return { align, signal, scope }
}

/** Launch a LAMMPS oxDNA2 run on the active design ({steps, dump_every, temperature, salt_molar, ranks}). */
export const createLammpsJob     = (body)        => _oxdnaJSON('POST', '/lammps/jobs', body)
export const listLammpsJobs      = ()            => _backgroundJobList('/lammps/jobs')
export const getLammpsJob        = (id)          => _oxdnaJSON('GET',  `/lammps/jobs/${id}`)
export const stopLammpsJob       = (id)          => _oxdnaJSON('POST', `/lammps/jobs/${id}/stop`)
/** Scrub-able trajectory ({ready, keys, frames, stages, markers}) — same shape as the oxDNA one. */
export const getLammpsTrajectory = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getLammpsTrajectory')
  return _oxdnaJSON('GET', `/lammps/jobs/${id}/trajectory?align=${align}`, undefined, { signal })
}
/** Final structure as applyFemPositions positions (the display view); align superposes onto design pose. */
export const getLammpsDisplay = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getLammpsDisplay')
  return _oxdnaJSON('GET', `/lammps/jobs/${id}/display?align=${align}`, undefined, { signal })
}
/** Per-base average position + RMSF (flexibility map) — same shape as the oxDNA one. */
export const getLammpsRmsf = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getLammpsRmsf')
  return _oxdnaJSON('GET', `/lammps/jobs/${id}/rmsf?align=${align}`, undefined, { signal })
}
/** Per-base deviation (nm) from the design pose (deviation map) — same shape as the oxDNA one. */
export const getLammpsDeviation = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getLammpsDeviation')
  return _oxdnaJSON('GET', `/lammps/jobs/${id}/deviation?align=${align}`, undefined, { signal })
}

/** Forecast free-disk-after for an oxDNA relaxation run (same body as createOxdnaJob). */
export const estimateOxdnaDisk   = (body)        => _oxdnaJSON('POST', '/oxdna/jobs/estimate-disk', body)
/** Forecast free-disk-after for an oxDNA production/run stage ({steps}). */
export const estimateOxdnaRunDisk = (id, body)   => _oxdnaJSON('POST', `/oxdna/jobs/${id}/estimate-run-disk`, body)
export const listOxdnaJobs       = ()            => _backgroundJobList('/oxdna/jobs')
export const getOxdnaJob         = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}`)
export const getOxdnaErrorLog    = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/error-log`)
export const getOxdnaProgress    = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/progress`)
export const startOxdnaJob       = (id)          => _oxdnaJSON('POST', `/oxdna/jobs/${id}/start`)
export const appendOxdnaProduction = (id, body)  => _oxdnaJSON('POST', `/oxdna/jobs/${id}/production`, body)
export const appendOxdnaField    = (id, body)    => _oxdnaJSON('POST', `/oxdna/jobs/${id}/field`, body)
export const appendOxdnaRun      = (id, body)    => _oxdnaJSON('POST', `/oxdna/jobs/${id}/run`, body)
export const previewOxdnaFieldAnchors = (id, body) => _oxdnaJSON('POST', `/oxdna/jobs/${id}/field/anchor-preview`, body)
export const stopOxdnaJob        = (id)          => _oxdnaJSON('POST', `/oxdna/jobs/${id}/stop`)
export const deleteOxdnaJob      = (id)          => _oxdnaJSON('DELETE', `/oxdna/jobs/${id}`)
/** Start moving an oxDNA job's folder to <destRoot>/<job_id> (background; poll status). */
export const archiveOxdnaJob     = (id, destRoot) => _oxdnaJSON('POST', `/oxdna/jobs/${id}/archive`, { dest_root: destRoot })
export const unarchiveOxdnaJob   = (id)          => _oxdnaJSON('POST', `/oxdna/jobs/${id}/unarchive`)
export const oxdnaArchiveStatus  = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/archive-status`)
/** Start an autorefine-skips/loops run on the current (square-lattice) design → {autorefine_id}. */
export const startAutorefine     = (body)        => _oxdnaJSON('POST', '/design/oxdna/autorefine/start', body)
/** Poll an autorefine run → {state, phase, last_event, result?, error?}. */
export const getAutorefine       = (id)          => _oxdnaJSON('GET',  `/design/oxdna/autorefine/${id}`)
/** Request cancellation of a running autorefine (kills the in-flight job + ends the loop). */
export const stopAutorefine      = (id)          => _oxdnaJSON('POST', `/design/oxdna/autorefine/${id}/stop`)
/** Apply an autorefine's skips to the active design (feature-log entry).  Pass `period`
 *  to apply a specific iteration's pattern live; omit it to apply the converged result. */
export const applyAutorefineSkips = (id, period) => _oxdnaJSON('POST',
  `/design/oxdna/autorefine/${id}/apply${period != null ? `?period=${period}` : ''}`)
/** Per-nucleotide deviation map of a job's production mean structure vs its design. */
export const getOxdnaDeviation = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getOxdnaDeviation')
  return _oxdnaJSON('GET', `/oxdna/jobs/${id}/deviation?align=${align}`, undefined, { signal })
}
/** Per-nucleotide LOCAL STRAIN map of a job's production mean structure.
 *  `opts.metric`: 'backbone' (FENE backbone-bond strain, default) or 'wc' (Watson–Crick
 *  base-pair stretch).  Values are SIGNED oxDNA length units: + stretched, − compressed. */
export const getOxdnaStrain = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getOxdnaStrain')
  const metric = opts?.metric ?? 'backbone'
  if (metric !== 'backbone' && metric !== 'wc') {
    throw new TypeError(`getOxdnaStrain: opts.metric must be 'backbone' or 'wc', got ${JSON.stringify(metric)}.`)
  }
  return _oxdnaJSON('GET', `/oxdna/jobs/${id}/strain?align=${align}&metric=${metric}`,
                    undefined, { signal })
}
/** Graphs & Metrics card: start a background twist/curvature/base-pairing compute for a
 *  job (`{scope:'latest'|'chain'}`) → {metrics_id}; poll `getOxdnaMetricsRun`. */
export const startOxdnaMetrics   = (id, body)    => _oxdnaJSON('POST', `/oxdna/jobs/${id}/metrics/start`, body)
/** Poll a Graphs & Metrics run → {state, progress, eta_s, frames_done, frames_total, result?}. */
export const getOxdnaMetricsRun  = (runId)       => _oxdnaJSON('GET',  `/oxdna/metrics/${runId}`)
/** Cross-engine Shape comparison card (S5): start a comparison over per-engine source
 *  bundles (`{sources:[{engine, descriptors?, rmsf?, shape_frame?, field?}, …]}`) →
 *  {metrics_id}; poll `getShapeCompareRun` → {state, progress, result?}. */
export const startShapeCompare   = (body)        => _oxdnaJSON('POST', '/shape/compare/start', body)
export const getShapeCompareRun  = (runId)       => _oxdnaJSON('GET',  `/shape/compare/${runId}`)
/** oxDNA source bundle for the comparison card (O1): the `engine:"oxdna"` shape-reference
 *  column → {ready, engine, descriptors, rmsf, shape_frame, field}. */
export const getOxdnaShapeSource = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/shape-source`)
export const getOxdnaHealth      = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/health`)
export const getOxdnaMetrics     = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/metrics`)
export const getOxdnaDisplay = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getOxdnaDisplay')
  return _oxdnaJSON('GET', `/oxdna/jobs/${id}/display?align=${align}`, undefined, { signal })
}
export const getOxdnaRmsd        = (id)          => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/rmsd`)
export const getOxdnaRmsf = (id, opts) => {
  const { align, signal } = _vizOpts(opts, 'getOxdnaRmsf')
  return _oxdnaJSON('GET', `/oxdna/jobs/${id}/rmsf?align=${align}`, undefined, { signal })
}
/** Top-N most likely CONFIGURATIONS ({ready, verdict, clusters:[{population, frame, …}], keys}).
 *  Where RMSF gives one mean structure, this gives several real medoid frames with weights.
 *  `opts.nClusters` 0 = auto; `opts.basis` 'nt'|'bp'; `opts.maxFrames` — leave at 200 to share
 *  the trajectory route's frame cache, anything else re-reads the trajectory.
 *  Read `verdict` first: 'switching' | 'drift' | 'unimodal' (see routes_oxdna.get_oxdna_occupancy). */
export const getOxdnaOccupancy = (id, opts) => {
  const { align, signal, scope } = _vizOpts(opts, 'getOxdnaOccupancy')
  const { nClusters = 0, maxFrames = 200, method = 'pca', basis = 'nt', refetch = false } = opts ?? {}
  return _oxdnaJSON(
    'GET',
    `/oxdna/jobs/${id}/occupancy?align=${align}&scope=${scope}&n_clusters=${nClusters}`
      + `&max_frames=${maxFrames}&method=${method}&basis=${basis}&refetch=${refetch}`,
    undefined, { signal })
}
/** Occupancy clouds restricted to PART of the structure — same payload as
 *  getOxdnaOccupancy plus `opts.selection` (clusters / strands / domains / overhangs /
 *  bases). POST because a base-level selection is far too big for a query string.
 *  `opts.fit` is the reference frame the scoped feature set is re-superposed in
 *  ('selection' | 'local' | 'global'); the response echoes what was actually used. */
export const postOxdnaOccupancy = (id, opts) => {
  const { align, signal, scope } = _vizOpts(opts, 'postOxdnaOccupancy')
  const { nClusters = 0, maxFrames = 200, method = 'pca', basis = 'nt', refetch = false,
          selection = null, fit = 'selection' } = opts ?? {}
  return _oxdnaJSON('POST', `/oxdna/jobs/${id}/occupancy`, {
    align, scope, max_frames: maxFrames, n_clusters: nClusters, method, basis, refetch,
    selection, fit,
  }, { signal })
}
/** Live frames-processed progress for an in-flight occupancy build ({active,done,total}). */
export const getOxdnaOccupancyProgress = (id) =>
  _oxdnaJSON('GET', `/oxdna/jobs/${id}/occupancy-progress`)
/** Composite trajectory. `opts.scope`: 'lineage' (default, whole ancestor chain strided to
 *  ~200 frames — the fast view) or 'job' (this job's own stages only, EVERY written frame,
 *  no stride — the slow view). Scope must match whatever getOxdnaTrajectoryMeta was given. */
export const getOxdnaTrajectory = (id, opts) => {
  const { align, signal, scope } = _vizOpts(opts, 'getOxdnaTrajectory')
  return _oxdnaJSON('GET', `/oxdna/jobs/${id}/trajectory?align=${align}&scope=${scope}`,
                    undefined, { signal })
}
/** Frame count + stage markers only (no coordinates) — sizes the trajectory slider fast.
 *  Pass the SAME scope as getOxdnaTrajectory or the slider length won't match the payload. */
export const getOxdnaTrajectoryMeta = (id, scope = 'lineage') =>
  _oxdnaJSON('GET', `/oxdna/jobs/${id}/trajectory-meta?scope=${scope}`)
/** Live frames-processed progress for an in-flight trajectory build ({active,done,total}). */
export const getOxdnaTrajectoryProgress = (id)   => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/trajectory-progress`)
/** Live progress for an in-flight trajectory-RANGE export ({active,done,total,phase}). */
export const getOxdnaExportProgress = (id)       => _oxdnaJSON('GET',  `/oxdna/jobs/${id}/export-progress`)

/** Export a FRAME RANGE of an oxDNA job's composite trajectory and trigger a browser
 *  download. Returns the saved FILENAME (string) on success — the export card keeps it to
 *  name the ChimeraX `open` command — or false on failure (message in store.lastError). */
export async function exportOxdnaTrajectory(jobId, { lo, hi, format = 'pdb' } = {}) {
  const r = await fetch(`${BASE}/oxdna/jobs/${jobId}/export-trajectory`, {
    method: 'POST',
    headers: { ...docHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ lo, hi, format }),
  })
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({
      lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) },
    })
    return false
  }
  const blob = await r.blob()
  const cd = r.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : `${jobId}_frames${lo}-${hi}.${format === 'pdb' ? 'pdb' : 'zip'}`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  return filename
}
/** Per-frame ATOMISTIC coords for trajectory frame indices (atomistic-batch wire
 *  format). Heavy — pass a downsampled index set. `scope` must match the scope the
 *  trajectory itself was loaded with, or the indices address different frames. */
export const getOxdnaFramesAtomistic = (id, frameIndices, align=true, scope='lineage') =>
  _oxdnaJSON('POST', `/oxdna/jobs/${id}/frames-atomistic?align=${align}&scope=${scope}`, { frame_indices: frameIndices })
/** Per-frame SURFACE meshes for trajectory frame indices (surface-batch wire format). */
export const getOxdnaFramesSurface = (id, frameIndices, params = {}, align=true, scope='lineage') =>
  _oxdnaJSON('POST', `/oxdna/jobs/${id}/frames-surface?align=${align}&scope=${scope}`, { frame_indices: frameIndices, ...params })
/** All-atom flat-XYZ for the relaxed-display structure ({ready, atomistic:[x,y,z,…]}) —
 *  lets the OxDNA-display toggle drive the atomistic rep, not just CG beads. */
export const getOxdnaDisplayAtomistic = (id, align = true) =>
  _oxdnaJSON('POST', `/oxdna/jobs/${id}/display-atomistic?align=${align ? 'true' : 'false'}`)
/** The JOB design's atomistic model ({atoms, bonds, topology_hash}) — for rebuilding the
 *  renderer from the topology the relaxed positions belong to (loaded design may differ). */
export const getOxdnaAtomisticModel = (id) =>
  _oxdnaJSON('GET', `/oxdna/jobs/${id}/atomistic-model`)
/** Design-FIXED stamp descriptor ({atom_nuc, atom_local, nonrigid_serials, topology_hash})
 *  — fetched ONCE per job; drives the fast client-side CG→atomistic expansion. */
export const getOxdnaAtomisticStamp = (id) =>
  _oxdnaJSON('GET', `/oxdna/jobs/${id}/atomistic-stamp`)
/** COMBINED renderer topology (atoms+bonds) + stamp descriptor in one disk-cached build
 *  — fetched once per job; the fast path's single setup fetch (replaces model + stamp). */
/** Renderer topology (atoms [+bonds]) + stamp descriptor for a job, one disk-cached build.
 *  `bonds:false` omits the ~370k-pair bond list — the VDW rep draws no cylinders, so it
 *  would parse megabytes it never uses. */
export const getOxdnaAtomisticDisplayBundle = (id, { bonds = true } = {}) =>
  _oxdnaJSON('GET', `/oxdna/jobs/${id}/atomistic-display-bundle${bonds ? '' : '?bonds=false'}`)
/** BINARY/columnar sibling of the above (ArrayBuffer) — ~7× smaller AND no 330k-object
 *  JSON.parse; decode with scene/atomistic_bundle_bin.js. Null on error/absence, which is
 *  the signal to fall back to the JSON route. Carries bonds unconditionally: they are only
 *  ~3 MB of the packed blob, so a separate bond-less variant isn't worth the cache split. */
export const getOxdnaAtomisticDisplayBundleBin = (id) =>
  _oxdnaBin('GET', `/oxdna/jobs/${id}/atomistic-display-bundle-bin`)
/** Compact per-frame atomistic payload ({ready, frames:[12·nNuc], nonrigid_xyz, topology_hash})
 *  — per-nucleotide (origin,R) + non-rigid XYZ; expand with scene/atomistic_stamp.js. */
export const getOxdnaDisplayAtomisticFrames = (id, align = true) =>
  _oxdnaJSON('POST', `/oxdna/jobs/${id}/display-atomistic-frames?align=${align ? 'true' : 'false'}`)
/** Molecular surface for the relaxed-display structure ({ready, surface:{vertices,faces,…}}). */
export const getOxdnaDisplaySurface = (id, align = true, params = {}) =>
  _oxdnaJSON('POST', `/oxdna/jobs/${id}/display-surface?align=${align ? 'true' : 'false'}`, params)
/** BINARY surface mesh (ArrayBuffer) for the relaxed-display structure — ~2× smaller than
 *  JSON and no million-number parse; decode with scene/surface_bin.js. Null on error. */
export const getOxdnaDisplaySurfaceBin = (id, align = true, params = {}) =>
  _oxdnaBin('POST', `/oxdna/jobs/${id}/display-surface-bin?align=${align ? 'true' : 'false'}`, params)
/** BINARY molecular surface (ArrayBuffer) for the ACTIVE DESIGN — the binary sibling of the
 *  /design/surface JSON (~2× smaller, no million-number parse; carries the strand-index table
 *  so the surface still recolours client-side). Decode with scene/surface_bin.js. Null on error. */
export const getDesignSurfaceBin = ({ color_mode = 'strand', probe_radius = 0.28,
                                      detail = 'coarse' } = {}) =>
  _oxdnaBin('GET', `/design/surface-bin?color_mode=${color_mode}`
                   + `&probe_radius=${probe_radius}&detail=${detail}`)
/** All-atom flat-XYZ for the flexibility-map AVERAGE structure ({ready, atomistic:[…]}). */
export const getOxdnaRmsfAtomistic = (id, opts) => {
  const { align } = _vizOpts(opts, 'getOxdnaRmsfAtomistic')
  return _oxdnaJSON('POST', `/oxdna/jobs/${id}/rmsf-atomistic?align=${align}`)
}
/** Molecular surface for the flexibility-map AVERAGE structure ({ready, surface:{…}}). */
export const getOxdnaRmsfSurface = (id, params = {}, opts) => {
  const { align } = _vizOpts(opts, 'getOxdnaRmsfSurface')
  return _oxdnaJSON('POST', `/oxdna/jobs/${id}/rmsf-surface?align=${align}`, params)
}

// ── Ephemeral LIVE oxDNA field session (routes_oxdna_live.py) ────────────────
// An in-process oxpy run that stores NO job — seeded from a completed relaxed
// job, re-aimable in (near) real time.  Display-only; never mutates topology.
export const oxdnaLiveAvailable  = ()            => _oxdnaJSON('GET',  '/oxdna/live/available')
export const startOxdnaLive      = (body)        => _oxdnaJSON('POST', '/oxdna/live/start', body)
export const updateOxdnaLiveField = (id, body)   => _oxdnaJSON('POST', `/oxdna/live/${id}/field`, body)
export const reconfigureOxdnaLive = (id, body)   => _oxdnaJSON('POST', `/oxdna/live/${id}/reconfigure`, body)
export const getOxdnaLiveFrame   = (id)          => _oxdnaJSON('GET',  `/oxdna/live/${id}/frame`)
export const stopOxdnaLive       = (id)          => _oxdnaJSON('POST', `/oxdna/live/${id}/stop`)

// ── mrDNA / ARBD coarse-grained relaxation jobs (routes_mrdna.py) ────────────
// Sibling of the oxDNA job API, simplified to a single coarse ARBD stage (one
// Run button).  Display-only; never mutates topology.  Reuse the same _oxdnaJSON
// transport (design-sync-free JSON).
export const mrdnaAvailable      = ()            => _oxdnaJSON('GET',  '/mrdna/available')
export const createMrdnaJob      = (body)        => _oxdnaJSON('POST', '/mrdna/jobs', body)
export const listMrdnaJobs       = ()            => _backgroundJobList('/mrdna/jobs')
export const getMrdnaJob         = (id)          => _oxdnaJSON('GET',  `/mrdna/jobs/${id}`)
export const getMrdnaProgress    = (id)          => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/progress`)
export const getMrdnaErrorLog    = (id)          => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/error-log`)
export const startMrdnaJob       = (id)          => _oxdnaJSON('POST', `/mrdna/jobs/${id}/start`)
export const stopMrdnaJob        = (id)          => _oxdnaJSON('POST', `/mrdna/jobs/${id}/stop`)
export const deleteMrdnaJob      = (id)          => _oxdnaJSON('DELETE', `/mrdna/jobs/${id}`)
export const getMrdnaDisplay     = (id, signal)  => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/display`, undefined, { signal })
export const getMrdnaBeads       = (id, signal)  => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/beads`, undefined, { signal })
export const getMrdnaSnapshotGeometry = (id, signal) => _oxdnaJSON('GET', `/mrdna/jobs/${id}/snapshot-geometry`, undefined, { signal })
export const getMrdnaRmsf        = (id, signal)  => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/rmsf`, undefined, { signal })
export const getMrdnaDeviation   = (id, signal)  => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/deviation`, undefined, { signal })
export const getMrdnaStrain      = (id, signal)  => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/strain`, undefined, { signal })
/** Designed (analytic Dietz) vs simulated (mrDNA) curvature for a completed job. */
export const getMrdnaCurvature   = (id)          => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/curvature`)
/** Analytic curvature of the ACTIVE design's loop/skip pattern (instant, no run). */
export const getMrdnaAnalyticCurvature = ()      => _oxdnaJSON('GET',  '/mrdna/curvature/analytic')

// ── CanDo FEM shape-prediction jobs (routes_cando.py) ───────────────────────
// Native CanDo-replica FEM: Coarse = linear preview, Fine = nonlinear corotational
// solve.  Pure in-process solver (no GPU), so /available is always true.  Output is
// Physical-layer / display-only; never mutates topology.  Same _oxdnaJSON transport.
export const candoAvailable      = ()            => _oxdnaJSON('GET',  '/cando/available')
export const createCandoJob      = (body)        => _oxdnaJSON('POST', '/cando/jobs', body)
export const listCandoJobs       = ()            => _backgroundJobList('/cando/jobs')
export const getCandoJob         = (id)          => _oxdnaJSON('GET',  `/cando/jobs/${id}`)
export const getCandoProgress    = (id)          => _oxdnaJSON('GET',  `/cando/jobs/${id}/progress`)
export const getCandoErrorLog    = (id)          => _oxdnaJSON('GET',  `/cando/jobs/${id}/error-log`)
export const startCandoJob       = (id)          => _oxdnaJSON('POST', `/cando/jobs/${id}/start`)
export const stopCandoJob        = (id)          => _oxdnaJSON('POST', `/cando/jobs/${id}/stop`)
export const deleteCandoJob      = (id)          => _oxdnaJSON('DELETE', `/cando/jobs/${id}`)
export const getCandoDisplay     = (id, signal)  => _oxdnaJSON('GET',  `/cando/jobs/${id}/display`, undefined, { signal })
/** Full geometry of the job's OWN design snapshot (topology at solve time), for the
 *  display modes to render instead of the live model. */
export const getCandoSnapshotGeometry = (id, signal) => _oxdnaJSON('GET',  `/cando/jobs/${id}/snapshot-geometry`, undefined, { signal })
/** Per-bp RMSF (nm) for the flexibility map (Item 3). */
export const getCandoRmsf        = (id, signal)  => _oxdnaJSON('GET',  `/cando/jobs/${id}/rmsf`, undefined, { signal })
/** 298 K normal-mode ensemble and its representative static conformation. */
export const getCandoThermalTrajectory = (id, signal) => _oxdnaJSON('GET', `/cando/jobs/${id}/thermal-trajectory`, undefined, { signal })
/** Per-bp deviation from the intended (displayed) geometry + global RMSD (Item 3). */
export const getCandoDeviation   = (id, signal)  => _oxdnaJSON('GET',  `/cando/jobs/${id}/deviation`, undefined, { signal })
/** CanDo-style jointed-cylinder geometry (per-helix axis tubes + crossover joints). */
export const getCandoCylinders   = (id, signal)  => _oxdnaJSON('GET',  `/cando/jobs/${id}/cylinders`, undefined, { signal })
/** CanDo source bundle for the cross-engine comparison card (S5/C5): shared descriptors + RMSF. */
export const getCandoShapeSource = (id)          => _oxdnaJSON('GET',  `/cando/jobs/${id}/shape-source`)
/** mrDNA source bundle for the cross-engine comparison card (S5/M5): shared descriptors + CG-trajectory RMSF. */
export const getMrdnaShapeSource = (id)          => _oxdnaJSON('GET',  `/mrdna/jobs/${id}/shape-source`)
/** NAMD source bundle for the cross-engine comparison card (S5/N4): shared descriptors + trajectory RMSF (gold-override reference). */
export const getMdShapeSource    = (id)          => _oxdnaJSON('GET',  `/md/jobs/${id}/shape-source`)

// ── SNUPI FEM shape-prediction jobs (routes_snupi.py) ───────────────────────
// The SAME in-process FEM as CanDo, run with the anisotropic SNUPI material law
// (material="snupi"): validated ≥ CanDo vs MD at $0.  Coarse = linear, Fine = nonlinear.
// Output is Physical-layer / display-only; never mutates topology.
export const snupiAvailable      = ()            => _oxdnaJSON('GET',  '/snupi/available')
export const createSnupiJob      = (body)        => _oxdnaJSON('POST', '/snupi/jobs', body)
export const listSnupiJobs       = ()            => _backgroundJobList('/snupi/jobs')
export const getSnupiJob         = (id)          => _oxdnaJSON('GET',  `/snupi/jobs/${id}`)
export const getSnupiProgress    = (id)          => _oxdnaJSON('GET',  `/snupi/jobs/${id}/progress`)
export const getSnupiErrorLog    = (id)          => _oxdnaJSON('GET',  `/snupi/jobs/${id}/error-log`)
export const startSnupiJob       = (id)          => _oxdnaJSON('POST', `/snupi/jobs/${id}/start`)
export const stopSnupiJob        = (id)          => _oxdnaJSON('POST', `/snupi/jobs/${id}/stop`)
export const deleteSnupiJob      = (id)          => _oxdnaJSON('DELETE', `/snupi/jobs/${id}`)
export const getSnupiDisplay     = (id, signal)  => _oxdnaJSON('GET',  `/snupi/jobs/${id}/display`, undefined, { signal })
/** Full geometry of the job's OWN design snapshot (topology at solve time). */
export const getSnupiSnapshotGeometry = (id, signal) => _oxdnaJSON('GET',  `/snupi/jobs/${id}/snapshot-geometry`, undefined, { signal })
/** Per-bp RMSF (nm) for the flexibility map. */
export const getSnupiRmsf        = (id, signal)  => _oxdnaJSON('GET',  `/snupi/jobs/${id}/rmsf`, undefined, { signal })
export const getSnupiTrajectory  = (id, signal)  => _oxdnaJSON('GET',  `/snupi/jobs/${id}/trajectory`, undefined, { signal })
/** Per-bp deviation from the intended (displayed) geometry + global RMSD. */
export const getSnupiDeviation   = (id, signal)  => _oxdnaJSON('GET',  `/snupi/jobs/${id}/deviation`, undefined, { signal })
/** CanDo-style jointed-cylinder geometry (per-helix axis tubes + crossover joints). */
export const getSnupiCylinders   = (id, signal)  => _oxdnaJSON('GET',  `/snupi/jobs/${id}/cylinders`, undefined, { signal })
/** SNUPI source bundle for the cross-engine comparison card: shared descriptors + RMSF. */
export const getSnupiShapeSource = (id)          => _oxdnaJSON('GET',  `/snupi/jobs/${id}/shape-source`)

// ── BLADE implicit-solvent relax jobs (routes_blade.py) ────────────────────
// Box-free CHARMM36 + OBC2 atomistic relax — no explicit water, no periodic cell.  Unlike
// CanDo/SNUPI the compute is EXTERNAL (OpenMM in the micromamba gpu env via a detached
// worker), so `bladeAvailable` is a real probe that can say no, and Stop actually kills.
// Output is Physical-layer / display-only; never mutates topology.
export const bladeAvailable      = ()            => _oxdnaJSON('GET',  '/blade/available')
export const createBladeJob      = (body)        => _oxdnaJSON('POST', '/blade/jobs', body)
export const listBladeJobs       = ()            => _backgroundJobList('/blade/jobs')
export const getBladeJob         = (id)          => _oxdnaJSON('GET',  `/blade/jobs/${id}`)
export const getBladeProgress    = (id)          => _oxdnaJSON('GET',  `/blade/jobs/${id}/progress`)
export const getBladeErrorLog    = (id)          => _oxdnaJSON('GET',  `/blade/jobs/${id}/error-log`)
export const startBladeJob       = (id)          => _oxdnaJSON('POST', `/blade/jobs/${id}/start`)
export const stopBladeJob        = (id)          => _oxdnaJSON('POST', `/blade/jobs/${id}/stop`)
export const deleteBladeJob      = (id)          => _oxdnaJSON('DELETE', `/blade/jobs/${id}`)
/** The settled shape as {keys, frame} (same encoding as /trajectory) + the run summary. */
export const getBladeDisplay     = (id, signal)  => _oxdnaJSON('GET',  `/blade/jobs/${id}/display`, undefined, { signal })
/** Full geometry of the job's OWN design snapshot (topology at relax time). */
export const getBladeSnapshotGeometry = (id, signal) => _oxdnaJSON('GET',  `/blade/jobs/${id}/snapshot-geometry`, undefined, { signal })
/** The relaxation trajectory for the scrubber — oxDNA/SNUPI wire shape, reuses framesToUpdates. */
export const getBladeTrajectory  = (id, signal)  => _oxdnaJSON('GET',  `/blade/jobs/${id}/trajectory`, undefined, { signal })

// ── CanDo-FEM autorefine (Phase-5 Item 4): greedy loop/skip tuning driven by the FEM shape oracle.
/** Start a CanDo-FEM autorefine run on the active design → {autorefine_id, state}. */
export const startCandoAutorefine = (body)        => _oxdnaJSON('POST', '/design/cando/autorefine/start', body)
/** Poll a CanDo autorefine run → {state, phase, last_event, result?, error?}. */
export const getCandoAutorefine   = (id)          => _oxdnaJSON('GET',  `/design/cando/autorefine/${id}`)
/** Request cancellation of a running CanDo autorefine (exits at the next hotspot/trial). */
export const stopCandoAutorefine  = (id)          => _oxdnaJSON('POST', `/design/cando/autorefine/${id}/stop`)
/** Apply a completed CanDo autorefine's converged loop/skip marks to the active design. */
export const applyCandoAutorefine = (id)          => _oxdnaJSON('POST', `/design/cando/autorefine/${id}/apply`)

/** Create a NAMD MD job (routes_md.py).  Pass {oxdna_job_id} / {mrdna_job_id} /
 *  {blade_job_id} to seed the run from that completed job's relaxed coordinates
 *  instead of ideal B-DNA (BLADE seeds the EXACT all-atom conformation).  Pass
 *  {draft:true} (seeded only) to create an unprepared draft — solvation is
 *  deferred to prepareMdDraft ("Relax from oxDNA/BLADE"). */
// Named relaxation protocols for the panel's Protocol dropdown (backend owns the
// catalogue; see backend/core/md_presets.py).
export const getRelaxPresets     = ()            => _oxdnaJSON('GET',  '/md/relax-presets')
/** Every parameter a NAMD job WOULD run, per stage, without preparing anything — the
 *  Job Wizard's source of truth. Built server-side by running the real conf writers, so
 *  it cannot drift from what the run does. Writes nothing and (for a relaxation) touches
 *  no disk, so it is safe to re-request behind a short debounce as the user edits. */
export const fetchProtocolPlan   = (body)        => _oxdnaJSON('POST', '/md/protocol-plan', body)
export const createMdJob         = (body)        => _oxdnaJSON('POST', '/md/jobs', body)
/** Validate the selected NAMD run/download directory. With no path, the backend creates and
 * returns NADOC's portable <workspace>/md_jobs default. */
export const getMdRunDirStatus   = (path = null) =>
  _oxdnaJSON('GET', `/md/run-dir-status${path ? `?path=${encodeURIComponent(path)}` : ''}`)
/** Prepare (solvate) + start a DRAFT NAMD job with the given advanced settings
 *  (same body shape as createMdJob). Seeds from the draft's recorded oxDNA/mrDNA
 *  source; backs the "Relax from oxDNA" button. */
export const prepareMdDraft      = (id, body)    => _oxdnaJSON('POST', `/md/jobs/${id}/prepare`, body)
/** Forecast free-disk-after for a NAMD relaxation run (same body as createMdJob). */
export const estimateMdDisk      = (body)        => _oxdnaJSON('POST', '/md/jobs/estimate-disk', body)
/** Pre-flight water-box size verdict for a Relax launch (Gate A). Returns
 *  {tier:'ok'|'a3', ...full-box sizing advice} or {skipped:true,tier:'ok'}. */
export const preflightMdVram     = (body)        => _oxdnaJSON('POST', '/md/jobs/preflight-vram', body)
/** Forecast free-disk-after for a NAMD production stage (same body as appendMdProduction). */
export const estimateMdProductionDisk = (id, body) => _oxdnaJSON('POST', `/md/jobs/${id}/estimate-production-disk`, body)
/** List NAMD/MD jobs (for the trajectory-keyframe dropdown). */
export const listMdJobs          = ()            => _backgroundJobList('/md/jobs')
/** Start moving an MD job's folder to <destRoot>/<job_id> (background; poll status). */
export const archiveMdJob        = (id, destRoot) => _oxdnaJSON('POST', `/md/jobs/${id}/archive`, { dest_root: destRoot })
export const unarchiveMdJob      = (id)          => _oxdnaJSON('POST', `/md/jobs/${id}/unarchive`)
export const mdArchiveStatus     = (id)          => _oxdnaJSON('GET',  `/md/jobs/${id}/archive-status`)

// ── Host filesystem browse (archive folder picker, routes_fs.py) ────────────────
/** Subdirectories of an absolute host path (default: home). {path, parent, entries}. */
export const fsListDir           = (path)        => _oxdnaJSON('GET',  `/fs/listdir${path ? `?path=${encodeURIComponent(path)}` : ''}`)
/** Create a folder under an absolute host path; returns the refreshed listing. */
export const fsMkdir             = (path, name)  => _oxdnaJSON('POST', '/fs/mkdir', { path, name })
/** `?stride=N` when N is a usable frame interval, else ''. Kept out of the two
 *  fetchers below so they can't disagree about what counts as "no interval" —
 *  omitting it is what preserves the legacy 200-frame budget server-side. */
function _strideQuery(opts) {
  const s = _strideOrNull(opts)
  return s == null ? '' : `?stride=${s}`
}
function _strideOrNull(opts) {
  const s = Number(opts?.stride)
  return Number.isFinite(s) && s >= 1 ? Math.floor(s) : null
}
/** Same rule for the POST bodies — omit the key entirely when there's no usable
 *  interval, so the backend keeps its legacy downsample rather than seeing a null. */
function _strideBody(opts) {
  const s = _strideOrNull(opts)
  return s == null ? {} : { stride: s }
}
/** Composite NAMD trajectory ({keys, frames, markers, stages}) — same shape as
 *  getOxdnaTrajectory, so the animation trajectory path is shared.
 *  `opts.stride` = frame interval (every Nth frame of each segment, VMD-style);
 *  omit it for the legacy ≤200-frame budget. It is a third positional OBJECT, never
 *  a bare value, so it can't be mistaken for `signal` (see _oxdnaJSON's type check). */
export const getMdTrajectory     = (id, signal, opts = {}) =>
  _oxdnaJSON('GET',  `/md/jobs/${id}/trajectory${_strideQuery(opts)}`, undefined, { signal })
/** Frame count + segment markers only (no coordinates) — sizes the trajectory slider fast.
 *  Also returns `total_raw` + per-stage `n_raw` (undownsampled DCD counts). */
export const getMdTrajectoryMeta = (id, opts = {})       =>
  _oxdnaJSON('GET',  `/md/jobs/${id}/trajectory-meta${_strideQuery(opts)}`)
export const getMdTrajectoryProgress = (id) =>
  _oxdnaJSON('GET', `/md/jobs/${id}/trajectory-progress`)
/** Per-nucleotide flexibility map (RMSF) over the NAMD run — same shape as
 *  getOxdnaRmsf, so the flexibility-map display code is shared. */
export const getMdRmsf           = (id, signal)  => _oxdnaJSON('GET',  `/md/jobs/${id}/rmsf`, undefined, { signal })
/** NAMD atom coordinates for the flexibility ensemble's average structure. */
export const getMdRmsfAtomistic  = (id) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/rmsf-atomistic`)
/** NAMD molecular surface for the average structure, carrying per-vertex RMSF. */
export const getMdRmsfSurface    = (id, params = {}) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/rmsf-surface`, params)
/** Occupancy clouds for a NAMD run — same payload shape as the oxDNA twin, so the same
 *  overlay draws it. Only PRODUCTION (unrestrained) dynamics is clustered — frames from
 *  the restrained relaxation ladder describe the ramp, not the structure. */
export const getMdOccupancy = (id, signal, opts = {}) => {
  const { nClusters = 0, maxFrames = 200, basis = 'nt', refetch = false,
          sampling = 'fast', density = false } = opts
  return _oxdnaJSON('GET',
    `/md/jobs/${id}/occupancy?max_frames=${maxFrames}&n_clusters=${nClusters}`
    + `&basis=${basis}&refetch=${refetch}&sampling=${sampling}&density=${density}`,
    undefined, { signal })
}
/** Occupancy clouds restricted to picked clusters / strands / bases / crossover extra
 *  bases. POST because a base-level selection is far too big for a query string.
 *  `opts.fit` picks the frame the scoped set is re-superposed in — same vocabulary as the
 *  oxDNA twin, because both engines run the one shared `occupancy_fit_plan`. */
export const postMdOccupancy = (id, signal, opts = {}) => {
  const { nClusters = 0, maxFrames = 200, basis = 'nt', refetch = false,
          selection = null, fit = 'selection', sampling = 'fast', density = false } = opts
  return _oxdnaJSON('POST', `/md/jobs/${id}/occupancy`, {
    max_frames: maxFrames, n_clusters: nClusters, basis, refetch, selection, fit,
    sampling, density,
  }, { signal })
}
/** Kill the in-flight trajectory/RMSF/surface analysis for a job (view toggled
 *  off / job deselected) so a heavy MDAnalysis read of a live DCD can't run away.
 *  `kind` cancels one view; omit to cancel all. Never throws. */
export const cancelMdAnalysis = (id, kind) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/analysis/cancel${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`)
    .catch(() => null)
/** Per-frame NAMD heavy atoms ({idx:{atoms,bonds}}) for COMPOSITE trajectory frame
 *  indices. `opts.stride` must repeat the interval the trajectory was loaded with —
 *  a frame index only addresses the same frame within one interval. */
export const getMdFramesAtomistic = (id, frameIndices, opts = {}) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/frames-atomistic`,
    { frame_indices: frameIndices, ..._strideBody(opts),
      ...(opts.positionsOnly ? { positions_only: true } : {}) })
/** The NAMD job's STATIC heavy-atom set ({atoms, bonds, n_serials}) — fetch once, then
 *  stream coordinates with getMdFramesAtomistic(..., {positionsOnly:true}). Same
 *  contract as getOxdnaAtomisticModel. */
export const getMdAtomisticModel = (id) =>
  _oxdnaJSON('GET', `/md/jobs/${id}/atomistic-model`)
/** The design's intended extra-base UV weld pairs + their C5/C6 atom serials
 *  ({ready, pairs, constants}). Identity only — the viewer computes d_mid/eta from the
 *  frame it is already rendering, so the markers can't drift off the atoms. `pairs` is
 *  empty for a design with no insert-carrying reciprocal crossover pair (most designs). */
export const getMdCpdPairs = (id) =>
  _oxdnaJSON('GET', `/md/jobs/${id}/cpd-pairs`)
/** Start a background pass measuring (d_mid, eta, k) for the weld pairs over the WHOLE
 *  trajectory → {trace_id}. The overlay answers "how close now"; this answers "did they
 *  ever get close". Poll with getMdCpdTrace. */
export const startMdCpdTrace = (id, body = {}) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/cpd-trace/start`,
    { stride: body.stride ?? 1, max_frames: body.maxFrames ?? 2000,
      with_windows: !!body.withWindows })
/** Progress + result of a weld-trace run ({state, progress, frames_done, result?}). */
export const getMdCpdTrace = (traceId) =>
  _oxdnaJSON('GET', `/md/cpd-trace/${traceId}`)
/** Runnable Colvars config for this job's weld pair + the suggested umbrella window
 *  ladder ({ready, config, windows}). Preview only — launches nothing. */
export const getMdCpdColvars = (id, opts = {}) =>
  _oxdnaJSON('GET', `/md/jobs/${id}/cpd-colvars?mode=${opts.mode || 'metrics'}`
    + `&d_start_ang=${opts.dStartAng ?? 3.5}&d_end_ang=${opts.dEndAng ?? 12.0}`)
/** Per-frame NAMD surface ({idx:{vertices,faces}}) for COMPOSITE trajectory frame indices. */
export const getMdFramesSurface = (id, frameIndices, params = {}) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/frames-surface`,
    { frame_indices: frameIndices, ...params, ..._strideBody(params) })
/**
 * Per-frame explicit solvent + periodic cell, BINARY — decode with
 * scene/md_solvent_bin.js `parseSolventBin`. Returns an ArrayBuffer or null.
 *
 * COMPOSITE frame indices, and `opts.stride` must repeat the trajectory's interval
 * exactly like getMdFramesAtomistic.
 *
 * Options: `water`/`ions`/`box` toggles · `shellAng` (null = the whole cell) ·
 * `atomistic` (real O+2H instead of one sphere) · `maxWaters` (hard cap from the
 * measured memory budget) · `includeDna` (also return this frame's DNA coordinates,
 * so an atomistic-rep scrub pays the ~30 s server-side context build once per chunk
 * instead of twice).
 *
 * Follows the `(id, frameIndices, opts)` shape of its siblings. Never pass a
 * positional boolean or a bare AbortSignal to a viz fetcher — `_vizOpts` throws on
 * exactly that, because an `align` argument once silently bound to `signal` and
 * killed the NAMD trajectory scrub with a fully green suite.
 */
export const getMdFramesSolventBin = (id, frameIndices, opts = {}) =>
  _oxdnaBin('POST', `/md/jobs/${id}/frames-solvent-bin`, {
    frame_indices: frameIndices,
    ..._strideBody(opts),
    water: opts.water !== false,
    ions: opts.ions !== false,
    box: opts.box !== false,
    shell_ang: opts.shellAng === undefined ? 5.0 : opts.shellAng,
    atomistic: !!opts.atomistic,
    max_waters: opts.maxWaters ?? null,
    include_dna: !!opts.includeDna,
  })
/** How much solvent a NAMD job HAS ({ready, n_waters, n_ions, species, box_nm}) —
 *  read from the package's charge audit, so it answers in milliseconds and can price
 *  a fetch before one is made. */
export const getMdSolventMeta = (id) =>
  _oxdnaJSON('GET', `/md/jobs/${id}/solvent-meta`)

/** MD "Graphs and Metrics" — launch a background twist/curvature/base-pairing compute for a
 *  NAMD job (`{scope:'latest'|'chain'}`) → {metrics_id}; poll `getMdMetricsRun`. Same shape
 *  as the oxDNA metrics endpoints, so the shared metrics card reuses it. */
export const startMdMetrics      = (id, body)    => _oxdnaJSON('POST', `/md/jobs/${id}/metrics/start`, body)
/** Poll an MD metric run → {state, progress, eta_s, frames_done, frames_total, result?}. */
export const getMdMetricsRun     = (runId)       => _oxdnaJSON('GET',  `/md/metrics/${runId}`)

// NAMD MD job lifecycle (routes_md.py).  All go through _oxdnaJSON so the tab's
// X-NADOC-Doc header is ALWAYS stamped — the staleness/out-of-date checks read the
// active design from that document, so a missing header silently compares against
// the wrong (default) doc.  Do NOT call these endpoints with a bare `fetch`.
export const getMdJob            = (id)          => _oxdnaJSON('GET',    `/md/jobs/${id}`)
export const deleteMdJob         = (id)          => _oxdnaJSON('DELETE', `/md/jobs/${id}`)
export const startMdJob          = (id)          => _oxdnaJSON('POST',   `/md/jobs/${id}/start`)
export const prepareMdSequenceJob = (id)         => _oxdnaJSON('POST',   `/md/jobs/${id}/prepare-sequence`)
/** Attach (or clear) anchors + E-field on a PREPARED-but-not-started job. Patches the
 *  existing package's confs in place — no re-solvation. Send `anchors: []`/`field: null`
 *  to clear. NAMD has no floor implementation, so no surface is sent. */
/** What a job is ACTUALLY anchored/fielded with, from its own manifest. The anchors card
 *  was write-only for its whole life — a selected run showed either someone else's
 *  unsubmitted selection or nothing. This is the read side. */
export const getMdJobForces      = (id)          => _oxdnaJSON('GET',    `/md/jobs/${id}/forces`)
export const setMdJobForces      = (id, body)    => _oxdnaJSON('POST',   `/md/jobs/${id}/forces`, body)
export const stopMdJob           = (id)          => _oxdnaJSON('POST',   `/md/jobs/${id}/stop`)
/** Flip the relaxation early-stop accelerator on a job without relaunching. */
export const setMdEarlyStop      = (id, enabled) => _oxdnaJSON('POST',   `/md/jobs/${id}/early-stop`, { enabled })
// ── The NAMD run queue ────────────────────────────────────────────────────────
// The machine runs one NAMD job at a time, so a prepared job can be parked behind the
// one that's going. The queue lives on the SERVER (backend/core/md_queue.py) and the
// server starts the next job itself — closing the tab does not cancel what's waiting.
// All four return {queue, running_job_id, busy}.
export const getMdQueue          = ()            => _oxdnaJSON('GET',    '/md/queue')
export const enqueueMdJob        = (id)          => _oxdnaJSON('POST',   '/md/queue', { job_id: id })
export const dequeueMdJob        = (id)          => _oxdnaJSON('DELETE', `/md/queue/${id}`)
export const reorderMdQueue      = (ids)         => _oxdnaJSON('PUT',    '/md/queue', { job_ids: ids })
/** Append a production stage (the "continue from previous run" path). Body:
 *  {steps, autostart, continue_from_production}. 409 when the active design ≠ the
 *  job's — hence the doc header must be correct (see block comment above). */
export const appendMdProduction  = (id, body)    => _oxdnaJSON('POST',   `/md/jobs/${id}/production`, body)
/** Branch a production run off a completed relaxation (or production) as a CHILD job,
 *  seeded from the parent's equilibrated coords with a distinct velocity seed. Body:
 *  {steps, length_ns, autostart}. Relaxation stays selectable; children nest under it. */
export const spawnMdProduction   = (id, body)    => _oxdnaJSON('POST',   `/md/jobs/${id}/production-run`, body)
/** Migrate a legacy job whose production was appended onto the relaxation back to a
 *  clean relaxation (production artifacts moved to _superseded_production/, not deleted),
 *  so relax + production become separate entries. */
export const revertMdProduction  = (id)          => _oxdnaJSON('POST',   `/md/jobs/${id}/revert-production`)
export const refitMdJob          = (id, body)    => _oxdnaJSON('POST',   `/md/jobs/${id}/refit`, body)
/** Resolve a paused job's GPU-resident fallback decision (Gate B). choice: "offload"
 *  (run the slower GPU mode, then resume) or "cancel" (stop the job). */
export const resolveMdGpuDecision = (id, choice)  => _oxdnaJSON('POST',   `/md/jobs/${id}/gpu-decision`, { choice })
/** Live-display metadata for a job ({ready, config_path, …}). */
export const getMdDisplayMeta    = (id)          => _oxdnaJSON('GET',    `/md/jobs/${id}/display`)
/** Pull ONE current frame off a job still running on the cluster, so it can be
 *  displayed.  Cheap counterpart to the whole-output `fetch-remote`: one
 *  `.restart.coor`, not a multi-GB DCD.  Needs a live (Duo) cluster session. */
export const fetchMdLiveFrame    = (id, force = false) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/fetch-live-frame${force ? '?force=true' : ''}`)
export const startMdLiveFrameRefresh = (id) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/fetch-live-frame/start`)
export const getMdLiveFrameRefreshProgress = (id) =>
  _oxdnaJSON('GET', `/md/jobs/${id}/fetch-live-frame/progress`)
export const getMdJobMetrics     = (id)          => _oxdnaJSON('GET',    `/md/jobs/${id}/metrics`)
export const getMdJobFixAdvice   = (id)          => _oxdnaJSON('GET',    `/md/jobs/${id}/fix-advice`)
/** NAMD/GROMACS availability + recommended thread count. */
export const namdAvailable       = ()            => _oxdnaJSON('GET',    '/md/namd-available')

// ── Multi-stage chains (P — job planner). Queue an MdPipeline that runs unattended,
//    stage N seeded from stage N-1; a halted chain resumes from its failed stage. ─────
export const createChain         = (body)        => _oxdnaJSON('POST', '/md/chains', body)
export const listMdChains        = ()            => _oxdnaJSON('GET',  '/md/chains')
export const getMdChain          = (id)          => _oxdnaJSON('GET',  `/md/chains/${id}`)
export const resumeMdChain       = (id, body = {}) => _oxdnaJSON('POST', `/md/chains/${id}/resume`, body)

// ── Remote (Alpine/SLURM) execution — Phase 4 submit-review flow ───────────────
/** Preview the auto-recommended SLURM resources for a prepared job (read-only, no
 *  cluster connection needed). Returns {prepared:false,…} while still preparing. */
export const getMdRemoteRecommendation = (id, { clusterName = 'alpine', safetyFactor = 1.5, partition = null, current = false } = {}) => {
  let url = `/md/jobs/${id}/remote-recommendation?cluster_name=${encodeURIComponent(clusterName)}&safety_factor=${safetyFactor}`
  if (partition) url += `&partition=${encodeURIComponent(partition)}`
  if (current) url += '&current=true'
  return _oxdnaJSON('GET', url)
}
/** Stage + submit a prepared job to the cluster. `resources` omitted → auto-recommend. */
export const submitMdJobRemote   = (id, body = {}) => _oxdnaJSON('POST', `/md/jobs/${id}/submit-remote`, body)
/** Replace settings and rebuild an unstarted draft/prepared job in place. */
export const updateMdJobSettings = (id, body = {}) => _oxdnaJSON('PUT', `/md/jobs/${id}/settings`, body)
/** Resume a timed-out remote job from its last checkpoint (new SLURM submission). */
export const resumeMdJobRemote   = (id, body = {}) => _oxdnaJSON('POST', `/md/jobs/${id}/resume-remote`, body)
export const finishMdJob = (id, destRoot) =>
  _oxdnaJSON('POST', `/md/jobs/${id}/finish-and-download`, { dest_root: destRoot })
export const mdDownloadStatus = (id) => _oxdnaJSON('GET', `/md/jobs/${id}/download-status`)
/** Stage N production replicas (distinct seeds) from a completed parent (offline; no cluster session). */
export const stageMdEnsemble     = (id, body = {}) => _oxdnaJSON('POST', `/md/jobs/${id}/ensemble-production`, body)
/** Submit every prepared replica of a parent to the cluster in one action (needs a live session). */
export const submitMdEnsemble    = (id, body = {}) => _oxdnaJSON('POST', `/md/jobs/${id}/ensemble-submit`, body)
/** Current cluster connection status ({state, who, host}); used to gate the Alpine target. */
export const getClusterStatus    = ()            => _oxdnaJSON('GET',    '/cluster/status')
/**
 * Live per-partition GPU availability + queue-wait estimate (needs a live session).
 * `jobId` shapes the estimate around a specific prepared job; `force` bypasses the
 * backend's 60 s probe cache (the popup's Re-check button).
 */
/**
 * The SLURM request a job WOULD be submitted with, before it exists — resolved
 * resources plus the literal sbatch header. Offline; no cluster session needed.
 */
export const getSlurmPreview = (body = {}) => _oxdnaJSON('POST', '/cluster/slurm-preview', body)
export const getClusterAvailability = ({ jobId = null, force = false, historyDays = 30 } = {}) => {
  const q = new URLSearchParams()
  if (jobId) q.set('job_id', jobId)
  if (force) q.set('force', 'true')
  if (historyDays !== 30) q.set('history_days', String(historyDays))
  const qs = q.toString()
  return _oxdnaJSON('GET', `/cluster/availability${qs ? `?${qs}` : ''}`)
}

// ── Cluster rigid transforms ──────────────────────────────────────────────────

export async function createCluster(body) {
  const json = await _request('POST', '/design/cluster', body)
  return _syncFromDesignResponse(json)
}

export async function patchCluster(clusterId, body) {
  const json = await _request('PATCH', `/design/cluster/${clusterId}`, body)
  if (!json) return null
  if (body.commit) {
    // Plan B: commit goes through the full design/validation sync but
    // SKIPS the geometry refetch. The gizmo's live-drag has already painted
    // the world-space cluster-transformed positions into the renderer's
    // instance buffers; the backend's role here is just to persist
    // `cluster_transforms[idx]`. The caller (cluster_gizmo /
    // _confirmTranslateRotateTool) is responsible for calling
    // helixCtrl.commitClusterPositions(helix_ids) after a successful commit
    // so currentGeometry mirrors the rendered state for downstream consumers.
    return _syncFromDesignResponse(json, { skipGeometry: true })
  }
  // Live drag: minimal update (design only). No broadcast (would spam other
  // tabs at frame rate). Don't touch loopStrandIds: cluster transforms can't
  // change strand topology, and writing a new array reference triggers a
  // full design_renderer rebuild.
  const updates = {}
  if (json.design)     updates.currentDesign     = json.design
  if (json.validation) updates.validationReport  = json.validation
  store.setState(updates)
  return json
}

export async function deleteCluster(clusterId) {
  const json = await _request('DELETE', `/design/cluster/${clusterId}`)
  return _syncFromDesignResponse(json)
}

// ── Independent atomistic nucleotide transforms ─────────────────────────────

export async function putNucleotideTransform(body) {
  const json = await _request('PUT', '/design/nucleotide-transform', body)
  // "extra_base" poses aren't baked into backend geometry (applied client-side
  // instead), so those responses flag geometry_unchanged — same contract as
  // the extra-bases routes. "base" poses DO move real geometry and arrive
  // through the normal partial/full path, where this flag is absent.
  return _syncFromDesignResponse(json, { skipGeometry: json?.geometry_unchanged === true })
}

export async function deleteNucleotideTransform(transformId) {
  const json = await _request('DELETE', `/design/nucleotide-transform/${transformId}`)
  return _syncFromDesignResponse(json, { skipGeometry: json?.geometry_unchanged === true })
}

/**
 * Paste a copy of `clusterIds` at a lattice offset (Ctrl+C / Ctrl+V).
 * `(deltaRow + deltaCol)` must be EVEN — an odd shift flips helix polarity and moves
 * every crossover off its allowed bp phase; the backend 400s on it. bp indices are
 * copied verbatim (Δbp = 0). Emits a `cluster-paste` feature-log entry.
 * Returns the design response plus `pasteReport` (what the copy actually grabbed).
 */
export async function pasteClusters({ clusterIds, deltaRow, deltaCol }) {
  const json = await _request('POST', '/design/cluster-paste', {
    cluster_ids: clusterIds, delta_row: deltaRow, delta_col: deltaCol,
  })
  if (!json) return null
  await _syncFromDesignResponse(json)
  return { ...json, pasteReport: json.paste_report }
}

/** List an overhang-DUPLEX cluster's candidate rotation points (each overhang's root bead
 *  + the centroid). Returns [{kind, overhang_id, label, point}]. Doc-aware (routes to this
 *  tab's backend document). [[overhang-duplex-cluster]] P2. */
export async function getClusterRotationPoints(clusterId) {
  const json = await _request('GET', `/design/cluster/${encodeURIComponent(clusterId)}/rotation-points`)
  return json?.rotation_points ?? []
}

/** Free-until-taut drag tethers for a DUPLEX cluster (each applied connection's backbone
 *  bond as {moving, fixed, contour_nm}). Doc-aware. [[overhang-duplex-cluster]] P3. */
export async function getClusterDuplexTethers(clusterId) {
  const json = await _request('GET', `/design/cluster/${encodeURIComponent(clusterId)}/duplex-tethers`)
  return json?.tethers ?? []
}

/** Free-until-taut drag tethers from a REGULAR cluster's applied overhang CONNECTIONS
 *  (direct duplex + ss/ds linker bridge) to the partner cluster, as {moving, fixed,
 *  contour_nm}. Merged with ssDNA flexible tethers for the "Constrained (tethers)" drag. */
export async function getClusterConnectionTethers(clusterId) {
  const json = await _request('GET', `/design/cluster/${encodeURIComponent(clusterId)}/connection-tethers`)
  return json?.tethers ?? []
}

/** Movable intermediate links (overhang-duplex bodies) for dragging a regular cluster: each link
 *  swings live to follow the drag, anchored to the fixed partner part. Carries its bonds to both
 *  parts (`part_dragged` marks the bond on the dragged cluster). */
export async function getClusterMovableLinks(clusterId) {
  const json = await _request('GET', `/design/cluster/${encodeURIComponent(clusterId)}/movable-links`)
  return json?.links ?? []
}

/** Set an overhang-DUPLEX cluster's rotation pivot to one of its candidate points
 *  (an overhang's root bead — {kind:'overhang_root', overhangId} — or {kind:'centroid'}).
 *  The backend rebases the translation so the geometry doesn't jump. [[overhang-duplex-cluster]] P2. */
export async function setClusterRotationPoint(clusterId, { kind, overhangId } = {}) {
  const body = { kind }
  if (overhangId) body.overhang_id = overhangId
  const json = await _request('POST', `/design/cluster/${encodeURIComponent(clusterId)}/rotation-point`, body)
  return _syncFromDesignResponse(json)
}

/**
 * Plan B companion: ask the backend to re-emit ds-linker bridge nucs after a
 * cluster commit. Bridge midpoints are derived from live OH anchor positions,
 * so they go stale when one cluster moves and the other doesn't. The endpoint
 * computes only the affected partial geometry and returns just the bridge nucs.
 *
 * @param {string[]} clusterIds  IDs of clusters whose transforms changed.
 *                               Pass [] to refresh all bridges.
 * @returns {Promise<Array<object>>}  Updated bridge nuc dicts (helix_id starts
 *                                    with `__lnk__`); empty array if no ds
 *                                    linkers, or none affected.
 */
export async function refreshBridges(clusterIds) {
  const json = await _request('POST', '/design/refresh-bridges', { cluster_ids: clusterIds ?? [] })
  return json?.bridge_nucs ?? []
}

// ── Cluster joints ────────────────────────────────────────────────────────────

export async function createJoint(clusterId, body) {
  const json = await _request('POST', `/design/cluster/${clusterId}/joint`, body)
  return _syncFromDesignResponse(json)
}

export async function patchJoint(jointId, body) {
  const json = await _request('PATCH', `/design/joint/${jointId}`, body)
  return _syncFromDesignResponse(json)
}

export async function deleteJoint(jointId) {
  const json = await _request('DELETE', `/design/joint/${jointId}`)
  return _syncFromDesignResponse(json)
}

export async function rollbackLastFeature() {
  const json = await _request('DELETE', '/design/features/last')
  return _syncFromDesignResponse(json)
}

// "Roll to a job's state": restore the design to the EXACT snapshot an oxDNA/MD job
// was run at (sequences + manual edits intact, unlike a feature-log seek), saving the
// current edits as a "Return to latest" loadout branch. Returns the design response +
// `return_loadout_id`. _request syncs the design response → the scene rebuilds.
export async function rollOxdnaJobDesign(jobId) {
  const json = await _request('POST', `/oxdna/jobs/${jobId}/roll-design`)
  if (json) await _syncFromDesignResponse(json)   // apply the seeked design (scene + feature-log cursor)
  return json
}
export async function rollMdJobDesign(jobId) {
  const json = await _request('POST', `/md/jobs/${jobId}/roll-design`)
  if (json) await _syncFromDesignResponse(json)
  return json
}

export async function deleteFeature(index, subIndex = null, { cascade = false } = {}) {
  // subIndex targets a single sub-step inside a Fine Routing cluster; omit it
  // (or pass null) to delete the whole top-level entry.
  const params = []
  if (subIndex != null) params.push(`sub_index=${subIndex}`)
  if (cascade) params.push('cascade=true')
  const path = params.length
    ? `/design/features/${index}?${params.join('&')}`
    : `/design/features/${index}`
  const json = await _request('DELETE', path)
  // Deleting a topology-producing op whose later entries depend on it returns a
  // (non-mutating) decision payload instead of a design — the caller shows the
  // dependent list and re-calls with {cascade:true} or reverts. Pass it through
  // untouched (no design to sync).
  if (json?.needs_cascade_decision) return json
  // Backend now picks between the fast-path responses (cluster_only /
  // positions_only) and the embedded full-geometry response so a cluster_op
  // deletion lands in the lean path. Caller is expected to invoke
  // _applyClusterUndoRedoDeltas / _applyPositionsOnlyDiff for those branches
  // (matches the seek/undo/redo pattern).
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

export async function createLoadout(name) {
  const json = await _request('POST', '/design/loadouts', { name })
  return _syncFromDesignResponse(json)
}

export async function selectLoadout(loadoutId, { saveCurrent = true } = {}) {
  const q = saveCurrent ? '' : '?save_current=false'
  const json = await _request('POST', `/design/loadouts/${loadoutId}/select${q}`)
  return _syncFromDesignResponse(json)
}

export async function renameLoadout(loadoutId, name) {
  const json = await _request('PATCH', `/design/loadouts/${loadoutId}`, { name })
  return _syncFromDesignResponse(json)
}

export async function deleteLoadout(loadoutId) {
  const json = await _request('DELETE', `/design/loadouts/${loadoutId}`)
  return _syncFromDesignResponse(json)
}

/**
 * Restore the pre-state snapshot of an auto-op SnapshotLogEntry and truncate
 * the feature log to entries strictly before it. Pre-revert state is pushed
 * onto the undo stack so Ctrl-Z restores it.
 *
 * Returns 410 if the entry's snapshot was evicted to free space.
 * Returns 400 if the entry is not a snapshot type.
 *
 * ``subIndex`` (optional) reverts to just BEFORE a single sub-step inside a
 * Fine Routing cluster: children[0..subIndex-1] are kept, that sub-step and
 * everything after it is dropped.
 */
export async function revertToBeforeFeature(index, subIndex = null) {
  const path = subIndex == null
    ? `/design/features/${index}/revert`
    : `/design/features/${index}/revert?sub_index=${subIndex}`
  const json = await _request('POST', path)
  const result = await _syncFromDesignResponse(json)
  _clearStaleSelections()
  return result
}

/** Drop non-selection UI scope whose owner no longer exists.
 * Canonical selection reconciliation is owned by main's selection controller
 * subscriber and runs synchronously when currentDesign changes. */
function _clearStaleSelections() {
  const state = store.getState()
  const design = state.currentDesign
  const strandIds = new Set((design?.strands ?? []).map(s => s.id))
  const updates = {}

  if (state.isolatedStrandId && !strandIds.has(state.isolatedStrandId)) {
    updates.isolatedStrandId = null
  }

  if (Object.keys(updates).length > 0) store.setState(updates)
}

/**
 * Replay the extrusion at feature_log[index] with new parameters.
 *
 * Only works for extrusion op_kinds (bundle-create, extrude-*, overhang-extrude)
 * AND when no later SnapshotLogEntry exists in the log (otherwise 409).
 *
 * @param {number} index  feature_log index of the snapshot to edit
 * @param {object} params new request body, in the format originally sent to
 *                        the extrude endpoint
 */
export async function editFeature(index, params) {
  const json = await _request('POST', `/design/features/${index}/edit`, { params })
  // Edit responses now go through _design_replace_response on the backend so
  // they may take the lean fast paths when the diff is small (deformation
  // edits often hit positions_only since topology is unchanged).
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

/**
 * Seek the feature log to a position. ``subPosition`` is honored when ``position``
 * indexes a RoutingClusterLogEntry: ``null`` → cluster post-state (all children
 * active); ``-2`` → cluster pre-state; ``0..M-1`` → first ``subPosition+1``
 * children active.
 *
 * Mirrors undo/redo: if the seek changes only cluster_transforms (common when
 * scrubbing through cluster_op entries), the backend returns a lean
 * ``diff_kind: 'cluster_only'`` response and the caller is expected to apply
 * the delta via the same renderer fast path used for undo/redo.
 */
export async function seekFeatures(position, subPosition = null) {
  const json = await _request('POST', '/design/features/seek', {
    position,
    sub_position: subPosition,
  }, { suppressBusy: true })
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

/**
 * Fetch pre-computed geometry for multiple feature-log positions in one request.
 * Stateless — does not change the design cursor.
 * Used by the animation player to pre-bake keyframe states before playback.
 * @param {number[]} positions  e.g. [-2, 0, 1, -1]
 * @returns {Promise<Record<string, {nucleotides: object[], helix_axes: object[]}> | null>}
 */
export async function getGeometryBatch(positions, { signal, suppressBusy = false } = {}) {
  return _request('POST', '/design/features/geometry-batch', { positions }, { signal, suppressBusy })
}

/**
 * Fetch the design-layer steric-clash report over the POSED geometry.
 * Read-only; never mutates the design.
 * @returns {Promise<{clashes: object[], count: number, threshold_nm: number,
 *                     designed_margin_nm: number} | null>}
 */
export async function getClashes() {
  return _request('GET', '/design/clashes')
}

/**
 * Return flat atom-position arrays for multiple feature-log positions.
 * @param {number[]} positions  e.g. [-2, 0, 1, -1]
 * @returns {Promise<Record<string, number[]> | null>}  pos → [x0,y0,z0, x1,y1,z1, ...]
 */
export async function getAtomisticBatch(positions, { signal, suppressBusy = false } = {}) {
  return _request('POST', '/design/features/atomistic-batch', { positions }, { signal, suppressBusy })
}

/**
 * Return flat surface vertex arrays for multiple feature-log positions.
 * @param {number[]} positions
 * @param {string}  colorMode    'strand' | 'uniform'
 * @param {number}  probeRadius  nm
 * @param {number}  gridSpacing  nm
 * @returns {Promise<Record<string, {vertices: number[], vertex_count: number}> | null>}
 */
export async function getSurfaceBatch(positions, colorMode = 'strand', probeRadius = 0.28, gridSpacing = 0.20,
                                      { signal, suppressBusy = false } = {}) {
  return _request('POST', '/design/features/surface-batch', {
    positions,
    color_mode:   colorMode,
    probe_radius: probeRadius,
    grid_spacing: gridSpacing,
  }, { signal, suppressBusy })
}

/**
 * Molecular surface over ONLY the given column segments (per-region SURFACE rep).
 * `segments` = [{helix_id, bp_start, bp_end}]. Returns the raw mesh JSON
 * ({vertices, faces, vertex_strand_index*, stats}); NOT a design response.
 */
export async function getRegionSurface(segments, { colorMode = 'strand', probeRadius = 0.28,
                                                   signal, suppressBusy = false } = {}) {
  return _request('POST', '/design/surface/region', {
    segments,
    color_mode:   colorMode,
    probe_radius: probeRadius,
  }, { signal, suppressBusy })
}

export async function beginClusterDrag(clusterId) {
  return _request('POST', `/design/cluster/${clusterId}/begin-drag`)
}

export async function snapshotDesign() {
  return _request('POST', '/design/snapshot')
}

// ── Camera poses ──────────────────────────────────────────────────────────────
// Camera-pose mutations only touch ``design.camera_poses`` — they don't move
// any nucleotide. ``skipGeometry: true`` avoids the multi-second
// ``getGeometry()`` refetch that ``_syncFromDesignResponse`` would otherwise
// fire on every mutation.

export async function createCameraPose(name, { position, target, up, fov, orbitMode }) {
  const json = await _request('POST', '/design/camera-poses', {
    name, position, target, up, fov, orbit_mode: orbitMode,
  })
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function updateCameraPose(poseId, patch) {
  // patch may have: name, position, target, up, fov, orbitMode
  const body = { ...patch }
  if (body.orbitMode !== undefined) { body.orbit_mode = body.orbitMode; delete body.orbitMode }
  const json = await _request('PATCH', `/design/camera-poses/${poseId}`, body)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function deleteCameraPose(poseId) {
  const json = await _request('DELETE', `/design/camera-poses/${poseId}`)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function reorderCameraPoses(orderedIds) {
  const json = await _request('PUT', '/design/camera-poses/reorder', { ordered_ids: orderedIds })
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function createAssemblyCameraPose(name, { position, target, up, fov, orbitMode }) {
  const json = await _request('POST', '/assembly/camera-poses', {
    name, position, target, up, fov, orbit_mode: orbitMode,
  })
  return _syncFromAssemblyResponse(json)
}

export async function updateAssemblyCameraPose(poseId, patch) {
  const body = { ...patch }
  if (body.orbitMode !== undefined) { body.orbit_mode = body.orbitMode; delete body.orbitMode }
  const json = await _request('PATCH', `/assembly/camera-poses/${poseId}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteAssemblyCameraPose(poseId) {
  const json = await _request('DELETE', `/assembly/camera-poses/${poseId}`)
  return _syncFromAssemblyResponse(json)
}

export async function reorderAssemblyCameraPoses(orderedIds) {
  const json = await _request('PUT', '/assembly/camera-poses/reorder', { ordered_ids: orderedIds })
  return _syncFromAssemblyResponse(json)
}

// Animation, keyframe, and assembly-configuration helpers live in
// `./animation_endpoints.js` and are re-exported at the bottom of this file.

// ── Assembly ──────────────────────────────────────────────────────────────────

export async function getAssembly() {
  const json = await _request('GET', '/assembly')
  return _syncFromAssemblyResponse(json)
}

export async function createAssembly(name = 'Untitled') {
  const json = await _request('POST', '/assembly', { name })
  return _syncFromAssemblyResponse(json)
}

export async function getAssemblyContent() {
  const r = await fetch(`${BASE}/assembly/export`)
  if (!r.ok) return null
  return r.text()
}

export async function importAssembly(content, { docId } = {}) {
  const json = await _request('POST', '/assembly/import', { content }, { docId })
  return _syncFromAssemblyResponse(json)
}

/**
 * Trigger a browser download of the active assembly as a .nass file.
 */
export async function exportAssembly() {
  const r = await fetch(`${BASE}/assembly/export`)
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: errorDetailToMessage(json?.detail, r.statusText) } })
    return false
  }
  const disposition = r.headers.get('Content-Disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : 'assembly.nass'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return true
}

export async function addInstance(body) {
  const json = await _request('POST', '/assembly/instances', body)
  return _syncFromAssemblyResponse(json)
}

export async function duplicateInstance(instanceId, { offset, name } = {}) {
  const body = {}
  if (offset) body.offset = offset
  if (name)   body.name   = name
  const json = await _request('POST', `/assembly/instances/${encodeURIComponent(instanceId)}/duplicate`, body)
  return _syncFromAssemblyResponse(json)
}

// ── PartGroup (PowerPoint-style grouping) ──────────────────────────────────

export async function createGroup({ instanceIds = [], subgroupIds = [], name } = {}) {
  const body = { instance_ids: instanceIds, subgroup_ids: subgroupIds }
  if (name) body.name = name
  const json = await _request('POST', '/assembly/groups', body)
  return _syncFromAssemblyResponse(json)
}

export async function ungroup(groupId) {
  const json = await _request('DELETE', `/assembly/groups/${encodeURIComponent(groupId)}`)
  return _syncFromAssemblyResponse(json)
}

export async function patchGroup(groupId, { name, visible, representation, clearRepresentation, expanded } = {}) {
  const body = {}
  if (name !== undefined)          body.name = name
  if (visible !== undefined)       body.visible = visible
  if (representation !== undefined) body.representation = representation
  if (clearRepresentation)         body.clear_representation = true
  if (expanded !== undefined)      body.expanded = expanded
  const json = await _request('PATCH', `/assembly/groups/${encodeURIComponent(groupId)}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function duplicateGroup(groupId, { offset, name } = {}) {
  const body = {}
  if (offset) body.offset = offset
  if (name)   body.name   = name
  const json = await _request('POST', `/assembly/groups/${encodeURIComponent(groupId)}/duplicate`, body)
  return _syncFromAssemblyResponse(json)
}

/** Delete a group AND all its transitive members (cascade). To remove only the
 *  group wrapper while keeping the parts, use `ungroup`. */
export async function deleteGroupCascade(groupId) {
  const json = await _request('DELETE', `/assembly/groups/${encodeURIComponent(groupId)}/cascade`)
  return _syncFromAssemblyResponse(json)
}

/** Rigid transform of a group; rigidly-mated external partners follow. Pass
 *  either `translation` (3 floats) or `matrix` (16 floats, row-major 4×4). */
export async function transformGroup(groupId, { translation, matrix } = {}) {
  const body = {}
  if (translation) body.translation = translation
  if (matrix)      body.matrix      = matrix
  const json = await _request('POST', `/assembly/groups/${encodeURIComponent(groupId)}/transform`, body)
  return _syncFromAssemblyResponse(json)
}

export async function polymerizeAssembly(body) {
  const json = await _request('POST', '/assembly/polymerize', body)
  return _syncFromAssemblyResponse(json)
}

/** Polymerize a periodic part from a single instance (no hand-defined mate).
 *  body: { instance_id, count, direction }. The repeat transform is derived
 *  server-side from the part's is_periodic_seam forced ligations. */
export async function polymerizePeriodicAssembly(body) {
  const json = await _request('POST', '/assembly/polymerize-periodic', body)
  return _syncFromAssemblyResponse(json)
}

export async function patchInstance(id, body) {
  const json = await _request('PATCH', `/assembly/instances/${id}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function batchPatchInstances(patches, { skipSync = false } = {}) {
  const json = await _request('PATCH', '/assembly/instances/batch', { patches })
  // skipSync: persist server-side without re-syncing the store (used when the
  // caller has already updated the store, to avoid a redundant renderer rebuild).
  if (skipSync) return json
  return _syncFromAssemblyResponse(json)
}

/** Set the per-assembly representation used ONLY for photo-mode export
 *  ('working' = export current reps as-is). Stored on the assembly (saved to
 *  .nass); the working view is unchanged. The response carries
 *  `export_representation` through `_expandV2Assembly` into the store. */
export async function setAssemblyExportRepresentation(representation) {
  const json = await _request('POST', '/assembly/export-representation', { representation })
  return _syncFromAssemblyResponse(json)
}

export async function propagateFk(instanceId, transformValues) {
  const json = await _request('POST', '/assembly/propagate_fk', {
    instance_id: instanceId,
    transform:   { values: transformValues },
  })
  return _syncFromAssemblyResponse(json)
}

export async function patchInstanceClusterTransform(id, body) {
  const json = await _request('PATCH', `/assembly/instances/${id}/cluster-transform`, body)
  return _syncFromAssemblyResponse(json)
}

export async function patchInstanceDesign(id, content, { docId } = {}) {
  // docId lets a part-editor tab (which lives on its OWN isolated doc) write the
  // edit back into the ASSEMBLY's doc, where the assembly actually lives.
  const json = await _request('PATCH', `/assembly/instances/${id}/design`, { content }, { docId })
  return _syncFromAssemblyResponse(json)
}

export async function extrudeInstanceOverhang(instanceId, { helixId, bpIndex, direction, isFivePrime, neighborRow, neighborCol, lengthBp }) {
  const json = await _request('POST', `/assembly/instances/${instanceId}/overhang/extrude`, {
    helix_id:      helixId,
    bp_index:      bpIndex,
    direction,
    is_five_prime: isFivePrime,
    neighbor_row:  neighborRow,
    neighbor_col:  neighborCol,
    length_bp:     lengthBp,
  })
  _syncFromAssemblyResponse(json)
  return json
}

export async function patchInstanceOverhang(instanceId, overhangId, { sequence, label, rotation } = {}) {
  const body = {}
  if (sequence !== undefined) body.sequence = sequence
  if (label    !== undefined) body.label    = label
  if (rotation !== undefined) body.rotation = rotation
  const json = await _request(
    'PATCH',
    `/assembly/instances/${instanceId}/overhang/${encodeURIComponent(overhangId)}`,
    body,
  )
  _syncFromAssemblyResponse(json)
  return json
}

export async function seekInstanceFeatures(id, position, subPosition = null) {
  const json = await _request('POST', `/assembly/instances/${id}/features/seek`, {
    position,
    sub_position: subPosition,
  })
  _syncFromAssemblyResponse(json)
  return json
}

export async function createAssemblyOverhangBinding(body) {
  const json = await _request('POST', '/assembly/overhang-bindings', body)
  _syncFromAssemblyResponse(json)
  return json
}

export async function patchAssemblyOverhangBinding(id, body) {
  const json = await _request('PATCH', `/assembly/overhang-bindings/${encodeURIComponent(id)}`, body)
  _syncFromAssemblyResponse(json)
  return json
}

export async function deleteAssemblyOverhangBinding(id) {
  const json = await _request('DELETE', `/assembly/overhang-bindings/${encodeURIComponent(id)}`)
  _syncFromAssemblyResponse(json)
  return json
}

export async function createAssemblyOverhangConnection(body) {
  const json = await _request('POST', '/assembly/overhang-connections', body)
  _syncFromAssemblyResponse(json)
  return json
}

export async function patchAssemblyOverhangConnection(id, body) {
  const json = await _request('PATCH', `/assembly/overhang-connections/${encodeURIComponent(id)}`, body)
  _syncFromAssemblyResponse(json)
  return json
}

export async function deleteAssemblyOverhangConnection(id) {
  const json = await _request('DELETE', `/assembly/overhang-connections/${encodeURIComponent(id)}`)
  _syncFromAssemblyResponse(json)
  return json
}

// Read-only gate for the per-row Relax button: { available, reason,
// movable_instance_id, fixed_instance_id, linker_type }. Does NOT mutate state.
export async function getAssemblyOverhangConnectionRelaxStatus(id) {
  return _request('GET', `/assembly/overhang-connections/${encodeURIComponent(id)}/relax-status`)
}

// Rigid-place the free part so the ds linker becomes a coaxial native-length
// duplex. Returns the assembly response (+ relax_info) and syncs the store.
export async function relaxAssemblyOverhangConnection(id) {
  const json = await _request('POST', `/assembly/overhang-connections/${encodeURIComponent(id)}/relax`)
  _syncFromAssemblyResponse(json)
  return json
}

// ── Cross-part AssemblyDuplex (Proposal-B convergence) ──────────────────────────
// Assembly-level analog of the per-design duplex client fns in
// overhang_endpoints.js. See memory/project_assembly_overhang_bindings.md (Phase C).

export async function listAssemblyDuplexes() {
  // Read-only — no store side effect. Returns { duplexes: [...] }.
  return _request('GET', '/assembly/duplexes')
}

export async function connectAssemblyDuplex(body) {
  // body: { instance_a_id, overhang_a_id, overhang_a_attach?, instance_b_id,
  //         overhang_b_id, overhang_b_attach?, driver?, allow_n_wildcard? }
  // Producer: min-length register at the attach ends, longest-drives default.
  // Returns null on a 409 (pair already connected) so callers can ignore dupes.
  const json = await _request('POST', '/assembly/duplexes/connect', body)
  if (!json) return null
  _syncFromAssemblyResponse(json)
  return json
}

export async function patchAssemblyDuplex(id, patch) {
  // patch: subset of { left, right, driver, bound, name }. The driver just persists
  // (read by flatten_assembly at materialization) — NO live geometry is moved.
  const json = await _request('PATCH', `/assembly/duplexes/${encodeURIComponent(id)}`, patch)
  _syncFromAssemblyResponse(json)
  return json
}

export async function deleteAssemblyDuplex(id) {
  const json = await _request('DELETE', `/assembly/duplexes/${encodeURIComponent(id)}`)
  _syncFromAssemblyResponse(json)
  return json
}

export async function syncAssemblyDuplexesFromBindings() {
  // Idempotently ensure every legacy AssemblyOverhangBinding pair also has a
  // display duplex. A no-op returns the assembly unchanged (no feature-log entry).
  const json = await _request('POST', '/assembly/duplexes/sync-from-bindings')
  _syncFromAssemblyResponse(json)
  return json
}

export async function seekAssemblyFeatures(position) {
  const json = await _request('POST', '/assembly/features/seek', { position })
  _syncFromAssemblyResponse(json)
  return json
}

export async function revertAssemblyToBeforeFeature(index) {
  const json = await _request('POST', `/assembly/features/${index}/revert`)
  return _syncFromAssemblyResponse(json)
}

export async function deleteAssemblyFeature(index) {
  const json = await _request('DELETE', `/assembly/features/${index}`)
  return _syncFromAssemblyResponse(json)
}

export async function editAssemblyFeature(index, params) {
  const json = await _request('POST', `/assembly/features/${index}/edit`, { params })
  return _syncFromAssemblyResponse(json)
}

export async function createInstanceLoadout(id, name) {
  const json = await _request('POST', `/assembly/instances/${id}/loadouts`, { name })
  _syncFromAssemblyResponse(json)
  return json
}

export async function selectInstanceLoadout(id, loadoutId) {
  const json = await _request('POST', `/assembly/instances/${id}/loadouts/${loadoutId}/select`)
  _syncFromAssemblyResponse(json)
  return json
}

export async function renameInstanceLoadout(id, loadoutId, name) {
  const json = await _request('PATCH', `/assembly/instances/${id}/loadouts/${loadoutId}`, { name })
  _syncFromAssemblyResponse(json)
  return json
}

export async function deleteInstanceLoadout(id, loadoutId) {
  const json = await _request('DELETE', `/assembly/instances/${id}/loadouts/${loadoutId}`)
  _syncFromAssemblyResponse(json)
  return json
}

export async function deleteInstance(id) {
  const json = await _request('DELETE', `/assembly/instances/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function addAssemblyJoint(body) {
  const json = await _request('POST', '/assembly/joints', body)
  return _syncFromAssemblyResponse(json)
}

/**
 * Atomic mate creation — registers blunt-end connectors, propagates FK to the
 * aligned pose, and adds the joint in ONE round-trip.  Replaces the old
 * addInstanceConnector ×2 → propagateFk → addAssemblyJoint sequence, which
 * fired the store subscriber four times and snapped the live preview around.
 */
export async function createMate(body) {
  const json = await _request('POST', '/assembly/joints/create-mate', body)
  return _syncFromAssemblyResponse(json)
}

export async function patchAssemblyJoint(id, body) {
  const json = await _request('PATCH', `/assembly/joints/${id}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteAssemblyJoint(id) {
  const json = await _request('DELETE', `/assembly/joints/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function createGearRelation(body) {
  const json = await _request('POST', '/assembly/gear-relations', body)
  return _syncFromAssemblyResponse(json)
}

export async function patchGearRelation(id, body) {
  const json = await _request('PATCH', `/assembly/gear-relations/${id}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteGearRelation(id) {
  const json = await _request('DELETE', `/assembly/gear-relations/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function resolveGearRelation(id) {
  const json = await _request('POST', `/assembly/gear-relations/${id}/resolve`)
  return _syncFromAssemblyResponse(json)
}

export async function createBeltPath(body) {
  const json = await _request('POST', '/assembly/belt-paths', body)
  return _syncFromAssemblyResponse(json)
}

export async function patchBeltPath(id, body) {
  const json = await _request('PATCH', `/assembly/belt-paths/${id}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteBeltPath(id) {
  const json = await _request('DELETE', `/assembly/belt-paths/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function createBeltRider(body) {
  const json = await _request('POST', '/assembly/belt-riders', body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteBeltRider(id) {
  const json = await _request('DELETE', `/assembly/belt-riders/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function polymerizeBelt(body) {
  const json = await _request('POST', '/assembly/polymerize-belt', body)
  return _syncFromAssemblyResponse(json)
}

export async function resolveAssembly() {
  const json = await _request('POST', '/assembly/resolve')
  _syncFromAssemblyResponse(json)
  return json
}

export async function refreshMate(jointId) {
  const json = await _request('POST', `/assembly/joints/${jointId}/refresh-mate`)
  return _syncFromAssemblyResponse(json)
}

export async function getJointConnectorFrames(jointId) {
  return _request('GET', `/assembly/joints/${jointId}/connector-frames`)
}

export async function getAllConnectorFrames() {
  return _request('GET', '/assembly/connector-frames')
}

export async function getJointDebugFrames(jointId) {
  return _request('GET', `/assembly/joints/${jointId}/debug-frames`)
}

export async function addInstanceConnector(instanceId, body) {
  const json = await _request('POST', `/assembly/instances/${instanceId}/connectors`, body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteInstanceConnector(instanceId, label) {
  const json = await _request('DELETE', `/assembly/instances/${instanceId}/connectors/${encodeURIComponent(label)}`)
  return _syncFromAssemblyResponse(json)
}

export async function addLinkerHelix(body) {
  const json = await _request('POST', '/assembly/linker-helices', body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteLinkerHelix(id) {
  const json = await _request('DELETE', `/assembly/linker-helices/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function addLinkerStrand(body) {
  const json = await _request('POST', '/assembly/linker-strands', body)
  return _syncFromAssemblyResponse(json)
}

export async function deleteLinkerStrand(id) {
  const json = await _request('DELETE', `/assembly/linker-strands/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function getLinkerGeometry() {
  return _request('GET', '/assembly/linker-geometry')
}

export async function undoAssembly() {
  const json = await _request('POST', '/assembly/undo')
  return _syncFromAssemblyResponse(json)
}

export async function redoAssembly() {
  const json = await _request('POST', '/assembly/redo')
  return _syncFromAssemblyResponse(json)
}


export async function getInstanceDesign(id) {
  return _request('GET', `/assembly/instances/${id}/design`)
}

/**
 * Re-materialise the COMPACT per-helix-per-direction parallel-array form
 * shipped by the backend (`nucleotides_compact`) into the flat per-nuc
 * dict list the renderer pipeline expects. Mirrors the decoder used in
 * _syncFromDesignResponse above; kept module-local so both the main
 * design path and the assembly geometry path share one implementation.
 *
 * @param {object} compact - { helixId: { direction: { bp:[], bb:[], ... } } }
 * @returns {Array} flat list of nucleotide dicts
 */
export function _expandCompactNucleotides(compact) {
  const flat = []
  if (!compact) return flat
  for (const helixId of Object.keys(compact)) {
    const byDir = compact[helixId]
    for (const dir of Object.keys(byDir)) {
      const b = byDir[dir]
      if (!b || !Array.isArray(b.bp)) continue
      const M = b.bp.length
      for (let i = 0; i < M; i++) {
        flat.push({
          helix_id:          helixId,
          bp_index:          b.bp[i],
          direction:         dir,
          backbone_position: b.bb[i],
          base_position:     b.bs[i],
          base_normal:       b.bn[i],
          axis_tangent:      b.at[i],
          strand_id:         b.sid?.[i] ?? null,
          strand_type:       b.stype?.[i] ?? null,
          is_five_prime:     !!b.is5?.[i],
          is_three_prime:    !!b.is3?.[i],
          domain_index:      b.did?.[i] ?? 0,
          overhang_id:       b.ohid?.[i] ?? null,
          extension_id:      b.extid?.[i] ?? null,
          is_modification:   !!b.ismod?.[i],
          modification:      b.mod?.[i] ?? null,
          nucleobase:        b.base?.[i] ?? null,
        })
      }
    }
  }
  return flat
}

export async function getInstanceGeometry(id) {
  const json = await _request('GET', `/assembly/instances/${id}/geometry`)
  // Decode compact wire format → flat nuc list (legacy shape the renderer
  // expects). Server always ships compact for this endpoint now.
  if (json && !json.nucleotides && json.nucleotides_compact) {
    json.nucleotides = _expandCompactNucleotides(json.nucleotides_compact)
  }
  return json
}

export async function getInstanceSurfaceGeometry(id, colorMode = 'strand', probeRadius = 0.28, gridSpacing = 0.20) {
  const q = `color_mode=${encodeURIComponent(colorMode)}&probe_radius=${probeRadius}&grid_spacing=${gridSpacing}`
  return _request('GET', `/assembly/instances/${id}/surface-geometry?${q}`)
}

export async function getInstanceAtomisticGeometry(id) {
  return _request('GET', `/assembly/instances/${id}/atomistic-geometry`)
}

/**
 * Per-instance bend-center connectors for "Define Mate" picking.
 *
 * Returns ``{ bend_centers: [{label, position, normal, cluster_id,
 * bend_index, radius_nm}] }`` in instance-LOCAL coordinates. Frontend
 * transforms with the instance's world matrix the same way blunt ends
 * are handled.
 */
export async function getInstanceBendCenters(id) {
  return _request('GET', `/assembly/instances/${id}/bend-centers`)
}

/**
 * Ring-closure residual for a periodic-polymer chain of `count` copies of
 * this instance. Returns the rotational and translational drift of δ^count
 * away from identity, plus a suggested κ that would close the chain.
 */
export async function getInstancePeriodicClosure(id, count = 4) {
  return _request('GET', `/assembly/instances/${id}/periodic-closure?count=${count}`)
}

/**
 * Batch-fetch geometry for every visible instance in the active assembly.
 *
 * Server returns the deduplicated shape ``{ sources, instances, errors }``
 * where multiple instance ids of the same part point at one source entry.
 * For renderer compatibility we project this back into the legacy
 * per-instance map ``{ instances: { id: { nucleotides, helix_axes, design } } }``
 * — the per-instance entries share the same underlying decoded JS arrays,
 * so V8 doesn't carry N copies of identical nucleotide lists.
 */
export async function getAssemblyGeometry() {
  const json = await _request('GET', '/assembly/geometry')
  if (!json) return json
  if (!json.sources) return json  // pre-Phase-3 shape passthrough (legacy)

  // Decode each source's compact form once; shared across all referencing
  // instances. The arrays inside are the same JS objects in every entry.
  const decoded = {}
  for (const [srcKey, src] of Object.entries(json.sources)) {
    decoded[srcKey] = {
      nucleotides: src.nucleotides_compact
        ? _expandCompactNucleotides(src.nucleotides_compact)
        : (src.nucleotides ?? []),
      helix_axes:  src.helix_axes,
      design:      src.design,
    }
  }

  const instances = {}
  for (const [instId, srcKey] of Object.entries(json.instances || {})) {
    const src = decoded[srcKey]
    instances[instId] = src
      ? { nucleotides: src.nucleotides, helix_axes: src.helix_axes, design: src.design }
      : { error: `unknown source key ${srcKey}` }
  }
  for (const [instId, msg] of Object.entries(json.errors || {})) {
    instances[instId] = { error: msg }
  }
  return { instances }
}

export async function saveAssemblyToWorkspace(filename) {
  const json = await _request('POST', '/assembly/save', filename ? { filename } : {})
  return _syncFromAssemblyResponse(json)
}

export async function saveDesignToWorkspace(path) {
  const json = await _request('POST', '/design/save-workspace', { path, overwrite: true })
  if (!json) return null
  // A same-path save refreshes only the backend's identity_confirmed_at stamp.
  // Feeding that response back through currentDesign creates an autosave loop:
  // design ref changes → autosave → fresh timestamp/ref → autosave, and every
  // turn also invalidates/reloads the atomistic model. The already-open frontend
  // design is canonical for a "confirmed" save, so keep its object identity.
  if (json.identity_disposition === 'confirmed') return json
  // Initial path claims and Save As can change identity/path metadata (and Save
  // As can mint a new UUID), so those responses still must enter the store.
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/** Save current in-memory design to an explicit workspace path.
 *  Pass overwrite:false to get a 409 if the file already exists (for Save As confirm flow). */
export async function saveDesignAs(path, overwrite = true) {
  const json = await _request('POST', '/design/save-workspace', { path, overwrite })
  if (!json) return null
  if (json.identity_disposition === 'confirmed') return json
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/** Save current in-memory assembly to an explicit workspace path. */
export async function saveAssemblyAs(path, overwrite = true) {
  const json = await _request('POST', '/assembly/save', { path, overwrite })
  return _syncFromAssemblyResponse(json)
}

// ── Workspace library ─────────────────────────────────────────────────────────

let _libraryFilesInflight = null
export async function listLibraryFiles() {
  if (_libraryFilesInflight) return _libraryFilesInflight
  _libraryFilesInflight = _request('GET', '/library/files')   // returns array directly
  try {
    return await _libraryFilesInflight
  } finally {
    _libraryFilesInflight = null
  }
}

/** Simulation bytes keyed by workspace-relative design path. Kept separate so
 * the welcome screen can paint file metadata before disk accounting completes. */
export async function libraryDiskUsage() {
  return _request('GET', '/library/disk-usage')
}

/** Currently-busy (running/preparing) MD + oxDNA jobs across the workspace, for the
 *  welcome-screen activity spinner and the concurrent-job guard. See routes_jobs.py. */
let _activeJobsCache = null
let _activeJobsInflight = null
export async function listActiveJobs() {
  // This display-only poll repeatedly contended with the CPU-heavy geometry
  // response during large edits. Hold the last four-second poll result while an
  // interactive operation is in flight; launch guards refresh normally once the
  // operation's final frame has rendered.
  if (activeOperationTiming() && _activeJobsCache) return _activeJobsCache
  if (_activeJobsInflight) return _activeJobsInflight
  await whenOperationIdle()
  // Background activity polling must never own the centred operation popup. On a
  // saturated MD host this read can take tens of seconds and several independent
  // UI consumers call it concurrently; letting each one increment op-progress's
  // ref-count strands a generic "Working…" modal over an otherwise usable app.
  if (_activeJobsInflight) return _activeJobsInflight
  _activeJobsInflight = _request('GET', '/jobs/active', undefined, { suppressBusy: true })
  try {
    const result = await _activeJobsInflight
    if (result) _activeJobsCache = result
    return result
  } finally {
    _activeJobsInflight = null
  }
}

/** Current external GPU-compute contention (a non-NADOC process holding the GPU),
 *  so the MD/oxDNA panels can warn before a second run OOMs the card. Returns
 *  { available, busy, processes, message, ... }. See routes_md.py gpu_status. */
export async function gpuStatus(devices = '0') {
  return _request('GET', `/md/gpu-status?devices=${encodeURIComponent(devices)}`)
}

/** Whole-machine utilisation snapshot for the live "System monitor" sparklines
 *  (CPU %, GPU %, host RAM + VRAM). Polled a few times a second while a card's
 *  monitor is open; the card buffers samples into rolling minigraphs. Returns
 *  { cpu_pct, ram_pct, ram_used_mb, ram_total_mb, gpu_present, gpu_pct, vram_pct,
 *  vram_used_mb, vram_total_mb } (percent fields null when unavailable). See
 *  routes_system.py system_resources. */
const _systemResourcesInflight = new Map()
export async function getSystemResources(devices = '0') {
  // High-frequency monitor poll: on a saturated host even this cheap probe can
  // queue for seconds. It must update its card when it lands, never open/ref-count
  // the centred operation popup over unrelated user work.
  const key = String(devices)
  const existing = _systemResourcesInflight.get(key)
  if (existing) return existing
  const request = _request('GET', `/system/resources?devices=${encodeURIComponent(devices)}`, undefined, {
    suppressBusy: true,
  })
  _systemResourcesInflight.set(key, request)
  try {
    return await request
  } finally {
    if (_systemResourcesInflight.get(key) === request) _systemResourcesInflight.delete(key)
  }
}

/** Recommended NAMD Advanced settings for the active design on THIS machine
 *  (backs the Advanced card's ⚡ Optimize button). Read-only — it proposes, the
 *  panel applies only after the user confirms. Returns
 *  { recommended, rationale, warnings, facts }. See routes_md.py optimize_advanced. */
export async function optimizeMdAdvanced({ devices = '0', padding_nm = 1.2, minimize_steps = 10000 } = {}) {
  const q = new URLSearchParams({
    devices, padding_nm: String(padding_nm), minimize_steps: String(minimize_steps),
  })
  return _request('GET', `/md/optimize-advanced?${q}`)
}

/** GPU/RAM/core facts for this host — the FAST first stage of ⚡ Optimize (~0.5 s).
 *  Separate from optimizeMdAdvanced (~30 s: it builds the design's heavy-atom model)
 *  so the panel's progress bar has a real stage boundary to report. */
export async function optimizeMdHardware(devices = '0') {
  return _request('GET', `/md/optimize-advanced/hardware?devices=${encodeURIComponent(devices)}`)
}

/** Auto engine recommendation for the active design given live GPU/CPU state
 *  → {recommendation, gpu, free_cores, has_proteins, n_nucleotides, gpu_eta_seconds}.
 *  Returns null on error so callers can degrade to "GPU unknown / recommend oxDNA". */
export async function simulateRecommendation(devices = '0') {
  await whenOperationIdle()
  // This read-only policy refresh runs automatically when Dynamics opens. It
  // must not claim the global operation popup while Display MD reports its own
  // precise progress.
  return _request('GET', `/simulate/recommendation?devices=${encodeURIComponent(devices)}`, null,
    { suppressBusy: true })
}

/** The UNIFIED simulation job list — every oxDNA + LAMMPS run for the active design,
 *  normalized into one common node shape (engine/kind/status/parent_job_id/…) so the
 *  Simulate panel renders GPU-oxDNA and CPU-LAMMPS runs in one hierarchical list. */
const _simJobsInflight = new Map()
export async function listSimJobs(designSourcePath = null, showAll = false) {
  const q = new URLSearchParams()
  if (designSourcePath) q.set('design_source_path', designSourcePath)
  if (showAll) q.set('show_all', 'true')
  const s = q.toString()
  // Background status poll (every ~1.5 s while the Simulate tab watches an active
  // job). Suppress the generic 5 s "Working…" auto-popup: while a NAMD/oxDNA run
  // saturates the machine this endpoint routinely exceeds the threshold, and a
  // repeating poll would otherwise flash the modal on a loop.
  await whenOperationIdle()
  const path = `/simulate/jobs${s ? `?${s}` : ''}`
  const existing = _simJobsInflight.get(path)
  if (existing) return existing
  const request = _request('GET', path, undefined, { suppressBusy: true })
  _simJobsInflight.set(path, request)
  try {
    return await request
  } finally {
    if (_simJobsInflight.get(path) === request) _simJobsInflight.delete(path)
  }
}

export async function getLibraryFileContent(path) {
  return _request('GET', `/library/content?path=${encodeURIComponent(path)}`)
}

/** Aggregate facts about the active design / open file: total bases, loadouts,
 *  MD + oxDNA jobs and their on-disk sizes, and assemblies that use the part. */
export async function getDesignAbout(path) {
  const q = path ? `?path=${encodeURIComponent(path)}` : ''
  return _request('GET', `/design/about${q}`)
}

export async function uploadLibraryFile(content, filename, opts = {}) {
  const body = { content, filename }
  if (opts.destPath)  body.dest_path = opts.destPath
  if (opts.overwrite !== undefined) body.overwrite = opts.overwrite
  return _request('POST', '/library/upload', body)
}

export async function mkdirLibrary(path) {
  return _request('POST', '/library/mkdir', { path })
}

export async function renameLibrary(path, newName) {
  return _request('PATCH', '/library/rename', { path, new_name: newName })
}

export async function moveLibrary(path, destFolder) {
  return _request('POST', '/library/move', { path, dest_folder: destFolder })
}

export async function deleteLibraryItem(path, deleteJobs = false) {
  const q = deleteJobs ? '&delete_jobs=true' : ''
  return _request('DELETE', `/library/file?path=${encodeURIComponent(path)}${q}`)
}

/** MD / oxDNA job folders associated with a workspace file/folder. */
export async function getAssociatedJobs(path) {
  return _request('GET', `/library/file/jobs?path=${encodeURIComponent(path)}`)
}

export function subscribeLibraryEvents(onEvent) {
  const es = new EventSource('/api/library/events')
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch { /* malformed event — ignore */ }
  }
  return () => es.close()
}

// ── Flatten to Design ─────────────────────────────────────────────────────────

export async function validateAssembly() {
  return _request('GET', '/assembly/validate')
}

export async function flattenAssembly() {
  return _request('GET', '/assembly/flatten')
}

export async function flattenAssemblyLoadAsDesign() {
  const json = await _request('POST', '/assembly/flatten/load-as-design')
  if (!json) return null
  return _syncFromDesignResponse(json)
}

// ── Simulation hardware benchmark ──────────────────────────────────────────────
// Auto-tune oxDNA/NAMD hardware settings for the current machine.  All return plain
// dicts (not design responses), so they don't sync the store; apply mutates the
// active design server-side (metadata only).

export async function benchmarkHardware() {
  return _request('GET', '/benchmark/hardware')
}

export async function startOxdnaBenchmark(body = {}) {
  return _request('POST', '/benchmark/oxdna', body)
}

export async function startNamdBenchmark(body = {}) {
  return _request('POST', '/benchmark/namd', body)
}

export async function getBenchmark(id) {
  return _request('GET', `/benchmark/${id}`)
}

export async function applyBenchmark(id, body = {}) {
  return _request('POST', `/benchmark/${id}/apply`, body)
}

export async function cancelBenchmark(id) {
  return _request('POST', `/benchmark/${id}/cancel`)
}

// ── Re-exports ────────────────────────────────────────────────────────────────
// Animation / keyframe / assembly-configuration endpoints live in their own
// module to keep this file readable. Re-exported here so existing callers
// (`import { createAnimation } from '.../api/client.js'` and
//  `import * as api from '.../api/client.js'`) keep working unchanged.
export * from './animation_endpoints.js'
export * from './overhang_endpoints.js'
