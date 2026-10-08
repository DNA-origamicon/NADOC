import { it, expect, vi } from 'vitest'
import { createFeatureAtomisticDisplay } from './feature_atomistic_display.js'
it('changes atom topology without interpolating unrelated serial identities', () => {
  const renderer = { update: vi.fn(), applyPositionLerp: vi.fn() }
  const display = createFeatureAtomisticDisplay(() => renderer)
  const from = { atoms: [{ serial: 0, name: 'P', strand_id: 'old' }], bonds: [], positions: [1, 2, 3] }
  const to = { atoms: [{ serial: 0, name: 'P', strand_id: 'new' }], bonds: [], positions: [9, 8, 7] }
  display.show(from, to, 0.25, [], null)
  expect(renderer.update).toHaveBeenLastCalledWith(from)
  expect(renderer.applyPositionLerp).toHaveBeenLastCalledWith(from.positions, from.positions, 0)
  display.show(from, to, 1, [], null)
  expect(renderer.update).toHaveBeenLastCalledWith(to)
  expect(renderer.applyPositionLerp).toHaveBeenLastCalledWith(to.positions, to.positions, 0)
})
it('lerps matching atom identities without rebuilding every frame', () => {
  const renderer = { update: vi.fn(), applyPositionLerp: vi.fn() }
  const display = createFeatureAtomisticDisplay(() => renderer)
  const from = { atoms: [{ serial: 0, name: 'P' }], bonds: [], positions: [1, 2, 3] }
  const to = { ...from, positions: [9, 8, 7] }
  display.show(from, to, 0.25, [], null); display.show(from, to, 0.75, [], null)
  expect(renderer.update).toHaveBeenCalledOnce()
  expect(renderer.applyPositionLerp).toHaveBeenLastCalledWith(from.positions, to.positions, 0.75, from.positions, [], null)
  display.clear(); display.show(to, to, 0, [], null)
  expect(renderer.update).toHaveBeenCalledTimes(2)
})
it('keeps the full sweep atom model available for an origin-first reveal before the midpoint', () => {
  const renderer = { update: vi.fn(), applyPositionLerp: vi.fn() }
  const display = createFeatureAtomisticDisplay(() => renderer)
  const from = { atoms: [], bonds: [], positions: [] }
  const to = { atoms: [{ serial: 0, helix_id: 'h', bp_index: 0 }], bonds: [], positions: [1, 2, 3] }
  const reveal = { scale: vi.fn() }
  display.show(from, to, .1, [], null, reveal)
  expect(renderer.update).toHaveBeenLastCalledWith(to)
  expect(renderer.applyPositionLerp).toHaveBeenLastCalledWith(to.positions, to.positions, 0, null, [], null, reveal.scale)
})
