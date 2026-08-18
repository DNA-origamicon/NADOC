import { describe, expect, it } from 'vitest'
import {
  initialVRToolShellState, reduceVRToolShell, VR_TOOL_ACTIONS, VR_TOOL_MODES,
} from './vr_tool_shell.js'

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
    result = reduceVRToolShell(result.state, {
      sequence: 2, mode: 'twist', action: 'confirm',
    }, { selectedRef })
    expect(result.reason).toBe('preview_required')
    expect(result.effect).toBeNull()

    result = reduceVRToolShell(result.state, {
      sequence: 3, mode: 'twist', action: 'preview',
    }, { selectedRef })
    expect(result.state.stage).toBe('preview')
    expect(result.effect).toEqual({
      type: 'preview_requested', tool: 'twist', selectedRef,
    })

    result = reduceVRToolShell(result.state, {
      sequence: 4, mode: 'twist', action: 'confirm',
    }, { selectedRef })
    expect(result.state.stage).toBe('confirm_pending')
    expect(result.accepted).toBe(false)
    expect(result.reason).toBe('executor_not_attached')
    expect(result.effect?.type).toBe('commit_requested')
  })

  it('makes cancel reversible and undo explicitly inert before a VR commit exists', () => {
    const selectedRef = { kind: 'cluster', id: 'c1' }
    const active = reduceVRToolShell(initialVRToolShellState, {
      sequence: 1, mode: 'move_rotate', action: 'activate',
    }, { selectedRef }).state
    const preview = reduceVRToolShell(active, {
      sequence: 2, mode: 'move_rotate', action: 'preview',
    }, { selectedRef }).state
    const cancelled = reduceVRToolShell(preview, {
      sequence: 3, mode: 'move_rotate', action: 'cancel',
    }, { selectedRef })
    expect(cancelled.state.stage).toBe('armed')
    expect(cancelled.effect).toEqual({
      type: 'cancel_requested', tool: 'move_rotate',
    })

    const undo = reduceVRToolShell(cancelled.state, {
      sequence: 4, mode: 'move_rotate', action: 'undo',
    }, { selectedRef })
    expect(undo.accepted).toBe(false)
    expect(undo.reason).toBe('no_vr_commit')
    expect(undo.effect?.type).toBe('undo_requested')
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
