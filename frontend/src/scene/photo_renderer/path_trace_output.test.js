import {it,expect,vi} from 'vitest'
import * as THREE from 'three'
import {traceOutputKey,createTraceOutputCache} from './path_trace_output.js'
it('invalidates solved pixels for camera, geometry, color, lighting, dimensions and settings changes',()=>{
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.1,100)
  const mesh=new THREE.Mesh(new THREE.SphereGeometry(),new THREE.MeshStandardMaterial()),light=new THREE.DirectionalLight()
  scene.add(mesh,light,light.target)
  const options={scene,camera,settings:{pathTraceSamples:4,pathTraceExportBackend:'webgl'},width:64,height:64,viewHeight:64}
  const key=()=>traceOutputKey(options)
  let previous=key()
  for(const change of [()=>camera.position.x++,()=>mesh.position.y++,()=>mesh.material.color.set('red'),
    ()=>light.target.position.x++,()=>scene.environmentRotation.y++,()=>options.width++,
    ()=>mesh.material.map=new THREE.Texture(),()=>mesh.material.map.repeat.x++,()=>mesh.material.normalScale.x++,
    ()=>mesh.material.onBeforeCompile=()=>{},()=>options.settings.pathTraceSamples++,()=>options.settings.pathTraceExportBackend='optix',
    ()=>{mesh.geometry.attributes.position.setX(0,5);mesh.geometry.attributes.position.needsUpdate=true}]){
    change();const next=key();expect(next).not.toBe(previous);previous=next
  }
  mesh.geometry.attributes.position.needsUpdate=true
  expect(key()).toBe(previous)
  mesh.geometry.dispose();mesh.material.dispose()
})
it('keeps only one copied output and clears it without retaining caller canvases',()=>{
  const drawImage=vi.fn(),spy=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage})
  const source={width:12,height:15},cache=createTraceOutputCache()
  cache.put('a',source);const copy=cache.get('a')
  expect(copy).not.toBe(source);expect(copy.width).toBe(12);expect(drawImage).toHaveBeenCalledWith(source,0,0)
  cache.put('b',source);expect(cache.get('a')).toBeNull();expect(cache.get('b')).toBe(copy)
  cache.clear();expect(cache.get('b')).toBeNull();expect(copy.width).toBe(0);spy.mockRestore()
})
it('does not fail an already rendered export if the optional cache cannot allocate a canvas',()=>{
  const spy=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null),cache=createTraceOutputCache()
  expect(()=>cache.put('large',{width:8192,height:8192})).not.toThrow()
  expect(cache.get('large')).toBeNull();spy.mockRestore()
})

it('separates cheap light/view updates from material, ambient and geometry changes',()=>{
  const scene=new THREE.Scene(),camera=new THREE.Camera(),rig=new THREE.Group()
  rig.userData.photoLightRig=true;const keyLight=new THREE.DirectionalLight(),ambient=new THREE.AmbientLight()
  rig.add(keyLight);const mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial())
  scene.add(rig,mesh,ambient)
  const key=()=>traceOutputKey({scene,camera,settings:{},width:100,height:100,ignoreTraceLighting:true})
  const before=key();rig.rotation.y=1;keyLight.intensity=3;scene.environmentRotation.y=2
  expect(key()).toBe(before)
  ambient.intensity=2;expect(key()).not.toBe(before)
  let prior=key();mesh.material.roughness=.2;expect(key()).not.toBe(prior)
  prior=key();mesh.position.y=2;expect(key()).not.toBe(prior)
  mesh.geometry.dispose();mesh.material.dispose()
})
