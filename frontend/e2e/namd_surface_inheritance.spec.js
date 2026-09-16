import {test,expect} from '@playwright/test'
import fs from 'node:fs'
test.use({viewport:{width:1280,height:900},deviceScaleFactor:.5})
test('inherited, restored and refreshed surface jobs actually render when View surface is on',async({page,request})=>{
 test.setTimeout(360000)
 const fixture=new URL('../../workspace/cube_pore.nadoc',import.meta.url)
 test.skip(!fs.existsSync(fixture),'Requires cube_pore.nadoc')
 let jobs=[]
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.message)})
 page.on('console',m=>{if(m.type()==='error')console.log('BROWSER',m.text())})
 await page.addInitScript(()=>{localStorage.setItem('nadoc:md-jobs-show-all','1');localStorage.setItem('nadoc.grapheneDisplay',JSON.stringify({visible:false,representation:'plane'}))})
 await page.route('**/api/md/jobs',r=>r.fulfill({json:jobs}))
 await page.route('**/api/md/jobs/*',r=>{const id=new URL(r.request().url()).pathname.split('/').at(-1);return r.fulfill({json:jobs.find(j=>j.job_id===id)||{}})})
 await page.route('**/api/md/protocol-box-preview',r=>r.fulfill({json:{warnings:['Preview deferred for surface test']}}))
 console.log('start')
 await page.goto('/?doc=__e2e__surface-inheritance')
 await page.waitForFunction(()=>window.__nadocTest)
 await page.evaluate(async content=>{
  const api=await import('/src/api/client.js');await api.importDesign(content)
  document.getElementById('welcome-screen')?.classList.add('hidden')
  document.getElementById('left-panel')?.classList.remove('locked-hidden','hidden')
  document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b=>b.disabled=false)
  window.__leftSidebar?.refresh?.()
 },fs.readFileSync(fixture,'utf8'))
 console.log('import complete')
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.locator('#md-surface-toggle').evaluate(el=>{if(document.getElementById('md-surface-body').style.display==='none')el.click()})
 await page.locator('#md-hard-surface-settings').evaluate(el=>el.open=true)
 const base={design_name:'cube_pore',design_source_path:'cube_pore.nadoc',status:'draft',created_at:1,segments:[],protocol:'equilibrium_aware_namd',execution_target:'local'}
 const parent={...base,job_id:'surface-parent',prep_params:{graphene_nanopore:true,graphene_pore_diameter_nm:8,graphene_surface_axis:'-z'}}
 jobs=[parent,{...base,job_id:'surface-child',parent_job_id:parent.job_id,prep_params:null,run_kind:'production',created_at:2}]
 // The same automatic selection used after creation/production; no explicit row authorization.
 await page.evaluate(async()=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob('surface-child')})
 const info=()=>page.evaluate(()=>{const m=window.__nadocScene.getObjectByName('Graphene nanopore preview');return m&&{visible:m.visible,uuid:m.uuid}})
 await expect.poll(async()=>(await info())?.visible).toBe(false)
 await page.locator('#md-graphene-show').check()
 await expect.poll(async()=>(await info())?.visible).toBe(true)
 await page.evaluate(async()=>{
  const THREE=await import('/node_modules/three/build/three.module.js')
  const box=new THREE.Box3(),t=window.__nadocTest
  for(const entry of t.getDesignRenderer().getBackboneEntries())box.expandByPoint(entry.pos)
  const c=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length()
  t.applyCameraPoseForTest({target:c.toArray(),position:c.clone().add(new THREE.Vector3(size,-size,size)).toArray()})
 })
 async function rendered(){
  const result=await page.evaluate(()=>{
   const t=window.__nadocTest,m=window.__nadocScene.getObjectByName('Graphene nanopore preview')
   const visible=m?.visible,on=t.renderedPixelCensus().pixelHash
   if(m)m.visible=false
   const off=t.renderedPixelCensus().pixelHash
   if(m)m.visible=visible
   return {visible,on,off}
  })
  expect(result.visible).toBe(true);expect(result.on).not.toBe(result.off)
 }
 for(const representation of ['plane','ball','stick']){
  await page.selectOption('#md-graphene-representation',representation);await rendered()
  await page.uncheck('#md-graphene-show');await expect.poll(async()=>(await info())?.visible).toBe(false)
  await page.check('#md-graphene-show');await rendered()
 }
 // Closed charged wall, multilayer opposite axis, and own-package descriptor without its ancestor.
 for(const prep of [
  {graphene_nanopore:true,graphene_pore_diameter_nm:0,graphene_charge_density_C_m2:.1,graphene_surface_axis:'-z'},
  {graphene_nanopore:true,graphene_pore_diameter_nm:4,graphene_layers:3,graphene_surface_axis:'+y'},
 ]){
  jobs=[{...base,job_id:'orphan',parent_job_id:'missing',surface_prep_params:prep}]
  await page.evaluate(async()=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob('orphan')})
  await page.selectOption('#md-graphene-representation','plane');await rendered()
  const id=(await info()).uuid
  await page.evaluate(()=>window.__nadocMdPanel.refresh())
  expect((await info()).uuid).toBe(id);await rendered()
 }
 await page.click('.engine-selector-btn[data-engine="oxdna"]')
 await expect.poll(async()=>!!(await info())?.visible).toBe(false)
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.evaluate(()=>window.__nadocMdPanel.selectJob('orphan'))
 await rendered()
 // An enabled trajectory transport with no replacement frame must not hide the wall.
 await page.evaluate(()=>window.__nadocMdPanel.trajectorySolvent.setEnabled(true))
 await rendered()
 await page.evaluate(()=>window.__nadocMdPanel.trajectorySolvent.setEnabled(false))
 jobs=[{...base,job_id:'plain',prep_params:{}}]
 await page.evaluate(async()=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob('plain')})
 await expect.poll(async()=>!!(await info())?.visible).toBe(false)
 console.log('graphene scenarios complete')
 const peg={schema:'nadoc.namd_peg_review.v1',title:'PEG walls',note:'Saved initial configuration',job_id:'peg-wall',stage:'resident',
  coordinates_nm:[[1,1,.4],[1,1,.5]],elements:['C','H'],bonds:[[0,1]],peg_indices:[0,1],anchor_indices:[0],atoms:2,
  slit:{box_nm:[4.8,4.8,4.8],inset_nm:.2},jobs:[],frames:[]}
 await page.route('**/api/md/peg-qualifications/**',r=>r.fulfill({json:peg}))
 jobs=[{...base,job_id:'peg-wall',run_kind:'peg_wall_qualification'}]
 await page.evaluate(async()=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob('peg-wall')})
 await expect.poll(()=>page.evaluate(()=>{const g=window.__nadocScene.getObjectByName('NAMD PEG qualification');return g?.visible && g.children.filter(n=>n.name==='NAMD PEG hard surface' && n.visible).length})).toBe(2)
 await page.evaluate(()=>window.__nadocTest.applyCameraPoseForTest({target:[2.4,2.4,2.4],position:[9,-9,9]}))
 const pegHash=()=>page.evaluate(()=>window.__nadocTest.renderedPixelCensus().pixelHash)
 const pegOn=await pegHash()
 await page.uncheck('#md-graphene-show')
 expect(await pegHash()).not.toBe(pegOn)
 await page.check('#md-graphene-show')
 await expect.poll(()=>page.evaluate(()=>window.__nadocScene.getObjectByName('NAMD PEG qualification').children.filter(n=>n.name==='NAMD PEG hard surface').every(n=>n.visible))).toBe(true)
 expect(errors).toEqual([])
 await page.close();await request.delete('/api/documents/__e2e__surface-inheritance')
})
