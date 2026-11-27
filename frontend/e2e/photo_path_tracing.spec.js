import {test,expect} from '@playwright/test'
test.use({launchOptions:{args:['--enable-unsafe-webgpu']}})

// Generic rendering primitives and optical samples only. No NADOC structures,
// uploads, jobs or persistent exports. Browser resources die with the context;
// the configured reporter/global teardown clean reports and isolated bridge keys.
test('GPU path tracing includes EM emitters, resets on field changes, exports and turns off',async({page})=>{
  test.setTimeout(180000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  page.on('requestfailed',r=>errors.push(`${r.method()} ${r.url()}: ${r.failure()?.errorText}`))
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
  await page.route('**/photo-trace-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/photo-trace-check')
  await page.evaluate(async()=>{
    const html=new DOMParser().parseFromString(await(await fetch('/')).text(),'text/html')
    const panel=html.getElementById('photo-settings');panel.disabled=false;document.body.append(panel,html.getElementById('op-progress'))
    window.__exportProgress=[];window.addEventListener('nadoc:op-progress',event=>window.__exportProgress.push(event.detail))
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js')
    const {createEMFieldOverlay}=await import('/src/scene/em_field.js')
    const {initPhotoPanel}=await import('/src/ui/photo_panel.js')
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.1,100)
    const {addTraceGraphics}=await import('/e2e/helpers/trace_graphics_fixture.js')
    const disposeGraphics=addTraceGraphics(THREE,scene)
    camera.position.set(0,0,8)
    const renderer=new THREE.WebGLRenderer({alpha:true,preserveDrawingBuffer:true});renderer.setSize(96,96);document.body.append(renderer.domElement)
    const surface=new THREE.Mesh(new THREE.SphereGeometry(.7,12,8),new THREE.MeshStandardMaterial({color:0xcccccc,metalness:1,roughness:.1}))
    surface.position.z=-1;surface.userData.photoMaterialKind='gold-nanoparticle';scene.add(surface)
    const overlay=createEMFieldOverlay(scene),data={shape:[2,2,2],lower_nm:[-1,-1,0],upper_nm:[1,1,1],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity:Array(8).fill(100),outside:Array(8).fill(true)}
    const options={mode:'volume',minimum:0,dotSize:16,lighting:'glow',opacity:1}
    overlay.show(data,options)
    // Render opaque emitters to make the low-sample GPU regression deterministic.
    const cloud=scene.getObjectByName('experimental-em-field').children.find(o=>o.isPoints);cloud.material.opacity=1
    let draw=()=>renderer.render(scene,camera)
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn:fn=>draw=fn,resetRenderFn:()=>draw=()=>renderer.render(scene,camera),setResizeCallback(){},clearResizeCallback(){}})
    const ui=initPhotoPanel(mode);mode.activate();ui.onEnter();mode.setPathTraceSamples(4);mode.setExportSize(64,64)
    const animate=()=>{draw();window.__traceRAF=requestAnimationFrame(animate)};animate()
    window.__trace={mode,ui,scene,camera,renderer,overlay,data,options,cloud,disposeGraphics}
  })
  await page.locator('#photo-path-tracing').check()
  await expect.poll(()=>page.evaluate(()=>window.__trace.mode.getPathTracingStatus()),{timeout:120000}).toMatchObject({samples:4,emSamples:8,state:'tracing',error:''})
  await expect(page.locator('#photo-trace-progress-bar')).toHaveJSProperty('value',100)
  await expect(page.locator('#photo-trace-spinner')).toBeHidden()
  const result=await page.evaluate(async()=>{
    cancelAnimationFrame(window.__traceRAF) // isolate offline exports from unrelated preview rebuilding
    const {mode,overlay,data,options,renderer,cloud}=window.__trace
    const sample=async(video=false)=>{
      const canvas=Object.assign(document.createElement('canvas'),{width:64,height:64}),ctx=canvas.getContext('2d')
      if(video){
        const {photoVideoFrame}=await import('/src/scene/export_video.js')
        const session=mode.beginFrameSession(64,64,{followMotion:true})
        try{await photoVideoFrame({player:{seekTo(){},settleFrame:async()=>true},session,canvas,ctx,w:64,h:64})(0)}finally{await session.dispose()}
      }else{
        const bitmap=await createImageBitmap(await mode.renderToBlob(64,64));ctx.drawImage(bitmap,0,0);bitmap.close()
      }
      const pixels=ctx.getImageData(0,0,64,64).data;let red=0,blue=0
      for(let i=0;i<pixels.length;i+=4){if(pixels[i]>pixels[i+1]+15&&pixels[i]>pixels[i+2]+15)red++;if(pixels[i+2]>pixels[i]+15)blue++}
      return {red,blue}
    }
    const previewProgress=[],previewSession=mode.beginFrameSession(96,96,{onProgress:p=>previewProgress.push(p)})
    let previewReuse
    try{
      const canvas=await previewSession.renderFrameToCanvas()
      const pixels=canvas.getContext('2d').getImageData(0,0,96,96).data
      previewReuse={...previewSession.getDiagnostics(),colored:Array.from(pixels).some((v,i)=>i%4!==3&&v>0)}
    }finally{await previewSession.dispose()}
    const red=await sample()
    const button=document.getElementById('photo-export-btn');button.click()
    while(button.disabled)await new Promise(resolve=>setTimeout(resolve,10))
    const imageProgress=window.__exportProgress

    overlay.show({...data,intensity:Array(8).fill(.2)},options);cloud.material.opacity=1
    const blue=await sample(true)
    // Keep one export session across changes: material changes must reuse the
    // tree, position changes refit, and changed sample counts rebuild safely.
    const session=mode.beginFrameSession(64,64)
    let reuse
    try{
      const coldStart=performance.now();await session.renderFrameToCanvas();const coldMs=performance.now()-coldStart,cold=session.getDiagnostics()
      overlay.show({...data,intensity:Array(8).fill(100)},options);cloud.material.opacity=1
      const warmStart=performance.now();await session.renderFrameToCanvas();const warmMs=performance.now()-warmStart
      const colors=session.getDiagnostics()
      cloud.position.x=.25
      await session.renderFrameToCanvas()
      reuse={cold,colors,moved:session.getDiagnostics(),coldMs,warmMs}
    }finally{await session.dispose();cloud.position.x=0}
    const hasWebGPU=!!(await navigator.gpu?.requestAdapter())
    let webgpu=null
    if(hasWebGPU){mode.setPathTraceExportBackend('webgpu');webgpu=await sample(true);mode.setPathTraceExportBackend('webgl')}
    return {red,blue,reuse,previewReuse,previewProgress,imageProgress,hasWebGPU,webgpu,pointSize:cloud.material.size,contextLost:renderer.getContext().isContextLost()}
  })
  expect(result.red.red).toBeGreaterThan(10);expect(result.blue.blue).toBeGreaterThan(10)
  expect(result.blue.red).toBeLessThan(result.red.red)
  expect(result.pointSize).toBe(16);expect(result.contextLost).toBe(false)
  expect(result.imageProgress.some(p=>p.label==='Reusing completed export')).toBe(true)
  expect(result.imageProgress.some(p=>p.label==='Encoding PNG')).toBe(true)
  expect(result.imageProgress.at(-1)).toMatchObject({action:'hide',visible:false})
  expect(result.previewReuse).toMatchObject({reused:'preview',samples:4,colored:true})
  expect(result.previewProgress.some(p=>p.stage==='reused')).toBe(true)
  expect(result.previewProgress.some(p=>p.stage==='denoise')).toBe(true)
  expect(result.reuse.cold).toMatchObject({reused:'export'})
  expect(result.reuse.colors).toMatchObject({builds:1,refits:0,updates:1,environmentBuilds:1})
  expect(result.reuse.moved).toMatchObject({builds:1,refits:1,updates:2})
  console.log('TRACE_BACKEND_CHECK',JSON.stringify(result))
  if(result.hasWebGPU)expect(result.webgpu.red).toBeGreaterThan(10)
  await page.locator('#photo-path-tracing').uncheck()
  expect(await page.evaluate(()=>window.__trace.mode.getPathTracingStatus().state)).toBe('off')
  await page.evaluate(()=>{cancelAnimationFrame(window.__traceRAF);const {ui,mode,overlay,renderer,disposeGraphics}=window.__trace;ui.dispose();mode.deactivate();overlay.dispose();disposeGraphics();renderer.dispose()})
  expect(errors).toEqual([])
})
