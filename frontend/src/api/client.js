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
import { nadocBroadcast } from '../shared/broadcast.js'
import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'

const BASE = '/api'

const LS_DESIGN_KEY = 'nadoc:design'

/** Persist the current design topology to localStorage for session recovery. */
export function persistDesign() {
  const design = store.getState().currentDesign
  if (!design) return
  try { localStorage.setItem(LS_DESIGN_KEY, JSON.stringify(design)) } catch { /* quota exceeded — ignore */ }
}

/** Read the persisted design from localStorage (parsed JSON or null). */
export function getPersistedDesign() {
  try {
    const raw = localStorage.getItem(LS_DESIGN_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** Remove the persisted design (e.g. when returning to the welcome screen). */
export function clearPersistedDesign() {
  try { localStorage.removeItem(LS_DESIGN_KEY) } catch { /* ignore */ }
}

const LS_ASSEMBLY_KEY = 'nadoc:assembly'
const LS_MODE_KEY     = 'nadoc:mode'  // 'assembly' | 'part-edit:{id}' | null

export function persistAssembly() {
  const assembly = store.getState().currentAssembly
  if (!assembly) return
  try { localStorage.setItem(LS_ASSEMBLY_KEY, JSON.stringify(assembly)) } catch { /* quota exceeded — ignore */ }
}

export function getPersistedAssembly() {
  try {
    const raw = localStorage.getItem(LS_ASSEMBLY_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function clearPersistedAssembly() {
  try { localStorage.removeItem(LS_ASSEMBLY_KEY) } catch { /* ignore */ }
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

/** Erase the active design on the server and clear all local persistence. */
export async function closeSession() {
  try { await fetch(`${BASE}/design`, { method: 'DELETE' }) } catch { /* ignore if unreachable */ }
  clearPersistedDesign()
}

// ── Recent files ─────────────────────────────────────────────────────────────
const LS_RECENT_KEY = 'nadoc:recent'
const RECENT_MAX    = 2

/**
 * Return the recent-files list: [{ name, content, type, ts }, ...] newest first.
 * `type` is 'nadoc' | 'cadnano' | 'scadnano'.
 */
export function getRecentFiles() {
  try {
    const raw = localStorage.getItem(LS_RECENT_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

/**
 * Add or update a recent-file entry.  Keeps only the newest RECENT_MAX entries.
 * @param {string} name     Display name (filename or design name).
 * @param {string} content  Raw file content string.
 * @param {'nadoc'|'cadnano'|'scadnano'} [type='nadoc']  File type.
 */
export function addRecentFile(name, content, type = 'nadoc') {
  try {
    let recent = getRecentFiles().filter(r => r.name !== name)
    recent.unshift({ name, content, type, ts: Date.now() })
    recent = recent.slice(0, RECENT_MAX)
    localStorage.setItem(LS_RECENT_KEY, JSON.stringify(recent))
  } catch { /* quota exceeded — ignore */ }
}

/** Clear the recent-files list. */
export function clearRecentFiles() {
  try { localStorage.removeItem(LS_RECENT_KEY) } catch { /* ignore */ }
}

/** Slow-call threshold for the perf log; calls under this are silent to keep
 *  the console useful. Set window.__nadocApiTraceAll = true to trace everything. */
const _API_PERF_THRESHOLD_MS = 200

/** Delay before the "still working…" progress popup appears for a slow API
 *  call. Keeps fast calls (sub-1.5 s) from flashing the widget — covers most
 *  routine mutations (save-workspace, library/files, animation keyframe
 *  setup, small cluster commits, etc.) and only triggers for truly long ops
 *  (linker-creation seek, autostaple, big bundle imports). */
const _BUSY_POPUP_DELAY_MS = 1500

/** Once the popup actually appears, keep it visible for at least this many
 *  milliseconds even if the response arrives sooner. Avoids one-frame flashes
 *  for ops that finish just after the threshold. */
const _BUSY_POPUP_MIN_VISIBLE_MS = 400

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
  if (path.startsWith('/design/features/') && path.endsWith('/edit'))   return 'Editing Feature'
  if (path.startsWith('/design/features/') && path.endsWith('/revert')) return 'Reverting Feature'
  if (path.startsWith('/design/features/') && method === 'DELETE')      return 'Deleting Feature'
  if (path === '/design/undo')                                     return 'Undo'
  if (path === '/design/redo')                                     return 'Redo'
  if (path.startsWith('/design/overhang-connections/') && path.endsWith('/relax')) return 'Relaxing Linker'
  if (path.startsWith('/design/cluster/') && method === 'PATCH')   return 'Applying Transform'
  if (path === '/design/auto-scaffold')                            return 'Auto Scaffold'
  if (path.startsWith('/design/auto-staple'))                      return 'Auto Staple'
  if (path === '/design/auto-break')                               return 'Auto Break'
  if (path.startsWith('/design/auto-crossover'))                   return 'Auto Crossover'
  if (path.startsWith('/design/bundle'))                           return 'Building Bundle'
  if (path.startsWith('/design/extrude'))                          return 'Extruding'
  if (path.startsWith('/design/load') || path.startsWith('/design/import')) return 'Loading Design'
  return 'Working…'
}

async function _request(method, path, body) {
  const opts = {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
  // Show a centred indeterminate progress popup if the call hasn't returned
  // within _BUSY_POPUP_DELAY_MS. Fast calls clear the timer before it fires
  // and the user never sees the popup. Slow calls (linker seek, autostaple,
  // big imports) get a "still working" indicator so they don't look frozen.
  let _busyShown = false
  let _busyShownAt = 0
  const _busyTimer = setTimeout(() => {
    _busyShown = true
    _busyShownAt = performance.now()
    showOpProgress(_busyHeaderForPath(method, path), '')
  }, _BUSY_POPUP_DELAY_MS)
  const t0 = performance.now()
  let r, json, tNetwork = 0
  try {
    r = await fetch(`${BASE}${path}`, opts)
    tNetwork = performance.now() - t0
    json = await r.json().catch(() => null)
  } finally {
    clearTimeout(_busyTimer)
    if (_busyShown) {
      // Keep the popup up for a minimum visible time so it doesn't flash for
      // calls that finish just a hair past the trigger threshold. Most ops
      // that hit the popup are well above this floor (multi-second seeks),
      // so the floor doesn't add perceived latency.
      const visibleFor = performance.now() - _busyShownAt
      const wait = Math.max(0, _BUSY_POPUP_MIN_VISIBLE_MS - visibleFor)
      if (wait > 0) setTimeout(hideOpProgress, wait)
      else hideOpProgress()
    }
  }
  const tTotal = performance.now() - t0
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
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
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
async function _syncFromDesignResponse(json, { skipGeometry = false } = {}) {
  if (!json) return null
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
    if (json.design) nadocBroadcast.emit('design-changed')
    if (json.design) persistDesign()
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
        updates.currentHelixAxes = { ...(store.getState().currentHelixAxes ?? {}), ...helixAxesMap }
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
  } else {
    store.setState(updates)
    if (json.design) {
      const h0 = json.design.helices?.[0]
      console.debug('[NADOC import] design set: first helix axis_start =',
        h0 ? `(${h0.axis_start?.x?.toFixed(3)}, ${h0.axis_start?.y?.toFixed(3)})` : 'none',
        '| debug =', json.debug ?? 'none')
    }
    // Re-fetch full geometry whenever the design changes (getGeometry stores it directly).
    if (json.design) {
      await getGeometry()
      const axes0 = Object.values(store.getState().currentHelixAxes ?? {})[0]
      console.debug('[NADOC import] geometry applied: first helix_axes start =',
        axes0 ? `(${axes0.start[0]?.toFixed(3)}, ${axes0.start[1]?.toFixed(3)})` : 'none')
    }
  }
  // Notify other tabs (cadnano editor, second 3D windows) that the design changed.
  if (json.design) nadocBroadcast.emit('design-changed')
  // Persist design to localStorage for session recovery on refresh/restart.
  if (json.design) persistDesign()
  return json
}

/** Sync the store with an assembly mutation response. */
function _syncFromAssemblyResponse(json) {
  if (!json) return null
  if (json.assembly) {
    store.setState({ currentAssembly: json.assembly })
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
  const updates = {}
  if (json.design)     updates.currentDesign     = json.design
  if (json.validation) updates.validationReport  = json.validation
  store.setState(updates)
  if (json.design) {
    nadocBroadcast.emit('design-changed')
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
  if (json.design) {
    nadocBroadcast.emit('design-changed')
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
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
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

export async function createNearEnds(placements) {
  const json = await _request('POST', '/design/near-ends/create', {
    crossovers: placements.map(p => ({
      helix_id_a: p.helix_id_a,
      helix_id_b: p.helix_id_b,
      face_bp:    p.face_bp,
      new_lo:     p.new_lo,
      xover_bp:   p.xover_bp,
      strand_a:   p.strand_a,
      strand_b:   p.strand_b,
      nick_bp_a:  p.nick_bp_a,
      nick_bp_b:  p.nick_bp_b,
    })),
  })
  return _syncFromDesignResponse(json)
}

export async function createFarEnds(placements) {
  const json = await _request('POST', '/design/far-ends/create', {
    crossovers: placements.map(p => ({
      helix_id_a: p.helix_id_a,
      helix_id_b: p.helix_id_b,
      face_bp:    p.face_bp,
      new_hi:     p.new_hi,
      xover_bp:   p.xover_bp,
      strand_a:   p.strand_a,
      strand_b:   p.strand_b,
      nick_bp_a:  p.nick_bp_a,
      nick_bp_b:  p.nick_bp_b,
    })),
  })
  return _syncFromDesignResponse(json)
}

export async function patchCrossoverExtraBases(crossoverId, sequence) {
  const json = await _request('PATCH', `/design/crossovers/${crossoverId}/extra-bases`, { sequence })
  return _syncFromDesignResponse(json)
}

export async function patchForcedLigationExtraBases(flId, sequence) {
  const json = await _request('PATCH', `/design/forced-ligations/${flId}/extra-bases`, { sequence })
  return _syncFromDesignResponse(json)
}

export async function addAutoBreak(opts = {}) {
  const json = await _request('POST', '/design/auto-break', opts)
  return _syncFromDesignResponse(json)
}

export async function addAutoMerge() {
  const json = await _request('POST', '/design/auto-merge')
  return _syncFromDesignResponse(json)
}

export async function autoScaffold(opts = {}) {
  const { minStapleMargin = 3 } = opts
  const json = await _request('POST', '/design/auto-scaffold', {
    min_staple_margin: minStapleMargin,
  })
  return _syncFromDesignResponse(json)
}

export async function autoScaffoldSeamed() {
  const json = await _request('POST', '/design/auto-scaffold-seamed')
  if (json?.warnings?.length) console.warn('[AutoScaffoldSeamed] warnings:', json.warnings)
  return _syncFromDesignResponse(json)
}

export async function autoScaffoldAdvancedSeamed() {
  const json = await _request('POST', '/design/auto-scaffold-advanced-seamed')
  if (json?.warnings?.length) console.warn('[AutoScaffoldAdvancedSeamed] warnings:', json.warnings)
  return _syncFromDesignResponse(json)
}


// ── Scaffold end-loop operations ──────────────────────────────────────────

export async function scaffoldExtrudeNear(lengthBp = 10) {
  const json = await _request('POST', '/design/scaffold-extrude-near', { length_bp: lengthBp })
  return _syncFromDesignResponse(json)
}

export async function scaffoldExtrudeFar(lengthBp = 10) {
  const json = await _request('POST', '/design/scaffold-extrude-far', { length_bp: lengthBp })
  return _syncFromDesignResponse(json)
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

export async function autoScaffoldAdvancedSeamless(opts = {}) {
  const { nickHelixId = null, nickOffset = 7, minEndMargin = 9 } = opts
  const json = await _request('POST', '/design/auto-scaffold-advanced-seamless', {
    nick_helix_id: nickHelixId,
    nick_offset: nickOffset,
    min_end_margin: minEndMargin,
  })
  if (json?.warnings?.length) console.warn('[AutoScaffoldAdvancedSeamless] warnings:', json.warnings)
  return _syncFromDesignResponse(json)
}

export async function partitionScaffold(helixGroups, opts = {}) {
  const { mode = 'end_to_end', nickOffset = 7, minEndMargin = 9 } = opts
  const json = await _request('POST', '/design/partition-scaffold', {
    helix_groups: helixGroups,
    mode,
    nick_offset: nickOffset,
    min_end_margin: minEndMargin,
  })
  return _syncFromDesignResponse(json)
}

export async function jointedScaffold(opts = {}) {
  const { mode = 'end_to_end', nickOffset = 7, minEndMargin = 9 } = opts
  const json = await _request('POST', '/design/jointed-scaffold', {
    mode,
    nick_offset: nickOffset,
    min_end_margin: minEndMargin,
  })
  return _syncFromDesignResponse(json)
}

export async function scaffoldSplit(strandId, helixId, bpPosition) {
  const json = await _request('POST', '/design/scaffold-split', {
    strand_id: strandId,
    helix_id: helixId,
    bp_position: bpPosition,
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
  const r = await fetch(`${BASE}/design/export/sequence-csv`)
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
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

export async function exportCadnano() {
  const r = await fetch(`${BASE}/design/export/cadnano`)
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
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

// ── Deformation endpoints ──────────────────────────────────────────────────

export async function addDeformation(type, planeA, planeB, params, helixIds = [], preview = false, clusterId = null) {
  const body = {
    type,
    plane_a_bp: planeA,
    plane_b_bp: planeB,
    params,
    affected_helix_ids: helixIds,
    preview,
  }
  if (clusterId) body.cluster_id = clusterId
  const json = await _request('POST', '/design/deformation', body)
  return _syncFromDesignResponse(json)
}

export async function updateDeformation(opId, params) {
  const json = await _request('PATCH', `/design/deformation/${opId}`, { params })
  return _syncFromDesignResponse(json)
}

export async function deleteDeformation(opId, preview = false) {
  const url = preview ? `/design/deformation/${opId}?preview=true` : `/design/deformation/${opId}`
  const json = await _request('DELETE', url)
  return _syncFromDesignResponse(json)
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
  const url  = helixIds?.length
    ? `/design/geometry?helix_ids=${helixIds.join(',')}`
    : '/design/geometry'
  const json = await _request('GET', url)
  if (!json) return null
  // Response format: { nucleotides: [...], helix_axes: [...] }
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
  if (json.partial_geometry && json.changed_helix_ids?.length) {
    // ── Fix B merge path ────────────────────────────────────────────────────
    const changedSet = new Set(json.changed_helix_ids)
    const existing   = store.getState().currentGeometry ?? []
    store.setState({
      currentGeometry: [
        ...existing.filter(n => !changedSet.has(n.helix_id)),
        ...nucleotides,
      ],
      currentHelixAxes: Object.keys(helixAxesMap).length
        ? { ...(store.getState().currentHelixAxes ?? {}), ...helixAxesMap }
        : store.getState().currentHelixAxes,
    })
  } else {
    store.setState({
      currentGeometry:  nucleotides,
      currentHelixAxes: Object.keys(helixAxesMap).length ? helixAxesMap : null,
    })
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

export async function extrudeOverhang({ helixId, bpIndex, direction, isFivePrime, neighborRow, neighborCol, lengthBp }) {
  const json = await _request('POST', '/design/overhang/extrude', {
    helix_id:      helixId,
    bp_index:      bpIndex,
    direction,
    is_five_prime: isFivePrime,
    neighbor_row:  neighborRow,
    neighbor_col:  neighborCol,
    length_bp:     lengthBp,
  })
  return _syncFromDesignResponse(json)
}

export async function patchOverhang(overhangId, { sequence, label, rotation } = {}) {
  const body = {}
  if (sequence !== undefined) body.sequence = sequence
  if (label    !== undefined) body.label    = label
  if (rotation !== undefined) body.rotation = rotation
  const json = await _request('PATCH', `/design/overhang/${encodeURIComponent(overhangId)}`, body)
  return _syncFromDesignResponse(json)
}

export async function patchOverhangRotationsBatch(ops) {
  // ops: Array<{ overhang_id: string, rotation: [qx, qy, qz, qw] }>
  const json = await _request('PATCH', '/design/overhangs/rotations', { ops })
  return _syncFromDesignResponse(json)
}

export async function generateOverhangRandomSequence(overhangId) {
  const json = await _request('POST', `/design/overhang/${encodeURIComponent(overhangId)}/generate-random`)
  return _syncFromDesignResponse(json)
}

export async function clearOverhangs() {
  const json = await _request('DELETE', '/design/overhangs')
  return _syncFromDesignResponse(json)
}

export async function clearAllLoopSkips() {
  const json = await _request('POST', '/design/loop-skip/clear-all')
  return _syncFromDesignResponse(json)
}

export async function createOverhangConnection(payload) {
  // payload: { overhang_a_id, overhang_a_attach, overhang_b_id, overhang_b_attach,
  //            linker_type, length_value, length_unit, name? }
  const json = await _request('POST', '/design/overhang-connections', payload)
  return _syncFromDesignResponse(json)
}

export async function patchOverhangConnection(connId, patch) {
  // patch: { name?, length_value?, length_unit? }
  const json = await _request('PATCH', `/design/overhang-connections/${encodeURIComponent(connId)}`, patch)
  return _syncFromDesignResponse(json)
}

export async function deleteOverhangConnection(connId) {
  const json = await _request('DELETE', `/design/overhang-connections/${encodeURIComponent(connId)}`)
  return _syncFromDesignResponse(json)
}

export async function relaxLinker(connId, jointIds = null) {
  // Optimizes joint angle(s) so the dsDNA linker's connector arcs collapse.
  // jointIds:
  //   null / [] → backend auto-picks (requires the 1-DOF case).
  //   non-empty array → backend optimizes over the named joints (multi-DOF).
  // Backend now picks between fast paths (cluster_only / positions_only)
  // since relax typically only mutates cluster_transforms — drops the
  // 5-MB full-geometry payload that dominated the response time.
  const body = (jointIds && jointIds.length) ? { joint_ids: jointIds } : null
  const json = await _request('POST',
    `/design/overhang-connections/${encodeURIComponent(connId)}/relax`, body)
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

export async function generateAllOverhangSequences() {
  const json = await _request('POST', '/design/generate-overhang-sequences')
  if (!json) return null
  return { ok: _syncFromDesignResponse(json), count: json.generated_count ?? 0 }
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

/** Apply the same color to multiple strands in one atomic request.
 *  color: '#RRGGBB' hex string, or null to reset to palette.
 */
export async function patchStrandsColor(strandIds, color) {
  const json = await _request('PATCH', '/design/strands/colors', { strand_ids: strandIds, color })
  // Color-only update — no geometry refetch needed.
  return _syncFromDesignResponse(json, { skipGeometry: true })
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
export async function addBundleDeformedContinuation({ cells, lengthBp, plane = 'XY', frame, refHelixId = null }) {
  const json = await _request('POST', '/design/bundle-deformed-continuation', {
    cells,
    length_bp:    lengthBp,
    plane,
    grid_origin:  frame.grid_origin,
    axis_dir:     frame.axis_dir,
    frame_right:  frame.frame_right,
    frame_up:     frame.frame_up,
    ref_helix_id: refHelixId,
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
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
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

export async function deleteFeature(index) {
  const json = await _request('DELETE', `/design/features/${index}`)
  // Backend now picks between the fast-path responses (cluster_only /
  // positions_only) and the embedded full-geometry response so a cluster_op
  // deletion lands in the lean path. Caller is expected to invoke
  // _applyClusterUndoRedoDeltas / _applyPositionsOnlyDiff for those branches
  // (matches the seek/undo/redo pattern).
  if (json?.diff_kind === 'cluster_only')   return _syncClusterOnlyDiff(json)
  if (json?.diff_kind === 'positions_only') return _syncPositionsOnlyDiff(json)
  return _syncFromDesignResponse(json)
}

/**
 * Restore the pre-state snapshot of an auto-op SnapshotLogEntry and truncate
 * the feature log to entries strictly before it. Pre-revert state is pushed
 * onto the undo stack so Ctrl-Z restores it.
 *
 * Returns 410 if the entry's snapshot was evicted to free space.
 * Returns 400 if the entry is not a snapshot type.
 */
export async function revertToBeforeFeature(index) {
  const json = await _request('POST', `/design/features/${index}/revert`)
  return _syncFromDesignResponse(json)
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
  })
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
export async function getGeometryBatch(positions) {
  return _request('POST', '/design/features/geometry-batch', { positions })
}

/**
 * Return flat atom-position arrays for multiple feature-log positions.
 * @param {number[]} positions  e.g. [-2, 0, 1, -1]
 * @returns {Promise<Record<string, number[]> | null>}  pos → [x0,y0,z0, x1,y1,z1, ...]
 */
export async function getAtomisticBatch(positions) {
  return _request('POST', '/design/features/atomistic-batch', { positions })
}

/**
 * Return flat surface vertex arrays for multiple feature-log positions.
 * @param {number[]} positions
 * @param {string}  colorMode    'strand' | 'uniform'
 * @param {number}  probeRadius  nm
 * @param {number}  gridSpacing  nm
 * @returns {Promise<Record<string, {vertices: number[], vertex_count: number}> | null>}
 */
export async function getSurfaceBatch(positions, colorMode = 'strand', probeRadius = 0.28, gridSpacing = 0.20) {
  return _request('POST', '/design/features/surface-batch', {
    positions,
    color_mode:   colorMode,
    probe_radius: probeRadius,
    grid_spacing: gridSpacing,
  })
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

export async function createAssemblyConfiguration(name = null) {
  const json = await _request('POST', '/assembly/configurations', name ? { name } : {})
  return _syncFromAssemblyResponse(json)
}

export async function restoreAssemblyConfiguration(configId) {
  const json = await _request('POST', `/assembly/configurations/${configId}/restore`, {})
  return _syncFromAssemblyResponse(json)
}

export async function updateAssemblyConfiguration(configId, patch) {
  const json = await _request('PATCH', `/assembly/configurations/${configId}`, patch)
  return _syncFromAssemblyResponse(json)
}

export async function deleteAssemblyConfiguration(configId) {
  const json = await _request('DELETE', `/assembly/configurations/${configId}`)
  return _syncFromAssemblyResponse(json)
}

// ── Animations ────────────────────────────────────────────────────────────────
// Animation / keyframe mutations only touch ``design.animations`` — they
// never move any nucleotide. ``skipGeometry: true`` avoids the multi-second
// ``getGeometry()`` refetch that ``_syncFromDesignResponse`` would otherwise
// fire on every mutation.

export async function createAnimation(name = 'Animation', fps = 30, loop = false) {
  const json = await _request('POST', '/design/animations', { name, fps, loop })
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function updateAnimation(animId, patch) {
  const json = await _request('PATCH', `/design/animations/${animId}`, patch)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function deleteAnimation(animId) {
  const json = await _request('DELETE', `/design/animations/${animId}`)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function createKeyframe(animId, kf) {
  const json = await _request('POST', `/design/animations/${animId}/keyframes`, kf)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function updateKeyframe(animId, kfId, patch) {
  const json = await _request('PATCH', `/design/animations/${animId}/keyframes/${kfId}`, patch)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function deleteKeyframe(animId, kfId) {
  const json = await _request('DELETE', `/design/animations/${animId}/keyframes/${kfId}`)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function reorderKeyframes(animId, orderedIds) {
  const json = await _request('PUT', `/design/animations/${animId}/keyframes/reorder`, { ordered_ids: orderedIds })
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

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

export async function importAssembly(content) {
  const json = await _request('POST', '/assembly/import', { content })
  return _syncFromAssemblyResponse(json)
}

/**
 * Trigger a browser download of the active assembly as a .nass file.
 */
export async function exportAssembly() {
  const r = await fetch(`${BASE}/assembly/export`)
  if (!r.ok) {
    const json = await r.json().catch(() => null)
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
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

export async function patchInstance(id, body) {
  const json = await _request('PATCH', `/assembly/instances/${id}`, body)
  return _syncFromAssemblyResponse(json)
}

export async function batchPatchInstances(patches) {
  const json = await _request('PATCH', '/assembly/instances/batch', { patches })
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

export async function patchInstanceDesign(id, content) {
  const json = await _request('PATCH', `/assembly/instances/${id}/design`, { content })
  return _syncFromAssemblyResponse(json)
}

export async function deleteInstance(id) {
  const json = await _request('DELETE', `/assembly/instances/${id}`)
  return _syncFromAssemblyResponse(json)
}

export async function addAssemblyJoint(body) {
  const json = await _request('POST', '/assembly/joints', body)
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

export async function resolveAssembly() {
  const json = await _request('POST', '/assembly/resolve')
  _syncFromAssemblyResponse(json)
  return json
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

export async function getInstanceGeometry(id) {
  return _request('GET', `/assembly/instances/${id}/geometry`)
}

export async function getInstanceAtomisticGeometry(id) {
  return _request('GET', `/assembly/instances/${id}/atomistic-geometry`)
}

export async function getAssemblyGeometry() {
  return _request('GET', '/assembly/geometry')
}

export async function saveAssemblyToWorkspace(filename) {
  const json = await _request('POST', '/assembly/save', filename ? { filename } : {})
  return _syncFromAssemblyResponse(json)
}

export async function saveDesignToWorkspace(path) {
  return _request('POST', '/design/save-workspace', { path, overwrite: true })
}

/** Save current in-memory design to an explicit workspace path.
 *  Pass overwrite:false to get a 409 if the file already exists (for Save As confirm flow). */
export async function saveDesignAs(path, overwrite = true) {
  return _request('POST', '/design/save-workspace', { path, overwrite })
}

/** Save current in-memory assembly to an explicit workspace path. */
export async function saveAssemblyAs(path, overwrite = true) {
  const json = await _request('POST', '/assembly/save', { path, overwrite })
  return _syncFromAssemblyResponse(json)
}

// ── Workspace library ─────────────────────────────────────────────────────────

export async function listLibraryFiles() {
  return _request('GET', '/library/files')   // returns array directly
}

export async function getLibraryFileContent(path) {
  return _request('GET', `/library/content?path=${encodeURIComponent(path)}`)
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

export async function deleteLibraryItem(path) {
  return _request('DELETE', `/library/file?path=${encodeURIComponent(path)}`)
}

export function subscribeLibraryEvents(onEvent) {
  const es = new EventSource('/api/library/events')
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch { /* malformed event — ignore */ }
  }
  return () => es.close()
}

// ── Assembly animations ───────────────────────────────────────────────────────

export async function createAssemblyAnimation(name = 'Animation', fps = 30, loop = false) {
  const json = await _request('POST', '/assembly/animations', { name, fps, loop })
  return _syncFromAssemblyResponse(json)
}

export async function updateAssemblyAnimation(animId, patch) {
  const json = await _request('PATCH', `/assembly/animations/${animId}`, patch)
  return _syncFromAssemblyResponse(json)
}

export async function deleteAssemblyAnimation(animId) {
  const json = await _request('DELETE', `/assembly/animations/${animId}`)
  return _syncFromAssemblyResponse(json)
}

export async function createAssemblyKeyframe(animId, kf) {
  const json = await _request('POST', `/assembly/animations/${animId}/keyframes`, kf)
  return _syncFromAssemblyResponse(json)
}

export async function updateAssemblyKeyframe(animId, kfId, patch) {
  const json = await _request('PATCH', `/assembly/animations/${animId}/keyframes/${kfId}`, patch)
  return _syncFromAssemblyResponse(json)
}

export async function deleteAssemblyKeyframe(animId, kfId) {
  const json = await _request('DELETE', `/assembly/animations/${animId}/keyframes/${kfId}`)
  return _syncFromAssemblyResponse(json)
}

export async function reorderAssemblyKeyframes(animId, orderedIds) {
  const json = await _request('PUT', `/assembly/animations/${animId}/keyframes/reorder`, { ordered_ids: orderedIds })
  return _syncFromAssemblyResponse(json)
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
