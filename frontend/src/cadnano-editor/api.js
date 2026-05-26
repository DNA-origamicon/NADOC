/**
 * Minimal API client for the cadnano editor.
 *
 * Standalone — does not import the main app's store.  All functions
 * return the parsed JSON or null on error.
 */

import { editorStore } from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'
import { notifyRequestFailure, notifyRequestSuccess } from '../shared/connection_monitor.js'
import { docHeaders, getDocId } from '../shared/doc_id.js'

const BASE = '/api'

// ── Stale-response guard + sync diagnostics ──────────────────────────────────
// The 2D editor shares the backend document with the 3D view. Rapid edits (e.g.
// resizing ends then nicking quickly) fire CONCURRENT mutations whose responses
// can arrive OUT OF ORDER. The backend stamps every design response with a
// monotonic `revision`; we drop any response older than the newest already
// applied, so a late/stale response can't clobber newer topology (the "nick
// appears then reverts a second later" bug). Mirrors the guard in the 3D client
// (src/api/client.js). Reset on backend restart (revision resets low) via
// resetRevisionWatermark().
let _lastAppliedRev = -1
let _inFlight = 0
let _droppedCount = 0
const _syncLog = []            // ring buffer of recent sync decisions (debug)
const _SYNC_LOG_MAX = 200
const _syncListeners = new Set()

function _pushSyncLog(entry) {
  entry.t = Date.now()
  _syncLog.push(entry)
  if (_syncLog.length > _SYNC_LOG_MAX) _syncLog.shift()
  for (const fn of _syncListeners) { try { fn(entry) } catch { /* ignore */ } }
}

/** Apply a design response to the editor store, dropping it if a newer response
 *  has already been applied (out-of-order/stale → would clobber). Returns json. */
function _applyDesignResponse(json, { emit = false, source = '' } = {}) {
  if (!json?.design) return json
  const rev = (typeof json.revision === 'number') ? json.revision : null
  if (rev !== null && rev < _lastAppliedRev) {
    _droppedCount++
    _pushSyncLog({ decision: 'DROP', source, rev, lastRev: _lastAppliedRev,
                   strands: json.design.strands?.length, flog: json.design.feature_log?.length })
    return json   // superseded by a newer response — skip so we don't clobber it
  }
  if (rev !== null) _lastAppliedRev = rev
  editorStore.setState({ design: json.design })
  if (emit) nadocBroadcast.emit('design-changed')
  _pushSyncLog({ decision: 'APPLY', source, rev, lastRev: _lastAppliedRev,
                 strands: json.design.strands?.length, flog: json.design.feature_log?.length })
  return json
}

/** Reset the stale-response watermark. MUST be called when the backend restarts
 *  (its per-session revision resets low, so post-restart responses would
 *  otherwise be dropped as "stale" and freeze the editor on old data). */
export function resetRevisionWatermark() {
  _lastAppliedRev = -1
  _pushSyncLog({ decision: 'RESET', source: 'restart', rev: null, lastRev: -1 })
}

/** Snapshot of sync state for the debug tools (window.__nadocSyncDebug.sync). */
export function getSyncDebugState() {
  return {
    docId:          getDocId(),
    lastAppliedRev: _lastAppliedRev,
    inFlight:       _inFlight,
    dropped:        _droppedCount,
    storeStrands:   editorStore.getState().design?.strands?.length ?? null,
    storeFlog:      editorStore.getState().design?.feature_log?.length ?? null,
    log:            _syncLog.slice(-40),
  }
}

/** Subscribe to every sync decision (APPLY/DROP/RESET) — for a live overlay. */
export function onSyncEvent(fn) { _syncListeners.add(fn); return () => _syncListeners.delete(fn) }

