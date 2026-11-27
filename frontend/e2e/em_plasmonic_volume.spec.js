import {test,expect} from '@playwright/test'
import {readFile} from 'node:fs/promises'
// Read-only source, solver response held in memory; no document or simulation jobs.
// Optional review PNG is owned/removed by the invoking review wrapper.
test('Plasmonic adaptive volume remains bounded at a close oblique camera',async({page})=>{
 test.setTimeout(120000)
 const design=JSON.parse(await readFile(new URL('../../workspace/Plasmonic_test.nadoc',import.meta.url),'utf8'))
 const particles=design.nanoparticles.map(p=>({id:p.id,diameter_nm:p.diameter_nm,center_nm:[3,7,11].map(i=>p.pose.values[i])}))
 await page.route('**/plasmonic-volume-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body style="margin:0"></body></html>'}))
 await page.goto('/plasmonic-volume-fixture')
 const result=await page.evaluate(async particles=>{
  const T=await import('/node_modules/.vite/deps/three.js'),{createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const response=await fetch('/api/em-analysis/solve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({particles,shell:{model:'none'},sampling:'field_adaptive',resolution:33,solver:'multipole',polarization:'parallel'})})
  if(!response.ok)throw new Error(await response.text());const data=await response.json()
  const {drawEMVolumes}=await import('/src/scene/em_volume.js')
  const {volumeGrid,prepareVolumeCells}=await import('/src/scene/em_volume_data.js')
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(35,1,.01,10000)
  camera.position.set(-34.570386146871485,22.944321858110698,5.043808126161814);camera.up.set(.24672746455822822,.9545284074472415,.1673352252483059);camera.lookAt(-3.145956409518721,13.127276522925737,14.709309056681587)
  const renderer=new T.WebGLRenderer({preserveDrawingBuffer:true});renderer.setSize(512,512);renderer.setClearColor(0x000000);document.body.append(renderer.domElement)
  const target=new T.WebGLRenderTarget(512,512,{type:T.FloatType}),overlay=createEMFieldOverlay(scene),spheres=[]
  for(const p of particles){const sphere=new T.Mesh(new T.SphereGeometry(p.diameter_nm/2,32,24),new T.MeshBasicMaterial({color:0x554400}));sphere.position.fromArray(p.center_nm);scene.add(sphere);spheres.push(sphere)}
  try{
   const cells=prepareVolumeCells(data,volumeGrid(data),3);let coefficient=0,baryError=0,badCells=0
   for(let i=0;i<cells.count;i++){let error=0;for(let j=0;j<3;j++){const b=cells.arrays['b'+j].subarray(i*4,i*4+4);coefficient=Math.max(coefficient,...b.map(Math.abs));for(let k=0;k<4;k++){const p=cells.arrays['p'+k].subarray(i*3,i*3+3);error=Math.max(error,Math.abs(b[0]*p[0]+b[1]*p[1]+b[2]*p[2]+b[3]-(j===k?1:0)))}}baryError=Math.max(baryError,error);if(error>.1)badCells++}
   overlay.show(data,{mode:'smooth',minimum:3});renderer.setRenderTarget(target);renderer.render(scene,camera)
   const pixels=new Float32Array(512*512*4);renderer.readRenderTargetPixels(target,0,0,512,512,pixels)
   let peak=0,bad=0;for(let i=0;i<pixels.length;i++)if(i%4!==3){peak=Math.max(peak,pixels[i]);if(!Number.isFinite(pixels[i]))bad++}
   const volume=scene.getObjectByName('experimental-em-field');volume.visible=false;renderer.render(scene,camera);volume.visible=true;drawEMVolumes(renderer,scene,camera,target)
   const composed=new Float32Array(pixels.length);renderer.readRenderTargetPixels(target,0,0,512,512,composed)
   let difference=0;for(let i=0;i<pixels.length;i++)difference=Math.max(difference,Math.abs(pixels[i]-composed[i]))
   renderer.setRenderTarget(null);renderer.render(scene,camera)
   const canvas=document.createElement('canvas');canvas.width=512;canvas.height=512;canvas.getContext('2d').drawImage(renderer.domElement,0,0);document.body.append(canvas)
   return {peak,bad,difference,coefficient,baryError,badCells,samples:data.intensity.length,tets:data.display_tetrahedra.length}
  }finally{overlay.dispose();target.dispose();for(const s of spheres){s.geometry.dispose();s.material.dispose()}renderer.dispose()}
 },particles)
 if(process.env.NADOC_EM_PATCH_REVIEW)await page.screenshot({path:process.env.NADOC_EM_PATCH_REVIEW})
 console.log('EM_OBLIQUE',result)
 expect(result.badCells).toBe(0);expect(result.baryError).toBeLessThan(.001);expect(result.difference).toBeLessThan(.0001);expect(result.bad).toBe(0);expect(result.peak).toBeLessThan(20)
})
