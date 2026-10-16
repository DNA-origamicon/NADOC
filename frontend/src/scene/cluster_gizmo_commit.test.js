import { expect, it, vi } from 'vitest'
import { initClusterGizmo } from './cluster_gizmo.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const client = { patchCluster: vi.fn(), groupOrganizationCommand: vi.fn() }
const pose = { translation: [1, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] }

it('actual gizmo retains a refused transform instead of reporting it committed', async () => {
  client.patchCluster.mockResolvedValue(null)
  const store = createMockStore({ currentDesign: { id: 'd', cluster_transforms: [] } })
  const gizmo = initClusterGizmo(store, { enabled: true }, null, null, null, client)
  gizmo.setPendingTransform('same', pose)
  const result = await gizmo.commitPendingTransforms()
  expect(result.clusterIds).toEqual([])
  expect(result.error).toBeInstanceOf(Error)
  expect(gizmo.getPendingTransform('same')).toEqual(pose)
})

it('actual active gizmo commits through the atomic owned endpoint and keeps newer pending state', async () => {
  client.groupOrganizationCommand.mockResolvedValue({ revision: 2 })
  client.patchCluster.mockClear()
  const store = createMockStore({ currentDesign: { id: 'd', cluster_transforms: [],
    group_organization: { version: 1, groups: [] } } })
  const gizmo = initClusterGizmo(store, { enabled: true }, null, null, null, client)
  gizmo.setPendingTransform('same', pose)
  const result = await gizmo.commitPendingTransforms()
  expect(result.clusterIds).toEqual(['same'])
  expect(result.geometryApplied).toBe(true)
  expect(client.patchCluster).not.toHaveBeenCalled()
  expect(gizmo.getPendingTransform('same')).toBeNull()
})
