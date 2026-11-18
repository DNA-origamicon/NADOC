import { expect, it, vi } from 'vitest'
import { refreshPublishedDisplay } from './display_recovery.js'
import { createMockStore } from '../test-helpers/mock_store.js'

it('identifies stale cached coordinates and rebuilds without changing authored data', async () => {
  const design = { id: 'part', feature_log: [{ id: 'recorded' }] }
  const n = { helix_id: 'h', bp_index: 1, direction: 1, backbone_position: [8, 0, 0] }
  const store = createMockStore({ currentDesign: design, currentGeometry: [n], translateRotateActive: true })
  const api = { cancelHistoryPreview: vi.fn(async () => store.setState({ translateRotateActive: false })),
    getGeometry: vi.fn(async () => { store.setState({ currentGeometry: [{ ...n, backbone_position: [0, 0, 0] }] }); return {} }) }
  expect(await refreshPublishedDisplay({ store, api })).toEqual({ previewCancelled: true, correctedNucleotides: 1 })
  expect(store.getState().currentDesign).toBe(design)
  expect(n.backbone_position).toEqual([8, 0, 0])
})

it('stops when preview cancellation changes the document and does not claim failed refresh succeeded', async () => {
  const store = createMockStore({ currentDesign: { id: 'part' } })
  const api = { cancelHistoryPreview: vi.fn(async () => store.setState({ currentDesign: { id: 'other' } })), getGeometry: vi.fn() }
  await expect(refreshPublishedDisplay({ store, api })).rejects.toThrow('Document changed')
  expect(api.getGeometry).not.toHaveBeenCalled()
  api.cancelHistoryPreview.mockResolvedValue(undefined)
  api.getGeometry.mockResolvedValue(null)
  await expect(refreshPublishedDisplay({ store, api })).rejects.toThrow('Could not refresh')
})
