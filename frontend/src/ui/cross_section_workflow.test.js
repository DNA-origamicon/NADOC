import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { crossSectionViewPose, createCrossSectionWorkflow } from './cross_section_workflow.js'

const box = new THREE.Box3(new THREE.Vector3(-5, -4, 0), new THREE.Vector3(5, 4, 20))
it.each([[0,0,1], [0,1,0], [1,0,0], [0.3,0.4,0.5]])('faces the actual source normal %j', (...values) => {
  const n = new THREE.Vector3(...values).normalize()
  const up = Math.abs(n.y) > .9 ? new THREE.Vector3(0,0,1) : new THREE.Vector3(0,1,0)
  const pose = crossSectionViewPose(box, n, up)
  expect(pose.position.clone().sub(pose.target).normalize().dot(n)).toBeCloseTo(1)
})
it('fits the entire length in a perspective beside the popup', () => {
  const camera = new THREE.PerspectiveCamera(45, 1.8, .1, 10000)
  const pose = crossSectionViewPose(box, new THREE.Vector3(0,0,1), new THREE.Vector3(0,1,0), { aspect:1.8, fraction:.6, offset:.4, perspective:true })
  camera.position.copy(pose.position); camera.up.copy(pose.up); camera.lookAt(pose.target); camera.updateMatrixWorld()
  for (const x of [-5,5]) for (const y of [-4,4]) for (const z of [0,20]) {
    const projected = new THREE.Vector3(x,y,z).project(camera)
    expect(projected.x).toBeGreaterThan(-.2)
    expect(projected.x).toBeLessThan(1)
    expect(Math.abs(projected.y)).toBeLessThan(1)
  }
  const dir=pose.position.clone().sub(pose.target).normalize()
  expect(dir.z).toBeGreaterThan(.3); expect(dir.z).toBeLessThan(.9)
})
it('shares source-change alignment, orbit gating and cleanup between tool hosts', () => {
  let sourceChanged
  const camera = new THREE.PerspectiveCamera(45, 1.5, .1, 1000)
  const controls = { target:new THREE.Vector3(), enableRotate:true, update:vi.fn() }
  let normal = new THREE.Vector3(0,0,1)
  const slicePlane = { getAuthoringBounds:()=>box, getPlaneNormalWorld:()=>normal, getPlaneUpWorld:()=>new THREE.Vector3(0,1,0),
    setAuthoringStage:vi.fn(), subscribeSource:fn=>{sourceChanged=fn;return vi.fn()} }
  let frame, time = 0
  const finish = () => { time += 500; frame(time) }
  const release = vi.fn(), beginAuthoringDisplay = vi.fn(()=>release)
  const workflow=createCrossSectionWorkflow({slicePlane,getCamera:()=>camera,getControls:()=>controls,beginAuthoringDisplay,
    transitionOptions:{now:()=>time,requestFrame:fn=>{frame=fn;return 1},cancelFrame:vi.fn()} })
  workflow.setStep(1); expect(controls.enableRotate).toBe(false)
  normal=new THREE.Vector3(1,0,0); sourceChanged(); finish()
  expect(camera.position.clone().sub(controls.target).normalize().x).toBeCloseTo(1)
  workflow.setStep(2); expect(controls.enableRotate).toBe(true)
  expect(slicePlane.setAuthoringStage).toHaveBeenLastCalledWith('length')
  workflow.setStep(1); workflow.close()
  expect(controls.enableRotate).toBe(true)
  expect(slicePlane.setAuthoringStage).toHaveBeenLastCalledWith(null)
  expect(beginAuthoringDisplay).toHaveBeenCalledTimes(1); expect(release).toHaveBeenCalledTimes(1)
})

it('fills the available cross-section viewport without wasting the space on a sphere fit', () => {
  const grid = new THREE.Box3(new THREE.Vector3(-25,-20,0), new THREE.Vector3(25,20,0))
  const camera = new THREE.PerspectiveCamera(45,1.8,.1,10000)
  const pose = crossSectionViewPose(grid,new THREE.Vector3(0,0,1),new THREE.Vector3(0,1,0),{aspect:1.8,fraction:.6,offset:.4})
  camera.position.copy(pose.position);camera.up.copy(pose.up);camera.lookAt(pose.target);camera.updateMatrixWorld()
  const edge = new THREE.Vector3(25,20,0).project(camera)
  expect(edge.x).toBeGreaterThan(.85);expect(edge.x).toBeLessThan(1)
  expect(Math.abs(new THREE.Vector3(-25,-20,0).project(camera).y)).toBeLessThan(1)
})
