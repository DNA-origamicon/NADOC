import {test,expect} from '@playwright/test'
import fs from 'node:fs'
test.use({viewport:{width:1280,height:900},deviceScaleFactor:0.5})
test('cube pore surface setup creates a draft promptly',async({page,request})=>{
 test.setTimeout(180000)
 const pending=new Map()
 page.on('request',r=>pending.set(r,Date.now()))
 page.on('response',r=>{if(r.url().includes('/api/') && /protocol|md\/jobs|presets|geometry/.test(r.url()))console.log(r.status(),Date.now()-pending.get(r.request()),r.url())})
 page.on('pageerror',e=>console.log('PAGE ERROR',e.message))
 const fixture=new URL('../../workspace/cube_pore.nadoc',import.meta.url)
 test.skip(!fs.existsSync(fixture),'Requires cube_pore.nadoc')
 await page.goto('/?doc=__e2e__surface-preview')
 await page.waitForFunction(()=>window.__nadocTest)
 await page.evaluate(async content=>{
  const api=await import('/src/api/client.js')
  await api.importDesign(content)
  document.getElementById('welcome-screen')?.classList.add('hidden')
  document.getElementById('left-panel')?.classList.remove('locked-hidden','hidden')
  document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b=>b.disabled=false)
  window.__leftSidebar?.refresh?.()
 },fs.readFileSync(fixture,'utf8'))
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.click('#md-surface-toggle')
 await page.waitForTimeout(1500)
 await page.evaluate(()=>window.__nadocMdPanel.deselectJob())
 expect(await page.evaluate(()=>window.__nadocMdPanel.getSelectedJob())).toBeNull()
 // A hidden previous membrane and an old solvent display must not hide new setup.
 await page.evaluate(()=>{
  const show=document.getElementById('md-graphene-show')
  show.checked=false;show.dispatchEvent(new Event('change'))
  window.__nadocMdPanel.trajectorySolvent.setEnabled(true)
 })
 await page.check('#md-surface-enable')
 await expect.poll(()=>page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview')?.visible)).toBe(true)
 await page.evaluate(()=>window.__previewId=window.__nadocScene.getObjectByName('Graphene nanopore preview').uuid)
 await page.evaluate(async()=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.refresh()})
 expect(await page.evaluate(()=>window.__nadocScene.getObjectByName('Graphene nanopore preview')?.uuid)).toBe(await page.evaluate(()=>window.__previewId))
 const pixels=await page.evaluate(async()=>{
  const THREE=await import('/node_modules/three/build/three.module.js')
  const t=window.__nadocTest,box=new THREE.Box3()
  for(const entry of t.getDesignRenderer().getBackboneEntries())box.expandByPoint(entry.pos)
  const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length()
  t.applyCameraPoseForTest({target:center.toArray(),position:center.clone().add(new THREE.Vector3(size,-size,size)).toArray()})
  const mesh=window.__nadocScene.getObjectByName('Graphene nanopore preview')
  const on=t.renderedPixelCensus().visible
  mesh.visible=false
  const off=t.renderedPixelCensus().visible
  mesh.visible=true
  return {on,off}
 })
 expect(pixels.on).toBeGreaterThan(pixels.off+100)
 // Hold the optional estimate pending to verify it cannot block draft creation.
 let releaseEstimate
 const estimateGate=new Promise(resolve=>releaseEstimate=resolve)
 await page.route('**/api/md/protocol-box-preview',async route=>{await estimateGate;await route.fulfill({json:{warnings:['Deferred for draft test']}})})
 await page.locator('#md-nanopore-settings > summary').click()
 await page.fill('#md-surface-pore-diameter','3')
 await page.click('#md-jobs-new-btn')
 const modal=page.locator('.modal--wizard')
 await modal.getByRole('tab',{name:/What each stage runs/}).click()
 const create=modal.getByRole('button',{name:'Create job',exact:true})
 await expect(create).toBeEnabled({timeout:15000})
 const response=page.waitForResponse(r=>r.url().endsWith('/api/md/jobs') && r.request().method()==='POST')
 await create.click()
 const result=await response,job=await result.json()
 console.log('created',result.status(),job.job_id,job.detail)
 expect(result.ok()).toBe(true)
 try {await expect(modal).not.toBeVisible({timeout:15000});expect(job.status).toBe('draft');expect(job.prep_params.graphene_nanopore).toBe(true);expect(job.prep_params.graphene_pore_diameter_nm).toBe(3)}
 finally {releaseEstimate();if(job.job_id)await request.delete(`/api/md/jobs/${job.job_id}`)}
 await page.close()
 await request.delete('/api/documents/__e2e__surface-preview')
})
