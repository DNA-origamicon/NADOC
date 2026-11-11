import { expect, it, vi } from 'vitest'
import { createKeyframeActionsAPI } from './keyframe_actions.js'
import { createDesignRevisionTracker } from './design_revisions.js'

it.each([false, true])('applies captured metadata without replacing geometry (assembly=%s)', async assembly => {
  const key = assembly ? 'currentAssembly' : 'currentDesign', host = assembly ? 'assembly' : 'design'
  const geometry = [{ id: 'live' }]
  let state = { [key]: { id: 'd', helices: geometry }, currentGeometry: geometry }
  const metadata = { id: 'd', animations: [{ id: 'a' }], camera_poses: [{ id: 'pose' }] }
  if (assembly) metadata.configurations = [{ id: 'config' }]
  const request = vi.fn(async () => ({ [host]: metadata, revision: 2 })), persist = vi.fn()
  const tracker = createDesignRevisionTracker()
  const action = createKeyframeActionsAPI({ store: { getState: () => state, setState: patch => { state = { ...state, ...patch } } }, request,
    designRevisions: tracker, assemblyRevisions: tracker, persistDesign: persist, persistAssembly: persist, signalDesignChanged: vi.fn() })
  await action(assembly, 'capture', 'a', 'k', { pose: {} })
  expect(state.currentGeometry).toBe(geometry); expect(state[key].helices).toBe(geometry)
  expect(state[key].camera_poses).toEqual(metadata.camera_poses)
  expect(request.mock.calls[0][1]).toBe(`/${host}/animations/a/keyframes/k/capture`)
  expect(persist).toHaveBeenCalledOnce()
})
