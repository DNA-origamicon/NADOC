/** Pure validation/state for target-bound native-VR tool configuration drafts.
 *
 * These are transport bounds, not design-operation limits. Canonical desktop
 * adapters must still resolve geometry and run their normal validation before a
 * visual preview or mutation can be enabled.
 */

export const VR_TOOL_CONFIG_LIMITS = Object.freeze({
  maxLengthBp: 1_000_000,
  maxPlaneBp: 2_147_483_647,
  maxTwistMagnitude: 1_000_000,
})

const PARAMETERIZED_MODES = new Set(['extrude', 'twist', 'bend'])
const TARGET_KINDS = new Set([
  'none', 'cluster', 'strand', 'domain', 'base', 'end', 'bond', 'crossover',
  'overhang', 'extension', 'protein',
])
const STRAND_FILTERS = new Set(['both', 'scaffold', 'staples'])
const TWIST_AMOUNT_MODES = new Set(['total_degrees', 'degrees_per_nm'])
const PLANE_PICK_REASONS = new Set([
  'resolved', 'invalid_primitive', 'ambiguous_primitive',
  'synthetic_not_supported', 'out_of_range', 'stale_target',
])

export const initialVRToolConfigState = Object.freeze({
  sequence: 0,
  draft: null,
  toolContext: null,
  toolContextReason: null,
})

function _boundedInteger(value, minimum, maximum, { nullable = false } = {}) {
  if (nullable && value === null) return null
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum
    ? value : undefined
}

function _boundedNumber(value, minimum, maximum) {
  return typeof value === 'number' && Number.isFinite(value) &&
    value >= minimum && value <= maximum ? value : undefined
}

function _target(input) {
  const targetIdentity = input?.target_identity
  const targetKind = input?.target_kind
  const ownerTokens = input?.target_owner_tokens
  if (!TARGET_KINDS.has(targetKind) || !Array.isArray(ownerTokens) ||
      ownerTokens.length > 8 || ownerTokens.some(token =>
        typeof token !== 'string' || !token || token.length > 2048 || /\s/.test(token))) return null
  if (targetKind === 'none') {
    if (targetIdentity !== null || ownerTokens.length) return null
  } else if (typeof targetIdentity !== 'string' || !targetIdentity ||
             targetIdentity.length > 2048 || !ownerTokens.length) return null
  return {
    target_identity: targetIdentity,
    target_kind: targetKind,
    target_owner_tokens: [...ownerTokens],
  }
}

/** Return a copied canonical draft, or null for any malformed/unbounded field. */
export function normalizeVRToolConfig(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      !PARAMETERIZED_MODES.has(input.mode)) return null
  const target = _target(input)
  if (!target) return null
  if (input.mode === 'extrude') {
    const lengthBp = _boundedInteger(input.length_bp, 0, VR_TOOL_CONFIG_LIMITS.maxLengthBp)
    if (lengthBp === undefined || ![-1, 1].includes(input.direction_sign) ||
        !STRAND_FILTERS.has(input.strand_filter) ||
        typeof input.ligate_adjacent !== 'boolean' ||
        input.footprint_state !== 'unresolved') return null
    return {
      mode: input.mode, ...target,
      length_bp: lengthBp,
      direction_sign: input.direction_sign,
      strand_filter: input.strand_filter,
      ligate_adjacent: input.ligate_adjacent,
      footprint_state: input.footprint_state,
    }
  }
  const planeA = _boundedInteger(
    input.plane_a_bp, -VR_TOOL_CONFIG_LIMITS.maxPlaneBp,
    VR_TOOL_CONFIG_LIMITS.maxPlaneBp, { nullable: true },
  )
  const planeB = _boundedInteger(
    input.plane_b_bp, -VR_TOOL_CONFIG_LIMITS.maxPlaneBp,
    VR_TOOL_CONFIG_LIMITS.maxPlaneBp, { nullable: true },
  )
  if (planeA === undefined || planeB === undefined) return null
  if (input.mode === 'twist') {
    const amount = _boundedNumber(
      input.amount, -VR_TOOL_CONFIG_LIMITS.maxTwistMagnitude,
      VR_TOOL_CONFIG_LIMITS.maxTwistMagnitude,
    )
    if (!TWIST_AMOUNT_MODES.has(input.amount_mode) || amount === undefined) return null
    return {
      mode: input.mode, ...target,
      plane_a_bp: planeA,
      plane_b_bp: planeB,
      amount_mode: input.amount_mode,
      amount,
    }
  }
  const angle = _boundedNumber(input.angle_deg, 0, 360)
  const direction = _boundedNumber(input.direction_deg, 0, 360)
  if (angle === undefined || direction === undefined) return null
  return {
    mode: input.mode, ...target,
    plane_a_bp: planeA,
    plane_b_bp: planeB,
    angle_deg: angle,
    direction_deg: direction,
  }
}

