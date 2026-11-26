import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { createCornerPreview } from './corner_preview.js'

const guide = {
  center_nm: [0, 0, 0], plane_normal: [0, 0, 1],
  cuts: [{ incoming_nm: [0, 0, 0], outgoing_nm: [0, 0, 0],
    incoming_path_nm: [[0, 0, -5], [0, 0, 0]],
    outgoing_path_nm: [[0, 0, 0], [5, 0, 0]] }],
}

describe('Corner preview ownership', () => {
  it('replaces the provisional view and restores live visibility on cancellation', () => {
    const scene = new THREE.Scene(), live = new THREE.Group()
    scene.add(live)
    const preview = createCornerPreview({ scene, getLiveRoot: () => live })
    preview.guide(guide)
    expect(live.visible).toBe(false)
    expect(scene.getObjectByName('corner-plane')).toBeTruthy()
    const previous = scene.getObjectByName('corner-cylinder-preview')
    preview.guide({ ...guide, plane_normal: [0, 1, 0] })
    expect(previous.parent).toBeNull()
    expect(scene.children).toHaveLength(2)
    preview.clear()
    expect(scene.children).toEqual([live])
    expect(live.visible).toBe(true)
    live.visible = false
    preview.guide(guide)
    preview.dispose()
    expect(live.visible).toBe(false)
  })

  it('does not change a replacement document root when an old preview closes', () => {
    const scene = new THREE.Scene()
    let live = new THREE.Group()
    const preview = createCornerPreview({ scene, getLiveRoot: () => live })
    preview.guide(guide)
    live = new THREE.Group()
    live.visible = false
    preview.dispose()
    expect(live.visible).toBe(false)
    expect(scene.children).toHaveLength(0)
  })
})
