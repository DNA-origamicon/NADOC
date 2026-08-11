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

export async function patchOverhang(overhangId, { sequence, label, rotation, deferReassign } = {}) {
  const body = {}
  if (sequence !== undefined) body.sequence = sequence
  if (label    !== undefined) body.label    = label
  if (rotation !== undefined) body.rotation = rotation
  // Skip the per-write staple re-derivation when the caller (the connection-creation
  // flow) will re-derive once at apply — avoids redundant full re-assignments.
  if (deferReassign) body.defer_reassign = true
  const json = await _request('PATCH', `/design/overhang/${encodeURIComponent(overhangId)}`, body)
  // Connection setup always caps the sequence to the live backing-domain length
  // before setting deferReassign.  It therefore changes bases only; the atomic
  // connection-version Apply that follows performs the one required geometry sync.
  return _syncFromDesignResponse(json, { skipGeometry: !!deferReassign })
}

export async function patchOverhangRotationsBatch(ops) {
  // ops: Array<{ overhang_id: string, rotation: [qx, qy, qz, qw] }>
  const json = await _request('PATCH', '/design/overhangs/rotations', { ops })
  return _syncFromDesignResponse(json)
}

export async function generateOverhangRandomSequence(overhangId, { deferReassign } = {}) {
  const q = deferReassign ? '?defer_reassign=true' : ''
  const json = await _request('POST', `/design/overhang/${encodeURIComponent(overhangId)}/generate-random${q}`)
  // This endpoint deliberately preserves the overhang's domain length: it only
  // fills sequence fields (and their feature-log / derived-strand metadata).
  // No nucleotide position or helix axis can change, so keep the geometry that
  // is already in the store.  The generic sync fallback would otherwise issue
  // a full GET /design/geometry; on deformed designs that also recomputes the
  // embedded straight geometry, making a sequence-only edit take several seconds.
  return _syncFromDesignResponse(json, { skipGeometry: true })
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

export async function deleteOverhangs(overhangIds) {
  const ids = [...new Set((overhangIds ?? []).filter(Boolean))]
  if (!ids.length) return null
  const json = await _request('POST', '/design/overhangs/batch-delete', { overhang_ids: ids })
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

// ── Connection versions (design-exploration candidates; metadata only) ────────
export async function createConnectionVersion(payload) {
  // payload: { overhang_a_id, overhang_b_id, connection_type, overhang_a_seq?,
  //            overhang_b_seq?, bridge_length?, bridge_seq?, applied?, name? }
  const json = await _request('POST', '/design/connection-versions', payload)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

/** First-time Connect: create the version and materialize it in one backend
 * snapshot, so one Undo removes both topology and the sidebar version group. */
export async function createAndApplyConnectionVersion(payload) {
  const json = await _request('POST', '/design/connection-versions/connect', payload)
  return _syncFromDesignResponse(json)
}

export async function patchConnectionVersion(versionId, patch) {
  const json = await _request('PATCH', `/design/connection-versions/${encodeURIComponent(versionId)}`, patch)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function deleteConnectionVersion(versionId) {
  const json = await _request('DELETE', `/design/connection-versions/${encodeURIComponent(versionId)}`)
  return _syncFromDesignResponse(json, { skipGeometry: true })
}

export async function relaxOverhangBinding(bindingId) {
  // UNIFIED direct-binding relax (root-to-root + end-to-root): swing the driver's
  // overhang duplex about its root (persisted as the driver's overhang rotation;
  // the driven tip co-rotates) + cluster kinematics (joint-rotate, else rigid-
  // translate the driven root cluster) so the driven tip↔root bond closes to one
  // backbone bond. Same rigid body → swing only. The binding stays bound.
  const json = await _request('POST', `/design/overhang-bindings/${encodeURIComponent(bindingId)}/relax`)
  return _syncFromDesignResponse(json)
}

export async function applyConnectionVersion(versionId) {
  // Atomically materializes the version: sets both overhang sequences (resizing
  // each overhang to the sequence length), tears down the pair's current
  // connection/binding, and (re)creates the version's connection type.
  const json = await _request('POST', `/design/connection-versions/${encodeURIComponent(versionId)}/apply`)
  return _syncFromDesignResponse(json)
}

export async function patchConnectionDisplayPose(connId, patch) {
  // patch: subset of { unbound_angle_deg, bound_angle_deg } — authored hinge
  // angles for the animation player; the server auto-detects + stores
  // target_joint_id. Annotation-only (never touches linker topology/bridge).
  const json = await _request(
    'PATCH',
    `/design/overhang-connections/${encodeURIComponent(connId)}/display-pose`,
    patch,
  )
  return _syncFromDesignResponse(json)
}

/** Server-side Johnson random sequence — used by the bridge-sequence box's
 *  "Gen" button before the linker exists. Returns a string of length `length`
 *  drawn against the current scaffold + staple corpus. */
export async function generateRandomSequence(length) {
  const json = await _request('POST', '/design/random-sequence', { length })
  return json?.sequence ?? null
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

// ── Proposal-B Duplex graph (register-bearing overhang pairing) ───────────────
// See memory/project_overhang_duplex_foundation.md. These sit alongside the
// legacy binding endpoints (retired in Phase 6).

export async function createDuplex(body) {
  // body: { left:{overhang_id,start_bp,end_bp}, right:{...}, driver?, bound?,
  //         binding_mode?, allow_n_wildcard?, connection_type? }
  const json = await _request('POST', '/design/duplexes', body)
  return _syncFromDesignResponse(json)
}

export async function patchDuplex(duplexId, patch) {
  // patch: subset of { left, right, driver, bound, name }
  const json = await _request('PATCH', `/design/duplexes/${encodeURIComponent(duplexId)}`, patch)
  return _syncFromDesignResponse(json)
}

export async function deleteDuplex(duplexId) {
  const json = await _request('DELETE', `/design/duplexes/${encodeURIComponent(duplexId)}`)
  return _syncFromDesignResponse(json)
}

export async function connectDuplex(body, { skipGeometry = false } = {}) {
  // body: { overhang_a_id, overhang_a_attach, overhang_b_id, overhang_b_attach, driver?, allow_n_wildcard? }
  // Producer: creates a display duplex at the attach ends (length = min, no resize).
  // Returns null on a 409 (pair already connected) so callers can ignore duplicates.
  const json = await _request('POST', '/design/duplexes/connect', body)
  return _syncFromDesignResponse(json, { skipGeometry })
}

export async function syncDuplexesFromBindings() {
  // Ensure every legacy OverhangBinding pair also has a display duplex (idempotent).
  const json = await _request('POST', '/design/duplexes/sync-from-bindings')
  return _syncFromDesignResponse(json)
}

export async function relaxDuplex(duplexId) {
  // Proposal-B equivalent of relaxOverhangBinding for a duplex-backed direct
  // connection with NO legacy OverhangBinding (e.g. a different-length root-to-root
  // pair): same swing-about-driver-root + cluster-kinematics solve that closes the
  // driven overhang's stretched tip↔root bond. The duplex must be bound.
  const json = await _request('POST', `/design/duplexes/${encodeURIComponent(duplexId)}/relax`)
  return _syncFromDesignResponse(json)
}

export async function patchBindingDisplayPose(bindingId, patch) {
  // patch: subset of { unbound_angle_deg, bound_angle_deg } — authored hinge
  // angles for the animation player. Annotation-only (never flips `bound`).
  const json = await _request(
    'PATCH',
    `/design/overhang-bindings/${encodeURIComponent(bindingId)}/display-pose`,
    patch,
  )
  return _syncFromDesignResponse(json)
}

export async function patchOverhangStrandAnimSetup(overhangId, setup) {
  // setup: the full Strand-Animation param dict (or null to clear). Display-only
  // annotation stored on OverhangSpec.strand_anim_setup; the per-keyframe φ lives
  // on AnimationKeyframe.strand_anim_phi.
  const json = await _request(
    'PATCH',
    `/design/overhangs/${encodeURIComponent(overhangId)}/strand-anim-setup`,
    { setup },
  )
  return _syncFromDesignResponse(json)
}
