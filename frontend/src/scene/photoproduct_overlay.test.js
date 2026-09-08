import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initPhotoproductOverlay } from './photoproduct_overlay.js'

describe('formed photoproduct overlay', () => {
  it('draws a distinct double rail for canonical endpoints and removes on design update', () => {
    const scene = new THREE.Scene()
    const store = createMockStore({ currentDesign: { photoproduct_junctions: [{
      id: 'cpd1', base_key_1: 'h:1:FORWARD', base_key_2: '__xb__:xo:0',
    }] } })
    const positions = new Map([
      ['h:1:FORWARD', new THREE.Vector3(0, 0, 0)],
      ['__xb__:xo:0', new THREE.Vector3(1, 0, 0)],
    ])
    const overlay = initPhotoproductOverlay({
      scene, THREE, store, getBasePosition: key => positions.get(key) ?? null,
    })
    expect(overlay.root.name).toBe('formedPhotoproductOverlay')
    expect(overlay.root.children).toHaveLength(1)
    expect(overlay.root.children[0].children).toHaveLength(2)
    expect(overlay.root.children[0].userData).toEqual({ kind: 'photoproduct', id: 'cpd1' })
    store._emit({ currentDesign: { photoproduct_junctions: [] } })
    expect(overlay.root.children).toHaveLength(0)
    overlay.dispose()
    expect(scene.getObjectByName('formedPhotoproductOverlay')).toBeUndefined()
  })
})
