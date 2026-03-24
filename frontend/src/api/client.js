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
  if (json.validation) {
    updates.validationReport = json.validation
    updates.loopStrandIds    = json.validation.loop_strand_ids ?? []
  }
  // Merge Strand.color values (from caDNAno import) into strandColors without
  // overwriting any colors the user has already set manually.
  if (json.design?.strands) {
    const existing = store.getState().strandColors ?? {}
    const fromDesign = {}
    for (const strand of json.design.strands) {
      if (strand.color && !(strand.id in existing)) {
        fromDesign[strand.id] = parseInt(strand.color.replace('#', ''), 16)
      }
    }
    if (Object.keys(fromDesign).length > 0) {
      updates.strandColors = { ...existing, ...fromDesign }
    }
  }
  store.setState(updates)
  // Re-fetch full geometry whenever the design changes (getGeometry stores it directly).
  if (json.design) await getGeometry()
  return json
}

// ── Design ────────────────────────────────────────────────────────────────────

export async function getDesign() {
  const json = await _request('GET', '/design')
  if (!json) return null
  store.setState({
    currentDesign:    json.design,
    validationReport: json.validation,
    loopStrandIds:    json.validation?.loop_strand_ids ?? [],
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

export async function createBundle({ cells, lengthBp, name = 'Bundle', plane = 'XY', strandFilter = 'both', latticeType = 'HONEYCOMB' }) {
  const json = await _request('POST', '/design/bundle', {
    cells,
    length_bp: lengthBp,
    name,
    plane,
    strand_filter: strandFilter,
    lattice_type: latticeType,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Append a bundle segment to the active design (slice-plane extrude).
 * lengthBp may be negative to extrude in the -axis direction.
 */
export async function addBundleSegment({ cells, lengthBp, plane = 'XY', offsetNm = 0, strandFilter = 'both' }) {
  const json = await _request('POST', '/design/bundle-segment', {
    cells,
    length_bp: lengthBp,
    plane,
    offset_nm: offsetNm,
    strand_filter: strandFilter,
  })
  return _syncFromDesignResponse(json)
}

/**
 * Extrude a continuation segment: cells whose helix ends at offsetNm extend existing strands;
 * fresh cells get new scaffold + staple strands.
 */
export async function addBundleContinuation({ cells, lengthBp, plane = 'XY', offsetNm = 0, strandFilter = 'both' }) {
  const json = await _request('POST', '/design/bundle-continuation', {
    cells,
    length_bp: lengthBp,
    plane,
    offset_nm: offsetNm,
    strand_filter: strandFilter,
  })
  return _syncFromDesignResponse(json)
}

export async function createDesign(name = 'Untitled', latticeType = 'HONEYCOMB') {
  const json = await _request('POST', '/design', { name, lattice_type: latticeType })
  return _syncFromDesignResponse(json)
}

export async function prebreak() {
  const json = await _request('POST', '/design/prebreak')
  return _syncFromDesignResponse(json)
}

export async function addAutoCrossover() {
  const json = await _request('POST', '/design/auto-crossover')
  return _syncFromDesignResponse(json)
}

export async function addAutoBreak() {
  const json = await _request('POST', '/design/auto-break')
  return _syncFromDesignResponse(json)
}

export async function addAutoMerge() {
  const json = await _request('POST', '/design/auto-merge')
  return _syncFromDesignResponse(json)
}

export async function autoScaffold(mode = 'seam_line', opts = {}) {
  const { nickOffset = 7, scaffoldLoops = true, loopSize = 7 } = opts
  const json = await _request('POST', '/design/auto-scaffold', {
    mode,
    nick_offset: nickOffset,
    scaffold_loops: scaffoldLoops,
    loop_size: loopSize,
  })
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

export async function scaffoldAddEndCrossovers(minEndMargin = 9) {
  const json = await _request('POST', '/design/scaffold-end-crossovers', { min_end_margin: minEndMargin })
  return _syncFromDesignResponse(json)
}

// ── Sequence assignment ────────────────────────────────────────────────────

export async function assignScaffoldSequence() {
  const json = await _request('POST', '/design/assign-scaffold-sequence')
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

export async function addDeformation(type, planeA, planeB, params, helixIds = [], preview = false) {
  const json = await _request('POST', '/design/deformation', {
    type,
    plane_a_bp: planeA,
    plane_b_bp: planeB,
    params,
    affected_helix_ids: helixIds,
    preview,
  })
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

export async function getGeometry() {
  const json = await _request('GET', '/design/geometry')
  if (!json) return null
  // Response format: { nucleotides: [...], helix_axes: [...] }
  const nucleotides = json.nucleotides ?? json   // backward compat with flat array
  const helixAxesMap = {}
  for (const ax of json.helix_axes ?? []) {
    helixAxesMap[ax.helix_id] = { start: ax.start, end: ax.end, samples: ax.samples ?? null }
  }
  store.setState({
    currentGeometry:  nucleotides,
    currentHelixAxes: Object.keys(helixAxesMap).length ? helixAxesMap : null,
  })
  return json
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
    helixAxesMap[ax.helix_id] = { start: ax.start, end: ax.end, samples: ax.samples ?? null }
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
 *   strand_type_a, strand_type_b, distance_nm}] }
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

export async function patchOverhang(overhangId, { sequence, label } = {}) {
  const body = {}
  if (sequence !== undefined) body.sequence = sequence
  if (label    !== undefined) body.label    = label
  const json = await _request('PATCH', `/design/overhang/${encodeURIComponent(overhangId)}`, body)
  return _syncFromDesignResponse(json)
}

export async function patchStrand(strandId, { notes, color } = {}) {
  const body = {}
  if (notes !== undefined) body.notes = notes
  if (color !== undefined) body.color = color
  const json = await _request('PATCH', `/design/strand/${encodeURIComponent(strandId)}`, body)
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

export async function addHalfCrossover({ helixAId, bpA, directionA, helixBId, bpB, directionB }) {
  const json = await _request('POST', '/design/half-crossover', {
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
export async function addBundleDeformedContinuation({ cells, lengthBp, plane = 'XY', frame }) {
  const json = await _request('POST', '/design/bundle-deformed-continuation', {
    cells,
    length_bp:   lengthBp,
    plane,
    grid_origin: frame.grid_origin,
    axis_dir:    frame.axis_dir,
    frame_right: frame.frame_right,
    frame_up:    frame.frame_up,
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
