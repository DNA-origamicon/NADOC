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
})

/** Reduce one validated native intent into UI state plus an unexecuted effect. */
export function reduceVRToolShell(state = initialVRToolShellState, intent = {}, {
  selectedRef = null,
} = {}) {
  const sequence = Number(intent.sequence)
  const mode = intent.mode
  const action = intent.action
  if (!Number.isSafeInteger(sequence) || sequence <= state.sequence ||
      !MODES.has(mode) || !ACTIONS.has(action)) {
    return { state, effect: null, accepted: false, reason: 'invalid_or_stale' }
  }

  const base = { mode, sequence }
  const selectionSupported = vrToolSupportsSelection(mode, selectedRef)
  if (action === 'activate') {
    const stage = mode === 'inspect'
      ? 'inspect'
      : !selectedRef ? 'waiting_selection'
        : selectionSupported ? 'armed' : 'unsupported_selection'
    return {
      state: { ...base, stage }, effect: null,
      accepted: mode === 'inspect' || selectionSupported,
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
      state: { ...base, stage: state.stage },
      effect: { type: 'undo_requested', tool: mode },
      accepted: false, reason: 'no_vr_commit',
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
      state: { ...base, stage: 'preview' },
      effect: { type: 'preview_requested', tool: mode, selectedRef },
      accepted: true, reason: 'preview_requested',
    }
  }
  if (action === 'confirm' && state.mode === mode && state.stage === 'preview') {
    return {
      state: { ...base, stage: 'confirm_pending' },
      effect: { type: 'commit_requested', tool: mode, selectedRef },
      accepted: false, reason: 'executor_not_attached',
    }
  }
  return {
    state: { ...base, stage: 'armed' }, effect: null,
    accepted: false, reason: 'preview_required',
  }
}
