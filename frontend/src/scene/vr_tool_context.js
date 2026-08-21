import { parseBaseKey } from './base_ref.js'
import { expandedHelixOffsetFrame } from './expanded_helix_offsets.js'

const VR_TOOL_CONTEXT_REASONS = new Set([
  'resolved', 'end_selection_required', 'invalid_end_ref',
  'loop_copy_not_supported', 'synthetic_end_not_supported',
  'ambiguous_live_end', 'stale_live_end', 'not_terminal', 'helix_not_live',
  'ambiguous_continuation_face', 'no_continuation_face',
  'invalid_continuation_face',
])

function _direction(value) {
  return value?.value ?? value
}

function _effectiveTransform(helixId, design) {
  return (design?.cluster_transforms ?? []).some(transform => {
    if (!transform?.helix_ids?.includes(helixId)) return false
    const rotation = transform.rotation ?? [0, 0, 0, 1]
    const translation = transform.translation ?? [0, 0, 0]
    return rotation.length === 4 && translation.length === 3 && (
      Math.abs(rotation[0]) > 1e-9 || Math.abs(rotation[1]) > 1e-9 ||
      Math.abs(rotation[2]) > 1e-9 || Math.abs(rotation[3] - 1) > 1e-9 ||
      translation.some(value => Math.abs(value) > 1e-9)
    )
  })
}

function _singleEndFootprint(helix, design) {
  let cell = helix?.grid_pos
  if (!Array.isArray(cell) || cell.length !== 2 ||
      !cell.every(Number.isSafeInteger)) {
    const match = /^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)/.exec(helix?.id ?? '')
    cell = match ? [Number(match[1]), Number(match[2])] : null
  }
  const latticeType = design?.lattice_type ?? 'HONEYCOMB'
  if (!cell || !['HONEYCOMB', 'SQUARE'].includes(latticeType)) return null
  return {
    kind: 'single_end_cell',
    latticeType,
    cells: [[...cell]],
  }
}

function _validSingleEndFootprint(value) {
  return value?.kind === 'single_end_cell' &&
    ['HONEYCOMB', 'SQUARE'].includes(value.latticeType) &&
    Array.isArray(value.cells) && value.cells.length === 1 &&
    Array.isArray(value.cells[0]) && value.cells[0].length === 2 &&
    value.cells[0].every(Number.isSafeInteger)
}

function _endConnections(parsed, design) {
  const matchesHalf = half => half?.helix_id === parsed.helix_id &&
    half?.index === parsed.bp_index && _direction(half?.strand) === parsed.direction
  const matchesForced = connection => (
    connection?.three_prime_helix_id === parsed.helix_id &&
    connection?.three_prime_bp === parsed.bp_index &&
    _direction(connection?.three_prime_direction) === parsed.direction
  ) || (
    connection?.five_prime_helix_id === parsed.helix_id &&
    connection?.five_prime_bp === parsed.bp_index &&
    _direction(connection?.five_prime_direction) === parsed.direction
  )
  return [
    ...(design?.crossovers ?? [])
      .filter(connection => matchesHalf(connection.half_a) || matchesHalf(connection.half_b))
      .map(connection => ({ type: 'crossover', id: connection.id })),
    ...(design?.forced_ligations ?? [])
      .filter(matchesForced)
      .map(connection => ({ type: 'forced_ligation', id: connection.id })),
  ].filter(connection => typeof connection.id === 'string' && connection.id)
    .sort((a, b) => a.type.localeCompare(b.type) || a.id.localeCompare(b.id))
}

/** Resolve a canonical End selection to the same physical face metadata used by
 * desktop blunt-end menus. This is read-only and refuses synthetic/ambiguous ends.
 */
