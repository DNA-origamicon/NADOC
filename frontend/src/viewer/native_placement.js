/** Consume the backend's sole molecular placement authority. Never infer a pose. */
export const NATIVE_PLACEMENT_SOURCE = 'native-full-o5-v1'
export const PLACEMENT_FAILURE_EVENT = 'nadoc:placement-integrity-failure'
const acceptedSources = new Set([NATIVE_PLACEMENT_SOURCE, 'authored-residue-c1-v1', 'authored-residue-o5-v1', 'native-full-extension-v1', 'chemical-modification-v1'])
let lastFailure = null

export function placementIntegrityFailure(nucleotide, field, actual, reason = 'Missing or invalid authoritative placement') {
  const identity = nucleotide
    ? `${nucleotide.helix_id}:${nucleotide.bp_index}:${nucleotide.direction}` : 'unknown nucleotide'
  const detail = {
    code: 'NATIVE_PLACEMENT_INTEGRITY',
    time: new Date().toISOString(),
    summary: 'DNA positioning could not be verified. Molecular rendering has stopped. A full placement review is required.',
    identity, field, actual: actual ?? null, reason,
    nucleotide_identity: nucleotide ? {
      helix_id: nucleotide.helix_id ?? null, bp_index: nucleotide.bp_index ?? null,
      direction: nucleotide.direction ?? null, strand_id: nucleotide.strand_id ?? null,
      domain_index: nucleotide.domain_index ?? null,
      copy_k: nucleotide.copy_k ?? nucleotide.copy ?? nucleotide._copy ?? null,
    } : null,
    expected_source: NATIVE_PLACEMENT_SOURCE,
    review_required: true,
  }
  const error = new Error(`${detail.summary} ${identity}: ${field}: ${reason}`)
  error.code = detail.code
  error.detail = { ...detail, stack: error.stack }
  lastFailure = error.detail
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(PLACEMENT_FAILURE_EVENT, { detail: error.detail }))
    showPlacementFailure(error.detail)
    void persistPlacementFailure(error.detail)
  }
  throw error
}

async function persistPlacementFailure(detail) {
  try {
    const { docHeaders } = await import('../shared/doc_id.js')
    const response = await fetch('/api/design/placement-integrity-report', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...docHeaders() },
      body: JSON.stringify({ message: detail.summary, code: detail.code,
        identity: detail.identity, field: detail.field, actual: detail.actual,
        expected: detail.expected_source, phase: 'frontend-rendering', details: detail }),
    })
    if (!response.ok) throw new Error(`Report endpoint returned HTTP ${response.status}`)
    Object.assign(detail, await response.json())
  } catch (error) {
    detail.report_delivery_error = String(error)
    detail.report_delivery_action = 'The server did not save this report. Download the report shown here.'
  }
  showPlacementFailure(detail)
}

function showPlacementFailure(detail) {
  if (typeof document === 'undefined' || !document.body) return
  let panel = document.getElementById('native-placement-integrity-block')
  if (!panel) {
    panel = document.createElement('div')
    panel.id = 'native-placement-integrity-block'
    panel.setAttribute('role', 'alertdialog')
    panel.setAttribute('aria-modal', 'true')
    Object.assign(panel.style, {
      position: 'fixed', inset: '0', zIndex: '2147483647', background: '#14171d', color: '#fff',
      padding: '6vh 8vw', overflow: 'auto', fontFamily: 'system-ui', boxSizing: 'border-box',
    })
    document.body.appendChild(panel)
  }
  panel.replaceChildren()
  const title = document.createElement('h1')
  title.textContent = 'DNA positioning integrity failure'
  const summary = document.createElement('p')
  summary.textContent = detail.summary + ' Your design has not been changed by this check. No substitute positions will be displayed.'
  const action = document.createElement('p')
  action.textContent = 'Download this report and review native placement, deformation transport, history, rendering, and VR before relying on this geometry.'
  const report = document.createElement('pre')
  report.style.whiteSpace = 'pre-wrap'
  report.textContent = JSON.stringify(detail, null, 2)
  const download = document.createElement('button')
  download.textContent = 'Download full positioning failure report'
  download.onclick = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(detail, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'nadoc-placement-integrity-failure.json'
    link.click()
    URL.revokeObjectURL(url)
  }
  panel.append(title, summary, action, download, report)
}

export function lastPlacementFailure() { return lastFailure }

