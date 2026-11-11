import { expect, it, vi } from 'vitest'
import { createKeyframeDeletionAPI } from './keyframe_deletion_endpoints.js'
import { createDesignRevisionTracker } from './design_revisions.js'

it.each([false, true])('merges deletion metadata without replacing geometry (assembly=%s)', async assembly => {
  const host = assembly ? 'assembly' : 'design', key = assembly ? 'currentAssembly' : 'currentDesign'
  const geometry = [{ id: 'displayed-simulation' }], instances = [{ id: 'instance' }]
  let state = { [key]: { id: 'd', helices: geometry, instances, animations: [{ id: 'a' }] } }
  const store = { getState: () => state, setState: patch => { state = { ...state, ...patch } } }
  const request = vi.fn(async () => ({ [host]: { id: 'd', animations: [] }, revision: 5 }))
  const tracker = createDesignRevisionTracker(), persist = vi.fn(), signal = vi.fn()
  const remove = createKeyframeDeletionAPI({ store, request, designRevisions: tracker, assemblyRevisions: tracker,
    persistDesign: persist, persistAssembly: persist, signalDesignChanged: signal })
  await remove(assembly, 'a', 'k')
  expect(state[key].animations).toEqual([])
  expect(state[key].helices).toBe(geometry)
  expect(state[key].instances).toBe(instances)
  expect(request).toHaveBeenCalledWith('DELETE', `/${host}/animations/a/keyframes/k?metadata_only=true`, undefined,
    { suppressBusy: true, skipSimulationPrepare: true })
  // An older full response must not resurrect a removed keyframe.
  const older = { revision: 4, design: { id: 'd', animations: [{ id: 'a', keyframes: [{ id: 'k' }] }] } }
  expect(tracker.acceptDesign(older)).toBe(true)
  expect(older.design.animations).toEqual([])
  expect(persist).toHaveBeenCalledOnce()
})
it.each([false, true])('ignores a late response after document replacement (assembly=%s)', async assembly => {
  const host = assembly ? 'assembly' : 'design', key = assembly ? 'currentAssembly' : 'currentDesign'
  let current = { id: 'old', animations: [] }
  const store = { getState: () => ({ [key]: current }), setState: vi.fn() }
  const request = async () => { current = { id: 'new', animations: ['new'] }; return { [host]: { id: 'old', animations: [] } } }
  const remove = createKeyframeDeletionAPI({ store, request })
  await remove(assembly, 'a', 'k')
  expect(store.setState).not.toHaveBeenCalled()
})