export function resolveVREndToolContext(
  selectedRef,
  { geometry = [], design = null, domainEnds = [] } = {},
) {
  if (selectedRef?.kind !== 'end') {
    return { accepted: false, reason: 'end_selection_required', context: null }
  }
  const parsed = parseBaseKey(selectedRef.key)
  if (!parsed || parsed.helix_id === '__xb__') {
    return { accepted: false, reason: 'invalid_end_ref', context: null }
  }
  if (parsed.copy !== 0) {
    return { accepted: false, reason: 'loop_copy_not_supported', context: null }
  }
  if (parsed.helix_id.startsWith('__ext_') || parsed.helix_id.startsWith('__lnk__')) {
    return { accepted: false, reason: 'synthetic_end_not_supported', context: null }
  }

  const nucleotides = (geometry ?? []).filter(nucleotide =>
    nucleotide?.helix_id === parsed.helix_id &&
    nucleotide?.bp_index === parsed.bp_index &&
    _direction(nucleotide?.direction) === parsed.direction &&
    (nucleotide?.copy_k ?? 0) === parsed.copy)
  if (nucleotides.length !== 1) {
    return {
      accepted: false,
      reason: nucleotides.length ? 'ambiguous_live_end' : 'stale_live_end',
      context: null,
    }
  }
  const nucleotide = nucleotides[0]
  if (!nucleotide.is_five_prime && !nucleotide.is_three_prime) {
    return { accepted: false, reason: 'not_terminal', context: null }
  }
  const helix = design?.helices?.find(candidate => candidate.id === parsed.helix_id)
  if (!helix) return { accepted: false, reason: 'helix_not_live', context: null }

  const candidates = (domainEnds ?? []).filter(end =>
    end?.helixId === parsed.helix_id && end?.bp === parsed.bp_index &&
    Array.isArray(end.owners) && end.owners.some(owner =>
      owner?.strandId === nucleotide.strand_id &&
      owner?.domainIndex === (nucleotide.domain_index ?? 0) &&
      _direction(owner?.direction) === parsed.direction))
  if (candidates.length !== 1) {
    return {
      accepted: false,
      reason: candidates.length ? 'ambiguous_continuation_face' : 'no_continuation_face',
      context: null,
    }
  }
  const face = candidates[0]
  if (!Number.isInteger(face.diskBp) || ![-1, 1].includes(face.openSide) ||
      typeof face.plane !== 'string' || !face.plane ||
      typeof face.offsetNm !== 'number' || !Number.isFinite(face.offsetNm) ||
      !Array.isArray(face.ringPos3d) || face.ringPos3d.length !== 3 ||
      !face.ringPos3d.every(Number.isFinite) ||
      !Array.isArray(face.endPos3d) || face.endPos3d.length !== 3 ||
      !face.endPos3d.every(Number.isFinite) ||
      !Array.isArray(face.faceNormal3d) || face.faceNormal3d.length !== 3 ||
      !face.faceNormal3d.every(Number.isFinite) ||
      Math.hypot(...face.faceNormal3d) < 1e-9) {
    return { accepted: false, reason: 'invalid_continuation_face', context: null }
  }
  const expansion = expandedHelixOffsetFrame(design)
  const expandedOffset = expansion?.offsets.get(parsed.helix_id)
  if (!expandedOffset) {
    return { accepted: false, reason: 'invalid_continuation_face', context: null }
  }
  const expand = point => point.map((value, axis) => value + expandedOffset[axis])
  const continuationBp = face.bp + Math.max(0, face.openSide)
  const continuationPosition = face.openSide < 0 ? face.endPos3d : face.ringPos3d
  return {
    accepted: true,
    reason: 'resolved',
    context: {
      kind: 'continuation_end',
      helixId: face.helixId,
      bp: face.bp,
      diskBp: face.diskBp,
      continuationBp,
      openSide: face.openSide,
      plane: face.plane,
      offsetNm: face.offsetNm,
      facePosition: [...face.ringPos3d],
      faceNormal: [...face.faceNormal3d],
      continuationPosition: [...continuationPosition],
      expandedFacePosition: expand(face.ringPos3d),
      expandedFaceNormal: [...face.faceNormal3d],
      expandedContinuationPosition: expand(continuationPosition),
      strandId: nucleotide.strand_id,
      domainIndex: nucleotide.domain_index ?? 0,
      direction: parsed.direction,
      endRole: nucleotide.is_five_prime && nucleotide.is_three_prime
        ? 'both' : nucleotide.is_five_prime ? 'five_prime' : 'three_prime',
      overhangId: face.overhangId ?? null,
      connections: _endConnections(parsed, design),
      footprint: _singleEndFootprint(helix, design),
      deformed: !!design?.deformations?.length ||
        _effectiveTransform(face.helixId, design),
    },
  }
}

/** Build the bounded, target-bound feedback record consumed by native VR. */
export function vrToolFeedbackPayload(sequence, draft, state) {
  if (!Number.isSafeInteger(sequence) || sequence < 1 || draft?.target_kind !== 'end' ||
      typeof draft.target_identity !== 'string' || !draft.target_identity ||
      draft.target_identity.length > 2048 || /\s/.test(draft.target_identity)) return null
  const context = state?.toolContext ?? null
  const reason = context ? 'resolved' : state?.toolContextReason
  if (!VR_TOOL_CONTEXT_REASONS.has(reason)) return null
  const validVector = value => Array.isArray(value) && value.length === 3 &&
    value.every(Number.isFinite)
  if (context) {
    if (!validVector(context.facePosition) || !validVector(context.faceNormal) ||
        Math.hypot(...context.faceNormal) < 1e-9 ||
        !validVector(context.expandedFacePosition) ||
        !validVector(context.expandedFaceNormal) ||
        Math.hypot(...context.expandedFaceNormal) < 1e-9) return null
  }
  const footprintResolved = _validSingleEndFootprint(context?.footprint) &&
    validVector(context?.continuationPosition) &&
    validVector(context?.expandedContinuationPosition)
  return {
    tool_config_sequence: sequence,
    target_identity: draft.target_identity,
    target_kind: draft.target_kind,
    resolved: !!context,
    reason,
    face_position: context ? [...context.facePosition] : null,
    face_normal: context ? [...context.faceNormal] : null,
    preview_origin: footprintResolved ? [...context.continuationPosition] : null,
    expanded_face_position: context ? [...context.expandedFacePosition] : null,
    expanded_face_normal: context ? [...context.expandedFaceNormal] : null,
    expanded_preview_origin: footprintResolved
      ? [...context.expandedContinuationPosition] : null,
    occupied: !!context?.connections?.length,
    deformed: context?.deformed === true,
    footprint_resolved: footprintResolved,
    footprint_lattice_type: footprintResolved
      ? context.footprint.latticeType : null,
    footprint_cell: footprintResolved
      ? [...context.footprint.cells[0]] : null,
  }
}
