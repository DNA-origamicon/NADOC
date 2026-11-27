import {test,expect} from '@playwright/test'

// Isolated graphics only; no documents or downloads. Worker/scratch is owned by
// the test API lifespan; reporter/global teardown also clean after failures.
test('native hardware preview selects independently, reuses scenes and hands off to export',async({page})=>{
  test.skip(!process.env.NADOC_TEST_OPTIX,'Explicit native GPU check')
  test.setTimeout(180000)
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/native-preview-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/native-preview-check')
  await page.evaluate(async()=>{
    await import('/src/styles/components.css')
    const html=new DOMParser().parseFromString(await(await fetch('/')).text(),'text/html')
    const panel=html.getElementById('photo-settings');panel.disabled=false;document.body.append(panel)
    const T=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js'),{initPhotoPanel}=await import('/src/ui/photo_panel.js')
    const scene=new T.Scene(),camera=new T.PerspectiveCamera(45,1.5,.1,100);camera.position.z=6
    const geometry=new T.SphereGeometry(1,16,12),material=new T.MeshPhysicalMaterial({color:0xdd6655,clearcoat:.5,roughness:.2})
    scene.add(new T.Mesh(geometry,material),new T.AmbientLight(0xffffff,.5))
    const light=new T.DirectionalLight(0xffffff,3);light.position.set(3,4,5);scene.add(light)
    const renderer=new T.WebGLRenderer();renderer.setSize(96,64);document.body.append(renderer.domElement)
    let draw=()=>renderer.render(scene,camera)
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn:fn=>draw=fn,resetRenderFn:()=>draw=()=>renderer.render(scene,camera),setResizeCallback(){},clearResizeCallback(){}})
    const ui=initPhotoPanel(mode);mode.activate();ui.onEnter();mode.setPathTraceSamples(64);mode.setPinLights(true)
    window.__native={mode,ui,camera,renderer,geometry,material,uploads:[],lightUpdates:[],stats:[],deletes:0,startups:0,held:false}
    const original=window.fetch
    window.fetch=async(...args)=>{
      const path=String(args[0]),frame=path.endsWith('/frame')
      if(frame){const body=JSON.parse(await args[1].body.text());window.__native.uploads.push(body.reuse_scene===true);window.__native.lightUpdates.push(body.reuse_scene===true&&Array.isArray(body.lights))}
      const response=await original(...args)
      // Reproduce the old leak: the server allocated its worker but the
      // frontend has not yet consumed the startup acknowledgement/ID.
      if(path.endsWith('/session')&&response.ok&&++window.__native.startups===1){
        window.__native.held=true
        await new Promise(resolve=>window.__native.releaseStartup=resolve)
      }
      if(frame&&response.ok&&window.__native.holdNextFrame){
        window.__native.holdNextFrame=false;window.__native.frameHeld=true
        await new Promise(resolve=>window.__native.releaseFrame=resolve)
      }
      if(frame&&response.ok)window.__native.stats.push(JSON.parse(response.headers.get('X-NADOC-Render-Stats')))
      if(args[1]?.method==='DELETE'&&response.ok)window.__native.deletes++
      return response
    }
    const animate=()=>{draw();window.__native.raf=requestAnimationFrame(animate)};animate()
  })
  await page.locator('#photo-advanced > summary').click()
  await page.locator('#photo-trace-preview-backend').selectOption('optix')
  await page.locator('#photo-path-tracing').check()
  await page.waitForFunction(()=>window.__native.held,null,{timeout:30000})
  await expect(page.locator('#photo-trace-spinner')).toBeVisible()
  await expect(page.locator('#photo-trace-progress-bar')).toHaveJSProperty('value',0)
  expect(await page.locator('#photo-trace-spinner').evaluate(el=>getComputedStyle(el).animationName)).toBe('nadoc-spin')
  await page.locator('#photo-path-tracing').uncheck()
  await expect(page.locator('#photo-trace-spinner')).toBeHidden()
  await page.locator('#photo-path-tracing').check()
  await page.evaluate(()=>window.__native.releaseStartup())
  const settled=async()=>{
    await page.waitForFunction(()=>{const s=window.__native.mode.getPathTracingStatus();return s.samples===64||s.error},null,{timeout:90000})
    expect(await page.evaluate(()=>window.__native.mode.getPathTracingStatus())).toMatchObject({backend:'optix',samples:64,error:''})
  }
  await settled()
  await expect(page.locator('#photo-trace-progress-bar')).toHaveJSProperty('value',100)
  await expect(page.locator('#photo-trace-spinner')).toBeHidden()
  expect(await page.evaluate(()=>window.__native.mode.getPathTracingStatus().work.stages.every(row=>row.state==='complete'))).toBe(true)
  expect(await page.evaluate(()=>window.__native.deletes)).toBeGreaterThanOrEqual(1)
  const first=await page.evaluate(()=>({status:window.__native.mode.getPathTracingStatus(),uploads:window.__native.uploads}))
  expect(first.uploads[0]).toBe(false);expect(first.uploads.slice(1).every(Boolean)).toBe(true);expect(first.uploads.length).toBeGreaterThan(3);expect(first.status.diagnostics.device).toMatch(/NVIDIA|RTX|GeForce/)
  await page.evaluate(()=>{window.__native.holdNextFrame=true;window.__native.camera.position.x=.5;window.__native.camera.lookAt(0,0,0)})
  await expect.poll(()=>page.evaluate(()=>window.__native.uploads.length),{timeout:30000}).toBeGreaterThan(2)
  await page.waitForFunction(()=>window.__native.frameHeld)
  await expect(page.locator('#photo-trace-spinner')).toBeVisible()
  const warm=await page.evaluate(()=>window.__native.mode.getPathTracingStatus().work)
  expect(warm.fraction).toBeLessThan(1)
  expect(warm.stages.filter(row=>row.state==='reused').map(row=>row.id)).toEqual(['device','snapshot','environment','upload','decode','geometry'])
  await page.locator('#photo-path-samples').fill('128')
  await page.locator('#photo-path-samples').press('Enter')
  await expect.poll(()=>page.evaluate(()=>window.__native.mode.getPathTracingStatus().work.fraction)).toBe(0)
  await page.locator('#photo-path-samples').fill('64')
  await page.locator('#photo-path-samples').press('Enter')
  const deletes=await page.evaluate(()=>window.__native.deletes)
  await page.evaluate(()=>{window.__native.camera.position.x=.6;window.__native.camera.lookAt(0,0,0)})
  await expect.poll(()=>page.evaluate(()=>window.__native.mode.getPathTracingStatus().state)).toBe('updating')
  await page.waitForTimeout(500)
  expect(await page.evaluate(()=>window.__native.deletes)).toBe(deletes)
  await page.evaluate(()=>window.__native.releaseFrame())
  await settled()
  await expect(page.locator('#photo-trace-progress-bar')).toHaveJSProperty('value',100)
  await expect(page.locator('#photo-trace-spinner')).toBeHidden()
  const reused=await page.evaluate(()=>window.__native.stats.at(-1).scene_reused)
  expect(reused).toBe(true)
  expect(await page.evaluate(()=>window.__native.lightUpdates.filter(Boolean).length)).toBe(2)
  // Different export dimensions force worker release/reacquisition, not cached
  // image reuse; a second native session must not race the preview's DELETE.
  const exported=await page.evaluate(async()=>{
    const n=window.__native;cancelAnimationFrame(n.raf);n.mode.setPathTraceExportBackend('optix')
    const blob=await n.mode.renderToBlob(80,64)
    return {size:blob.size,stats:n.stats,deletes:n.deletes}
  })
  expect(exported.size).toBeGreaterThan(100);expect(exported.deletes).toBeGreaterThanOrEqual(1)
  console.log('NATIVE_PREVIEW',JSON.stringify({first:first.status,exported}))
  await page.locator('#photo-path-tracing').uncheck()
  await page.evaluate(()=>{const n=window.__native;cancelAnimationFrame(n.raf);n.ui.dispose();n.mode.deactivate();n.geometry.dispose();n.material.dispose();n.renderer.dispose()})
  expect(errors).toEqual([])
})
