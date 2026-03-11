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

export async function createBundle({ cells, lengthBp, name = 'Bundle', plane = 'XY' }) {
  const json = await _request('POST', '/design/bundle', {
    cells,
    length_bp: lengthBp,
    name,
    plane,
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