export function validateNativePlacement(nuc) {
  if (!acceptedSources.has(nuc?.placement_source)) {
    placementIntegrityFailure(nuc, 'placement_source', nuc?.placement_source, 'The geometry was not produced by the current canonical placement authority')
  }
  const slabless = nuc.placement_source === 'native-full-extension-v1' || nuc.placement_source === 'chemical-modification-v1'
  if (slabless) {
    const modification = nuc.placement_source === 'chemical-modification-v1'
    if (typeof nuc.extension_id !== 'string' || !nuc.extension_id.trim()
        || typeof nuc.strand_id !== 'string' || !nuc.strand_id.trim()
        || nuc.is_modification !== modification
        || (modification && (typeof nuc.modification !== 'string' || !nuc.modification.trim()))) {
      placementIntegrityFailure(nuc, 'slabless_identity', { extension_id: nuc.extension_id,
        strand_id: nuc.strand_id, is_modification: nuc.is_modification, modification: nuc.modification },
      'Slabless placement is reserved for explicitly identified extensions and chemical modifications')
    }
  }
  if (slabless && (nuc.slab_position !== null || nuc.slab_quaternion !== null)) {
    placementIntegrityFailure(nuc, 'slab_position', nuc.slab_position, 'Slabless extension or modification records must explicitly declare null slab poses')
  }
  for (const field of ['backbone_position', 'base_position', 'base_normal', 'axis_tangent', ...(slabless ? [] : ['slab_position'])]) {
    const value = nuc[field]
    if (!Array.isArray(value) || value.length !== 3 || !value.every(Number.isFinite)) {
      placementIntegrityFailure(nuc, field, value, 'Expected exactly three finite coordinates')
    }
  }
  if (slabless) return nuc
  const q = nuc.slab_quaternion
  if (!Array.isArray(q) || q.length !== 4 || !q.every(Number.isFinite)
      || Math.abs(Math.hypot(...q) - 1) > 1e-5) {
    placementIntegrityFailure(nuc, 'slab_quaternion', q, 'Expected a finite unit quaternion in x,y,z,w order')
  }
  const tangent = nuc.axis_tangent
  if (Math.abs(Math.hypot(...tangent) - 1) > 1e-5) {
    placementIntegrityFailure(nuc, 'axis_tangent', tangent, 'Expected a unit local axis tangent')
  }
  return nuc
}

/** Preserve the complete authoritative pose when a consumer needs a position Map. */
export function attachNativePose(position, nuc) {
  validateNativePlacement(nuc)
  position.nativePlacement = { ...nuc }
  for (const field of ['backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']) {
    if (nuc[field]) position.nativePlacement[field] = [...nuc[field]]
  }
  return position
}

export function requireMappedNativePose(position, identity) {
  const nuc = position?.nativePlacement
  if (!nuc) placementIntegrityFailure(identity, 'nativePlacement', null, 'The animation endpoint omitted its authoritative nucleotide pose')
  return validateNativePlacement(nuc)
}

/** Copy a complete authority update; partial coordinates cannot retain stale slabs. */
export function replaceNativePlacement(target, update) {
  validateNativePlacement({ helix_id: target.helix_id, bp_index: target.bp_index, direction: target.direction, ...update })
  for (const field of ['backbone_position', 'base_position', 'base_normal', 'axis_tangent', 'slab_position', 'slab_quaternion']) {
    if (update[field] !== undefined) target[field] = update[field] === null ? null : [...update[field]]
  }
  target.placement_source = update.placement_source
}

/** Keep repeated inserted sites addressable while preserving existing map keys. */
export function setNativePoseMap(map, position, nuc) {
  attachNativePose(position, nuc)
  const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
  const first = map.get(key)
  if (!first) {
    position.nativeCopies = [position]
    map.set(key, position)
  } else first.nativeCopies.push(position)
  return position
}

export function nativeMapPosition(map, nuc, copy = 0) {
  const first = map?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
  if (!first) return undefined
  if (first.nativeCopies) {
    const position = first.nativeCopies[copy]
    if (!position) placementIntegrityFailure(nuc, 'nativeCopies', copy, 'The geometry endpoint omitted an inserted nucleotide copy')
    return position
  }
  if (copy !== 0) placementIntegrityFailure(nuc, 'nativeCopies', copy, 'The geometry map merged separate inserted nucleotide copies')
  return first
}

export function validateNativePoseMap(map) {
  for (const position of map?.values() ?? []) {
    for (const copy of position.nativeCopies ?? [position]) requireMappedNativePose(copy, copy.nativePlacement)
  }
}

/** Surface unresolved automated-test reviews in the running app as well as CI.
 * Reading an existing incident never creates a second journal entry. */
export function initNativePlacementIntegrityMonitor({ intervalMs = 30000 } = {}) {
  let stopped = false
  let pending = false
  async function check() {
    if (stopped || pending) return
    pending = true
    try {
      const { docHeaders } = await import('../shared/doc_id.js')
      const response = await fetch('/api/design/placement-integrity-status', { headers: docHeaders() })
      const status = await response.json()
      if (!response.ok && !status.review_required) throw new Error(`Placement review status returned HTTP ${response.status}`)
      if (stopped || !status.review_required) return
      const detail = {
        code: 'NATIVE_PLACEMENT_INTEGRITY', time: new Date().toISOString(),
        summary: 'An automated DNA positioning check failed. Molecular rendering is blocked until the required full placement review is completed.',
        reason: status.message ?? 'An unresolved positioning incident was found in the persistent review journal.',
        report_delivery_error: status.report_delivery_error,
        review_required: true, incidents: status.incidents ?? [], phase: 'persistent-review-status',
      }
      lastFailure = detail
      window.dispatchEvent(new CustomEvent(PLACEMENT_FAILURE_EVENT, { detail }))
      showPlacementFailure(detail)
    } catch (error) {
      // Native pose validation and backend geometry guards still fail closed;
      // a temporarily unavailable status endpoint is not a new geometry incident.
      console.warn('[native-placement] Could not read the placement review journal:', String(error))
    } finally {
      pending = false
    }
  }
  void check()
  const timer = setInterval(check, intervalMs)
  return () => { stopped = true; clearInterval(timer) }
}

/** A strand connector must terminate at its supplied backbone site, never its base. */
export function requireNativeBackbonePosition(nuc) {
  const position = nuc?.backbone_position
  if (!Array.isArray(position) || position.length !== 3 || !position.every(Number.isFinite)) {
    placementIntegrityFailure(nuc, 'backbone_position', position, 'The native strand connector is missing a finite authoritative backbone site; no base-site substitute is permitted')
  }
  return position
}
