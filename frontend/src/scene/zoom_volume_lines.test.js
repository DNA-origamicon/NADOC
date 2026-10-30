import { expect, it } from 'vitest'
import * as THREE from 'three'
import { zoomVolumeConnectors } from './zoom_volume_lines.js'

const bounds = new THREE.Box3(new THREE.Vector3(-3,-2,-1), new THREE.Vector3(3,2,1))
const viewport = { left: 30, top: 70, width: 1000, height: 700 }
const cornerPoints = camera => {
  const points = []
  for (const x of [-3,3]) for (const y of [-2,2]) for (const z of [-1,1]) {
    const p = new THREE.Vector3(x,y,z).project(camera)
    points.push({ x: viewport.left + (p.x+1)*viewport.width/2, y: viewport.top+(1-p.y)*viewport.height/2 })
  }
  return points
}
it('attaches to real box and inset vertices and keeps lines outside both silhouettes through rotations', () => {
  const camera = new THREE.PerspectiveCamera(55, viewport.width/viewport.height, .1, 100)
  for (let angle = 0; angle < 6.28; angle += .25) {
    camera.position.set(16*Math.cos(angle), 8, 16*Math.sin(angle)); camera.lookAt(0,0,0)
    // Deliberately do not update matrices: controls change poses before rendering.
    for (const inset of [
      { left: 50, right: 220, top: 90, bottom: 230 },
      { left: 800, right: 1000, top: 90, bottom: 230 },
      { left: 50, right: 220, top: 600, bottom: 750 },
      { left: 800, right: 1000, top: 600, bottom: 750 },
    ]) {
      const lines = zoomVolumeConnectors(bounds, camera, viewport, inset)
      expect(lines).toHaveLength(2)
      const points = cornerPoints(camera)
      for (const line of lines) {
        expect(Math.min(...points.map(p => Math.hypot(p.x-line.x1,p.y-line.y1)))).toBeLessThan(1e-8)
        expect([inset.left,inset.right]).toContain(line.x2)
        expect([inset.top,inset.bottom]).toContain(line.y2)
        const all = [...points, ...[inset.left,inset.right].flatMap(x => [inset.top,inset.bottom].map(y => ({ x,y })))]
        const sides = all.map(p => (line.x2-line.x1)*(p.y-line.y1)-(line.y2-line.y1)*(p.x-line.x1))
        expect(sides.every(n => n >= -1e-7) || sides.every(n => n <= 1e-7)).toBe(true)
      }
    }
  }
})
it('hides lines for empty, offscreen, behind-camera and contained volumes', () => {
  const camera = new THREE.PerspectiveCamera(55, viewport.width/viewport.height, .1, 100)
  camera.position.z = 20
  const inset = { left: 800, right: 1000, top: 90, bottom: 230 }
  expect(zoomVolumeConnectors(new THREE.Box3(), camera, viewport, inset)).toEqual([])
  expect(zoomVolumeConnectors(bounds.clone().translate(new THREE.Vector3(100,0,0)), camera, viewport, inset)).toEqual([])
  expect(zoomVolumeConnectors(bounds.clone().translate(new THREE.Vector3(0,0,50)), camera, viewport, inset)).toEqual([])
  expect(zoomVolumeConnectors(bounds, camera, viewport, { left: 0, top: 0, right: 1500, bottom: 1500 })).toEqual([])
})
