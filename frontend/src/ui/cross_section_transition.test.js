import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { createCrossSectionTransition } from './cross_section_transition.js'

it('takes 500ms, stays finite across opposite views, supersedes and cancels without a late snap', () => {
  let time = 0, next = 0
  const frames = new Map(), active = vi.fn()
  const tick = t => { time = t; const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn(t)) }
  const transition = createCrossSectionTransition({ now:()=>time, requestFrame:fn=>{frames.set(++next,fn);return next}, cancelFrame:id=>frames.delete(id), onActive:active })
  const camera = new THREE.PerspectiveCamera(); camera.position.set(0,0,10)
  const controls = { target:new THREE.Vector3(), update:vi.fn() }
  const pose = { position:new THREE.Vector3(0,0,-20), target:new THREE.Vector3(), up:new THREE.Vector3(0,-1,0), distance:20 }
  transition.move(camera,controls,pose)
  expect(camera.position.z).toBe(10)
  tick(250); expect(camera.position.length()).toBeCloseTo(15)
  expect(camera.position.toArray().every(Number.isFinite)).toBe(true)
  tick(499); expect(active).toHaveBeenLastCalledWith(true)
  tick(500); expect(camera.position.distanceTo(pose.position)).toBeLessThan(1e-10)
  expect(active).toHaveBeenLastCalledWith(false)
  transition.move(camera,controls,{...pose,position:new THREE.Vector3(20,0,0)})
  tick(600)
  transition.move(camera,controls,pose)
  expect(frames.size).toBe(1)
  transition.cancel(); const stopped=camera.position.clone(); tick(2000)
  expect(camera.position.equals(stopped)).toBe(true); expect(frames.size).toBe(0)
})