/** Missing semantic inputs are reported explicitly; this does not promise that a
 * desktop preview adapter exists or that backend validation will pass. */
export function vrToolConfigMissing(draft) {
  const config = normalizeVRToolConfig(draft)
  if (!config) return ['invalid_draft']
  const missing = []
  if (config.target_kind === 'none') missing.push('target')
  if (config.mode === 'extrude') {
    if (config.length_bp === 0) missing.push('length')
    if (config.footprint_state !== 'resolved') missing.push('footprint')
  } else {
    if (config.plane_a_bp === null) missing.push('plane_a')
    if (config.plane_b_bp === null) missing.push('plane_b')
    if (config.plane_a_bp !== null && config.plane_b_bp !== null &&
        config.plane_a_bp >= config.plane_b_bp) missing.push('ordered_planes')
  }
  return missing
}

export function reduceVRToolConfig(
  state = initialVRToolConfigState,
  event = {},
  { toolTarget = null, targetSnapshotPresent = false } = {},
) {
  const sequence = Number(event.sequence)
  if (!Number.isSafeInteger(sequence) || sequence <= state.sequence) {
    return { state, accepted: false, reason: 'invalid_or_stale' }
  }
  if (event.draft === null) {
    return {
      state: {
        sequence, draft: null, toolContext: null, toolContextReason: null,
      },
      accepted: true,
      reason: 'cleared',
    }
  }
  const draft = normalizeVRToolConfig(event.draft)
  if (!draft) return { state, accepted: false, reason: 'invalid_draft' }
  if (targetSnapshotPresent && !toolTarget) {
    return { state, accepted: false, reason: 'stale_target' }
  }
  if (draft.target_kind !== 'none' && (
    !toolTarget || toolTarget.identity !== draft.target_identity ||
    toolTarget.selectionKind !== draft.target_kind ||
    JSON.stringify(toolTarget.ownerTokens) !== JSON.stringify(draft.target_owner_tokens)
  )) return { state, accepted: false, reason: 'target_mismatch' }
  const toolContext = draft.target_kind === 'end'
    ? toolTarget?.toolContext ?? null : null
  const toolContextReason = draft.target_kind === 'end'
    ? toolTarget?.toolContextReason ?? 'geometry_context_required' : null
  return {
    state: { sequence, draft, toolContext, toolContextReason },
    accepted: true,
    reason: draft.target_kind === 'end' && !toolContext
      ? 'geometry_context_required'
      : vrToolConfigMissing(draft).length ? 'incomplete' : 'configured',
  }
}

/** Build one bounded acknowledgement for an explicit, non-selecting plane hit. */
export function vrPlaneFeedbackPayload(event, state, { toolTarget = null, planePick = null } = {}) {
  const sequence = Number(event?.sequence)
  const toolConfigSequence = Number(event?.toolConfigSequence)
  const slot = event?.slot
  const pickedIdentity = event?.identity
  const draft = normalizeVRToolConfig(state?.draft)
  if (!Number.isSafeInteger(sequence) || sequence < 1 ||
      !Number.isSafeInteger(toolConfigSequence) || toolConfigSequence < 1 ||
      toolConfigSequence !== state?.sequence || !['a', 'b'].includes(slot) ||
      typeof pickedIdentity !== 'string' || !pickedIdentity ||
      pickedIdentity.length > 2048 || /\s/.test(pickedIdentity) ||
      !draft || !['twist', 'bend'].includes(draft.mode) ||
      !['cluster', 'end'].includes(draft.target_kind)) return null

  const targetMatches = !!toolTarget &&
    toolTarget.identity === draft.target_identity &&
    toolTarget.selectionKind === draft.target_kind &&
    JSON.stringify(toolTarget.ownerTokens) === JSON.stringify(draft.target_owner_tokens)
  const resolved = targetMatches && planePick?.resolved === true &&
    Number.isSafeInteger(planePick.bp) &&
    Math.abs(planePick.bp) <= VR_TOOL_CONFIG_LIMITS.maxPlaneBp
  const reason = resolved ? 'resolved'
    : targetMatches && PLANE_PICK_REASONS.has(planePick?.reason)
      ? planePick.reason : 'stale_target'
  return {
    plane_pick_sequence: sequence,
    tool_config_sequence: toolConfigSequence,
    target_identity: draft.target_identity,
    target_kind: draft.target_kind,
    picked_identity: pickedIdentity,
    plane_slot: slot,
    resolved,
    reason,
    plane_bp: resolved ? planePick.bp : null,
  }
}
