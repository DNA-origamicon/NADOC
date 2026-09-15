import {readFileSync} from 'node:fs'
import {test,expect} from '@playwright/test'
const API=process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'
const owned=new Set(),pending=[]
test.afterEach(async({request})=>{
 await Promise.allSettled(pending)
 for(const id of owned){expect((await request.delete(`${API}/api/md/jobs/${id}`)).ok()).toBeTruthy();expect((await request.get(`${API}/api/md/jobs/${id}`)).status()).toBe(404)}
 owned.clear();pending.length=0
})
// One __e2e__ document (global teardown), exact draft IDs (afterEach). No native start.
test('electrodes select their protocol and create an immutable empty-system draft',async({page},testInfo)=>{
 page.on('response',r=>{if(r.url().endsWith('/api/md/jobs') && r.request().method()==='POST')pending.push(r.json().then(j=>{if(j.job_id)owned.add(j.job_id)}))})
 await page.goto('/')
 if(process.env.NADOC_SOLVENT_SOURCE){
   const d=JSON.parse(readFileSync(process.env.NADOC_SOLVENT_SOURCE,'utf8'))
   d.metadata.name='__e2e__electrode-protocol';delete d.metadata.identity_last_known_path
   d.loadouts=[];d.active_loadout_id=null
   await page.evaluate(async d=>{
     await (await import('/src/api/client.js')).importDesign(JSON.stringify(d))
     document.getElementById('welcome-screen')?.classList.add('hidden')
     document.getElementById('left-panel')?.classList.remove('locked-hidden','hidden')
     document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(b=>b.disabled=false)
   },d)
 }else{
   await page.locator('#menu-file-new').evaluate(el=>el.click())
   await page.fill('#new-design-name','__e2e__electrode-protocol')
   await page.getByRole('button',{name:'Create',exact:true}).click()
 }
 await expect.poll(()=>page.evaluate(()=>window.__nadocTest.store.getState().currentDesign?.metadata?.name)).toBe('__e2e__electrode-protocol')
 await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
 if(await page.locator('#simulate-body').evaluate(el=>getComputedStyle(el).display==='none'))await page.click('#simulate-heading')
 await page.click('.engine-selector-btn[data-engine="namd"]')
 await page.click('#md-surface-toggle');await page.check('#md-two-electrodes-enable')
 await page.click('#md-box-solvent-toggle');await page.check('#md-box-view-details')
 await expect.poll(()=>page.evaluate(()=>window.__nadocScene.getObjectByName('NAMD box and solvent details')?.visible)).toBe(true)
 const visual=await page.evaluate(()=>{
   const g=window.__nadocScene.getObjectByName('NAMD box and solvent details')
   return {preview:g.userData.preview,labels:g.children.filter(o=>o.name.startsWith('Cell dimension')).map(o=>o.userData.annotation),leader:!!g.getObjectByName('Solvent callout leader')}
 })
 expect(visual.labels).toEqual(['10nm','30nm','10nm']);expect(visual.leader).toBe(true)
 expect(visual.preview.dimensions).toEqual([10,30,10]);expect(visual.preview.solvent).toEqual([10,10,10])
 if(process.env.NADOC_SOLVENT_SOURCE)expect(visual.preview.na).toBe(300)
 await page.screenshot({path:testInfo.outputPath('solvent-only-details.png')})
 await page.click('#md-jobs-new-btn')
 const modal=page.getByRole('dialog')
 await modal.getByRole('tab',{name:/Protocol & settings/}).click()
 await expect(modal.locator('.wizard-preset.is-selected')).toContainText('Electrode relaxation')
 await modal.getByRole('tab',{name:/What each stage runs/}).click()
 const response=page.waitForResponse(r=>r.url().endsWith('/api/md/jobs') && r.request().method()==='POST')
 await modal.getByRole('button',{name:'Create job',exact:true}).click()
 const r=await response,j=await r.json()
 expect(r.ok(),JSON.stringify(j)).toBeTruthy();owned.add(j.job_id)
 expect(j.protocol).toBe('electrode_equilibration_namd')
 expect(j.prep_params.two_electrodes.gap_nm).toBe(10)
 expect(j.prep_params.box_size_nm).toEqual([10,30,10])
 expect(j.prep_params.early_stop_relax).toBe(true)
 if(process.env.NADOC_SOLVENT_SOURCE){expect(j.prep_params.ion_conc_mM).toBe(300);expect(j.prep_params.mg_conc_mM).toBe(0)}
})
