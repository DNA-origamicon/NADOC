import { it, expect, vi } from 'vitest'
import { Vector3 } from 'three'
import { initClusterGizmo } from './cluster_gizmo.js'
import { createMockStore } from '../test-helpers/mock_store.js'

function setup(enabled) {
  const cluster = { id: 'a', helix_ids: ['a'], pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
  const currentGeometry = ['a', 'loose'].flatMap(helix_id => [0, 1].map(bp_index => ({ helix_id, bp_index,
    helical_site: { axis_point: [helix_id === 'a' ? 0 : 5, 0, bp_index] } })))
  const store = createMockStore({ currentDesign: { cluster_transforms: [cluster] }, currentGeometry })
  const update = vi.fn(), live = vi.fn()
  const gizmo = initClusterGizmo(store, { enabled: true }, live, null, update)
  gizmo.relaxClusterHeadless('a', { connections: [{ movingKey: 'a', fixedKey: 'b', contour: 20 }],
    resolveWorldPos: () => new Vector3() })
  gizmo.setCollisionDetection(enabled)
  return { gizmo, update, live }
}
it('numeric edits clamp to loose barriers and queue the corrected pose', () => {
  const { gizmo } = setup(true)
  gizmo.setTransform([10, 0, 0], [0, 0, 0, 1])
  expect(gizmo.getGizmoWorldPosition()[0]).toBeCloseTo(3)
  expect(gizmo.getPendingTransform('a').translation[0]).toBeCloseTo(3)
})
it('numeric edits permit crossing barriers when collision detection is off', () => {
  const { gizmo } = setup(false)
  gizmo.setTransform([10, 0, 0], [0, 0, 0, 1])
  expect(gizmo.getPendingTransform('a').translation).toEqual([10, 0, 0])
})
it('numeric edits still project an overstretched tether with collisions off', () => {
  const { gizmo } = setup(false)
  gizmo.setTransform([100, 0, 0], [0, 0, 0, 1])
  // Same finite-iteration projection as pointer dragging, not an unconstrained 100 nm edit.
  expect(gizmo.getPendingTransform('a').translation[0]).toBeLessThan(21)
})
