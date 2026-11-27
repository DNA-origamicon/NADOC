import {test,expect} from '@playwright/test'
test.use({launchOptions:{args:['--enable-unsafe-webgpu']}})

// Synthetic scalar field + graphics only. No documents, solver jobs or downloads.
// Native sessions close in finally; API shutdown releases workers and scratch.
// Screenshot is inside test output (cleanup reporter), viewer bridge in global teardown.
for(const backend of ['raster','webgl','optix','webgpu'])test(`adaptive smooth EM display and cutoff in ${backend}`,async({page},testInfo)=>{
 test.skip(backend==='optix'&&!process.env.NADOC_TEST_OPTIX,'Explicit native check')
 test.skip(backend==='webgpu'&&!process.env.NADOC_TEST_WEBGPU,'Explicit WebGPU check')
 test.setTimeout(180000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/em-smooth-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body style="margin:0;background:black"></body></html>'}))
 await page.goto('/em-smooth-fixture')
 const result=await page.evaluate(async backend=>{
  const T=await import('/node_modules/.vite/deps/three.js')
  const {initEMAnalysis}=await import('/src/ui/em_analysis.js')
  const {saveEMColors}=await import('/src/ui/em_color_settings.js')
  saveEMColors({colorMinimum:.1,maximum:100,colormap:'plasma'})
  const {createPhotoMode}=await import('/src/scene/photo_mode.js')
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(45,1,.01,100);camera.position.set(4,2,7);camera.lookAt(0,0,0)
  const receiver=new T.Mesh(new T.SphereGeometry(.3,16,12),new T.MeshStandardMaterial({color:0x888888}));receiver.position.set(1.6,-.8,0);scene.add(receiver)
  const renderer=new T.WebGLRenderer({preserveDrawingBuffer:true});renderer.setSize(256,256);renderer.setClearColor(0x000000);document.body.append(renderer.domElement)
  const n=13,intensity=[],outside=[],sample_positions_nm=[],display_tetrahedra=[]
  for(let x=0;x<n;x++)for(let y=0;y<n;y++)for(let z=0;z<n;z++){
   const p=[x,y,z].map(v=>-2+4*v/(n-1))
   sample_positions_nm.push(p)
   intensity.push(1+99*Math.exp(-3*(p[0]**2+p[1]**2+p[2]**2)));outside.push(true)
  }
  const data={shape:[n,n,n],lower_nm:[-2,-2,-2],upper_nm:[2,2,2],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity,outside,peak_intensity:100,elapsed_seconds:0,inputs:{},gap_nm:null,multipole_order:6,probe_relative_error:.001,polarization_world:[1,0,0],propagation_world:[0,0,1]}
  const index=(x,y,z)=>x*n*n+y*n+z
  for(let x=0;x<n-1;x++)for(let y=0;y<n-1;y++)for(let z=0;z<n-1;z++){
   const a=index(x,y,z),b=index(x+1,y,z),c=index(x,y+1,z),d=index(x+1,y+1,z),
    e=index(x,y,z+1),f=index(x+1,y,z+1),g=index(x,y+1,z+1),h=index(x+1,y+1,z+1)
   display_tetrahedra.push([a,b,d,h],[a,d,c,h],[a,c,g,h],[a,g,e,h],[a,e,f,h],[a,f,b,h])
  }
  Object.assign(data,{sampling:{layout:'octree',sample_count:n**3,minimum_cell_width_nm:4/(n-1),maximum_cell_width_nm:4/(n-1)},sample_positions_nm,display_tetrahedra,cell_sizes_nm:sample_positions_nm.map(()=>[4/(n-1),4/(n-1),4/(n-1)])})
  // Run the real panel against an already-computed display fixture.
  const feature=initEMAnalysis({scene,store:{getState:()=>({}),subscribe:()=>()=>{}},
   nanoparticleSubsystem:{getQuenchingParticles:()=>[{id:'fixture',kind:'gold_nanosphere',diameter_nm:20,pos:new T.Vector3()}]},
   api:{_request:async()=>data}})
  feature.open();const panel=document.querySelector('#em-analysis-panel')
  if(panel.querySelector('[data-minimum]').value!=='3')throw new Error('Default cutoff must be 3')
  panel.querySelector('[data-run]').click();await new Promise(r=>setTimeout(r,20))
  // Include the weak 1x foreground to exercise hotspot visibility, not only clipping.
  panel.querySelector('[data-minimum]').value='1'
  const select=panel.querySelector('[data-mode]');select.value='smooth';select.dispatchEvent(new Event('input'))
  panel.style.display='none'
  const root=scene.getObjectByName('experimental-em-field'),meshes=root.children.filter(o=>o.isMesh),initial=meshes.length
  if(!initial)throw new Error('Panel did not display smooth field')
  const mode=createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
  let session
  try{
   mode.activate()
   const preserved=meshes.every(m=>m.userData.emVolume&&m.material.isShaderMaterial&&m.material.opacity>0)
   let canvas
   if(backend==='raster'){renderer.render(scene,camera);canvas=renderer.domElement}
   else{
    mode.setPathTracing(true);mode.setPathTraceSamples(8);mode.setPathTraceExportBackend(backend)
    session=mode.beginFrameSession(96,96);canvas=await session.renderFrameToCanvas()
   }
   const copy=document.createElement('canvas');copy.width=canvas.width;copy.height=canvas.height;copy.getContext('2d').drawImage(canvas,0,0)
   document.body.append(copy)
   const pixels=copy.getContext('2d').getImageData(0,0,copy.width,copy.height).data
   let colored=0;for(let i=0;i<pixels.length;i+=4)if(Math.max(pixels[i],pixels[i+1],pixels[i+2])-Math.min(pixels[i],pixels[i+1],pixels[i+2])>20)colored++
   const center=(Math.floor(copy.height/2)*copy.width+Math.floor(copy.width/2))*4
   const hot=Array.from(pixels.slice(center,center+3))
   if(hot[0]<=hot[2]+20)throw new Error(`Hotspot obscured by weak blue foreground: ${hot}`)
   panel.querySelector('[data-minimum]').value='101';panel.querySelector('[data-minimum]').dispatchEvent(new Event('input'))
   const empty=root.children.filter(o=>o.isMesh).length
   if(session)await session.renderFrameToCanvas()
   return {initial,preserved,colored,empty}
  }finally{await session?.dispose();mode.deactivate();feature.dispose();receiver.geometry.dispose();receiver.material.dispose();renderer.dispose()}
 },backend)
 await page.screenshot({path:testInfo.outputPath('smooth.png')})
 console.log('SMOOTH_EM',backend,JSON.stringify(result))
 expect(result.initial).toBe(1);expect(result.preserved).toBe(true);expect(result.colored).toBeGreaterThan(100);expect(result.empty).toBe(0);expect(errors).toEqual([])
})

test('direct volume clips to opaque depth, supports orthographic/inside views and linear crossfades',async({page})=>{
 await page.route('**/em-volume-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
 await page.goto('/em-volume-fixture')
 const result=await page.evaluate(async()=>{
  const T=await import('/node_modules/.vite/deps/three.js'),{createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const scene=new T.Scene(),camera=new T.OrthographicCamera(-1,1,1,-1,.01,20);camera.position.set(.2,.2,3);camera.lookAt(.2,.2,0)
  const renderer=new T.WebGLRenderer({preserveDrawingBuffer:true});renderer.setSize(64,64);renderer.setClearColor(0x000000)
  const target=new T.WebGLRenderTarget(64,64,{type:T.FloatType}),overlay=createEMFieldOverlay(scene)
  const data={sampling:{layout:'octree'},sample_positions_nm:[[1,0,0],[0,1,0],[0,0,1],[0,0,0]],display_tetrahedra:[[0,1,2,3]],intensity:[100,100,100,100],outside:[1,1,1,1],cell_sizes_nm:Array(4).fill([1,1,1]),shape:[4,1,1],lower_nm:[0,0,0],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]]}
  const options={mode:'smooth',minimum:3,colormap:'gray'}
  const read=()=>{renderer.setRenderTarget(target);renderer.render(scene,camera);const p=new Float32Array(4);renderer.readRenderTargetPixels(target,32,32,1,1,p);return p[0]}
  const occluder=new T.Mesh(new T.PlaneGeometry(4,4),new T.MeshBasicMaterial({color:0x000000}));occluder.position.z=2
  try{
   overlay.show(data,options);const full=read();const mesh=scene.children[0].children.find(o=>o.userData.emVolume),integrations=mesh.userData.emVolumeIntegrations;overlay.weight(.5);const half=read();const retained=mesh.userData.emVolumeIntegrations===integrations
   overlay.showTransition(data,{...data},.37,options);const crossfade=read()
   scene.add(occluder);const blocked=read();scene.remove(occluder)
   overlay.show(data,options);camera.position.z=.3;camera.lookAt(.2,.2,-1);const inside=read()
   const normal=new T.MeshNormalMaterial();scene.overrideMaterial=normal;const normalPass=read();scene.overrideMaterial=null;normal.dispose()
   return {full,half,crossfade,blocked,inside,retained,normalPass}
  }finally{overlay.dispose();target.dispose();occluder.geometry.dispose();occluder.material.dispose();renderer.dispose()}
 })
 expect(result.retained).toBe(true);expect(result.normalPass).toBe(0)
 expect(result.full).toBeGreaterThan(.05);expect(result.half).toBeCloseTo(result.full/2,5)
 expect(result.crossfade).toBeCloseTo(result.full,5);expect(result.blocked).toBe(0)
 expect(result.inside).toBeGreaterThan(.02);expect(result.inside).toBeLessThan(result.full)
})
