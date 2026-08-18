import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  initialVRToolShellState, reduceVRToolShell, vrToolSupportsSelection,
  vrToolSelectionCapability, VR_TOOL_ACTIONS, VR_TOOL_CAPABILITIES, VR_TOOL_MODES,
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
      sequence: 1, mode: 'move_rotate', action: 'activate',
    })
    expect(result.state.stage).toBe('waiting_selection')
    expect(result.effect).toBeNull()

    const selectedRef = { kind: 'domain', strandId: 's1', domainIndex: 2 }
    const toolTarget = targetFor(selectedRef)
    result = reduceVRToolShell(result.state, {
      sequence: 2, mode: 'move_rotate', action: 'confirm',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(result.reason).toBe('preview_required')
    expect(result.effect).toBeNull()

    result = reduceVRToolShell(result.state, {
      sequence: 3, mode: 'move_rotate', action: 'preview',
    }, { toolTarget, targetSnapshotPresent: true })
    expect(result.state.stage).toBe('preview')
    expect(result.effect).toEqual({
      type: 'preview_requested', tool: 'move_rotate', selectedRef, toolTarget,
    })

    result = reduceVRToolShell(result.state, {
      sequence: 4, mode: 'move_rotate', action: 'confirm',
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

  it('distinguishes direct previews, configuration targets, and unsupported scopes', () => {
    const capability = (mode, kind) => vrToolSelectionCapability(mode, { kind })
    const direct = VR_TOOL_CAPABILITIES.directPreview
    const configure = VR_TOOL_CAPABILITIES.configurationRequired
    const unsupported = VR_TOOL_CAPABILITIES.unsupported

    for (const kind of ['cluster', 'base', 'end', 'domain', 'strand']) {
      expect(capability('move_rotate', kind)).toBe(direct)
    }
    expect(capability('extrude', 'end')).toBe(configure)
    expect(capability('twist', 'cluster')).toBe(configure)
    expect(capability('twist', 'end')).toBe(configure)
    expect(capability('bend', 'cluster')).toBe(configure)
    expect(capability('bend', 'end')).toBe(configure)
    for (const mode of ['extrude', 'twist', 'bend']) {
      for (const kind of ['base', 'domain', 'strand', 'bond', 'crossover']) {
        expect(capability(mode, kind)).toBe(unsupported)
      }
    }
  })

  it('matches the native viewer canonical capability definition', () => {
    const definition = readFileSync(resolve(
      process.cwd(), '../native/vr_viewer/tool_capabilities.def',
    ), 'utf8')
    const rows = [...definition.matchAll(
      /NADOC_VR_TOOL_CAPABILITY\((\w+),\s*(\w+),\s*(\w+)\)/g,
    )].map(([, mode, kind, capability]) => ({ mode, kind, capability }))
    expect(rows).toHaveLength(10)
    expect(new Set(rows.map(row => `${row.mode}:${row.kind}`)).size).toBe(rows.length)
    for (const row of rows) {
      expect(vrToolSelectionCapability(row.mode, { kind: row.kind }))
        .toBe(row.capability)
    }
    for (const mode of ['move_rotate', 'extrude', 'twist', 'bend']) {
      for (const kind of ['cluster', 'strand', 'domain', 'end', 'base', 'bond', 'crossover']) {
        if (rows.some(row => row.mode === mode && row.kind === kind)) continue
        expect(vrToolSelectionCapability(mode, { kind }))
          .toBe(VR_TOOL_CAPABILITIES.unsupported)
      }
    }
  })

  it('does not claim a visual preview before required tool parameters exist', () => {
    for (const [mode, selectedRef] of [
      ['extrude', { kind: 'end', key: 'h:0:FORWARD' }],
      ['twist', { kind: 'cluster', id: 'c1' }],
      ['bend', { kind: 'end', key: 'h:9:FORWARD' }],
    ]) {
      const toolTarget = targetFor(selectedRef)
      const result = reduceVRToolShell(initialVRToolShellState, {
        sequence: 1, mode, action: 'preview',
      }, { toolTarget, targetSnapshotPresent: true })
      expect(result.state.stage).toBe('configuration_required')
      expect(result.reason).toBe('configuration_required')
      expect(result.effect).toBeNull()
      expect(result.accepted).toBe(false)
    }
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
