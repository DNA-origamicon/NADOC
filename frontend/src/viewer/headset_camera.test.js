import { it, expect } from 'vitest'
import { Matrix4, Quaternion, Vector3 } from 'three'
import { headsetCamera, smoothHeadsetCamera } from './headset_camera.js'
const packet = (transform = new Matrix4(), orientation = new Quaternion()) => ({schema:1,trackingToSource:transform.toArray(),head:{position:[0,1.6,0],orientation:orientation.toArray()},hands:[null,null]})
const direction = camera => new Vector3(...camera.target).sub(new Vector3(...camera.position)).normalize()
it('maps head position, orientation, model rotation/scale and recentering into the shared source frame', () => {
  const rotation = new Quaternion().setFromAxisAngle(new Vector3(0,1,0), Math.PI/2)
  const matrix = new Matrix4().compose(new Vector3(30,40,50),rotation,new Vector3(100,100,100))
  const camera = headsetCamera(packet(matrix))
  expect(camera.position).toEqual([30,200,50])
  expect(direction(camera).distanceTo(new Vector3(-1,0,0))).toBeLessThan(1e-8)
  expect(camera.unitsPerMeter).toBeCloseTo(100)
  expect(camera.near).toBeCloseTo(.5)
  expect(headsetCamera(null)).toBeNull()
})
it('attenuates jitter and bounds sudden rotations and translations without crossing the look target', () => {
  const initial=headsetCamera(packet()), target=headsetCamera(packet(new Matrix4(),new Quaternion().setFromAxisAngle(new Vector3(0,1,0),Math.PI)))
  target.position[0]+=10;target.target[0]+=10
  const next=smoothHeadsetCamera(initial,target,.1)
  expect(direction(initial).angleTo(direction(next))).toBeCloseTo(Math.PI/20,6)
  expect(new Vector3(...next.position).distanceTo(new Vector3(...initial.position))).toBeCloseTo(.1)
  expect(new Vector3(...next.target).distanceTo(new Vector3(...next.position))).toBeCloseTo(1)
  const jitter=headsetCamera(packet(new Matrix4(),new Quaternion().setFromAxisAngle(new Vector3(0,1,0),.01)))
  expect(direction(initial).angleTo(direction(smoothHeadsetCamera(initial,jitter,1/60)))).toBeLessThan(.001)
})
it('converges to the headset view consistently at 30 and 60 fps, and bounds background-tab jumps', () => {
  const target=headsetCamera(packet(new Matrix4(),new Quaternion().setFromAxisAngle(new Vector3(0,1,0),1)))
  const run=rate=>{let camera=headsetCamera(packet());for(let i=0;i<rate*2;i++)camera=smoothHeadsetCamera(camera,target,1/rate);return camera}
  expect(direction(run(30)).angleTo(direction(target))).toBeLessThan(.001)
  expect(direction(run(60)).angleTo(direction(run(30)))).toBeLessThan(.001)
  const initial=headsetCamera(packet())
  expect(direction(initial).angleTo(direction(smoothHeadsetCamera(initial,target,20)))).toBeLessThanOrEqual(Math.PI/20+1e-8)
})

it('keeps head tracking independent of invalid tool-menu graphics and controller poses', () => {
  const value=packet(), expected=headsetCamera(value)
  expect(headsetCamera({...value,ui:{lines:[NaN],panels:[{id:'desktop-frame'}]},hands:[{position:[NaN]},null]})).toEqual(expected)
  expect(()=>headsetCamera({...value,head:{...value.head,position:[NaN,0,0]}})).toThrow('Invalid VR presenter pose')
  expect(()=>headsetCamera({...value,trackingToSource:new Array(16).fill(0)})).toThrow('Invalid VR presenter transform')
})
