import { expect, it } from 'vitest'
import * as THREE from 'three'
import { buildCornerReviewFullLayer } from './corner_review_full_layer.js'

const data = { residues: [0, 1].map(i => ({ strand_id: 's', atom_serials: [3*i, 3*i+1, 3*i+2],
  backbone_position: [i, 2, 3], base_position: [i, 3, 3], slab_axes: [[1,0,0],[0,1,0],[0,0,1]] })),
  backbone_edges: [[0, 1]] }

it('reads actual atom landmarks and connectivity without changing evidence', () => {
  const scene = new THREE.Scene(), before = JSON.stringify(data)
  const layer = buildCornerReviewFullLayer(scene, data, new Map([['s', '#123456']]))
  const beads = layer.root.getObjectByName('beads'), matrix = new THREE.Matrix4()
  beads.getMatrixAt(1, matrix)
  expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual([1, 2, 3])
  expect(beads.count).toBe(2)
  expect(layer.root.getObjectByName('connections').count).toBe(3)
  expect(JSON.stringify(data)).toBe(before)
  layer.dispose(); expect(scene.children).toHaveLength(0)
})

it('expands a defect atom selection to its residue and excludes unrelated edges', () => {
  const scene = new THREE.Scene()
  const layer = buildCornerReviewFullLayer(scene, data, new Map(), [4])
  expect(layer.root.getObjectByName('beads').count).toBe(1)
  expect(layer.root.getObjectByName('connections').count).toBe(1)
  layer.dispose()
})
