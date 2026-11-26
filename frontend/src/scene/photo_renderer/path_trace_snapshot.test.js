import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { traceSnapshot, traceSnapshotAsync, traceLights } from './path_trace_snapshot.js'
import { createEMFieldOverlay } from '../em_field.js'
import { registerPreparedAssemblyMaterial } from '../prepared_assembly_instances.js'

describe('path-traced display snapshot', () => {
  const camera = () => { const c = new THREE.PerspectiveCamera(45, 1, .1, 100); c.position.z = 10; c.updateMatrixWorld(); return c }
  it('does not impose a three-million-triangle policy on a valid indexed snapshot',()=>{
    // Repeated indices keep this boundary regression small; no authored document.
    const scene=new THREE.Scene(),g=new THREE.BufferGeometry(),m=new THREE.MeshStandardMaterial()
    g.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,1,0,0,0,1,0],3))
    g.setAttribute('normal',new THREE.Float32BufferAttribute([0,0,1,0,0,1,0,0,1],3))
    const index=new Uint32Array(3000001*3)
    for(let i=0;i<index.length;i++)index[i]=i%3
    g.setIndex(new THREE.BufferAttribute(index,1));scene.add(new THREE.Mesh(g,m))
    const result=traceSnapshot(scene,camera(),100,{maxTextureSize:4096})
    expect(result.triangles).toBe(3000001);expect(result.root.children[0].geometry.index.count).toBe(index.length)
    result.dispose();g.dispose();m.dispose()
  })
  it('bakes visible instances, colors and alpha without touching editor buffers', () => {
    const scene = new THREE.Scene(), g = new THREE.BoxGeometry(), m = new THREE.MeshStandardMaterial()
    const mesh = new THREE.InstancedMesh(g, m, 2)
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(3, 0, 0))
    mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(20, 0, 0))
    mesh.setColorAt(0, new THREE.Color(1, 0, 0))
    g.setAttribute('instanceAlpha', new THREE.InstancedBufferAttribute(new Float32Array([.5, 0]), 1))
    scene.add(mesh)
    const before = mesh.instanceMatrix.array.slice()
    const result = traceSnapshot(scene, camera(), 200)
    const baked = result.root.children[0]; baked.geometry.computeBoundingBox()
    expect(baked.geometry.boundingBox.min.x).toBeCloseTo(2.5)
    expect(baked.geometry.boundingBox.max.x).toBeCloseTo(3.5)
    expect(baked.geometry.attributes.color.getW(0)).toBe(.5)
    expect(baked.geometry.attributes.color.getX(0)).toBe(1)
    expect(baked.geometry.attributes.color.getY(0)).toBe(0)
    result.dispose()
    expect(mesh.instanceMatrix.array).toEqual(before)
    expect(g.index).not.toBeNull()
  })
  it('includes every EM sample in both crossfade clouds as colored emissive geometry', () => {
    const scene = new THREE.Scene(), overlay = createEMFieldOverlay(scene)
    const data = {shape:[2,2,2], lower_nm:[-1,-1,-1], upper_nm:[1,1,1], origin_nm:[0,0,0],
      basis:[[1,0,0],[0,1,0],[0,0,1]], intensity:Array(8).fill(100), outside:Array(8).fill(true)}
    overlay.showTransition(data, {...data, intensity:Array(8).fill(.2)}, .25, {mode:'volume',minimum:0,dotSize:8,lighting:'illuminate'})
    const result = traceSnapshot(scene, camera(), 200)
    expect(result.emSamples).toBe(16)
    const clouds = result.root.children.filter(o => o.userData.emEmitter)
    expect(clouds).toHaveLength(2)
    expect(clouds[0].material.emissiveIntensity).toBeGreaterThan(0)
    expect(clouds[0].material.emissiveMap.image.data[0]).toBeGreaterThan(.9)
    expect(clouds[1].material.emissiveMap.image.data[2]).toBeGreaterThan(.9)
    expect(clouds[0].material.opacity / clouds[1].material.opacity).toBeCloseTo(3)
    expect(result.root.children.some(o => o.isPointLight)).toBe(false)
    result.dispose(); overlay.dispose()
  })
  it('honors ancestor visibility and refuses oversize snapshots instead of truncating', () => {
    const scene = new THREE.Scene(), hidden = new THREE.Group(); hidden.visible = false
    hidden.add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial())); scene.add(hidden)
    const empty = traceSnapshot(scene, camera(), 100); expect(empty.triangles).toBe(0); empty.dispose()
    hidden.visible = true
    expect(() => traceSnapshot(scene, camera(), 100, {maxTextureSize:1})).toThrow(/device reports/)
  })
  it('uses shared assembly placements and rejects unrecognized shader transforms',()=>{
    const scene=new THREE.Scene(),mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial(),1)
    mesh.userData.sharedInstanced=true;mesh.material.onBeforeCompile=()=>{}
    scene.add(mesh)
    expect(()=>traceSnapshot(scene,camera(),100)).toThrow(/shared display shader/)
    const texture=data=>({value:new THREE.DataTexture(new Float32Array(data),4,1)})
    registerPreparedAssemblyMaterial(mesh.material,{baseCount:1,xform:texture(new THREE.Matrix4().makeTranslation(7,0,0).elements),
      local:texture(new THREE.Matrix4().makeTranslation(2,0,0).elements),visibility:texture([1,...Array(15).fill(0)])})
    const result=traceSnapshot(scene,camera(),100),g=result.root.children[0].geometry
    g.computeBoundingBox();expect(g.boundingBox.min.x).toBe(8.5);expect(g.boundingBox.max.x).toBe(9.5)
    result.dispose();expect(mesh.instanceMatrix.array[12]).toBe(0)
  })
})

