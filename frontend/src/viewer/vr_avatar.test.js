import { it, expect } from 'vitest'
import * as THREE from 'three'
import { estimateVRBody, createVRAvatar } from './vr_avatar.js'
import { validateVRAvatar } from './vr_avatar_protocol.js'
const pose = (p=[0,1.6,0]) => ({position:p,orientation:[0,0,0,1]})
const packet = () => ({schema:1,trackingToSource:new THREE.Matrix4().toArray(),head:pose(),hands:[pose([-.3,1.2,-.4]),pose([.3,1.2,-.4])]})
it('estimates finite elbows while preserving tracked wrists including singular and extended reaches',()=>{
  for(const wrist of [[0,0,0],[0,1.38,.08],[.18,1.38,.08],[0,5,0],[0,1.6,-.01]]) {
    const body=estimateVRBody(pose(),[pose(wrist),null])
    expect(body.arms[0].wrist).toEqual(wrist)
    expect(body.arms[0].elbow.every(Number.isFinite)).toBe(true)
    expect(body.arms[1].elbow).toBeNull()
    const a=body.arms[0],distance=(x,y)=>new THREE.Vector3(...x).distanceTo(new THREE.Vector3(...y))
    expect(distance(a.shoulder,a.elbow)).toBeCloseTo(distance(a.elbow,a.wrist),8)
  }
})
it('scales all avatar dimensions inversely and removes stale/disabled tracking without changing the scene',()=>{
  const scene=new THREE.Scene();let clock=0
  const avatar=createVRAvatar({scene,now:()=>clock}), p=packet()
  avatar.receive({avatar:{pose:p,expiresAt:1500},serverTime:0});avatar.frame();scene.updateMatrixWorld(true)
  const size=new THREE.Box3().setFromObject(avatar.root).getSize(new THREE.Vector3())
  p.trackingToSource=new THREE.Matrix4().makeScale(.5,.5,.5).toArray()
  avatar.receive({avatar:{pose:p,expiresAt:1500},serverTime:0});avatar.frame();scene.updateMatrixWorld(true)
  scene.clear();avatar.frame();expect(avatar.root.parent).toBe(scene)
  scene.updateMatrixWorld(true)
  const smaller=new THREE.Box3().setFromObject(avatar.root).getSize(new THREE.Vector3())
  expect(smaller.x).toBeCloseTo(size.x*.5,8);expect(smaller.y).toBeCloseTo(size.y*.5,8)
  clock=1600;avatar.frame();expect(avatar.root.visible).toBe(false)
  avatar.receive({avatar:null});avatar.frame();expect(avatar.root.visible).toBe(false)
  avatar.dispose();expect(scene.children).toHaveLength(0)
})
it('rejects invalid poses, unbounded dimensions, malformed hands and shearing transforms',()=>{
  for(const modify of [p=>p.head.orientation[3]=0,p=>p.hands.push(null),p=>p.trackingToSource[4]=.1,p=>p.trackingToSource[0]=Infinity]) {
    const p=packet();modify(p);expect(()=>validateVRAvatar(p)).toThrow()
  }
})