async function _request(method, path, body) {
  editorStore.setState({ loading: true })
  _inFlight++
  const opts = {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...docHeaders(),   // edit the same backend document as the 3D view that opened us
      // The 2D editor renders from topology and never reads embedded 3D
      // geometry, so tell the backend to omit it. This skips a full-design
      // geometry recompute (hundreds of ms on large designs) and a multi-MB
      // JSON.parse of a payload we'd discard. The 3D view re-fetches its own
      // geometry on the design-changed broadcast, so it's unaffected.
      'X-NADOC-Skip-Geometry': '1',
    },
    body:    body !== undefined ? JSON.stringify(body) : undefined,
  }
  try {
    const r    = await fetch(`${BASE}${path}`, opts)
    notifyRequestSuccess()   // any HTTP response means the backend is reachable
    const json = await r.json().catch(() => null)
    if (!r.ok) {
      editorStore.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText }, loading: false })
      return null
    }
    editorStore.setState({ lastError: null, loading: false })
    return json
  } catch (err) {
    notifyRequestFailure()   // network-level failure → flag the connection as down
    editorStore.setState({ lastError: { status: 0, message: err.message }, loading: false })
    return null
  } finally {
    _inFlight = Math.max(0, _inFlight - 1)
  }
}

/** Stash the unligated crossover set + replay placement_warnings.
 * Backend's _design_response always emits unligated_crossover_ids. Pathview
 * reads it from the editor store to render ⚠ markers. */
function _absorbAuxFields(json) {
  if (!json) return
  if (Array.isArray(json.unligated_crossover_ids)) {
    editorStore.setState({
      unligatedCrossoverIds: new Set(json.unligated_crossover_ids),
    })
  }
}

/** Fetch the current design and update the editor store. */
export async function fetchDesign() {
  const json = await _request('GET', '/design')
  _applyDesignResponse(json, { source: 'fetchDesign' })
  _absorbAuxFields(json)
  return json
}

/**
 * Perform a mutation, update the editor store, and notify other tabs.
 * `mutationFn` receives `_request` and should return the response JSON.
 */
export async function mutate(mutationFn) {
  const json = await mutationFn(_request)
  _applyDesignResponse(json, { emit: true, source: 'mutate' })
  _absorbAuxFields(json)
  return json
}

/**
 * Replace the design's 96-well plate / tube layout (IDT ordering convenience).
 * Display-only metadata persisted in the .nadoc file; no geometry change.
 */
export async function savePlateLayout(layout) {
  return mutate(req => req('PUT', '/design/plate-layout', layout))
}

/**
 * Add an EMPTY helix at a lattice cell (row, col) — no strands.
 * The backend computes axis position, phase, and twist from the lattice type and
 * places the helix adjacent to its nearest neighbour (matching that neighbour's
 * bp extent + 3D Z-span), so a strand later penned onto it lands beside it in 3D.
 * The user pens scaffold/staple strands onto the bare track themselves.
 */
export async function addHelixAtCell(row, col, length_bp = 42) {
  return mutate(req => req('POST', '/design/helix-at-cell', { row, col, length_bp, populate_strands: false }))
}

/** Delete a helix by ID. */
export async function deleteHelix(helixId) {
  return mutate(req => req('DELETE', `/design/helix/${helixId}`))
}

/**
 * Reorder the vertical arrangement of helices in the pathview.
 * `orderedIds` must be every existing helix id exactly once, top-to-bottom.
 * Pure display change — touches design.helices array order only.
 */
export async function reorderHelices(orderedIds) {
  return mutate(req => req('PUT', '/design/helices/reorder', { ordered_ids: orderedIds }))
}

/**
 * Extend a helix's bp range to cover [loBp, hiBp].  Never shrinks.
 * Adjusts axis geometry and phase so existing nucleotides stay in place.
 */
export async function extendHelixBounds(helixId, loBp, hiBp) {
  return mutate(req =>
    req('PATCH', `/design/helices/${helixId}/extend`, { lo_bp: loBp, hi_bp: hiBp })
  )
}

/** Auto-scaffold the design. */
export async function autoScaffold(opts = {}) {
  const { minStapleMargin = 3 } = opts
  return mutate(req => req('POST', '/design/auto-scaffold', {
    min_staple_margin: minStapleMargin,
  }))
}

