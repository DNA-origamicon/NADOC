import {test,expect} from '@playwright/test'
// Synthetic display data only; no documents, downloads or native sessions.
// Browser output/bridge cleanup is owned by the standard reporter/teardown.
test('nearly coplanar adaptive cells cannot produce a white polygon',async({page})=>{
 await page.route('**/volume-sliver-fixture',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
 await page.goto('/volume-sliver-fixture')
 const result=await page.evaluate(async()=>{
  const T=await import('/node_modules/.vite/deps/three.js'),{createEMFieldOverlay}=await import('/src/scene/em_field.js')
  const renderer=new T.WebGLRenderer(),target=new T.WebGLRenderTarget(64,64,{type:T.FloatType})
  renderer.setSize(64,64);renderer.setClearColor(0x000000)
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(40,1,.01,10000)
  camera.position.set(11.7,15,10);camera.lookAt(11.7,15,6)
  const overlay=createEMFieldOverlay(scene),pixels=new Float32Array(64*64*4),peaks=[]
  try{
   for(let orientation=0;orientation<12;orientation++)for(const thickness of [1e-6,1e-10,1e-14])for(const grazing of [0,1,10,100,10000]){
    const data={sampling:{layout:'octree'},sample_positions_nm:[[0,0,0],[1,0,0],[1,1,thickness],[0,1,0]],display_tetrahedra:[[0,1,2,3]],intensity:[119,10,3,20],outside:[1,1,1,1],cell_sizes_nm:Array(4).fill([1,1,1]),shape:[4,1,1],lower_nm:[0,0,0],upper_nm:[1,1,1],origin_nm:[11.2,14.5,6],basis:[[1,0,0],[0,1,0],[0,0,1]]}
    const rotation=new T.Matrix4().makeRotationFromEuler(new T.Euler(.13*orientation,.23*orientation,.31*orientation))
    data.basis=[new T.Vector3(1,0,0),new T.Vector3(0,1,0),new T.Vector3(0,0,1)].map(p=>p.applyMatrix4(rotation).toArray())
    const center=new T.Vector3(.5,.5,0).applyMatrix4(rotation).add(new T.Vector3(...data.origin_nm));camera.position.copy(new T.Vector3(grazing,0,1).normalize().multiplyScalar(4).applyMatrix4(rotation).add(center));camera.lookAt(center)
    overlay.show(data,{mode:'smooth',minimum:3});renderer.setRenderTarget(target);renderer.render(scene,camera)
    renderer.readRenderTargetPixels(target,0,0,64,64,pixels)
    peaks.push(Math.max(...pixels.filter((_,i)=>i%4!==3)))
   }
   return peaks
  }finally{overlay.dispose();target.dispose();renderer.dispose()}
 })
 expect(result.every(value=>Number.isFinite(value)&&value<.001),JSON.stringify(result)).toBe(true)
})
