import {test,expect} from '@playwright/test'
import {guardNativeLease} from './native_lease_guard.js'
guardNativeLease(test)
import {readFile} from 'node:fs/promises'
// Read-only Plasmonic input, in-memory solver/display data. No document writes.
// Native lease owns worker scratch. Optional review PNG belongs to invoking wrapper.
let particles,field
// Solve separately so the solver and native-render checks each retain their
// existing 120 s / 180 s budgets and failures identify the responsible stage.
test.beforeAll(async({request})=>{
 if(!process.env.NADOC_TEST_OPTIX)return
 test.setTimeout(120000)
 const design=JSON.parse(await readFile(new URL('../../workspace/Plasmonic_test.nadoc',import.meta.url),'utf8'))
 particles=design.nanoparticles.map(p=>({id:p.id,diameter_nm:p.diameter_nm,center_nm:[3,7,11].map(i=>p.pose.values[i])}))
 const response=await request.post('/api/em-analysis/solve',{timeout:120000,data:{particles,shell:{model:'none'},sampling:'field_adaptive',resolution:33,solver:'multipole',polarization:'parallel'}})
 expect(response.ok()).toBe(true);field=await response.json()
})
test('Plasmonic smooth emission reflects in the actual Appearance gold material',async({page})=>{
 test.skip(!process.env.NADOC_TEST_OPTIX,'Explicit native GPU check')
 test.setTimeout(180000)
 await page.route('**/em-gold-reflection-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body style="margin:0;background:#222;color:white"></body></html>'}))
 await page.goto('/em-gold-reflection-fixture')
 page.on('console',message=>{if(message.text().startsWith('EM_CHUNK'))console.log(message.text())})
 const result=await page.evaluate(async({particles,data})=>{
  const T=await import('/node_modules/.vite/deps/three.js')
  const {createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const {makeGoldNanoparticleMaterial}=await import('/src/scene/photo_renderer/material_presets.js')
  const {traceSnapshot}=await import('/src/scene/photo_renderer/path_trace_snapshot.js')
  const {nativeTracePayload}=await import('/src/scene/photo_renderer/path_trace_native_payload.js')
  const {createNativeSession}=await import('/src/scene/photo_renderer/path_trace_native_session.js')
  const {requestOptix}=await import('/src/scene/photo_renderer/path_trace_errors.js')
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(35,1,.01,10000)
  camera.position.set(-34.570386146871485,22.944321858110698,5.043808126161814);camera.up.set(.24672746455822822,.9545284074472415,.1673352252483059);camera.lookAt(-3.145956409518721,13.127276522925737,14.709309056681587)
  const spheres=particles.map(p=>{const m=new T.Mesh(new T.SphereGeometry(p.diameter_nm/2,48,32),makeGoldNanoparticleMaterial());m.position.fromArray(p.center_nm);scene.add(m);return m})
  const overlay=createEMFieldOverlay(scene),environment=new T.DataTexture(new Float32Array([.05,.05,.05,1]),1,1,T.RGBAFormat,T.FloatType)
  const lease=await createNativeSession();let snapshot
  const render=async payload=>{
   camera.updateMatrixWorld(true)
   const response=await requestOptix(`/${lease.id}/frame`,{width:192,height:192,samples:32,...payload,camera:{matrix:camera.matrixWorld.toArray(),projection:camera.projectionMatrix.toArray(),orthographic:false}})
   return {pixels:new Float32Array(await response.arrayBuffer()),stats:JSON.parse(response.headers.get('X-NADOC-Render-Stats'))}
  }
  try{
   overlay.show(data,{mode:'smooth',minimum:3,lighting:'glow'})
   snapshot=traceSnapshot(scene,camera,192,{compactEM:true})
   const payload=nativeTracePayload(snapshot,environment,scene,{bgColor:'#000000'})
   const cells=scene.getObjectByName('experimental-em-field').children.find(o=>o.userData.emVolume).userData.emCellCount
   const lit=await render(payload),chunks=[],warm={pixels:new Float32Array(lit.pixels.length)}
   let offset=0
   for(const samples of [1,15,16]){
    const chunk=await render({reuse_scene:true,samples,sample_offset:offset,sample_total:32})
    for(let i=0;i<warm.pixels.length;i++)warm.pixels[i]+=chunk.pixels[i]*(samples/32)
    chunks.push(chunk.stats);warm.stats=chunk.stats;offset+=samples
    console.log('EM_CHUNK',JSON.stringify({samples,offset,render_ms:chunk.stats.render_ms}))
   }
   const dark=await render({reuse_scene:true,volumes:[]})
   let gain=0,changed=0,background=0,bad=0,retainedDifference=0
   for(let i=0;i<lit.pixels.length;i+=4){
    if(!Number.isFinite(lit.pixels[i]))bad++
    retainedDifference=Math.max(retainedDifference,Math.abs(lit.pixels[i]-warm.pixels[i]))
    const d=lit.pixels[i]-dark.pixels[i];gain+=d
    if(d>.001)changed++
    if(dark.pixels[i+3]===0)background=Math.max(background,Math.abs(d))
   }
   for(const [label,frame] of [['Reflected EM emission',lit],['Without reflected EM emission',dark]]){
    const box=document.createElement('div');box.style.display='inline-block';box.textContent=label;document.body.append(box)
    const canvas=document.createElement('canvas');canvas.width=canvas.height=192;canvas.style.cssText='display:block;width:384px;height:384px';box.append(canvas)
    const ctx=canvas.getContext('2d'),image=ctx.createImageData(192,192)
    for(let y=0;y<192;y++)for(let x=0;x<192;x++){const i=(y*192+x)*4,j=((191-y)*192+x)*4;for(let k=0;k<3;k++)image.data[i+k]=Math.min(255,255*Math.max(0,frame.pixels[j+k])**(1/2.2));image.data[i+3]=255}
    ctx.putImageData(image,0,0)
   }
   return {cells,gain:gain/(192*192),changed,background,bad,stats:lit.stats,warm:warm.stats,chunks,retainedDifference}
  }finally{await lease.close();snapshot?.dispose();overlay.dispose();environment.dispose();for(const m of spheres){m.geometry.dispose();m.material.dispose()}}
 },{particles,data:field})
 if(process.env.NADOC_EM_REFLECTION_REVIEW)await page.screenshot({path:process.env.NADOC_EM_REFLECTION_REVIEW})
 console.log('EM_GOLD_REFLECTION',JSON.stringify(result))
 expect(result.retainedDifference).toBeLessThan(.00001);expect(result.warm.scene_reused).toBe(true)
 expect(result.bad).toBe(0);expect(result.stats.em_volume_cells).toBe(result.cells)
 expect(result.changed).toBeGreaterThan(100);expect(result.gain).toBeGreaterThan(.0001);expect(result.background).toBeLessThan(.00001)
})
