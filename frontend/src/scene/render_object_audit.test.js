import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { auditRenderedObjects, compareRenderedObjects } from './render_object_audit.js'

describe('render object audit', () => {
  it('uses effective ancestor visibility and identifies occupancy descendants', () => {
    const scene = new THREE.Scene()
    const native = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial())
    native.name = 'native'
    scene.add(native)
    const ghost = new THREE.Group(); ghost.name = 'occupancyGhost0'
    ghost.add(new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial()))
    scene.add(ghost)
    expect(auditRenderedObjects(scene).visibleOccupancyRenderables).toBe(1)
    ghost.visible = false
    expect(auditRenderedObjects(scene).visibleOccupancyRenderables).toBe(0)
  })

  it('reports renderables introduced during occupancy that survive teardown', () => {
    const snap = ids => ({ objects: ids.map(uuid => ({ uuid, effectiveVisible: true })),
      visibleOccupancyRenderables: 0 })
    const diff = compareRenderedObjects(snap(['native']), snap(['ghost']), snap(['native', 'ghost']))
    expect(diff.leftAfter).toEqual(['ghost'])
  })
})
