import {test,expect} from '@playwright/test'

// Optical/display fixtures only: no NADOC structures, jobs, workspace files or
// persistent outputs. Blob URLs are revoked; browser downloads use its disposable
// context. Playwright's reporter removes screenshots/traces on success or failure.
test('EM glow and illumination survive PNG tiling and deterministic video export',async({page})=>{
 test.setTimeout(120000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 await page.route('**/em-photo-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
 await page.goto('/em-photo-fixture')
 const result=await page.evaluate(async()=>{
  const THREE=await import('/node_modules/three/build/three.module.js')
  const {createPhotoMode}=await import('/src/scene/photo_mode.js')
  const {createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const {registerEMExport}=await import('/src/scene/em_export.js')
  const {exportPhotoVideo}=await import('/src/scene/export_video.js')
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,4/3,.1,100)
  camera.position.set(0,0,18)
  const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setSize(320,240)
  const plane=new THREE.Mesh(new THREE.PlaneGeometry(10,10),new THREE.MeshPhongMaterial({color:0x888888}))
  plane.position.z=-2;scene.add(plane)
  const data={shape:[2,2,2],lower_nm:[-2,-2,0],upper_nm:[2,2,2],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],
   intensity:[100,100,100,100,100,100,100,100],outside:Array(8).fill(true),polarization_world:[1,0,0],propagation_world:[0,0,1]}
  const blue={...data,intensity:Array(8).fill(.2)}
  const overlay=createEMFieldOverlay(scene),options={mode:'volume',minimum:0,dotSize:12,lighting:'illuminate'}
  overlay.show(data,options)
  const mode=createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
  mode.activate();mode.setBackground('solid','#ffffff')
  const field=scene.getObjectByName('experimental-em-field')
  if(field.children.some(o=>!o.isPoints && o.name!=='em-illumination'))throw new Error('EM direction arrows remain')
  const lights=field.getObjectByName('em-illumination').children
  const visibleLights=lights.filter(l=>l.visible&&l.intensity>0&&!l.castShadow).length
  const pixels=canvas=>{
   const ctx=canvas.getContext('2d'),d=ctx.getImageData(0,0,canvas.width,canvas.height).data
   let red=0,blue=0,purple=0,total=0
   for(let i=0;i<d.length;i+=4){if(d[i]>d[i+1]+5&&d[i]>d[i+2]+5)red++;if(d[i+2]>d[i]+5)blue++;if(d[i]>d[i+1]+2&&d[i+2]>d[i+1]+2)purple++;total+=d[i]+d[i+1]+d[i+2]}
   return {red,blue,purple,total}
  }
  async function capture(width,height){
   const blob=await mode.renderToBlob(width,height),bmp=await createImageBitmap(blob)
   const c=document.createElement('canvas');c.width=320;c.height=240
   c.getContext('2d').drawImage(bmp,0,0,320,240);bmp.close()
   return pixels(c)
  }
  const lit=await capture(320,240)
  // Suppress only dots to verify the lights actually illuminate geometry.
  for(const child of field.children)if(child.name!=='em-illumination')child.visible=false
  const surfacesLit=await capture(320,240)
  field.getObjectByName('em-illumination').visible=false
  const surfacesUnlit=await capture(320,240)
  for(const child of field.children)child.visible=true
  overlay.show(data,{...options,lighting:'glow'})
  const normal=await capture(320,240)
  const tiled=await capture(4200,3150)
  const restoredSize=field.children.find(o=>o.isPoints).material.size
  let frame=0,prepared=0
  const unregister=registerEMExport(scene,async()=>{
   await Promise.resolve();prepared++
   if(frame===0)overlay.show(data,{...options,lighting:'glow'})
   else if(frame===1)overlay.show(blue,{...options,lighting:'glow'})
   else overlay.showTransition(data,blue,.5,{...options,lighting:'glow'})
  })
  const captures=[],realBegin=mode.beginFrameSession
  const photoRenderer={beginFrameSession(...args){const s=realBegin(...args);return {...s,renderFrameToCanvas(){const c=s.renderFrameToCanvas();captures.push(pixels(c));return c}}}}
  let savedBlob
  const click=HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click=function(){savedBlob=fetch(this.href).then(r=>r.blob())}
  try {
   const player={play:async()=>{},pause(){},stop(){},getTotalDuration:()=>1,seekTo(t){frame=Math.round(t*2)},settleFrame:async()=>true}
   await exportPhotoVideo({animation:{name:'EM fixture'},player,photoRenderer,width:320,height:240,options:{format:'gif',fps:2}})
  } finally {HTMLAnchorElement.prototype.click=click;unregister()}
  const blob=await savedBlob
  const decoder=new ImageDecoder({data:await blob.arrayBuffer(),type:'image/gif'})
  await decoder.tracks.ready
  const decoded=[]
  for(let i=0;i<decoder.tracks.selectedTrack.frameCount;i++){
   const {image}=await decoder.decode({frameIndex:i})
   const c=document.createElement('canvas');c.width=320;c.height=240;c.getContext('2d').drawImage(image,0,0)
   decoded.push(pixels(c));image.close()
  }
  decoder.close()
  // Modest optical-only benchmark. Explicit GPU completion prevents measuring
  // only command submission; no real point light is allocated per sample.
  const dense={...data,shape:[100000],sampling:{layout:'octree'},sample_positions_nm:[],cell_sizes_nm:[],intensity:[],outside:[]}
  for(let i=0;i<100000;i++){dense.sample_positions_nm.push([(i%100)/25-2,(Math.floor(i/100)%100)/25-2,Math.floor(i/10000)/5]);dense.cell_sizes_nm.push([.04,.04,.2]);dense.intensity.push(2+i%100);dense.outside.push(true)}
  const timings={}
  for(const lighting of ['off','glow','illuminate']){
   overlay.show(dense,{...options,lighting});renderer.render(scene,camera);renderer.getContext().finish()
   const samples=[]
   for(let i=0;i<5;i++){const start=performance.now();renderer.render(scene,camera);renderer.getContext().finish();samples.push(performance.now()-start)}
   timings[lighting]=samples.sort((a,b)=>a-b)[2]
  }
  overlay.clear();const remaining=field.children.length
  mode.deactivate();overlay.dispose();renderer.dispose();plane.geometry.dispose();plane.material.dispose()
  return {lit,normal,tiled,surfacesLit,surfacesUnlit,restoredSize,visibleLights,prepared,captures,decoded,remaining,timings}
 })
 console.log('EM_EXPORT',JSON.stringify(result))
 expect(errors).toEqual([])
 expect(result.visibleLights).toBeGreaterThan(0)
 expect(result.surfacesLit.total).toBeGreaterThan(result.surfacesUnlit.total+1000)
 expect(result.normal.red).toBeGreaterThan(100)
 expect(result.tiled.red/result.normal.red).toBeGreaterThan(.65)
 expect(result.tiled.red/result.normal.red).toBeLessThan(1.5)
 expect(result.restoredSize).toBe(12)
 expect(result.prepared).toBe(3)
 expect(result.decoded).toHaveLength(3)
 expect(result.decoded[0].red).toBeGreaterThan(50)
 expect(result.decoded[1].blue).toBeGreaterThan(result.decoded[0].blue+50)
 // The low-opacity volume blend is visible before encoding. GIF's RGB565
 // quantization can merge its faint purple with the gray background; decoded
 // endpoint hue checks above cover palette refresh without treating GIF as lossless.
 expect(result.captures[2].purple).toBeGreaterThan(10)
 expect(result.remaining).toBe(0)
})
