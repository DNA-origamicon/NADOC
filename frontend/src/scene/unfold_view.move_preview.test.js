import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initUnfoldView } from './unfold_view.js'
import { store } from '../state/store.js'

vi.mock('./glow_layer.js', () => ({ createGlowLayer: () => ({ dispose() {}, refresh() {} }) }))
vi.mock('../state/store.js', () => ({ store: { getState: vi.fn(), subscribe: vi.fn(() => () => {}) } }))

it.each([0, 0.4, 1].flatMap(fraction => [0, 1].map(movingEnd => [fraction, movingEnd])))
('keeps a moving crossover attached at deform fraction %s, endpoint %s', (fraction, movingEnd) => {
  const a = { helix_id: 'a', bp_index: 0, direction: 'FORWARD' }
  const b = { helix_id: 'b', bp_index: 0, direction: 'FORWARD' }
  const straight = new Map([['a:0:FORWARD', new THREE.Vector3(0, 0, 0)],
    ['b:0:FORWARD', new THREE.Vector3(4, 0, 0)]])
  const live = new Map([[a, new THREE.Vector3(0, fraction * 2, 0)],
    [b, new THREE.Vector3(4, fraction * 2, 0)]])
  const moving = [a, b][movingEnd], fixed = [b, a][movingEnd]
  store.getState.mockReturnValue({ unfoldSpacing: 3, currentDesign: { helices: [], strands: [] } })
  const scene = new THREE.Scene()
  const renderer = { getCrossHelixConnections: () => [{ from: new THREE.Vector3(0, 2, 0),
    to: new THREE.Vector3(4, 2, 0), fromHelixId: 'a', toHelixId: 'b', fromNuc: a, toNuc: b }],
    getHelixCtrl: () => ({ getNucLivePos: n => live.get(n) }), flushExtraBaseMeshes() {} }
  const view = initUnfoldView(scene, renderer)
  try {
    view.refreshExternalGeometry()
    view.applyDeformLerp(straight, fraction)
    const line = scene.getObjectByName('xoverArcMerged_staple')
    const endpoints = () => {
      const p = line.geometry.attributes.position
      return [new THREE.Vector3().fromBufferAttribute(p, 0), new THREE.Vector3().fromBufferAttribute(p, p.count - 1)]
    }
    for (const rotation of [0, Math.PI / 2]) {
      live.get(moving).set(movingEnd * 4, fraction * 2, 0).applyAxisAngle(new THREE.Vector3(0, 0, 1), rotation).add(new THREE.Vector3(2, 3, 1))
      view.applyClusterArcUpdate([moving.helix_id])
      expect(endpoints()[movingEnd].distanceTo(live.get(moving))).toBeLessThan(1e-6)
      expect(endpoints()[1 - movingEnd].distanceTo(live.get(fixed))).toBeLessThan(1e-6)
      view.refreshArcVisibility()
      expect(endpoints()[movingEnd].distanceTo(live.get(moving))).toBeLessThan(1e-6)
    }
    // Cancel/geometry replacement rebuilds the arcs and releases live overrides.
    view.refreshExternalGeometry()
    view.applyDeformLerp(straight, fraction)
    const reset = scene.getObjectByName('xoverArcMerged_staple').geometry.attributes.position
    expect(new THREE.Vector3().fromBufferAttribute(reset, 0).distanceTo(new THREE.Vector3(0, fraction * 2, 0))).toBeLessThan(1e-6)
  } finally { view.dispose() }
})

it('refreshes visible arc endpoints when Domain Designer flushes a deferred undo', () => {
  let state = { unfoldSpacing: 3, currentGeometry: [],
    currentDesign: { helices: [], strands: [], crossovers: [], deformations: [], extensions: [], overhangs: [] },
    domainDesigner: { modalActive: true },
  }
  store.getState.mockImplementation(() => state)
  let endpoint = 4
  const a = { helix_id: 'a', bp_index: 0, direction: 'FORWARD' }
  const b = { helix_id: 'b', bp_index: 0, direction: 'FORWARD' }
  const renderer = { getCrossHelixConnections: () => [{ from: new THREE.Vector3(),
    to: new THREE.Vector3(endpoint, 0, 0), fromHelixId: 'a', toHelixId: 'b', fromNuc: a, toNuc: b }],
    flushExtraBaseMeshes() {},
  }
  const offset = store.subscribe.mock.calls.length
  const scene = new THREE.Scene()
  const view = initUnfoldView(scene, renderer)
  try {
    view.refreshExternalGeometry()
    const previous = state
    state = { ...state, domainDesigner: { modalActive: false } }
    endpoint = 6 // helix renderer has now flushed the queued undo
    store.subscribe.mock.calls[offset][0](state, previous)
    const positions = scene.getObjectByName('xoverArcMerged_staple').geometry.attributes.position
    expect(new THREE.Vector3().fromBufferAttribute(positions, positions.count - 1).x).toBe(6)
  } finally { view.dispose() }
})
