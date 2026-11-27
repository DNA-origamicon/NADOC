import {test,expect} from '@playwright/test'
import {guardNativeLease} from './native_lease_guard.js'
guardNativeLease(test)
// Transient graphics only. Lease + reporter own all scratch; no saved documents.
test('completed EM chunks are drawn and equal the same unsplit sample sequence',async({page})=>{
 test.skip(!process.env.NADOC_TEST_OPTIX,'Explicit native GPU check')
 test.setTimeout(120000)
 await page.route('**/native-chunks-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
 await page.goto('/native-chunks-fixture')
 const result=await page.evaluate(async()=>{
  const T=await import('/node_modules/.vite/deps/three.js')
  const {createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const {createOptixTraceEngine}=await import('/src/scene/photo_renderer/path_trace_optix.js')
  const {createNativeTracePreviewEngine}=await import('/src/scene/photo_renderer/path_trace_native_preview.js')
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(25,1,.01,100)
  camera.position.set(.2,.2,3);camera.lookAt(.2,.2,0);camera.updateMatrixWorld(true)
  const mirror=new T.Mesh(new T.PlaneGeometry(4,4),new T.MeshStandardMaterial({color:0xd4af37,metalness:1,roughness:.16}));scene.add(mirror)
  const overlay=createEMFieldOverlay(scene),renderer=new T.WebGLRenderer({preserveDrawingBuffer:true});renderer.setSize(64,64);document.body.append(renderer.domElement)
  const data={sampling:{layout:'octree'},sample_positions_nm:[[1,0,0],[0,1,0],[0,0,1],[0,0,0]],display_tetrahedra:[[0,1,2,3]],intensity:[100,4,3,100],outside:[1,1,1,1],cell_sizes_nm:Array(4).fill([1,1,1]),shape:[4,1,1],lower_nm:[0,0,0],upper_nm:[1,1,1],origin_nm:[0,0,4],basis:[[1,0,0],[0,1,0],[0,0,1]]}
  overlay.show(data,{mode:'smooth',minimum:3,lighting:'glow'})
  const options={scene,camera,renderer,width:64,height:64,viewHeight:64,settings:{bgColor:'#000000'}}
  let native,preview
  try{
   native=await createOptixTraceEngine(options)
   preview=await createNativeTracePreviewEngine(options,{create:async()=>native})
   const delivered=[],displayed=[],gl=renderer.getContext()
   while(preview.samples<32){
    preview.advance(32)
    while(!preview.ready())await new Promise(r=>setTimeout(r,10))
    delivered.push(preview.samples);preview.draw(null)
    const pixels=new Uint8Array(64*64*4);gl.readPixels(0,0,64,64,gl.RGBA,gl.UNSIGNED_BYTE,pixels)
    displayed.push(pixels.some((v,i)=>i%4!==3&&v>0))
   }
   const chunked=preview.readPixels()
   native.reset(camera,64,64);await native.advance(32);const whole=native.readPixels()
   let difference=0;for(let i=0;i<whole.length;i++)difference=Math.max(difference,Math.abs(whole[i]-chunked[i]))
   native.reset(camera,64,64);await native.advance(512);const reference=native.readPixels()
   const error=p=>p.reduce((sum,v,i)=>sum+(i%4===3?0:(v-reference[i])**2),0)/(64*64*3)
   const error32=error(whole)
   native.reset(camera,64,64);await native.advance(1);const error1=error(native.readPixels())
   return {delivered,displayed,difference,error32,error1}
  }finally{if(preview)await preview.dispose();else await native?.dispose();overlay.dispose();mirror.geometry.dispose();mirror.material.dispose();renderer.dispose()}
 })
 console.log('NATIVE_CHUNKS',JSON.stringify(result))
 expect(result.delivered).toEqual([1,4,8,16,32]);expect(result.displayed.every(Boolean)).toBe(true)
 expect(result.difference).toBeLessThan(.00001);expect(result.error32).toBeLessThan(result.error1*.3)
})
