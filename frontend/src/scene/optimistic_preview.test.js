import { describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { freezeOptimisticPreview } from './optimistic_preview.js'

describe('optimistic scene preview', () => {
  it('preserves world transforms and settles without disposing shared geometry', () => {
    const scene = new THREE.Scene()
    const parent = new THREE.Group()
    parent.position.set(4, 5, 6)
    scene.add(parent)
    const geometry = new THREE.BoxGeometry(1, 1, 1)
    geometry.dispose = vi.fn()
    const source = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: 0xff0000 }))
    source.position.set(1, 2, 3)
    parent.add(source)
    scene.updateMatrixWorld(true)

    const tx = freezeOptimisticPreview(scene, [source], { name: 'pending-test' })
    expect(tx.active).toBe(true)
    expect(tx.group.name).toBe('pending-test')
    expect(tx.group.children[0].position.toArray()).toEqual([5, 7, 9])
    expect(tx.group.children[0].geometry).toBe(geometry)

    tx.settle()
    tx.settle()
    expect(tx.active).toBe(false)
    expect(scene.children).not.toContain(tx.group)
    expect(geometry.dispose).not.toHaveBeenCalled()
  })

  it('creates an inert transaction when nothing is visible', () => {
    const scene = new THREE.Scene()
    const hidden = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
    hidden.visible = false
    const tx = freezeOptimisticPreview(scene, [hidden])
    expect(tx.active).toBe(false)
    expect(scene.children).not.toContain(tx.group)
    tx.settle()
  })
})
