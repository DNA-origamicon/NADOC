// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { initTorqueDriveGlow, resolveTorqueDriveEntries } from './torque_drive_glow.js'

const entries = [0, 1, 2].map(bp => ({ pos: { x: bp, y: 0, z: 0 },
  nuc: { helix_id: 'h', bp_index: bp, direction: 'FORWARD', strand_id: 's' },
}))
const base = bp => ({ kind: 'base', helixId: 'h', bp, direction: 'FORWARD' })
const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }))

it('resolves explicit scopes and the implicit unanchored set with the anchor resolver', () => {
  expect(resolveTorqueDriveEntries([base(1)], entries, {})).toEqual([entries[1]])
  expect(resolveTorqueDriveEntries([], entries, {}, [base(0)], true)).toEqual(entries.slice(1))
  expect(resolveTorqueDriveEntries([], entries, {}, [base(0)], false)).toEqual([])
})

it('keeps driven and anchor layers independent through focus, geometry and engine changes', () => {
  let subscriber
  const designRenderer = { getBackboneEntries: () => entries,
    setTorqueDriveGlow: vi.fn(), clearTorqueDriveGlow: vi.fn(), setAnchorGlow: vi.fn() }
  const store = { getState: () => ({ currentDesign: {}, currentGeometry: [] }), subscribe: fn => { subscriber = fn } }
  initTorqueDriveGlow({ designRenderer, store })
  emit('nadoc:anchors-change', { engine: 'oxdna', anchors: [base(0)], highlighted: [] })
  emit('nadoc:torque-display', { enabled: true })
  expect(designRenderer.setTorqueDriveGlow).toHaveBeenLastCalledWith(entries.slice(1))
  emit('nadoc:anchors-change', { engine: 'oxdna-drive', anchors: [base(1), base(2)], highlighted: [base(2)], glow: true })
  expect(designRenderer.setTorqueDriveGlow).toHaveBeenLastCalledWith([entries[2]])
  subscriber()
  emit('nadoc:display-rebuilt', {})
  expect(designRenderer.setTorqueDriveGlow).toHaveBeenLastCalledWith([entries[2]])
  emit('nadoc:simulation-engine', { engine: 'namd' })
  expect(designRenderer.clearTorqueDriveGlow).toHaveBeenCalled()
  emit('nadoc:simulation-engine', { engine: 'oxdna' })
  expect(designRenderer.setTorqueDriveGlow).toHaveBeenLastCalledWith([entries[2]])
  emit('nadoc:anchors-change', { engine: 'oxdna-drive', anchors: [base(1)], highlighted: [], glow: false })
  expect(designRenderer.clearTorqueDriveGlow).toHaveBeenCalled()
  expect(designRenderer.setAnchorGlow).not.toHaveBeenCalled()
})
