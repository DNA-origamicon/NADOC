/**
 * Minimal API client for the cadnano editor.
 *
 * Standalone — does not import the main app's store.  All functions
 * return the parsed JSON or null on error.
 */

import { editorStore } from './store.js'
import { nadocBroadcast } from '../shared/broadcast.js'

const BASE = '/api'

async function _request(method, path, body) {
  editorStore.setState({ loading: true })
  const opts = {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body:    body !== undefined ? JSON.stringify(body) : undefined,
  }
  try {
    const r    = await fetch(`${BASE}${path}`, opts)
    const json = await r.json().catch(() => null)
    if (!r.ok) {
      editorStore.setState({ lastError: { status: r.status, message: json?.detail ?? r.statusText }, loading: false })
      return null
    }
    editorStore.setState({ lastError: null, loading: false })
    return json
  } catch (err) {
    editorStore.setState({ lastError: { status: 0, message: err.message }, loading: false })
    return null
  }
}

/** Fetch the current design and update the editor store. */
export async function fetchDesign() {
  const json = await _request('GET', '/design')
  if (json) editorStore.setState({ design: json })
  return json
}

/**
 * Perform a mutation, update the editor store, and notify other tabs.
 * `mutationFn` receives `_request` and should return the response JSON.
 */
export async function mutate(mutationFn) {
  const json = await mutationFn(_request)
  if (json?.design) {
    editorStore.setState({ design: json.design })
    nadocBroadcast.emit('design-changed')
  }
  return json
}

/**
 * Add a helix at a lattice cell (row, col).
 * The backend computes axis position, phase, and twist from the lattice type.
 */
export async function addHelixAtCell(row, col, length_bp = 42) {
  return mutate(req => req('POST', '/design/helix-at-cell', { row, col, length_bp }))
}

/** Delete a helix by ID. */
export async function deleteHelix(helixId) {
  return mutate(req => req('DELETE', `/design/helix/${helixId}`))
}

/** Auto-scaffold the design. */
export async function autoScaffold(params = {}) {
  return mutate(req => req('POST', '/design/auto-scaffold', params))
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
