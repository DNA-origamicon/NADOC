import {test,expect} from '@playwright/test'
// Graphics-only fixture: real controllers and browser DOM, no authored documents.
test('EM controls and Appearance warning actions',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/em-controls-fixture',r=>r.fulfill({contentType:'text/html',body:'<div id="canvas-area"></div><input id="photo-lighting-enabled" type="checkbox"><fieldset id="photo-settings"></fieldset>'}))
 await page.goto('/em-controls-fixture')
 await page.evaluate(async()=>{
  const T=await import('/node_modules/.vite/deps/three.js')
  const {initEMAnalysis}=await import('/src/ui/em_analysis.js')
  const {initPhotoMode}=await import('/src/scene/photo_mode.js')
  const {registerEMClear,hasEMRenderField}=await import('/src/scene/em_export.js')
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(45,1,.1,1000),renderer=new T.WebGLRenderer()
  renderer.setSize(64,64);camera.position.z=30
  const field=new T.Mesh(new T.BoxGeometry(2,2,2),new T.MeshBasicMaterial());field.userData.emVolume=true
  const store={getState:()=>({}),subscribe:()=>()=>{}}
  const em=initEMAnalysis({scene,store,api:{},nanoparticleSubsystem:{getQuenchingParticles:()=>[]}});em.open()
  const tab=initPhotoMode({store,sceneCtx:{scene,camera,renderer,controls:{target:new T.Vector3(),update(){}},setRenderFn(){},resetRenderFn(){}}})
  const unregister=registerEMClear(scene,()=>scene.remove(field))
  window.fixture={prepare(){tab.exit();scene.add(field);tab.mode.setPathTracing(true)},state:()=>({active:tab.mode.isActive(),tracing:tab.mode.getSettings().pathTracing,field:hasEMRenderField(scene)}),dispose(){tab.exit();em.dispose();unregister();renderer.dispose();field.geometry.dispose();field.material.dispose()}}
 })
 try{
  const run=page.locator('[data-run]'),wave=page.locator('[data-wavelength]')
  expect((await run.boundingBox()).y).toBeLessThan((await wave.boundingBox()).y)
  await wave.fill('650');await wave.press('Tab');await expect(run).toHaveText('Calculate 650 nm map')
  await expect(wave.locator('..')).toHaveAttribute('title',/Johnson/)
  await page.locator('[data-shell]').selectOption('none')
  for(const key of ['oligo-length','persistence','thickness','shell-index'])await expect(page.locator(`[data-${key}]`)).toBeHidden()
  await page.locator('[data-shell]').selectOption('manual');await expect(page.locator('[data-thickness]')).toBeVisible()
  await page.locator('[data-shell]').selectOption('ssdna_wlc');await expect(page.locator('[data-oligo-length]')).toBeVisible()
  for(const choice of ['Cancel','Continue','Clear field','Disable path tracing']){
   await page.evaluate(()=>window.fixture.prepare())
   await page.locator('#photo-lighting-enabled').check()
   const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible()
   await expect(dialog).toContainText('substantially longer')
   await dialog.getByRole('button',{name:choice,exact:true}).click()
   await expect(dialog).toHaveCount(0)
   expect(await page.evaluate(()=>window.fixture.state())).toEqual({active:choice!=='Cancel',tracing:choice!=='Disable path tracing',field:choice!=='Clear field'})
  }
  expect(errors).toEqual([])
 }finally{await page.evaluate(()=>window.fixture.dispose())}
})
