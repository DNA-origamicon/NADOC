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

/** Tool-specific canonical selection policy. Move/Rotate is intentionally strict:
 * desktop owns transforms at Cluster granularity and VR must not silently widen a
 * Base, End, Bond, Domain, or Strand selection into a whole cluster. */
export function vrToolSupportsSelection(mode, selectedRef) {
  if (mode === 'inspect') return true
  if (!selectedRef) return false
  if (mode === 'move_rotate') return selectedRef.kind === 'cluster'
  return true
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
  const selectionSupported = vrToolSupportsSelection(mode, selectedRef)
  if (action === 'activate') {
    const stage = mode === 'inspect'
      ? 'inspect'
      : targetSnapshotPresent && !toolTarget ? 'stale_target'
      : !selectedRef ? 'waiting_selection'
        : selectionSupported ? 'armed' : 'unsupported_selection'
    return {
      state: { ...base, stage }, effect: null,
      accepted: mode === 'inspect' || (!!toolTarget && selectionSupported),
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
      : selectionSupported ? 'armed' : 'unsupported_selection'
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
      accepted: false, reason: 'no_vr_commit',
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
  if (action === 'preview') {
    return {
      state: { ...base, stage: 'preview', targetKey },
      effect: { type: 'preview_requested', tool: mode, selectedRef, toolTarget },
      accepted: true, reason: 'preview_requested',
    }
  }
  if (action === 'confirm' && state.mode === mode && state.stage === 'preview' &&
      targetKey != null && state.targetKey === targetKey) {
    return {
      state: { ...base, stage: 'confirm_pending', targetKey },
      effect: { type: 'commit_requested', tool: mode, selectedRef, toolTarget },
      accepted: false, reason: 'executor_not_attached',
    }
  }
  if (action === 'confirm' && state.mode === mode && state.stage === 'preview' &&
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
