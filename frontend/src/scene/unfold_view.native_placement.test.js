import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import positions from './fixtures/native_animation_positions.json'
import { initUnfoldView } from './unfold_view.js'
import { nativeMapPosition, validateNativePoseMap } from '../viewer/native_placement.js'
import { store } from '../state/store.js'

vi.mock('./glow_layer.js', () => ({ createGlowLayer: () => ({ dispose() {}, refresh() {} }) }))

vi.mock('../state/store.js', () => ({ store: { getState: vi.fn(), setState: vi.fn(), subscribe: vi.fn() } }))

it('[native-placement] unfold preserves complete forward/reverse poses and inserted copies across history refresh', () => {
  let state = { straightGeometry: structuredClone(positions), currentDesign: null, unfoldSpacing: 3 }
  state.straightGeometry.push({ ...structuredClone(positions[0]), copy_k: 1,
    backbone_position: [4, 5, 6], slab_position: [7, 8, 9] })
  store.getState.mockImplementation(() => state)
  const view = initUnfoldView(new THREE.Scene(), { flushExtraBaseMeshes() {} })
  try {
    for (const shift of [0, 10, -10]) {
      const prev = state
      state = { ...state, straightGeometry: state.straightGeometry.map(n => ({ ...n,
        backbone_position: n.backbone_position.map(v => v + shift),
        slab_position: n.slab_position.map(v => v + shift) })) }
      for (const [callback] of store.subscribe.mock.calls) callback(state, prev)
      const map = view.getStraightPosMap()
      expect(() => validateNativePoseMap(map)).not.toThrow()
      for (const nuc of state.straightGeometry) {
        const point = nativeMapPosition(map, nuc, nuc.copy_k ?? 0)
        expect(point.toArray()).toEqual(nuc.backbone_position)
        expect(point.nativePlacement).toEqual(nuc)
        expect(point.nativePlacement.slab_position).not.toBe(nuc.slab_position)
      }
      expect(map.get(`${positions[0].helix_id}:${positions[0].bp_index}:${positions[0].direction}`).nativeCopies).toHaveLength(2)
    }
  } finally { view.dispose() }
})