/** Route a seamed scaffold. */
export async function autoScaffoldSeamed() {
  return mutate(req => req('POST', '/design/auto-scaffold-seamed'))
}

/** Route an experimental seamed scaffold. */
export async function autoScaffoldAdvancedSeamed() {
  return mutate(req => req('POST', '/design/auto-scaffold-advanced-seamed'))
}

/**
 * Paint a scaffold domain onto a helix from the pencil tool.
 * loBp/hiBp are bp indices left-to-right (order-independent).
 * The server determines strand direction from the helix's grid_pos.
 */
export async function scaffoldDomainPaint(helixId, loBp, hiBp) {
  return mutate(req =>
    req('POST', '/design/scaffold-domain-paint', { helix_id: helixId, lo_bp: loBp, hi_bp: hiBp })
  )
}

/**
 * Paint a new single-domain staple strand on the given helix + direction.
 * direction: 'FORWARD' | 'REVERSE'
 * loBp/hiBp: bp indices left-to-right (order-independent).
 */
export async function paintStapleDomain(helixId, direction, loBp, hiBp) {
  const isFwd = direction === 'FORWARD'
  return mutate(req =>
    req('POST', '/design/strands', {
      domains: [{
        helix_id:  helixId,
        start_bp:  isFwd ? loBp : hiBp,
        end_bp:    isFwd ? hiBp : loBp,
        direction,
      }],
      strand_type: 'staple',
    })
  )
}

/**
 * Place a crossover atomically: nick helix A, nick helix B, register the record.
 * All three steps are a single undo checkpoint — one Ctrl-Z fully reverts placement.
 * halfA/halfB carry index = sprite bp (used for the crossover record).
 * nickBpA/nickBpB are the nick positions computed by the pathview bow-direction rules.
 */
export async function placeCrossover(halfA, halfB, nickBpA, nickBpB) {
  return mutate(req => req('POST', '/design/crossovers/place', {
    half_a:    { helix_id: halfA.helix_id, index: halfA.index, strand: halfA.strand },
    half_b:    { helix_id: halfB.helix_id, index: halfB.index, strand: halfB.strand },
    nick_bp_a: nickBpA,
    nick_bp_b: nickBpB,
  }))
}

/** Move an existing crossover to a new bp index, resizing adjacent domains. */
export async function moveCrossover(crossoverId, newIndex) {
  return mutate(req => req('POST', '/design/crossovers/move', {
    crossover_id: crossoverId,
    new_index:    newIndex,
  }))
}

/** Move multiple crossovers to new bp indices in a single atomic operation. */
export async function batchMoveCrossovers(moves) {
  return mutate(req => req('POST', '/design/crossovers/batch-move', { moves }))
}

/** Remove a crossover by ID. */
export async function deleteCrossover(crossoverId) {
  return mutate(req => req('DELETE', `/design/crossovers/${crossoverId}`))
}

/** Remove multiple crossovers in a single atomic request. */
export async function batchDeleteCrossovers(crossoverIds) {
  if (!crossoverIds.length) return null
  return mutate(req => req('POST', '/design/crossovers/batch-delete', { crossover_ids: crossoverIds }))
}

/** Set (or clear) extra bases on a single crossover. Pass sequence='' to remove. */
export async function patchCrossoverExtraBases(crossoverId, sequence) {
  return mutate(req => req('PATCH', `/design/crossovers/${crossoverId}/extra-bases`, { sequence }))
}

/** Batch-set extra bases on multiple crossovers in one atomic request.
 *  entries: Array of { crossover_id: string, sequence: string }
 */
export async function batchCrossoverExtraBases(entries) {
  return mutate(req => req('PATCH', '/design/crossovers/extra-bases/batch', { entries }))
}

/** Set (or clear) extra bases on a forced ligation. Pass sequence='' to remove. */
export async function patchForcedLigationExtraBases(flId, sequence) {
  return mutate(req => req('PATCH', `/design/forced-ligations/${flId}/extra-bases`, { sequence }))
}

