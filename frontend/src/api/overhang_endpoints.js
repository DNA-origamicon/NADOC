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

/**
 * Resize an overhang via its FREE-end cap (Domain Designer drag-to-resize).
 * Backend re-tiles sub-domains so the last one absorbs Δ length.
 *   end:      '5p' | '3p'    — must be the strand's free tip
 *   deltaBp:  signed integer — bp offset applied to the strand-domain endpoint
 */
export async function resizeOverhangFreeEnd(overhangId, { end, deltaBp }) {
  const json = await _request(
    'POST',
    `/design/overhang/${encodeURIComponent(overhangId)}/resize-free-end`,
    { end, delta_bp: deltaBp },
  )
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

// ── Phase 3: sub-domain CRUD wrappers ──────────────────────────────────────────
// Backend lives in backend/api/crud.py Phase-1 endpoints; Phase 3 adds
// `generate-random` for a single sub-domain and PATCH for `tm_settings`.

export async function listSubDomains(overhangId) {
  return _request('GET', `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains`)
}

export async function splitSubDomain(overhangId, { sub_domain_id, split_at_offset }) {
  const json = await _request(
    'POST',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/split`,
    { sub_domain_id, split_at_offset },
  )
  return _syncFromDesignResponse(json)
}

export async function mergeSubDomains(overhangId, { sub_domain_a_id, sub_domain_b_id }) {
  const json = await _request(
    'POST',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/merge`,
    { sub_domain_a_id, sub_domain_b_id },
  )
  return _syncFromDesignResponse(json)
}

export async function patchSubDomain(overhangId, subDomainId, body) {
  const json = await _request(
    'PATCH',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/${encodeURIComponent(subDomainId)}`,
    body,
  )
  return _syncFromDesignResponse(json)
}

export async function recomputeSubDomainAnnotations(overhangId, subDomainId) {
  const json = await _request(
    'POST',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/${encodeURIComponent(subDomainId)}/recompute-annotations`,
  )
  return _syncFromDesignResponse(json)
}

export async function generateSubDomainRandom(overhangId, subDomainId, { seed } = {}) {
  const body = (seed !== undefined && seed !== null) ? { seed } : {}
  const json = await _request(
    'POST',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/${encodeURIComponent(subDomainId)}/generate-random`,
    body,
  )
  return _syncFromDesignResponse(json)
}

export async function patchTmSettings({ na_mM, conc_nM } = {}) {
  const body = {}
  if (na_mM   !== undefined) body.na_mM   = na_mM
  if (conc_nM !== undefined) body.conc_nM = conc_nM
  const json = await _request('PATCH', '/design/tm-settings', body)
  return _syncFromDesignResponse(json)
}

// ── Phase 4: per-sub-domain rotation wrappers ────────────────────────────────
//
// `patchSubDomainRotation(commit:false)` is the gizmo-drag live preview;
// `commit:true` is the pointer-up commit (server coalesces within 2 s).

export async function patchSubDomainRotation(overhangId, subDomainId, { theta_deg, phi_deg, commit = false } = {}) {
  const json = await _request(
    'PATCH',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/${encodeURIComponent(subDomainId)}/rotation`,
    { theta_deg, phi_deg, commit },
  )
  return _syncFromDesignResponse(json)
}

export async function patchSubDomainRotationsBatch(overhangId, ops, commit = false) {
  // ops: Array<{ sub_domain_id, theta_deg, phi_deg }>
  const json = await _request(
    'PATCH',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/rotations-batch`,
    { ops, commit },
  )
  return _syncFromDesignResponse(json)
}

export async function getSubDomainFrame(overhangId, subDomainId) {
  // Read-only — returns { pivot: [x,y,z], parent_axis: [x,y,z], phi_ref: [x,y,z] }.
  return _request(
    'GET',
    `/design/overhang/${encodeURIComponent(overhangId)}/sub-domains/${encodeURIComponent(subDomainId)}/frame`,
  )
}


// ── Phase 5: OverhangBinding CRUD wrappers ──────────────────────────────────
//
// Bindings record a Watson-Crick sub-domain↔sub-domain pairing across two
// overhangs. Flipping `bound` to True locks the connecting joint at the
// duplex-satisfying angle; flipping it back restores the joint window from
// the first-claimant snapshot.

export async function listOverhangBindings() {
  // Read-only — no design-sync side effect.
  return _request('GET', '/design/overhang-bindings')
}

export async function createOverhangBinding(body) {
  // body: { sub_domain_a_id, sub_domain_b_id, binding_mode?, target_joint_id?, allow_n_wildcard? }
  const json = await _request('POST', '/design/overhang-bindings', body)
  return _syncFromDesignResponse(json)
}

export async function patchOverhangBinding(bindingId, patch) {
  // patch: subset of { name, bound, binding_mode, target_joint_id, allow_n_wildcard }
  const json = await _request(
    'PATCH',
    `/design/overhang-bindings/${encodeURIComponent(bindingId)}`,
    patch,
  )
  return _syncFromDesignResponse(json)
}

export async function deleteOverhangBinding(bindingId) {
  const json = await _request(
    'DELETE',
    `/design/overhang-bindings/${encodeURIComponent(bindingId)}`,
  )
  return _syncFromDesignResponse(json)
}
