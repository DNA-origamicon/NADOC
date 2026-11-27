import {test,expect} from '@playwright/test'

// Real Appearance panel/controller, empty graphics scene. No documents, jobs,
// downloads or persistent exports. Context teardown releases browser state;
// the configured reporter/global teardown remove reports and isolated bridge keys.
test('Advanced trace controls preserve drafts, step powers of two and fit the sidebar',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/photo-controls-check',r=>r.fulfill({contentType:'text/html',body:'<html><body></body></html>'}))
  await page.goto('/photo-controls-check')
  await page.evaluate(async()=>{
    const html=new DOMParser().parseFromString(await(await fetch('/')).text(),'text/html')
    for(const style of html.querySelectorAll('style,link[rel="stylesheet"]')){
      if(style.href?.includes('google'))continue
      document.head.append(style.cloneNode(true))
    }
    const panel=html.getElementById('photo-settings');panel.disabled=false
    panel.style.cssText='width:280px;position:absolute;left:0;top:0;bottom:0;overflow:auto'
    document.body.append(panel)
    const THREE=await import('/node_modules/three/build/three.module.js')
    const {createPhotoMode}=await import('/src/scene/photo_mode.js')
    const {initPhotoPanel}=await import('/src/ui/photo_panel.js')
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.1,100),renderer=new THREE.WebGLRenderer()
    renderer.setSize(64,64);camera.position.z=8
    const mode=createPhotoMode({scene,camera,renderer,setRenderFn(){},resetRenderFn(){},setResizeCallback(){},clearResizeCallback(){}})
    const ui=initPhotoPanel(mode);mode.activate();ui.onEnter()
    window.__controls={mode,ui,renderer}
  })
  await expect(page.locator('#photo-path-tracing')).not.toBeChecked()
  await page.locator('#photo-advanced summary').click()
  const denoise=page.locator('#photo-trace-denoise')
  await expect(denoise).toBeChecked();await denoise.uncheck()
  expect(await page.evaluate(()=>window.__controls.mode.getSettings().pathTraceDenoise)).toBe(false)
  await page.waitForTimeout(350)
  await page.evaluate(()=>{window.__controls.mode.setTraceDenoise(true);window.__controls.ui.applyActiveProfile()})
  await expect(denoise).not.toBeChecked()
  expect(await page.evaluate(()=>window.__controls.mode.getSettings().pathTraceDenoise)).toBe(false)
  await denoise.check()
  const interactive=page.locator('#photo-trace-interactive')
  await expect(interactive).toBeChecked()
  await interactive.uncheck()
  expect(await page.evaluate(()=>window.__controls.mode.getSettings().pathTraceInteractive)).toBe(false)
  await interactive.check()
  const preview=page.locator('#photo-trace-preview-backend')
  await preview.selectOption('optix')
  await page.waitForTimeout(350)
  await page.evaluate(()=>{window.__controls.mode.setPathTracePreviewBackend('webgl');window.__controls.ui.applyActiveProfile()})
  await expect(preview).toHaveValue('optix')
  expect(await page.evaluate(()=>window.__controls.mode.getSettings().pathTracePreviewBackend)).toBe('optix')
  await preview.selectOption('webgl')
  await expect(page.locator('#photo-trace-metrics,#photo-trace-progress-stages,#photo-trace-progress-label')).toHaveCount(0)
  await expect(page.locator('#photo-path-status')).toHaveCount(1)
  await expect(page.locator('#photo-trace-progress > #photo-path-status')).toHaveCount(1)
  const samples=page.locator('#photo-path-samples')
  const saved=()=>page.evaluate(()=>window.__controls.mode.getSettings().pathTraceSamples)
  await samples.fill('2')
  // Let the real panel's 500 ms refresh run repeatedly while editing.
  await page.waitForTimeout(1100)
  await expect(samples).toHaveValue('2');expect(await saved()).toBe(64)
  await samples.pressSequentially('56',{delay:100})
  await expect(samples).toHaveValue('256');expect(await saved()).toBe(64)
  await samples.press('Enter');expect(await saved()).toBe(256)
  await samples.fill('64');await samples.press('Tab');expect(await saved()).toBe(64)
  await page.getByRole('button',{name:'Increase trace samples'}).click()
  await expect(samples).toHaveValue('128');expect(await saved()).toBe(64)
  await page.getByRole('button',{name:'Increase trace samples'}).click()
  await expect(samples).toHaveValue('256')
  await page.getByRole('button',{name:'Decrease trace samples'}).click()
  await expect(samples).toHaveValue('128')
  await samples.press('ArrowDown');await expect(samples).toHaveValue('64')
  await samples.press('ArrowUp');await samples.press('Enter');expect(await saved()).toBe(128)
  const layout=await page.locator('#photo-advanced').evaluate(el=>({
    labels:[...el.querySelectorAll('.pxr-lbl')].map(l=>({text:l.textContent,fits:l.scrollWidth<=l.clientWidth})),
    overflow:el.scrollWidth>el.clientWidth,
    explanations:el.querySelectorAll('.pxr-note').length,
    controls:[...el.querySelectorAll('.pxr-row')].every(row=>!!row.title),
    backend:el.querySelector('#photo-trace-backend').closest('label').title,
  }))
  expect(layout.labels.every(l=>l.fits)).toBe(true);expect(layout.overflow).toBe(false)
  expect(layout.explanations).toBe(0);expect(layout.controls).toBe(true)
  expect(layout.backend).toContain('independent of the Trace preview')
  await page.locator('#photo-trace-backend').selectOption('webgpu')
  expect(await page.evaluate(()=>window.__controls.mode.getSettings().pathTraceExportBackend)).toBe('webgpu')
  await page.locator('#photo-path-tracing').check()
  expect(await saved()).toBe(128)
  await expect(page.locator('#photo-path-status')).toContainText('0% · Hold the view still')
  await page.evaluate(()=>{const {mode,ui,renderer}=window.__controls;ui.dispose();mode.deactivate();renderer.dispose()})
  expect(errors).toEqual([])
})
