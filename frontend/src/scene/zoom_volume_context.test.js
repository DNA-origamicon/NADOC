import { expect, it } from 'vitest'
import * as THREE from 'three'
import { nearbyZoomEntries, zoomContextBounds, nearbyZoomExternalRefs, setZoomContextOpacity } from './zoom_volume_context.js'

it('includes nearby complementary bases, excludes selected identities and distant bases in world space', () => {
  const selection = new THREE.Box3(new THREE.Vector3(9,0,0), new THREE.Vector3(11,2,2))
  const bounds = zoomContextBounds(selection)
  const entry = (x, direction, copy_k = 0) => ({ nuc: { helix_id: 'h', bp_index: x, direction, copy_k }, pos: new THREE.Vector3(x,1,1) })
  const entries = [entry(0, 'FORWARD'), entry(0, 'REVERSE'), entry(0, 'FORWARD', 1), entry(50, 'FORWARD')]
  expect(nearbyZoomEntries(entries, new Set(['h:0:FORWARD']), bounds, new THREE.Matrix4().makeTranslation(10,0,0))).toEqual(entries.slice(1,3))
  expect(selection.min.toArray()).toEqual([9,0,0])
  expect(selection.max.toArray()).toEqual([11,2,2])
})

it('nearby external objects exclude selected attachments and remote proteins', () => {
  const bounds = new THREE.Box3(new THREE.Vector3(-3,-3,-3), new THREE.Vector3(3,3,3))
  const refs = nearbyZoomExternalRefs({ nanoparticles: [{ id: 'selected', diameter_nm: 2 }, { id: 'neighbor', diameter_nm: 2 }] }, [
    { helix_id: '__protein__near', x: 0, y: 0, z: 0 },
    { helix_id: '__protein__far', x: 100, y: 0, z: 0 },
  ], [{ kind: 'nanoparticle', id: 'selected' }], bounds)
  expect(refs).toEqual([{ kind: 'nanoparticle', id: 'neighbor' }, { kind: 'protein', id: 'near' }])
})

it('updates only context materials and hides fully transparent context without disposal', () => {
  const selection = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial({ opacity: .8 }))
  const context = new THREE.Group(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
  context.add(mesh)
  setZoomContextOpacity(context, .25)
  expect(mesh.material.opacity).toBe(.25)
  expect(mesh.material.depthWrite).toBe(false)
  expect(selection.material.opacity).toBe(.8)
  setZoomContextOpacity(context, 0); expect(context.visible).toBe(false)
  setZoomContextOpacity(context, 1); expect(context.visible).toBe(true)
  expect(mesh.material.opacity).toBe(1)
  for (const object of [selection, mesh]) { object.geometry.dispose(); object.material.dispose() }
})
