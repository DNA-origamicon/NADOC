import { it, expect, vi } from 'vitest'
import { createSimulationSurface } from './simulation_surface.js'
it('moves every surface vertex with simulation coordinates and restores the original surface', () => {
  const mesh = { vertices: [0,1,0, 0,0,1, 1,0,0], faces: [0,1,2] }
  const geometry = [{ helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0,0,0], base_normal: [1,0,0], axis_tangent: [0,0,1] }]
  const renderer = { applyDeformedFrame: vi.fn(), applyNucleotideScalarColors: vi.fn() }, visible = vi.fn()
  const view = createSimulationSurface({ renderer, getSurfaceData: () => mesh, getGeometry: () => geometry, setCGVisible: visible })
  const original = JSON.stringify([mesh, geometry])
  view.apply([{ ...geometry[0], backbone_position: [10,20,30] }], new Map())
  expect([...renderer.applyDeformedFrame.mock.calls[0][1]]).toEqual([10,21,30, 10,20,31, 11,20,30])
  expect(visible).toHaveBeenCalledWith(false)
  expect(JSON.stringify([mesh, geometry])).toBe(original)
  view.clear()
  expect(renderer.applyDeformedFrame).toHaveBeenLastCalledWith(mesh, mesh.vertices)
})
