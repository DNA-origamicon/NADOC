// Overhang endpoint helpers extracted from client.js (refactor 05-A-v2).
// `relaxLinker` remains in client.js because it depends on the still-private
// `_syncClusterOnlyDiff` / `_syncPositionsOnlyDiff` helpers.

import { _request, _syncFromDesignResponse } from './client.js'

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

export async function generateAllOverhangSequences() {
  const json = await _request('POST', '/design/generate-overhang-sequences')
  if (!json) return null
  return { ok: _syncFromDesignResponse(json), count: json.generated_count ?? 0 }
}
