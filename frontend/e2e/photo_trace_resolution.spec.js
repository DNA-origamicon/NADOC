import {test,expect} from '@playwright/test'

// Generic graphics only: no NADOC documents, jobs, exports or persistent captures.
// The configured reporter/global teardown remove reports and bridge credentials.
test('stationary traced preview retains native viewport pixels above 1024',async({page})=>{
  test.setTimeout(120000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/trace-resolution-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/trace-resolution-check')
  await page.evaluate(async()=>{
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js')
    const renderer=new THREE.WebGLRenderer({preserveDrawingBuffer:true});renderer.setSize(1280,64)
    document.body.append(renderer.domElement)
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,20,.1,100);camera.position.z=8
    const mesh=new THREE.Mesh(new THREE.SphereGeometry(1,12,8),new THREE.MeshPhongMaterial({color:0xcccccc}));mesh.name='backboneSpheres';scene.add(mesh)
    let draw
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn:fn=>draw=fn,resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
    mode.activate();mode.setPathTracing(true);mode.setPathTraceSamples(1)
    const frame=()=>{draw();window.__resolutionRAF=requestAnimationFrame(frame)};frame()
    window.__resolution={mode,renderer,mesh,camera}
  })
  await expect.poll(()=>page.evaluate(()=>window.__resolution.mode.getPathTracingStatus()),{timeout:110000}).toMatchObject({samples:1,state:'tracing',error:'',diagnostics:{width:1280,height:64}})
  await page.evaluate(()=>{const {renderer,camera}=window.__resolution;renderer.setSize(2560,64);camera.aspect=40;camera.updateProjectionMatrix()})
  await expect.poll(()=>page.evaluate(()=>window.__resolution.mode.getPathTracingStatus()),{timeout:30000}).toMatchObject({samples:1,state:'tracing',error:'',diagnostics:{width:2560,height:64,tilesX:10,tilesY:10,builds:1}})
  await page.evaluate(()=>{cancelAnimationFrame(window.__resolutionRAF);const {mode,renderer,mesh}=window.__resolution;mode.deactivate();renderer.dispose();mesh.geometry.dispose();mesh.material.dispose()})
  expect(errors).toEqual([])
})
