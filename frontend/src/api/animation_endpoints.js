// Animation, assembly-animation, and assembly-configuration endpoint helpers.
// Extracted verbatim from `client.js` (Refactor 03-B). Re-exported via
// `export * from './animation_endpoints.js'` in `client.js` so that every
// existing caller (`import { createAnimation } from '../api/client.js'`,
// `import * as api from '../api/client.js'`) continues working unchanged.

import { _request, _syncFromDesignResponse, _syncFromAssemblyResponse } from './client.js'

// ── Assembly configurations ──────────────────────────────────────────────────

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