/** Upsert (create or update) strand extensions in one atomic request.
 *  items: Array of { strandId, end, sequence?, modification?, label? }
 */
export async function upsertStrandExtensionsBatch(items) {
  const mapped = items.map(i => ({
    strand_id:    i.strandId,
    end:          i.end,
    sequence:     i.sequence   ?? null,
    modification: i.modification ?? null,
    label:        i.label       ?? null,
  }))
  return mutate(req => req('POST', '/design/extensions/batch', { items: mapped }))
}

/** Delete multiple strand extensions by ID. */
export async function deleteStrandExtensionsBatch(extIds) {
  if (!extIds.length) return null
  return mutate(req => req('DELETE', '/design/extensions/batch', { ext_ids: extIds }))
}

/** Delete a strand. */
export async function deleteStrand(strandId) {
  return mutate(req => req('DELETE', `/design/strands/${strandId}`))
}

/** Delete multiple strands in one atomic request. */
export async function deleteStrandsBatch(strandIds) {
  if (!strandIds.length) return null
  return mutate(req => req('DELETE', '/design/strands/batch', { strand_ids: strandIds }))
}

/**
 * Delete a single domain from a strand by its index.
 * Fails (409) if a crossover references the domain.
 */
export async function deleteDomain(strandId, domainIdx) {
  return mutate(req => req('DELETE', `/design/strands/${strandId}/domains/${domainIdx}`))
}

/**
 * Nick a strand at the 3′ side of bp_index.
 * direction: 'FORWARD' | 'REVERSE'
 */
export async function nickStrand(helixId, bpIndex, direction) {
  return mutate(req =>
    req('POST', '/design/nick', { helix_id: helixId, bp_index: bpIndex, direction })
  )
}

/**
 * Ligate (repair) a nick by merging the two strand ends adjacent to bp_index.
 * bp_index is the 3′ end of the left fragment — same convention as nickStrand.
 */
export async function ligateStrand(helixId, bpIndex, direction) {
  return mutate(req =>
    req('POST', '/design/ligate', { helix_id: helixId, bp_index: bpIndex, direction })
  )
}

/**
 * Forced ligation — connect any 3' end to any 5' end, bypassing crossover
 * lookup tables.  Manual pencil-tool feature only; must NOT be used by
 * autocrossover or any automated pipeline.
 */
export async function forcedLigation(threePrimeStrandId, fivePrimeStrandId, isPeriodicSeam = false) {
  return mutate(req =>
    req('POST', '/design/forced-ligation', {
      three_prime_strand_id: threePrimeStrandId,
      five_prime_strand_id:  fivePrimeStrandId,
      is_periodic_seam:      isPeriodicSeam,
    })
  )
}

/** Remove a forced ligation by ID — splits the strand back into two fragments. */
export async function deleteForcedLigation(flId) {
  return mutate(req => req('DELETE', `/design/forced-ligations/${flId}`))
}

/** Remove multiple forced ligations in a single atomic request. */
export async function batchDeleteForcedLigations(flIds) {
  if (!flIds.length) return null
  return mutate(req => req('POST', '/design/forced-ligations/batch-delete', { forced_ligation_ids: flIds }))
}

/**
 * Update editable strand metadata (color and/or notes).
 * color: '#RRGGBB' hex string, or null to reset to palette.
 */
export async function patchStrand(strandId, { color = undefined, notes = undefined } = {}) {
  return mutate(req =>
    req('PATCH', `/design/strand/${strandId}`, { color, notes })
  )
}

export async function patchOverhang(overhangId, { sequence = undefined, label = undefined } = {}) {
  const body = {}
  if (sequence !== undefined) body.sequence = sequence
  if (label    !== undefined) body.label    = label
  return mutate(req =>
    req('PATCH', `/design/overhang/${encodeURIComponent(overhangId)}`, body)
  )
}

