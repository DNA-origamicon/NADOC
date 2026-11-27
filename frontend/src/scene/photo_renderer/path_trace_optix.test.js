import {it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {createOptixTraceEngine} from './path_trace_optix.js'
import {requestOptix} from './path_trace_errors.js'

vi.mock('./path_trace_errors.js',()=>({requestOptix:vi.fn(async()=>new Response(new Float32Array([0,0,0,1]).buffer))}))
vi.mock('./path_trace_native_session.js',()=>({createNativeSession:async()=>({id:'test',device:'test',capacity:{},close:async()=>{}})}))
vi.mock('./path_trace_native_progress.js',()=>({pollNativeTrace:()=>()=>{}}))
vi.mock('./path_trace_environment.js',async()=>{const T=await import('three');return {traceEnvironment:()=>new T.DataTexture(new Float32Array([0,0,0,1]),1,1)}})

it('averages disjoint chunks by sample count and discards old pixels on reset',async()=>{
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera()
  const engine=await createOptixTraceEngine({scene,camera,settings:{},renderer:{},width:1,height:1,viewHeight:1})
  const response=value=>new Response(new Float32Array([value,0,0,1]).buffer)
  try{
    requestOptix.mockResolvedValueOnce(response(2));await engine.advance(1,{sampleTarget:8})
    requestOptix.mockResolvedValueOnce(response(6));await engine.advance(4,{sampleTarget:8})
    expect(requestOptix.mock.lastCall[1]).toMatchObject({samples:3,sample_offset:1,sample_total:8,reuse_scene:true})
    expect(engine.samples).toBe(4);expect(engine.readPixels()[0]).toBe(5)
    engine.reset(camera,1,1)
    requestOptix.mockResolvedValueOnce(response(9));await engine.advance(1,{sampleTarget:8})
    expect(requestOptix.mock.lastCall[1].sample_offset).toBe(0);expect(engine.readPixels()[0]).toBe(9)
  }finally{await engine.dispose()}
})

it('keeps pending emitter removal and lighting across coalesced updates before the next render',async()=>{
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();camera.position.z=8
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0],3))
  const material=new THREE.PointsMaterial({size:4}),cloud=new THREE.Points(geometry,material);cloud.userData.emSamples=true
  const light=new THREE.DirectionalLight();scene.add(cloud,light)
  const options={scene,camera,settings:{},renderer:{},width:1,height:1,viewHeight:100}
  const engine=await createOptixTraceEngine(options)
  try{
    await engine.advance(1)
    scene.remove(cloud);light.intensity=3
    await engine.update(options);await engine.update(options)
    await engine.advance(1)
    const sent=requestOptix.mock.lastCall[1]
    expect(sent.reuse_scene).toBe(true);expect(sent.emitters).toEqual([])
    expect(sent.lights[0].intensity).toBe(3);expect(sent.meshes).toBeUndefined()
  }finally{await engine.dispose();geometry.dispose();material.dispose()}
})


it('keeps volume hulls out of native snapshots across cutoff and mode changes',async()=>{
  const {createEMFieldOverlay}=await import('../em_field.js')
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),overlay=createEMFieldOverlay(scene)
  const data={shape:[3,3,3],lower_nm:[-1,-1,-1],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity:Array(27).fill(10),outside:Array(27).fill(true)}
  overlay.show(data,{mode:'smooth',minimum:2})
  const options={scene,camera,settings:{},renderer:{},width:1,height:1,viewHeight:100}
  const engine=await createOptixTraceEngine(options)
  try{
    expect(engine.emVolumeCells).toBeGreaterThan(0)
    await engine.advance(1);expect(requestOptix.mock.lastCall[1].smoothEM).toBe(true);expect(requestOptix.mock.lastCall[1].volumes).toHaveLength(1)
    overlay.show(data,{mode:'smooth',minimum:3});await engine.update(options);await engine.advance(1)
    expect(requestOptix.mock.lastCall[1].meshes).toEqual([])
    await engine.update(options);await engine.advance(1);expect(requestOptix.mock.lastCall[1].reuse_scene).toBe(true)
    overlay.show(data,{mode:'smooth',minimum:11});await engine.update(options);await engine.advance(1)
    expect(requestOptix.mock.lastCall[1].volumes).toEqual([]);expect(requestOptix.mock.lastCall[1].smoothEM).toBe(false);expect(engine.emVolumeCells).toBe(0)
    expect(requestOptix.mock.lastCall[1].meshes).toEqual([])
  }finally{await engine.dispose();overlay.dispose()}
})
