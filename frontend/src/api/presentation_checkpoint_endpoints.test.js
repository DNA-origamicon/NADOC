import { expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createPresentationCheckpointAPI } from './presentation_checkpoint_endpoints.js'
import { createDesignRevisionTracker } from './design_revisions.js'

it('updates only history, preserving geometry and annotations edited during the request', async () => {
  const geometry = [{ x: 1 }]
  const store = createMockStore({ currentDesign: { id: 'd', annotations: [] }, currentGeometry: geometry })
  const entry = { op_kind: 'annotations-state' }
  const request = vi.fn(async () => {
    store.setState({ currentDesign: { ...store.getState().currentDesign, annotations: [{ text: 'New draft' }] } })
    return { document_id: 'd', revision: 3, feature_log: [entry] }
  })
  const persistDesign = vi.fn()
  const save = createPresentationCheckpointAPI({ store, request, designRevisions: createDesignRevisionTracker(), persistDesign })
  await save('annotations-state')
  expect(store.getState().currentGeometry).toBe(geometry)
  expect(store.getState().currentDesign).toMatchObject({ annotations: [{ text: 'New draft' }], feature_log: [entry] })
  expect(persistDesign).toHaveBeenCalledOnce()
})

it('never merges a late response into a different document', async () => {
  const store = createMockStore({ currentDesign: { id: 'd' } })
  const persistDesign = vi.fn()
  const request = vi.fn(async () => {
    store.setState({ currentDesign: { id: 'other' } })
    return { document_id: 'd', revision: 1, feature_log: [] }
  })
  await createPresentationCheckpointAPI({ store, request, designRevisions: createDesignRevisionTracker(), persistDesign })('view-volumes-state')
  expect(store.getState().currentDesign).toEqual({ id: 'other' })
  expect(persistDesign).not.toHaveBeenCalled()
})
