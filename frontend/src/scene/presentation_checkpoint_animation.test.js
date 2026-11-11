import { describe, expect, it, vi } from 'vitest'
import { createPresentationAnimation, presentationAt } from './presentation_checkpoint_animation.js'

const first = { op_kind: 'annotations-state', params: { annotations: [{ id: 'note', text: 'First' }], annotations_enabled: false } }
const volumes = { op_kind: 'view-volumes-state', params: { view_volumes: [{ id: 'box', opacity: 0.5 }] } }
const last = { op_kind: 'annotations-state', params: { annotations: [], annotations_enabled: true } }
const doc = { id: 'd', feature_log: [first, { op_kind: 'bundle-create' }, volumes, last] }

describe('presentation checkpoint playback', () => {
  it('carries each saved channel independently and ignores live edits', () => {
    expect(presentationAt(doc, -2)).toEqual({ annotations: [], annotations_enabled: true, view_volumes: [] })
    expect(presentationAt(doc, 1)).toEqual({ ...first.params, view_volumes: [] })
    expect(presentationAt(doc, 2)).toEqual({ ...first.params, ...volumes.params })
    expect(presentationAt(doc, -1)).toEqual({ ...last.params, ...volumes.params })
    expect(presentationAt({ feature_log: [] }, -1)).toEqual({})
  })
  it('switches only at the endpoint, supports backwards seeks, and restores on stop', () => {
    const emit = vi.fn()
    const player = createPresentationAnimation({ getDocument: () => doc, emit })
    player.start(); player.show(0, 3, 0.5)
    expect(emit).toHaveBeenLastCalledWith(expect.objectContaining({ documentId: 'd', state: { ...first.params, view_volumes: [] } }))
    player.show(0, 3, 0.9)
    expect(emit).toHaveBeenCalledTimes(1)
    player.show(0, 3, 1)
    expect(emit.mock.lastCall[0].state.annotations).toEqual([])
    player.show(3, 0, 1)
    expect(emit.mock.lastCall[0].state.annotations[0].text).toBe('First')
    player.clear()
    expect(emit).toHaveBeenLastCalledWith(null)
    expect(doc.feature_log).toEqual([first, { op_kind: 'bundle-create' }, volumes, last])
  })
})

it('waits for asynchronous volume display work before exporting the frame', async () => {
  let release
  const work = new Promise(resolve => { release = resolve })
  const player = createPresentationAnimation({ getDocument: () => doc, emit: detail => detail?.waitUntil(work) })
  player.start(); player.show(0, 2, 1)
  let settled = false
  const result = player.settle().then(() => { settled = true })
  await Promise.resolve()
  expect(settled).toBe(false)
  release(true); await result
  expect(settled).toBe(true)
  player.clear()
})

it('keyframe annotation subsets override working visibility without changing the document', () => {
  const source = { id: 'd', annotations_enabled: false, annotations: [
    { id: 'a', name: 'Opening', text: 'A', visible: false }, { id: 'b', text: 'B' },
  ] }
  const original = structuredClone(source), emit = vi.fn()
  const player = createPresentationAnimation({ getDocument: () => source, emit })
  player.start(); player.show(-1, -1, 0, ['a'])
  expect(emit.mock.lastCall[0].state).toMatchObject({ annotations_enabled: true, annotations: [{ id: 'a', visible: true }] })
  player.show(-1, -1, 1, [])
  expect(emit.mock.lastCall[0].state.annotations).toEqual([])
  player.show(-1, -1, 1, null)
  expect(emit.mock.lastCall[0].state.annotations_enabled).toBe(false)
  player.clear(); expect(emit).toHaveBeenLastCalledWith(null)
  expect(source).toEqual(original)
})

it('overrides volume subsets independently and emits changes between zoom-only frames', () => {
  const source = { id: 'd', view_volumes: [{ id: 'v', enabled: false, representation: 'beads' }] }
  const original = structuredClone(source), emit = vi.fn()
  const player = createPresentationAnimation({ getDocument: () => source, emit })
  player.start(); player.show(-1, -1, 1, null, ['v'], ['z'])
  expect(emit.mock.lastCall[0]).toMatchObject({ state: { view_volumes: [{ id: 'v', enabled: true }] }, zoomVolumeIds: ['z'] })
  player.show(-1, -1, 1, null, ['v'], [])
  expect(emit).toHaveBeenCalledTimes(2)
  expect(emit.mock.lastCall[0].zoomVolumeIds).toEqual([])
  player.show(-1, -1, 1, null, [], null)
  expect(emit.mock.lastCall[0].state.view_volumes).toEqual([])
  player.clear(); expect(emit).toHaveBeenLastCalledWith(null)
  expect(source).toEqual(original)
})
