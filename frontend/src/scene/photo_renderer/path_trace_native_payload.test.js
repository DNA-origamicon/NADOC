import {it,expect} from 'vitest'
import * as THREE from 'three'
import {traceSnapshot} from './path_trace_snapshot.js'
import {nativeTracePayload,nativeTraceLighting} from './path_trace_native_payload.js'
import {createEMFieldOverlay} from '../em_field.js'
it('serializes every crossfade emitter with its palette and opacity without changing source buffers',()=>{
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),overlay=createEMFieldOverlay(scene)
  camera.position.z=10
  const data={shape:[2,2,2],lower_nm:[-1,-1,-1],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity:Array(8).fill(100),outside:Array(8).fill(true)}
  overlay.showTransition(data,{...data,intensity:Array(8).fill(.2)},.25,{mode:'volume',minimum:0,dotSize:8})
  const s=traceSnapshot(scene,camera,100),env=new THREE.DataTexture(new Float32Array([1,1,1,1]),1,1,THREE.RGBAFormat,THREE.FloatType)
  const dto=nativeTracePayload(s,env,scene,{})
  expect(dto.emSamples).toBe(16);expect(dto.meshes).toHaveLength(2)
  expect(dto.meshes[0].materials[0].opacity/dto.meshes[1].materials[0].opacity).toBeCloseTo(3)
  const palette=dto.meshes[0].materials[0].palette.data
  expect(new Float32Array(palette.buffer,palette.byteOffset,palette.byteLength/4)[0]).toBeGreaterThan(.9)
  s.root.children[0].material.map=new THREE.Texture()
  expect(()=>nativeTracePayload(s,env,scene,{})).toThrow(/textured materials/)
  s.dispose();env.dispose();overlay.dispose()
})

it('preserves glossy clearcoat parameters for the native material instead of rejecting it',()=>{
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera()
  const geometry=new THREE.SphereGeometry(1,8,6),material=new THREE.MeshPhysicalMaterial({clearcoat:.5,clearcoatRoughness:.1,ior:1.4})
  scene.add(new THREE.Mesh(geometry,material))
  const snapshot=traceSnapshot(scene,camera,100),env=new THREE.DataTexture(new Float32Array([1,1,1,1]),1,1,THREE.RGBAFormat,THREE.FloatType)
  try{expect(nativeTracePayload(snapshot,env,scene,{}).meshes[0].materials[0]).toMatchObject({clearcoat:.5,clearcoatRoughness:.1,ior:1.4})}
  finally{snapshot.dispose();env.dispose();geometry.dispose();material.dispose()}
})

it('serializes camera-pinned lights in world space without uploading any mesh',()=>{
  const scene=new THREE.Scene(),rig=new THREE.Group(),light=new THREE.DirectionalLight()
  rig.position.set(10,0,0);rig.rotation.y=Math.PI/2;light.position.set(0,0,2)
  rig.add(light);scene.add(rig,new THREE.AmbientLight());scene.environmentRotation.y=.5
  const update=nativeTraceLighting(scene)
  expect(Object.keys(update).sort()).toEqual(['lights','rotation'])
  expect(update.lights).toHaveLength(1);expect(update.lights[0].position[0]).toBeCloseTo(12)
  expect(update.rotation).toEqual([0,.5,0])
})
