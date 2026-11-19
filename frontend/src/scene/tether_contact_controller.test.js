import { it, expect } from 'vitest'
import { Object3D, Vector3, Quaternion } from 'three'
import { createTetherContactController } from './tether_contact_controller.js'
it('clamps the live pose, supports toggling, and rearms from each transaction', () => {
  const state = { type: 'ssdna', clusterId: 'a', dummy: new Object3D(), startPos: new Vector3(),
    startQuat: new Quaternion(), incrQuat: new Quaternion(), links: [], tethers: [] }
  const design = { cluster_transforms: [{ id: 'a', helix_ids: ['a'] }] }
  const geometry = ['a', 'loose'].flatMap(helix_id => [0, 1].map(bp_index => ({ helix_id, bp_index,
    helical_site: { axis_point: [helix_id === 'a' ? 0 : 5, 0, bp_index] } })))
  const controller = createTetherContactController({ store: { getState: () => ({ currentDesign: design, currentGeometry: geometry }) },
    read: () => state, pending: () => [] })
  controller.arm(); state.dummy.position.x = 10; controller.clamp()
  expect(state.dummy.position.x).toBeCloseTo(3)
  controller.setEnabled(false); state.dummy.position.x = 10; controller.clamp()
  expect(state.dummy.position.x).toBe(10)
  state.dummy.position.x = 0; controller.setEnabled(true); controller.arm()
  state.dummy.position.x = 10; controller.clamp()
  expect(state.dummy.position.x).toBeCloseTo(3)
})
