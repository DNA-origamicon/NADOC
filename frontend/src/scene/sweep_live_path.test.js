import {it,expect} from 'vitest'
import * as THREE from 'three'
import {sampleLiveSweep,bindSweepCloud,moveSweepCloud,SWEEP_LIVE_BUDGET} from './sweep_live_path.js'
import {createSweepLivePreview} from './sweep_live_preview.js'

it('matches the natural cubic at interior samples and interpolates every control',()=>{
  const path=sampleLiveSweep([[0,0,0],[5,0,10],[0,0,20]],[],undefined,null,5)
  expect(path.positions[1].toArray()).toEqual([3.4375,0,5])
  expect(path.positions[2].toArray()).toEqual([5,0,10])
  expect(path.positions.at(-1).toArray()).toEqual([0,0,20])
  expect(sampleLiveSweep([[0,0,0],[0,0,0]])).toBeNull()
  expect(sampleLiveSweep([[0,0,0],[NaN,0,10]])).toBeNull()
})
it('honors clamped source direction, authored tangents and twist',()=>{
  const path=sampleLiveSweep([[0,0,0],[5,0,10]],[],undefined,new THREE.Vector3(0,0,1))
  expect(new THREE.Vector3(0,0,1).applyQuaternion(path.pointFrames[0]).distanceTo(new THREE.Vector3(0,0,1))).toBeLessThan(1e-10)
  const turned=sampleLiveSweep([[0,0,0],[5,0,10]],[[0,90,30],[0,0,90]])
  const expected=new THREE.Quaternion().setFromEuler(new THREE.Euler(0,Math.PI/2,Math.PI/6,'YXZ'))
  expect(turned.pointFrames[0].angleTo(expected)).toBeLessThan(1e-7)
  expect(turned.pointFrames[1].angleTo(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),Math.PI/2))).toBeLessThan(1e-7)
})
it('keeps terminal offsets and rigid attached shape while the path grows and turns',()=>{
  const baseline=sampleLiveSweep([[0,0,0],[0,0,10]])
  const data={helix_path_ids:['root','child'],edit_attachment_groups:[{helix_ids:['child'],end:'end'}],helix_paths_nm:[
    [[1,0,10],[1,0,13]],[[0,0,10],[2,1,12],[1,3,15]],
  ]}
  const bindings=bindSweepCloud(data,baseline),buffer=new Float32Array(bindings.length*3)
  const old=new Float32Array(buffer.length);moveSweepCloud(bindings,baseline,old)
  moveSweepCloud(bindings,sampleLiveSweep([[0,0,0],[0,20,0]]),buffer)
  const points=Array.from({length:bindings.length},(_,i)=>new THREE.Vector3().fromArray(buffer,3*i))
  expect(points[127].distanceTo(points[0])).toBeCloseTo(3)
  expect(points[128].toArray()).toEqual([0,20,0])
  for(let i=129;i<points.length;i++) {
    const a=new THREE.Vector3().fromArray(old,3*i),b=new THREE.Vector3().fromArray(old,3*(i-1))
    expect(points[i].distanceTo(points[i-1])).toBeCloseTo(a.distanceTo(b),5)
  }
})
it('bounds a large cloud, excludes independent geometry and reuses GPU attributes',()=>{
  const scene=new THREE.Scene(),live=createSweepLivePreview(scene)
  const data={points_nm:[[0,0,0],[0,0,10]],helix_paths_nm:Array.from({length:100},(_,i)=>Array.from({length:300},(_,j)=>[i,0,j/30]))}
  live.setBaseline(data)
  const cloud=scene.getObjectByName('sweep-live-cloud'),attribute=cloud.geometry.attributes.position
  live.update([[0,0,0],[0,2,12]],[])
  expect(cloud.geometry.drawRange.count).toBeLessThanOrEqual(SWEEP_LIVE_BUDGET)
  const before=attribute.array.slice()
  live.update([[0,0,0],[0,4,12]],[])
  expect(cloud.geometry.attributes.position).toBe(attribute)
  expect(attribute.array).not.toEqual(before)
  const path=sampleLiveSweep(data.points_nm)
  expect(bindSweepCloud({...data,helix_path_ids:['own','other'],helix_paths_nm:data.helix_paths_nm.slice(0,2),edit_helix_ids:['own']},path)).toHaveLength(128)
  live.dispose();expect(scene.children).toHaveLength(0)
})
