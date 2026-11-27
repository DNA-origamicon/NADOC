import {test,expect} from '@playwright/test'
import {guardNativeLease} from './native_lease_guard.js'
guardNativeLease(test)
// Graphics-only fixture. Native leases own scratch; always close them. Standard
// reporter/teardown removes browser artifacts. No documents, jobs or downloads.
test('Native OptiX reflects off-camera adaptive emission without a second camera glow',async({page})=>{
 test.skip(!process.env.NADOC_TEST_OPTIX,'Explicit native GPU check')
 test.setTimeout(120000)
 await page.route('**/em-reflection-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
 await page.goto('/em-reflection-fixture')
 const result=await page.evaluate(async()=>{
  const T=await import('/node_modules/.vite/deps/three.js')
  const {createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const {traceSnapshot}=await import('/src/scene/photo_renderer/path_trace_snapshot.js')
  const {nativeTracePayload}=await import('/src/scene/photo_renderer/path_trace_native_payload.js')
  const {nativeTraceVolumes}=await import('/src/scene/photo_renderer/path_trace_volumes.js')
  const {createNativeSession}=await import('/src/scene/photo_renderer/path_trace_native_session.js')
  const {requestOptix}=await import('/src/scene/photo_renderer/path_trace_errors.js')
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(25,1,.01,100);camera.position.set(.2,.2,3);camera.lookAt(.2,.2,0)
  const mirror=new T.Mesh(new T.PlaneGeometry(4,4),new T.MeshStandardMaterial({color:0xffffff,metalness:1,roughness:0}));scene.add(mirror)
  const overlay=createEMFieldOverlay(scene),environment=new T.DataTexture(new Float32Array([0,0,0,1]),1,1,T.RGBAFormat,T.FloatType)
  const data={sampling:{layout:'octree'},sample_positions_nm:[[1,0,0],[0,1,0],[0,0,1],[0,0,0]],display_tetrahedra:[[0,1,2,3]],intensity:[100,100,100,100],outside:[1,1,1,1],cell_sizes_nm:Array(4).fill([1,1,1]),shape:[4,1,1],lower_nm:[0,0,0],upper_nm:[1,1,1],origin_nm:[0,0,4],basis:[[1,0,0],[0,1,0],[0,0,1]]}
  const lease=await createNativeSession(),snapshots=[]
  const render=async payload=>{
   camera.updateMatrixWorld(true)
   const response=await requestOptix(`/${lease.id}/frame`,{...payload,width:64,height:64,samples:32,camera:{matrix:camera.matrixWorld.toArray(),projection:camera.projectionMatrix.toArray(),orthographic:false}})
   const pixels=new Float32Array(await response.arrayBuffer());let sum=0,green=0,blue=0
   for(let y=30;y<34;y++)for(let x=30;x<34;x++){sum+=pixels[(y*64+x)*4];green+=pixels[(y*64+x)*4+1];blue+=pixels[(y*64+x)*4+2]}
   return {mean:sum/16,green:green/16,blue:blue/16,stats:JSON.parse(response.headers.get('X-NADOC-Render-Stats'))}
  }
  const payload=()=>{const s=traceSnapshot(scene,camera,64,{compactEM:true});snapshots.push(s);return nativeTracePayload(s,environment,scene,{bgColor:'#000000'})}
  try{
   overlay.show({...data,intensity:[100,100,100,1]},{mode:'smooth',minimum:3,colormap:'gray'})
   const coldGradient=await render(payload())
   overlay.show(data,{mode:'smooth',minimum:3,colormap:'gray',lighting:'glow'})
   const lit=await render(payload())
   overlay.weight(.5);const half=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.weight(1);mirror.visible=false;const primary=await render(payload())
   mirror.visible=true
   const blocker=new T.Mesh(new T.PlaneGeometry(4,4),new T.MeshBasicMaterial({color:0x000000}));blocker.position.z=3.5;scene.add(blocker)
   const blocked=await render(payload());scene.remove(blocker);blocker.geometry.dispose();blocker.material.dispose()
   const restored=await render(payload())
   const clear=await render({reuse_scene:true,volumes:[]})
   const split={...data,sample_positions_nm:[...data.sample_positions_nm,[0,0,.5]],intensity:Array(5).fill(100),outside:Array(5).fill(1),cell_sizes_nm:Array(5).fill([1,1,1]),display_tetrahedra:[[0,1,2,4],[0,1,4,3]]}
   overlay.show(split,{mode:'smooth',minimum:3,colormap:'gray'});const subdivided=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.show({...split,display_tetrahedra:[split.display_tetrahedra[0]]},{mode:'smooth',minimum:3,colormap:'gray'});const top=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.show({...split,display_tetrahedra:[split.display_tetrahedra[1]]},{mode:'smooth',minimum:3,colormap:'gray'});const bottom=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.show({...data,origin_nm:[0,0,-.2]},{mode:'smooth',minimum:3,colormap:'gray'});const inside=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.show({...data,intensity:[100,100,100,1]},{mode:'smooth',minimum:3,colormap:'gray'});const gradient=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.show(data,{mode:'smooth',minimum:3,colormap:'jet'});const jet=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   overlay.show(data,{mode:'smooth',minimum:3,colormap:'gray'});const recolored=await render({reuse_scene:true,volumes:nativeTraceVolumes(scene)})
   return {lit,half,primary,blocked,restored,clear,subdivided,inside,gradient,coldGradient,top,bottom,jet,recolored}
  }finally{await lease.close();for(const s of snapshots)s.dispose();overlay.dispose();environment.dispose();mirror.geometry.dispose();mirror.material.dispose()}
 })
 console.log('EM_REFLECTION',JSON.stringify(Object.fromEntries(Object.entries(result).map(([k,v])=>[k,{mean:v.mean,cells:v.stats.em_volume_cells}]))))
 expect(result.lit.stats.em_volume_cells).toBe(1)
 expect(result.lit.mean).toBeGreaterThan(.08);expect(result.lit.mean).toBeLessThan(.16)
 expect(result.half.mean/result.lit.mean).toBeCloseTo(.5,2)
 expect(result.primary.mean).toBeLessThan(.00001);expect(result.blocked.mean).toBeLessThan(.00001)
 expect(result.restored.mean).toBeCloseTo(result.lit.mean,3)
 expect(Math.abs(result.subdivided.mean/result.lit.mean-1)).toBeLessThan(.04)
 expect(result.inside.mean).toBeGreaterThan(.05);expect(result.inside.mean).toBeLessThan(.10)
 expect(result.gradient.mean).toBeGreaterThan(result.lit.mean*.4);expect(result.gradient.mean).toBeLessThan(result.lit.mean*.9)
 expect(result.gradient.mean).toBeCloseTo(result.coldGradient.mean,4)
 expect(result.jet.mean).toBeGreaterThan(.1);expect(result.jet.green).toBeLessThan(.00001);expect(result.jet.blue).toBeLessThan(.00001)
 expect(result.recolored.mean).toBeCloseTo(result.lit.mean,4);expect(result.recolored.blue).toBeCloseTo(result.lit.mean,4)
 expect(result.clear.mean).toBeLessThan(.00001);expect(result.clear.stats.em_volume_cells).toBe(0)
})
