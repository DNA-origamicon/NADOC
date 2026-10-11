import { describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { buildTJunctionPreviewGroup, disposeTJunctionPreviewGroup } from './t_junction_preview.js'

const fixture = {
  helices: [
    { id: 'body-0', bundle: 'body', start: [-10, 0, 0], end: [10, 0, 0], radiusNm: 1 },
    { id: 'branch-0', bundle: 'branch', start: [0, 3, 0], end: [0, 15, 0], radiusNm: 1 },
  ],
  routes: [{ id: 'joined', color: '#5ee7cb', closed: true, points: [[-10, 0, 0], [-1, 0, 0], [0, 3, 0], [0, 15, 0], [1, 3, 0], [1, 0, 0], [10, 0, 0], [-10, 0, 0]] }],
  bridges: [{ id: 'outbound', label: 'Enter branch', points: [[-1, 0, 0], [0, 3, 0]] }, { id: 'return', label: 'Return to body', points: [[1, 3, 0], [1, 0, 0]] }],
  cuts: [{ id: 'cut', points: [[-1, 0, 0], [1, 0, 0]] }],
  ports: [{ id: 'departure', label: 'Body departure', position: [-1, 0, 0] }],
}

describe('T-junction preview scene geometry', () => {
  it('places helix cylinders on model axes and renders a closed three-dimensional scaffold tube', () => {
    const group = buildTJunctionPreviewGroup(fixture)
    const body = group.children.find(child => child.userData.helixId === 'body-0')
    body.updateMatrixWorld()
    expect(new THREE.Vector3(0, -10, 0).applyMatrix4(body.matrixWorld).distanceTo(new THREE.Vector3(-10, 0, 0))).toBeLessThan(1e-10)
    const axis = new THREE.Vector3(0, 1, 0).applyQuaternion(body.quaternion)
    expect(axis.distanceTo(new THREE.Vector3(1, 0, 0))).toBeLessThan(1e-10)
    const route = group.children.find(child => child.userData.kind === 'scaffold')
    expect(route.isMesh).toBe(true)
    expect(route.geometry.type).toBe('TubeGeometry')
    expect(route.userData.closed).toBe(true)
    expect([...route.geometry.attributes.position.array].every(Number.isFinite)).toBe(true)
    expect(group.children.filter(child => child.userData.kind === 'bridge')).toHaveLength(2)
    disposeTJunctionPreviewGroup(group)
  })

  it('points bridge arrows along each directed route, including the return leg', () => {
    const group = buildTJunctionPreviewGroup(fixture)
    const arrows = group.children.filter(child => child.userData.kind === 'bridge-direction')
    const outward = new THREE.Vector3(0, 1, 0).applyQuaternion(arrows[0].quaternion)
    const returning = new THREE.Vector3(0, 1, 0).applyQuaternion(arrows[1].quaternion)
    expect(outward.dot(new THREE.Vector3(1, 3, 0).normalize())).toBeCloseTo(1)
    expect(returning.dot(new THREE.Vector3(0, -1, 0))).toBeCloseTo(1)
    disposeTJunctionPreviewGroup(group)
  })

  it('removes scaffold display or bundle display independently and toggles connection markers', () => {
    const bundles = buildTJunctionPreviewGroup(fixture, { representation: 'bundles', highlightBridges: false })
    expect(bundles.children.filter(child => child.userData.kind === 'scaffold')).toHaveLength(0)
    expect(bundles.children.filter(child => child.userData.kind === 'bridge')).toHaveLength(0)
    expect(bundles.children.every(child => child.visible)).toBe(true)
    const scaffold = buildTJunctionPreviewGroup(fixture, { representation: 'scaffold' })
    expect(scaffold.children.filter(child => child.userData.kind === 'helix').every(child => !child.visible)).toBe(true)
    expect(scaffold.children.some(child => child.userData.kind === 'scaffold')).toBe(true)
    disposeTJunctionPreviewGroup(bundles)
    disposeTJunctionPreviewGroup(scaffold)
  })

  it('disposes every owned material and geometry and removes the scene root', () => {
    const scene = new THREE.Scene(), group = buildTJunctionPreviewGroup(fixture)
    scene.add(group)
    const disposals = []
    group.traverse(child => {
      if (child.geometry) disposals.push(vi.spyOn(child.geometry, 'dispose'))
      if (child.material) disposals.push(vi.spyOn(child.material, 'dispose'))
    })
    disposeTJunctionPreviewGroup(group)
    expect(scene.children).toHaveLength(0)
    for (const dispose of disposals) expect(dispose).toHaveBeenCalledOnce()
  })
})
