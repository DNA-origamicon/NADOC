import {it,expect} from 'vitest'
import * as THREE from 'three'
import {traceSnapshot} from './path_trace_snapshot.js'
import {nativeTracePayload} from './path_trace_native_payload.js'
import {nativeJSONSize} from './path_trace_native_upload.js'

it('compact native emitters reproduce the legacy triangles and reduce transfer without changing the cloud',()=>{
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.1,100)
  camera.position.z=10
  const geometry=new THREE.BufferGeometry()
  geometry.setAttribute('position',new THREE.Float32BufferAttribute([1,2,0,-1,0,1],3))
  geometry.setAttribute('color',new THREE.Float32BufferAttribute([1,0,0,0,0,1],3))
  const material=new THREE.PointsMaterial({size:8,opacity:.24}),points=new THREE.Points(geometry,material)
  points.userData.emSamples=true;scene.add(points)
  const legacy=traceSnapshot(scene,camera,100),compact=traceSnapshot(scene,camera,100,{compactEM:true})
  const env=new THREE.DataTexture(new Float32Array([1,1,1,1]),1,1)
  try{
    const before=nativeTracePayload(legacy,env,scene,{}),after=nativeTracePayload(compact,env,scene,{})
    expect(after.meshes).toHaveLength(0);expect(after.emitters).toHaveLength(1)
    expect(compact.emSamples).toBe(2);expect(compact.triangles).toBe(40)
    const cloud=compact.emitters[0],original=legacy.root.children[0].geometry.attributes.position.array
    const rebuilt=[]
    for(let i=0;i<2;i++)for(let j=0;j<cloud.template.position.length;j++)
      rebuilt.push(cloud.centers[i*3+j%3]+cloud.radii[i]*cloud.template.position[j])
    expect(new Float32Array(rebuilt)).toEqual(original)
    expect(nativeJSONSize(after)).toBeLessThan(nativeJSONSize(before)/3)
    expect(geometry.attributes.position.array).toEqual(new Float32Array([1,2,0,-1,0,1]))
    expect(cloud.opacity).toBe(.24)
  }finally{legacy.dispose();compact.dispose();geometry.dispose();material.dispose();env.dispose()}
})
