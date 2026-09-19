import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initAnnotations } from './annotation_subsystem.js'

let container, pane, scene, api, store, sub

const flush = async () => { await new Promise(r => setTimeout(r, 400)); await Promise.resolve() }

beforeEach(() => {
  container = document.createElement('div'); pane = document.createElement('div')
  document.body.append(container, pane)
  scene = new THREE.Scene()
  api = { saveAnnotations: vi.fn(async () => ({})), persistDesign: vi.fn() }
  store = createMockStore({ currentDesign: { id: 'd1', annotations: [], annotations_enabled: true }, assemblyActive: false, selection: { context: 'design', items: [] } })
  sub = initAnnotations({ document, store, api, scene, getCamera: () => new THREE.PerspectiveCamera(), getEntries: () => [], resolveBasePosition: () => null, container, pane })
})
afterEach(() => { sub.dispose(); container.remove(); pane.remove() })

describe('annotation subsystem: annotations are saved with the design', () => {
  it('an edit lands in currentDesign (what autosave watches) and is PUT to the backend', async () => {
    const a = sub.controller.add({ text: 'hello', color: '#ff0000' })
    await flush()
    const design = store.getState().currentDesign
    expect(design.annotations.map(x => x.id)).toEqual([a.id])
    expect(design.annotations[0]).toMatchObject({ text: 'hello', color: '#ff0000', callout_type: 'elbow' })
    expect(api.saveAnnotations).toHaveBeenCalledTimes(1)
    expect(api.saveAnnotations.mock.calls[0][0]).toMatchObject({ enabled: true })
    expect(api.saveAnnotations.mock.calls[0][0].annotations[0].id).toBe(a.id)
    expect(api.persistDesign).toHaveBeenCalled()
  })
  it('the global switch is saved too', async () => {
    sub.controller.setEnabled(false)
    await flush()
    expect(store.getState().currentDesign.annotations_enabled).toBe(false)
    expect(api.saveAnnotations.mock.calls[0][0].enabled).toBe(false)
  })
  it('loading a design with saved annotations shows them; an unrelated design update keeps them', () => {
    const saved = [{ id: 'a', text: 'from file', icon: null, callout_type: 'line', color: '#00ff00', transparency: 0, size: 1, manual: false, screen_pos: null, visible: true, refs: [] }]
    store.setState({ currentDesign: { id: 'd2', annotations: saved, annotations_enabled: true } })
    expect(sub.controller.list()[0]).toMatchObject({ id: 'a', text: 'from file', calloutType: 'line' })
    expect(pane.textContent).toContain('Annotations')
    store.setState({ currentDesign: { ...store.getState().currentDesign, strands: [] } })
    expect(sub.controller.list()).toHaveLength(1)
  })
  it('re-asserts local edits when a stale design response raced the PUT', async () => {
    api.saveAnnotations.mockImplementation(async () => {
      // A response to some other edit lands with the OLD list while our PUT is in flight.
      store.setState({ currentDesign: { id: 'd1', annotations: [], annotations_enabled: true } })
    })
    const a = sub.controller.add({ text: 'keep me' })
    await flush()
    expect(store.getState().currentDesign.annotations.map(x => x.id)).toEqual([a.id])
    expect(sub.controller.list().map(x => x.id)).toEqual([a.id])
  })
  it('does not write into a different design if the part switched before the commit ran', async () => {
    sub.controller.add({ text: 'for d1' })
    store.setState({ currentDesign: { id: 'other', annotations: [], annotations_enabled: true } })
    await flush()
    expect(store.getState().currentDesign.annotations).toEqual([])
    expect(api.saveAnnotations).not.toHaveBeenCalled()
  })
  it('assembly mode hides the overlay and tab and holds no annotations', () => {
    sub.controller.add({ text: 'x' })
    store.setState({ assemblyActive: true })
    expect(container.querySelector('.nadoc-anno-layer').hidden).toBe(true)
    expect(pane.querySelector('.anno-unavailable').hidden).toBe(false)
    expect(sub.controller.list()).toEqual([])
    store.setState({ assemblyActive: false })
    expect(container.querySelector('.nadoc-anno-layer').hidden).toBe(false)
  })
})
