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

const BASE = '/api'

async function _request(method, path, body) {
  const opts = {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
  const r = await fetch(`${BASE}${path}`, opts)
  const json = await r.json().catch(() => null)
  if (!r.ok) {
    store.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText } })
    return null
  }
  store.setState({ lastError: null })
  return json
}

/** Sync the store with a mutation response (design + validation + optional geometry). */
async function _syncFromDesignResponse(json) {
  if (!json) return null
  const updates = {}
  if (json.design)     updates.currentDesign     = json.design
  if (json.validation) updates.validationReport  = json.validation
  // If the response includes geometry (POST /helices), re-fetch full geometry.
  if (json.design)     updates.currentGeometry   = await getGeometry()
  store.setState(updates)
  return json
}

// ── Design ────────────────────────────────────────────────────────────────────

export async function getDesign() {
  const json = await _request('GET', '/design')
  if (!json) return null
  store.setState({
    currentDesign:    json.design,
    validationReport: json.validation,
  })
  return json
}

/**
 * Revert to the previous design state (server-side undo stack, up to 50 steps).
 * Returns null if nothing to undo (404 from server).
 */
export async function undo() {
  const json = await _request('POST', '/design/undo')
  return _syncFromDesignResponse(json)
}

/**
 * Re-apply the last undone mutation (server-side redo stack, up to 50 steps).
 * Returns null if nothing to redo (404 from server).
 */
export async function redo() {
  const json = await _request('POST', '/design/redo')
  return _syncFromDesignResponse(json)
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

export async function createBundle({ cells, lengthBp, name = 'Bundle', plane = 'XY' }) {
  const json = await _request('POST', '/design/bundle', {
    cells,
    length_bp: lengthBp,
    name,
    plane,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Append a bundle segment to the active design (slice-plane extrude).
 * lengthBp may be negative to extrude in the -axis direction.
 */
export async function addBundleSegment({ cells, lengthBp, plane = 'XY', offsetNm = 0 }) {
  const json = await _request('POST', '/design/bundle-segment', {
    cells,
    length_bp: lengthBp,
    plane,
    offset_nm: offsetNm,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Extrude a continuation segment: cells whose helix ends at offsetNm extend existing strands;
 * fresh cells get new scaffold + staple strands.
 */
export async function addBundleContinuation({ cells, lengthBp, plane = 'XY', offsetNm = 0 }) {
  const json = await _request('POST', '/design/bundle-continuation', {
    cells,
    length_bp: lengthBp,
    plane,
    offset_nm: offsetNm,
  })
  return _syncFromDesignResponse(json)
}

export async function createDesign(name = 'Untitled', latticeType = 'HONEYCOMB') {
  const json = await _request('POST', '/design', { name, lattice_type: latticeType })
  return _syncFromDesignResponse(json)
}

export async function updateMetadata(fields) {
  const json = await _request('PUT', '/design/metadata', fields)
  return _syncFromDesignResponse(json)
}

export async function getGeometry() {
  const json = await _request('GET', '/design/geometry')
  if (!json) return null
  store.setState({ currentGeometry: json })
  return json
}

export async function loadDesign(path) {
  const json = await _request('POST', '/design/load', { path })
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

export async function addStrand({ domains, isScaffold = false, sequence = null }) {
  const json = await _request('POST', '/design/strands', {
    domains:     domains,
    is_scaffold: isScaffold,
    sequence,
  })
  return _syncFromDesignResponse(json)
}

export async function updateStrand(strandId, { domains, isScaffold, sequence = null }) {
  const json = await _request('PUT', `/design/strands/${strandId}`, {
    domains,
    is_scaffold: isScaffold,
    sequence,
  })
  return _syncFromDesignResponse(json)
}

export async function deleteStrand(strandId) {
  const json = await _request('DELETE', `/design/strands/${strandId}`)
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

// ── Crossovers ────────────────────────────────────────────────────────────────

export async function getValidCrossoverPositions(helixAId, helixBId) {
  return _request('GET', `/design/crossovers/valid?helix_a_id=${encodeURIComponent(helixAId)}&helix_b_id=${encodeURIComponent(helixBId)}`)
}

/**
 * Return valid staple crossover positions for every helix pair in the design.
 * Each element: { helix_a_id, helix_b_id, positions: [{bp_a, bp_b, direction_a, direction_b,
 *   is_scaffold_a, is_scaffold_b, distance_nm}] }
 */
export async function getAllValidCrossovers() {
  return _request('GET', '/design/crossovers/all-valid')
}

/**
 * Place a staple crossover between (helix_a_id, bp_a, direction_a) and
 * (helix_b_id, bp_b, direction_b) using topological strand split+reconnect.
 */
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

export async function addStapleCrossover({ helixAId, bpA, directionA, helixBId, bpB, directionB }) {
  const json = await _request('POST', '/design/staple-crossover', {
    helix_a_id:  helixAId,
    bp_a:        bpA,
    direction_a: directionA,
    helix_b_id:  helixBId,
    bp_b:        bpB,
    direction_b: directionB,
  })
  return _syncFromDesignResponse(json)
}

export async function addCrossover({ strandAId, domainAIndex, strandBId, domainBIndex, crossoverType }) {
  const json = await _request('POST', '/design/crossovers', {
    strand_a_id:    strandAId,
    domain_a_index: domainAIndex,
    strand_b_id:    strandBId,
    domain_b_index: domainBIndex,
    crossover_type: crossoverType,
  })
  return _syncFromDesignResponse(json)
}

export async function deleteCrossover(crossoverId) {
  const json = await _request('DELETE', `/design/crossovers/${crossoverId}`)
  return _syncFromDesignResponse(json)
}
