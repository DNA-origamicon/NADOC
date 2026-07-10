// Chain Simulations project endpoint helpers. Mirror animation_endpoints.js: each
// mutation only touches ``design.chain_sim_projects`` (a display/job-request annotation,
// never a nucleotide move), so ``skipGeometry: true`` avoids the multi-second geometry
// refetch. Re-exported via ``export * from './chain_sim_endpoints.js'`` in client.js so
// callers keep importing from ../api/client.js unchanged.

import { _request, _syncFromDesignResponse } from './client.js'

const BASE = '/design/chain-sim-projects'

export async function createChainSimProject(name = 'Chain', stages = null) {
  const body = stages ? { name, stages } : { name }
  const json = await _request('POST', BASE, body)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function updateChainSimProject(projectId, patch) {
  const json = await _request('PATCH', `${BASE}/${projectId}`, patch)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function deleteChainSimProject(projectId) {
  const json = await _request('DELETE', `${BASE}/${projectId}`)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/** Replace a project's ordered stage list (every queue edit goes through here). */
export async function setChainSimStages(projectId, stages) {
  const json = await _request('PUT', `${BASE}/${projectId}/stages`, { stages })
  return _syncFromDesignResponse(json, { skipGeometry: true })
}