/** Generate a rare, structure-safe sequence for a single overhang via
 *  the Johnson et al. 5-mer scoring algorithm. */
export async function generateOverhangRandomSequence(overhangId) {
  return mutate(req =>
    req('POST', `/design/overhang/${encodeURIComponent(overhangId)}/generate-random`)
  )
}

/**
 * Apply the same color to multiple strands in a single atomic request.
 * color: '#RRGGBB' hex string, or null to reset to palette.
 */
export async function patchStrandsColor(strandIds, color) {
  return mutate(req =>
    req('PATCH', '/design/strands/colors', { strand_ids: strandIds, color })
  )
}

/**
 * Mark/clear strands as inactive reference geometry (ignored by auto-features,
 * excluded from exports; still visible + editable). Atomic, one undo step.
 */
export async function patchStrandsReference(strandIds, isReference) {
  return mutate(req =>
    req('PATCH', '/design/strands/reference', { strand_ids: strandIds, is_reference: isReference })
  )
}

/**
 * Resize one or more strand ends by a shared delta_bp.
 * entries: [{ strand_id, helix_id, end: '5p'|'3p', delta_bp }]
 */
export async function resizeStrandEnds(entries) {
  return mutate(async req => {
    const json = await req('POST', '/design/strand-end-resize', { entries })
    // Log every strand that touches the affected helices so we can see nicks.
    if (json?.design) {
      const affectedIds = new Set(entries.map(e => e.helix_id))
      console.group('%c[API /strand-end-resize response]', 'color:cyan')
      console.log('sent entries:', entries)
      for (const hid of affectedIds) {
        const h = json.design.helices?.find(x => x.id === hid)
        if (!h) { console.log(`  helix ${hid}: NOT FOUND in response`); continue }
        console.log(`  helix ${hid}  bp_start=${h.bp_start}  length_bp=${h.length_bp}`)
        const doms = (json.design.strands ?? []).flatMap(s =>
          s.domains
            .filter(d => d.helix_id === hid)
            .map(d => ({
              strand: s.id.slice(0,16),
              type: s.strand_type,
              dir: d.direction,
              start_bp: d.start_bp,
              end_bp: d.end_bp,
              range: `[${Math.min(d.start_bp,d.end_bp)}..${Math.max(d.start_bp,d.end_bp)}]`,
            }))
        )
        console.table(doms)
      }
      console.groupEnd()
    }
    return json
  })
}

/**
 * Shift one or more whole domains by a signed bp offset (drag-to-move).
 * entries: [{ strand_id, domain_index, delta_bp }]
 */
export async function shiftDomains(entries) {
  return mutate(req =>
    req('POST', '/design/domain-shift', { entries })
  )
}

/**
 * Insert or remove a single loop/skip at a bp position.
 * delta: +1 = loop (insertion), -1 = skip (deletion), 0 = remove existing
 */
export async function insertLoopSkip(helixId, bpIndex, delta) {
  return mutate(req => req('POST', '/design/loop-skip/insert', {
    helix_id: helixId,
    bp_index: bpIndex,
    delta,
  }))
}

/** Remove all loop/skip modifications from every helix in the design. */
export async function clearAllLoopSkips() {
  return mutate(req => req('POST', '/design/loop-skip/clear-all'))
}

/** Generate Johnson et al. overhang sequences for all overhangs. */
export async function generateAllOverhangSequences() {
  const json = await mutate(req => req('POST', '/design/generate-overhang-sequences'))
  if (!json) return null
  return { ok: !!json.design, count: json.generated_count ?? 0 }
}

/** Create a new blank design, replacing the current one. */
export async function createDesign(name = 'Untitled', latticeType = 'HONEYCOMB') {
  return mutate(req => req('POST', '/design', { name, lattice_type: latticeType }))
}

/** Import a NADOC JSON string, replacing the current design. */
export async function importDesign(content) {
  return mutate(req => req('POST', '/design/import', { content }))
}

