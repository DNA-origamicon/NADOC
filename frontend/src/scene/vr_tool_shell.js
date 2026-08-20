/** Pure browser-authoritative state machine for native-VR tool intents.
 *
 * The shell deliberately returns effects instead of executing them. Phase 5 can
 * attach desktop preview/commit/undo adapters one tool at a time without letting
 * the native companion become a second design writer.
 */

export const VR_TOOL_MODES = Object.freeze([
  'inspect', 'move_rotate', 'extrude', 'twist', 'bend',
])

export const VR_TOOL_ACTIONS = Object.freeze([
  'activate', 'preview', 'confirm', 'cancel', 'undo',
])

const MODES = new Set(VR_TOOL_MODES)
const ACTIONS = new Set(VR_TOOL_ACTIONS)

export const VR_TOOL_CAPABILITIES = Object.freeze({
  viewOnly: 'view_only',
  directPreview: 'direct_preview',
  configurationRequired: 'configuration_required',
  unsupported: 'unsupported',
})

const DIRECT_MOVE_ROTATE_KINDS = new Set([
  'cluster', 'base', 'end', 'domain', 'strand',
])
const CONFIGURATION_KINDS = Object.freeze({
  extrude: new Set(['end']),
  twist: new Set(['cluster', 'end']),
  bend: new Set(['cluster', 'end']),
})

/** Honest selection × tool capability. A semantically valid target is not called
 * previewable until every required parameter and visual adapter exists. */
export function vrToolSelectionCapability(mode, selectedRef) {
  if (mode === 'inspect') return VR_TOOL_CAPABILITIES.viewOnly
  if (!selectedRef) return VR_TOOL_CAPABILITIES.unsupported
  if (mode === 'move_rotate' && DIRECT_MOVE_ROTATE_KINDS.has(selectedRef.kind)) {
    return VR_TOOL_CAPABILITIES.directPreview
  }
  if (CONFIGURATION_KINDS[mode]?.has(selectedRef.kind)) {
    return VR_TOOL_CAPABILITIES.configurationRequired
  }
  return VR_TOOL_CAPABILITIES.unsupported
}

/** Backward-compatible semantic eligibility check. Configuration-required targets
 * are valid targets even though Preview must remain disabled. */
export function vrToolSupportsSelection(mode, selectedRef) {
  return vrToolSelectionCapability(mode, selectedRef) !== VR_TOOL_CAPABILITIES.unsupported
}

export const initialVRToolShellState = Object.freeze({
  mode: 'inspect',
  stage: 'inspect',
  sequence: 0,
  targetKey: null,
})

/** Collision-safe identity for one validated action-time native target snapshot. */
export function vrToolTargetKey(target) {
  if (!target || typeof target.identity !== 'string' || !target.identity ||
      typeof target.selectionKind !== 'string' || !target.selectionKind ||
      !Array.isArray(target.ownerTokens) || !target.ownerTokens.length ||
      !target.ownerTokens.every(token => typeof token === 'string' && token)) return null
  return JSON.stringify([
    target.selectionKind,
    target.identity,
    target.ownerTokens,
  ])
}

/** Reduce one validated native intent into UI state plus an unexecuted effect. */
export function reduceVRToolShell(state = initialVRToolShellState, intent = {}, {
  toolTarget = null,
  targetSnapshotPresent = false,
  executorAttached = false,
  undoAvailable = false,
} = {}) {
  const sequence = Number(intent.sequence)
  const mode = intent.mode
  const action = intent.action
  if (!Number.isSafeInteger(sequence) || sequence <= state.sequence ||
      !MODES.has(mode) || !ACTIONS.has(action)) {
    return { state, effect: null, accepted: false, reason: 'invalid_or_stale' }
  }

  const selectedRef = toolTarget?.selectedRef ?? null
  const targetKey = vrToolTargetKey(toolTarget)
  const base = { mode, sequence, targetKey: null }
  const capability = vrToolSelectionCapability(mode, selectedRef)
  const selectionSupported = capability !== VR_TOOL_CAPABILITIES.unsupported
  const directPreview = capability === VR_TOOL_CAPABILITIES.directPreview
  if (action === 'activate') {
    const stage = mode === 'inspect'
      ? 'inspect'
      : targetSnapshotPresent && !toolTarget ? 'stale_target'
      : !selectedRef ? 'waiting_selection'
        : !selectionSupported ? 'unsupported_selection'
          : directPreview ? 'armed' : 'configuration_required'
    return {
      state: { ...base, stage }, effect: null,
      accepted: mode === 'inspect' || (!!toolTarget && directPreview),
      reason: stage,
    }
  }
  if (mode === 'inspect') {
    return {
      state: { ...base, stage: 'inspect' }, effect: null,
      accepted: false, reason: 'choose_tool',
    }
  }
  if (action === 'cancel') {
    const stage = !selectedRef
      ? 'waiting_selection'
      : !selectionSupported ? 'unsupported_selection'
        : directPreview ? 'armed' : 'configuration_required'
    return {
      state: { ...base, stage },
      effect: { type: 'cancel_requested', tool: mode },
      accepted: true, reason: stage,
    }
  }
  if (action === 'undo') {
    return {
      state: { ...base, stage: state.stage, targetKey: state.targetKey ?? null },
      effect: { type: 'undo_requested', tool: mode },
      accepted: undoAvailable, reason: undoAvailable ? 'undo_requested' : 'no_vr_commit',
    }
  }
  if (targetSnapshotPresent && !toolTarget) {
    return {
      state: { ...base, stage: 'stale_target' }, effect: null,
      accepted: false, reason: 'stale_target',
    }
  }
  if (!selectedRef) {
    return {
      state: { ...base, stage: 'waiting_selection' }, effect: null,
      accepted: false, reason: 'selection_required',
    }
  }
  if (!selectionSupported) {
    return {
      state: { ...base, stage: 'unsupported_selection' }, effect: null,
      accepted: false, reason: 'unsupported_selection',
    }
  }
  if (!directPreview) {
    return {
      state: { ...base, stage: 'configuration_required' }, effect: null,
      accepted: false, reason: 'configuration_required',
    }
  }
  if (action === 'preview') {
    return {
      state: { ...base, stage: 'preview', targetKey },
      effect: { type: 'preview_requested', tool: mode, selectedRef, toolTarget },
      accepted: true, reason: 'preview_requested',
    }
  }
  const confirmableStage = state.stage === 'preview' || state.stage === 'confirm_pending'
  if (action === 'confirm' && state.mode === mode && confirmableStage &&
      targetKey != null && state.targetKey === targetKey) {
    return {
      state: { ...base, stage: 'confirm_pending', targetKey },
      effect: { type: 'commit_requested', tool: mode, selectedRef, toolTarget },
      accepted: executorAttached,
      reason: executorAttached ? 'commit_requested' : 'executor_not_attached',
    }
  }
  if (action === 'confirm' && state.mode === mode && confirmableStage &&
      state.targetKey !== targetKey) {
    return {
      state: { ...base, stage: 'armed' }, effect: null,
      accepted: false, reason: 'target_changed_preview_required',
    }
  }
  return {
    state: { ...base, stage: 'armed' }, effect: null,
    accepted: false, reason: 'preview_required',
  }
}