it('refreshes camera-pinned physical lights in world space without EM proxies or ambient duplication',()=>{
  const scene=new THREE.Scene(),rig=new THREE.Group(),key=new THREE.DirectionalLight(0xffffff,2)
  rig.position.set(3,4,5);key.position.set(1,2,3);rig.add(key);scene.add(rig,new THREE.AmbientLight())
  const em=new THREE.PointLight();em.userData.emLight=true;scene.add(em)
  const hidden=new THREE.PointLight();hidden.visible=false;scene.add(hidden)
  scene.updateMatrixWorld(true)
  const [copy,...rest]=traceLights(scene)
  expect(rest).toHaveLength(0);expect(copy).not.toBe(key);expect(copy.position.toArray()).toEqual([4,6,8])
  expect(copy.intensity).toBe(2);copy.position.x=100;expect(key.position.x).toBe(1)
})


it('async preparation reports partial vertex work and matches every synchronous display buffer',async()=>{
  const scene=new THREE.Scene(),geometry=new THREE.BoxGeometry(),material=new THREE.MeshStandardMaterial(),mesh=new THREE.InstancedMesh(geometry,material,300)
  for(let i=0;i<300;i++)mesh.setMatrixAt(i,new THREE.Matrix4().makeTranslation(i,0,0))
  scene.add(mesh)
  const camera=new THREE.PerspectiveCamera(),progress=[]
  const expected=traceSnapshot(scene,camera,100),actual=await traceSnapshotAsync(scene,camera,100,{onProgress:f=>progress.push(f)})
  expect(progress[0]).toBe(0);expect(progress.at(-1)).toBe(1);expect(progress.some(f=>f>0&&f<1)).toBe(true)
  for(const key of ['position','normal','color','uv'])expect(actual.root.children[0].geometry.attributes[key].array).toEqual(expected.root.children[0].geometry.attributes[key].array)
  expect(actual.root.children[0].geometry.index.array).toEqual(expected.root.children[0].geometry.index.array)
  actual.dispose();expected.dispose();geometry.dispose();material.dispose()
})
it('cancels partial async preparation without changing source geometry',async()=>{
  const scene=new THREE.Scene(),geometry=new THREE.BoxGeometry(),material=new THREE.MeshStandardMaterial(),mesh=new THREE.InstancedMesh(geometry,material,300)
  for(let i=0;i<300;i++)mesh.setMatrixAt(i,new THREE.Matrix4())
  scene.add(mesh)
  const controller=new AbortController(),before=geometry.attributes.position.array.slice()
  await expect(traceSnapshotAsync(scene,new THREE.PerspectiveCamera(),100,{signal:controller.signal,onProgress:f=>{if(f>0)controller.abort()}})).rejects.toMatchObject({name:'AbortError'})
  expect(geometry.attributes.position.array).toEqual(before)
  geometry.dispose();material.dispose()
})
