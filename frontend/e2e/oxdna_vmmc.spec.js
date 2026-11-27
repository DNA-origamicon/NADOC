// No molecular authoring. Optional native validation reads the existing duplex;
// only the newly created simulation child is removed in finally. E2E sessions,
// screenshots and reports are removed by the existing global teardown/reporter.
import {test,expect} from '@playwright/test'
import {writeFileSync} from 'node:fs'
test('VMMC wizard create, edit, view and export',async({page},info)=>{
 test.setTimeout(240000)
 const native=!!process.env.NADOC_VMMC_NATIVE
 let createdJobId=null, copiedJobId=null
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/?doc=__e2e__oxdna-vmmc')
 await page.waitForFunction(()=>!!window.__nadocTest)
 try {
 await page.evaluate(async({native,design,parentId})=>{
  const api=await import('/src/api/client.js');window.vapi=api
  let parent={job_id:'parent',status:'completed',salt_concentration:.3,can_seed_production:true,continuation_parameters:{temperature:'298.15K',salt_concentration:.3},run_config:{kind:'relax'}}
  if(native){await api.loadDesign(design);parent=await api.getOxdnaJob(parentId)}
  const {initOxdnaJobWizard}=await import('/src/ui/oxdna_job_wizard.js')
  window.vwizard=initOxdnaJobWizard({getInitialValues:()=>({dna_strand_count:2}),getJobs:()=>[parent],getParentLabels:()=>new Map([[parent.job_id,'Relax 1']]),
   spawnProduction:async(id,payload)=>{window.vpayload=payload;window.vjob=native?await api.appendOxdnaRun(id,{...payload,run_dir:null,submodel:{box:null}}):{job_id:'mock',parent_job_id:id,status:'queued',salt_concentration:.3,run_config:{kind:'run',...payload},stages:[],stage_specs:[]};return window.vjob},
   updateJob:async(id,payload)=>{window.vedited=payload;if(native)window.vjob=await api.updateOxdnaJobSettings(id,payload);return window.vjob}})
  window.vwizard.open()
 },{native,design:process.env.NADOC_VMMC_DESIGN,parentId:process.env.NADOC_VMMC_PARENT})
 const dialog=page.locator('.modal--oxdna-wizard')
 await dialog.getByRole('tab',{name:'Parameters & options',exact:true}).click()
 await dialog.locator('.wizard-mode',{hasText:'Production'}).click()
 await dialog.locator('[data-thermal-field="enabled"]').check()
 await dialog.locator('[data-vmmc-field="enabled"]:visible').check()
 await expect(dialog.locator('[data-thermal-field="enabled"]')).not.toBeChecked()
 await expect(dialog.locator('[data-vmmc-field="production_steps"]')).toHaveValue('2000000000')
 for(const [key,value]of Object.entries({tuning_rounds:2,tuning_steps:10000,equil_steps:10000,production_steps:20000,replicas:3})){
  const input=dialog.locator(`[data-vmmc-field="${key}"]`);await input.fill(String(value));await input.blur()
 }
 await dialog.locator('[data-oxdna-field="dna_concentration_uM"]:visible').fill('12000')
 await page.waitForTimeout(300)
 await page.screenshot({path:info.outputPath('vmmc-desktop.png')})
 await page.setViewportSize({width:720,height:900})
 expect(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true)
 await page.screenshot({path:info.outputPath('vmmc-narrow.png')})
 await page.setViewportSize({width:1280,height:900})
 await dialog.getByRole('tab',{name:'Summary',exact:true}).click()
 await dialog.getByRole('button',{name:'Create job',exact:true}).click()
 await expect.poll(()=>page.evaluate(()=>window.vjob?.job_id)).toBeTruthy()
 if(native)createdJobId=await page.evaluate(()=>window.vjob.job_id)
 expect(await page.evaluate(()=>window.vpayload.backend)).toBe('CPU')
 if(native){
  await page.evaluate(async()=>{window.vjob=await window.vapi.getOxdnaJob(window.vjob.job_id)})
  expect(await page.evaluate(()=>window.vjob.stages.length)).toBe(8)
  await page.evaluate(()=>window.vwizard.openEditable(window.vjob))
  await expect(dialog.locator('[data-vmmc-field="enabled"]:visible')).toBeChecked()
  await dialog.locator('[data-oxdna-salt]:visible').fill('0.35')
  await dialog.getByRole('button',{name:'Save changes',exact:true}).click()
  await expect.poll(()=>page.evaluate(()=>window.vjob.salt_concentration)).toBe(.35)
  await page.evaluate(async()=>{await window.vapi.startOxdnaJob(window.vjob.job_id)})
  await expect.poll(async()=>page.evaluate(async()=>{window.vjob=await window.vapi.getOxdnaJob(window.vjob.job_id);if(window.vjob.status==='failed')throw new Error(window.vjob.error);return window.vjob.status}),{timeout:120000,intervals:[2000]}).toBe('completed')
 } else {
  await page.evaluate(()=>{window.vjob.run_config.vmmc_result={status:'inconclusive',tm_c:null,replica_tm_sem_c:null,temperatures_c:[60,70,80],duplex_yield:[1,.9,.8],reasons:['Too few transitions']};window.vjob.status='completed'})
 }
 await page.evaluate(()=>window.vwizard.openReadOnly(window.vjob))
 await expect(dialog).toContainText('CPU VMMC protocol')
 await expect(dialog).toContainText('Inconclusive')
 await dialog.getByRole('button',{name:'Export melting CSV',exact:true}).scrollIntoViewIfNeeded()
 await page.waitForTimeout(300)
 await page.screenshot({path:info.outputPath('vmmc-results.png')})
 const [download]=await Promise.all([page.waitForEvent('download'),dialog.getByRole('button',{name:'Export melting CSV',exact:true}).click()])
 expect(download.suggestedFilename()).toMatch(/vmmc-.*\.csv/)
 if(native){
  copiedJobId=await page.evaluate(async()=>{window.vcopy=(await window.vapi.copyOxdnaJob(window.vjob.job_id)).job;return window.vcopy.job_id})
  await page.evaluate(async()=>{await window.vapi.startOxdnaJob(window.vcopy.job_id)})
  await expect.poll(async()=>page.evaluate(async()=>{window.vcopy=await window.vapi.getOxdnaJob(window.vcopy.job_id);if(window.vcopy.status==='failed')throw new Error(window.vcopy.error);return window.vcopy.status}),{timeout:120000,intervals:[2000]}).toBe('completed')
  writeFileSync('../.development-artifacts/vmmc-development/native-repeat.json',JSON.stringify(await page.evaluate(()=>({job:window.vjob,copy:window.vcopy,errors:[]})),null,2))
 }
 expect(errors).toEqual([])
 if(process.env.NADOC_VMMC_REVIEW){console.log('VMMC_REVIEW',info.outputPath(''));await page.waitForTimeout(45000)}
 }finally{
  for(const id of [copiedJobId,createdJobId].filter(Boolean)){
   const response=await page.request.get(`/api/oxdna/jobs/${id}`)
   if((await response.json()).status==='running')await page.request.post(`/api/oxdna/jobs/${id}/stop`)
   const deleted=await page.request.delete(`/api/oxdna/jobs/${id}`)
   expect(deleted.ok(),await deleted.text()).toBe(true)
  }
 }
})
