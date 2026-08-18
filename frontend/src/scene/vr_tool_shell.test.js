import { describe, expect, it } from 'vitest'
import {
  initialVRToolShellState, reduceVRToolShell, vrToolSupportsSelection,
  VR_TOOL_ACTIONS, VR_TOOL_MODES,
} from './vr_tool_shell.js'

const targetFor = (selectedRef, identity = 'primitive:1') => ({
  identity,
  selectionKind: selectedRef.kind,
  ownerTokens: [`owner:${selectedRef.kind}`],
  selectedRef,
  primitiveKind: 'nucleotide',
})

describe('native VR transactional tool shell', () => {
  it('exposes the requested tool and action vocabulary', () => {
    expect(VR_TOOL_MODES).toEqual([
      'inspect', 'move_rotate', 'extrude', 'twist', 'bend',
    ])
    expect(VR_TOOL_ACTIONS).toEqual([
      'activate', 'preview', 'confirm', 'cancel', 'undo',
    ])
  })

  it('requires canonical selection before preview and preview before confirm', () => {
    let result = reduceVRToolShell(initialVRToolShellState, {
      sequence: 1, mode: 'twist', action: 'activate',
    })
    expect(result.state.stage).toBe('waiting_selection')
    expect(result.effect).toBeNull()

    const selectedRef = { kind: 'domain', strandId: 's1', domainIndex: 2 }
    const toolTarget = targetFor(selectedRef)
    result = reduceVRToolShell(result.state, {
      sequence: 2, mode: 'twist', action: 'confirm',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(result.reason).toBe('preview_required')
    expect(result.effect).toBeNull()

    result = reduceVRToolShell(result.state, {
      sequence: 3, mode: 'twist', action: 'preview',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(result.state.stage).toBe('preview')
    expect(result.effect).toEqual({
      type: 'preview_requested', tool: 'twist', selectedRef, toolTarget,
    })

    result = reduceVRToolShell(result.state, {
      sequence: 4, mode: 'twist', action: 'confirm',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(result.state.stage).toBe('confirm_pending')
    expect(result.accepted).toBe(false)
    expect(result.reason).toBe('executor_not_attached')
    expect(result.effect?.type).toBe('commit_requested')
  })

  it('makes cancel reversible and undo explicitly inert before a VR commit exists', () => {
    const selectedRef = { kind: 'cluster', id: 'c1' }
    const toolTarget = targetFor(selectedRef)
    const active = reduceVRToolShell(initialVRToolShellState, {
      sequence: 1, mode: 'move_rotate', action: 'activate',
    }, { toolTarget, targetSnapshotPresent: true }).state
    const preview = reduceVRToolShell(active, {
      sequence: 2, mode: 'move_rotate', action: 'preview',
    }, { toolTarget, targetSnapshotPresent: true }).state
    const cancelled = reduceVRToolShell(preview, {
      sequence: 3, mode: 'move_rotate', action: 'cancel',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(cancelled.state.stage).toBe('armed')
    expect(cancelled.effect).toEqual({
      type: 'cancel_requested', tool: 'move_rotate',
    })

    const undo = reduceVRToolShell(cancelled.state, {
      sequence: 4, mode: 'move_rotate', action: 'undo',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(undo.accepted).toBe(false)
    expect(undo.reason).toBe('no_vr_commit')
    expect(undo.effect?.type).toBe('undo_requested')
  })

  it('accepts exact v12 scopes and never widens unsupported connectivity targets', () => {
    expect(vrToolSupportsSelection('move_rotate', { kind: 'cluster', id: 'c1' })).toBe(true)
    expect(vrToolSupportsSelection('move_rotate', { kind: 'base', key: 'h:1:FORWARD' })).toBe(true)
    expect(vrToolSupportsSelection('move_rotate', {
      kind: 'domain', strandId: 's1', domainIndex: 0,
    })).toBe(true)
    expect(vrToolSupportsSelection('move_rotate', { kind: 'bond' })).toBe(false)
    const result = reduceVRToolShell(initialVRToolShellState, {
      sequence: 1, mode: 'move_rotate', action: 'preview',
    }, {
      toolTarget: targetFor({ kind: 'bond', fromKey: 'a', toKey: 'b' }),
      targetSnapshotPresent: true,
    })
    expect(result.state.stage).toBe('unsupported_selection')
    expect(result.effect).toBeNull()
  })

  it('requires Preview and Confirm to name the identical action-time target', () => {
    const first = targetFor({ kind: 'cluster', id: 'c1' }, 'nuc:first')
    const second = targetFor({ kind: 'cluster', id: 'c2' }, 'nuc:second')
    const preview = reduceVRToolShell(initialVRToolShellState, {
      sequence: 1, mode: 'move_rotate', action: 'preview',
    }, { toolTarget: first, targetSnapshotPresent: true }).state
    const changed = reduceVRToolShell(preview, {
      sequence: 2, mode: 'move_rotate', action: 'confirm',
    }, { toolTarget: second, targetSnapshotPresent: true })
    expect(changed.accepted).toBe(false)
    expect(changed.reason).toBe('target_changed_preview_required')
    expect(changed.effect).toBeNull()
    expect(changed.state.stage).toBe('armed')
  })

  it('rejects a present target snapshot that no longer resolves in the browser', () => {
    const result = reduceVRToolShell(initialVRToolShellState, {
      sequence: 1, mode: 'move_rotate', action: 'preview',
    }, { toolTarget: null, targetSnapshotPresent: true })
    expect(result.accepted).toBe(false)
    expect(result.reason).toBe('stale_target')
    expect(result.effect).toBeNull()
  })

  it('rejects stale or unknown intents without changing state', () => {
    const state = { mode: 'bend', stage: 'armed', sequence: 7 }
    expect(reduceVRToolShell(state, {
      sequence: 7, mode: 'bend', action: 'preview',
    }).state).toBe(state)
    expect(reduceVRToolShell(state, {
      sequence: 8, mode: 'delete', action: 'confirm',
    }).reason).toBe('invalid_or_stale')
  })
})