/** Shift all helix grid positions so min row = 0, min col = 0. */
export async function centerDesign() {
  return mutate(req => req('POST', '/design/center'))
}

/** Import a caDNAno JSON string, replacing the current design. */
export async function importCadnanoDesign(content) {
  return mutate(req => req('POST', '/design/import/cadnano', { content }))
}

/** Import a scadnano .sc JSON string, replacing the current design. */
export async function importScadnanoDesign(content) {
  return mutate(req => req('POST', '/design/import/scadnano', { content }))
}

/** Import a PDB file containing DNA, replacing the current design. */
export async function importPdbDesign(content, merge = false) {
  return mutate(req => req('POST', '/design/import/pdb', { content, merge }))
}

/** Download the current design as a .nadoc file. */
export async function exportDesign() {
  const r = await fetch('/api/design/export', { headers: docHeaders() })
  if (!r.ok) return false
  const cd   = r.headers.get('Content-Disposition') ?? ''
  const m    = cd.match(/filename="([^"]+)"/)
  const name = m ? m[1] : 'design.nadoc'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  return true
}

/** Download the current design as a caDNAno JSON file. */
export async function exportCadnano() {
  const r = await fetch('/api/design/export/cadnano', { headers: docHeaders() })
  if (!r.ok) return false
  const cd   = r.headers.get('Content-Disposition') ?? ''
  const m    = cd.match(/filename="([^"]+)"/)
  const name = m ? m[1] : 'design.json'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  return true
}

/** Download the staple/scaffold sequences as a CSV file. */
export async function exportSequenceCsv() {
  const r = await fetch('/api/design/export/sequence-csv', { headers: docHeaders() })
  if (!r.ok) return false
  const cd   = r.headers.get('Content-Disposition') ?? ''
  const m    = cd.match(/filename="?([^"]+)"?/)
  const name = m ? m[1] : 'sequences.csv'
  const blob = await r.blob()
  const url  = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  return true
}

/** Place all valid staple crossovers automatically. */
export async function addAutoCrossover() {
  return mutate(req => req('POST', '/design/crossovers/auto'))
}

/** Break the scaffold at canonical nicking points. */
export async function addAutoBreak(opts = {}) {
  return mutate(req => req('POST', '/design/auto-break', opts))
}

/** Merge short staple fragments across nicks. */
export async function addAutoMerge() {
  return mutate(req => req('POST', '/design/auto-merge'))
}

/** Extend the near scaffold end by lengthBp. */
export async function scaffoldExtrudeNear(lengthBp = 10) {
  return mutate(req => req('POST', '/design/scaffold-extrude-near', { length_bp: lengthBp }))
}

/** Extend the far scaffold end by lengthBp. */
export async function scaffoldExtrudeFar(lengthBp = 10) {
  return mutate(req => req('POST', '/design/scaffold-extrude-far', { length_bp: lengthBp }))
}

/** Route a seamless (looped) scaffold. */
export async function autoScaffoldSeamless(opts = {}) {
  const { nickHelixId = null, nickOffset = 7, minEndMargin = 9 } = opts
  return mutate(req => req('POST', '/design/auto-scaffold-seamless', {
    nick_helix_id: nickHelixId, nick_offset: nickOffset, min_end_margin: minEndMargin,
  }))
}

/** Route an experimental seamless scaffold. */
export async function autoScaffoldAdvancedSeamless(opts = {}) {
  const { nickHelixId = null, nickOffset = 7, minEndMargin = 9 } = opts
  return mutate(req => req('POST', '/design/auto-scaffold-advanced-seamless', {
    nick_helix_id: nickHelixId, nick_offset: nickOffset, min_end_margin: minEndMargin,
  }))
}

/** Route a jointed scaffold. */
export async function jointedScaffold(opts = {}) {
  const { mode = 'end_to_end', nickOffset = 7, minEndMargin = 9 } = opts
  return mutate(req => req('POST', '/design/jointed-scaffold', {
    mode, nick_offset: nickOffset, min_end_margin: minEndMargin,
  }))
}

