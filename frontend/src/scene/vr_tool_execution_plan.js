/** Pure, non-executing transaction descriptors for parameterized native-VR tools.
 *
 * These descriptors deliberately contain no API calls. They pin the exact desktop
 * operation, preflight, transient-preview cleanup, and undo authority that a later
 * adapter must use after the physical headset gates pass.
 */
import { parseBaseKey } from './base_ref.js'
import { clusterIdForNucleotide } from './cluster_entries.js'
import { normalizeVRToolConfig } from './vr_tool_config.js'

function _direction(value) {
  return value?.value ?? value
}

function _targetMatches(config, toolTarget) {
  return !!toolTarget && toolTarget.identity === config.target_identity &&
    toolTarget.selectionKind === config.target_kind &&
    JSON.stringify(toolTarget.ownerTokens) ===
      JSON.stringify(config.target_owner_tokens) &&
    toolTarget.selectedRef?.kind === config.target_kind
}

function _exactEndNucleotide(selectedRef, geometry) {
  const parsed = parseBaseKey(selectedRef?.key)
  if (!parsed || parsed.copy !== 0 || parsed.helix_id === '__xb__') return null
  const matches = (geometry ?? []).filter(nucleotide =>
    nucleotide?.helix_id === parsed.helix_id &&
    nucleotide?.bp_index === parsed.bp_index &&
    _direction(nucleotide?.direction) === parsed.direction &&
    (nucleotide?.copy_k ?? 0) === parsed.copy)
  return matches.length === 1 ? matches[0] : null
}

/** Resolve the explicit deformation scope for a Cluster or exact End target. */
export function resolveVRDeformationScope(selectedRef, { design = null, geometry = [] } = {}) {
  const clusters = design?.cluster_transforms ?? []
  if (selectedRef?.kind === 'cluster') {
    const cluster = clusters.find(candidate => candidate.id === selectedRef.id)
    return cluster?.helix_ids?.length
      ? { resolved: true, reason: 'resolved', clusterIds: [cluster.id] }
      : { resolved: false, reason: 'stale_cluster', clusterIds: [] }
  }
  if (selectedRef?.kind !== 'end') {
    return { resolved: false, reason: 'unsupported_target', clusterIds: [] }
  }
  const nucleotide = _exactEndNucleotide(selectedRef, geometry)
  if (!nucleotide) {
    return { resolved: false, reason: 'stale_end', clusterIds: [] }
  }
  if (!clusters.length) {
    return { resolved: true, reason: 'resolved', clusterIds: [] }
  }
  const clusterId = clusterIdForNucleotide(nucleotide, design)
  return clusterId
    ? { resolved: true, reason: 'resolved', clusterIds: [clusterId] }
    : { resolved: false, reason: 'target_scope_unresolved', clusterIds: [] }
}

function _validFootprint(footprint) {
  return footprint?.kind === 'single_end_cell' &&
    ['HONEYCOMB', 'SQUARE'].includes(footprint.latticeType) &&
    Array.isArray(footprint.cells) && footprint.cells.length === 1 &&
    Array.isArray(footprint.cells[0]) && footprint.cells[0].length === 2 &&
    footprint.cells[0].every(Number.isSafeInteger)
}

function _extrusionPlan(config, toolTarget) {
  const context = toolTarget?.toolContext
  if (config.target_kind !== 'end' || context?.kind !== 'continuation_end') {
    return { accepted: false, reason: 'exact_end_context_required', plan: null }
  }
  if (config.length_bp === 0) {
    return { accepted: false, reason: 'length_required', plan: null }
  }
  if (context.connections?.length) {
    return { accepted: false, reason: 'occupied_target', plan: null }
  }
  if (context.deformed) {
    return { accepted: false, reason: 'deformed_frame_required', plan: null }
  }
  if (!_validFootprint(context.footprint) ||
      !['XY', 'XZ', 'YZ'].includes(context.plane) ||
      ![-1, 1].includes(context.openSide) ||
      !Number.isSafeInteger(context.continuationBp) ||
      !Number.isFinite(context.offsetNm)) {
    return { accepted: false, reason: 'footprint_unresolved', plan: null }
  }
  return {
    accepted: true,
    reason: 'ready_read_only',
    plan: {
      kind: 'extrude_continuation',
      targetIdentity: config.target_identity,
      commit: {
        apiMethod: 'addBundleContinuation',
        arguments: {
          cells: context.footprint.cells.map(cell => [...cell]),
          lengthBp: context.openSide * config.direction_sign * config.length_bp,
          plane: context.plane,
          offsetNm: context.offsetNm,
          strandFilter: config.strand_filter,
          ligateAdjacent: config.ligate_adjacent,
        },
      },
      lifecycle: {
        previewAuthority: 'native_read_only_geometry',
        preflight: 'desktop_continuation_validation_required',
        cancel: 'discard_descriptor',
        undo: 'desktop_feature_log',
      },
    },
  }
}

function _deformationPlan(config, toolTarget, environment) {
  if (!['cluster', 'end'].includes(config.target_kind)) {
    return { accepted: false, reason: 'unsupported_target', plan: null }
  }
  if (config.plane_a_bp === null || config.plane_b_bp === null) {
    return { accepted: false, reason: 'planes_required', plan: null }
  }
  if (config.plane_a_bp >= config.plane_b_bp) {
    return { accepted: false, reason: 'ordered_planes_required', plan: null }
  }
  const scope = resolveVRDeformationScope(toolTarget.selectedRef, environment)
  if (!scope.resolved) return { accepted: false, reason: scope.reason, plan: null }
  const params = config.mode === 'twist'
    ? { [config.amount_mode]: config.amount }
    : { angle_deg: config.angle_deg, direction_deg: config.direction_deg }
  const args = {
    type: config.mode,
    planeA: config.plane_a_bp,
    planeB: config.plane_b_bp,
    params,
    helixIds: [],
    clusterIds: [...scope.clusterIds],
  }
  return {
    accepted: true,
    reason: 'ready_read_only',
    plan: {
      kind: 'deformation',
      targetIdentity: config.target_identity,
      preflight: { apiMethod: 'validateDeformation', arguments: { ...args } },
      preview: {
        apiMethod: 'addDeformation',
        arguments: [
          args.type, args.planeA, args.planeB, { ...args.params },
          [...args.helixIds], true, [...args.clusterIds],
        ],
        transient: true,
      },
      commit: {
        apiMethod: 'addDeformation',
        arguments: [
          args.type, args.planeA, args.planeB, { ...args.params },
          [...args.helixIds], false, [...args.clusterIds],
        ],
        requiresPreviewDeleteFirst: true,
      },
      lifecycle: {
        cancel: 'delete_transient_preview',
        undo: 'desktop_feature_log',
      },
    },
  }
}

/** Build an exact desktop-operation descriptor without previewing or mutating. */
export function buildVRParameterizedToolPlan(draft, {
  toolTarget = null,
  design = null,
  geometry = [],
} = {}) {
  const config = normalizeVRToolConfig(draft)
  if (!config) return { accepted: false, reason: 'invalid_draft', plan: null }
  if (!_targetMatches(config, toolTarget)) {
    return { accepted: false, reason: 'stale_target', plan: null }
  }
  return config.mode === 'extrude'
    ? _extrusionPlan(config, toolTarget)
    : _deformationPlan(config, toolTarget, { design, geometry })
}