/**
 * Assign a scaffold sequence by name or custom string.
 * Returns raw JSON (not synced to store) — caller reads padded_nt etc. first.
 */
export async function assignScaffoldSequence(scaffoldName = 'M13mp18', opts = {}) {
  const { customSequence = null, strandId = null } = opts
  return _request('POST', '/design/assign-scaffold-sequence', {
    scaffold_name:   scaffoldName,
    custom_sequence: customSequence || null,
    strand_id:       strandId || null,
  })
}

/** Apply scaffold sequence to design store after assignScaffoldSequence call. */
export async function syncScaffoldSequenceResponse(json) {
  _applyDesignResponse(json, { emit: true, source: 'scaffoldSeq' })
  return json
}

/** Derive complementary staple sequences from the scaffold sequence. */
export async function assignStapleSequences() {
  return mutate(req => req('POST', '/design/assign-staple-sequences'))
}

/** Apply all DeformationOps as loop/skip topology modifications. */
export async function applyAllDeformations() {
  return mutate(req => req('POST', '/design/loop-skip/apply-deformations'))
}

// ── Feature-log operations (used by the shared feature_log_panel) ────────────
// These MUST go through `mutate` (→ _request) so they carry docHeaders() — i.e.
// target THIS editor's document, not the default doc. (The old inline shim in
// main.js used a bare fetch with no doc header, so revert/delete/seek hit the
// wrong document and threw "Feature index N out of range (log has 1 entries)".)
// They also forward subIndex for per-sub-step revert/delete and ride the
// stale-response guard via `mutate`.

export async function seekFeatures(position, subPosition = null) {
  return mutate(req => req('POST', '/design/features/seek', { position, sub_position: subPosition }))
}

export async function deleteFeature(index, subIndex = null) {
  const path = subIndex == null
    ? `/design/features/${index}`
    : `/design/features/${index}?sub_index=${subIndex}`
  return mutate(req => req('DELETE', path))
}

export async function revertToBeforeFeature(index, subIndex = null) {
  const path = subIndex == null
    ? `/design/features/${index}/revert`
    : `/design/features/${index}/revert?sub_index=${subIndex}`
  return mutate(req => req('POST', path))
}

export async function editFeature(index, params) {
  return mutate(req => req('POST', `/design/features/${index}/edit`, { params }))
}

/**
 * Revert the last mutation.
 * Returns the restored design, or null if nothing to undo (404 is silent — not an error).
 */
export async function undoDesign() {
  editorStore.setState({ loading: true })
  try {
    // docHeaders() targets THIS editor's document — without it undo/redo hit the
    // default doc and silently revert the wrong stack (broken undo in multi-doc).
    const r = await fetch(`${BASE}/design/undo`, { method: 'POST', headers: { ...docHeaders(), 'X-NADOC-Skip-Geometry': '1' } })
    editorStore.setState({ loading: false })
    if (r.status === 404) return null          // stack empty — silent
    const json = await r.json().catch(() => null)
    if (!r.ok) return null
    _applyDesignResponse(json, { emit: true, source: 'undo' })
    return json
  } catch (err) {
    editorStore.setState({ loading: false })
    return null
  }
}

/**
 * Re-apply the last undone mutation.
 * Returns the restored design, or null if nothing to redo (404 is silent — not an error).
 */
export async function redoDesign() {
  editorStore.setState({ loading: true })
  try {
    const r = await fetch(`${BASE}/design/redo`, { method: 'POST', headers: { ...docHeaders(), 'X-NADOC-Skip-Geometry': '1' } })
    editorStore.setState({ loading: false })
    if (r.status === 404) return null          // stack empty — silent
    const json = await r.json().catch(() => null)
    if (!r.ok) return null
    _applyDesignResponse(json, { emit: true, source: 'redo' })
    return json
  } catch (err) {
    editorStore.setState({ loading: false })
    return null
  }
}
