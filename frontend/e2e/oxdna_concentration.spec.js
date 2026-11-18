// No molecular documents or jobs authored. Session persistence disabled by e2e
// config; __e2e__ naming, global teardown and cleanup reporter cover all artifacts.
import {test,expect} from '@playwright/test'
test('DNA concentration beside conditions: create, ramp, edit and view',async({page},info)=>{
 test.setTimeout(120000)
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/?doc=__e2e__oxdna-concentration')
 await page.waitForFunction(()=>!!window.__nadocTest)
 await page.evaluate(async()=>{
  const {initOxdnaJobWizard}=await import('/src/ui/oxdna_job_wizard.js')
  window.concentrationParent={job_id:'parent',status:'completed',salt_concentration:.3,can_seed_production:true,
   box_conditions:{dna_strands:2,concentration_uM:26.5686,box_nm:[50,50,50]},
   continuation_parameters:{temperature:'298.15K',salt_concentration:.3},run_config:{kind:'relax'}}
  window.concentrationWizard=initOxdnaJobWizard({getInitialValues:()=>({dna_strand_count:2}),
   getJobs:()=>[window.concentrationParent],getParentLabels:()=>new Map([['parent','Relax 1']]),
   spawnProduction:async(id,payload)=>{window.concentrationSubmitted=payload;return {job_id:'mock'}},
   updateJob:async(id,payload)=>{window.concentrationEdited=payload;return {job_id:id}}})
  window.concentrationWizard.open()
 })
 const dialog=page.locator('.modal--oxdna-wizard'), input=()=>dialog.locator('[data-oxdna-field="dna_concentration_uM"]:visible')
 const capture=async name=>{await page.waitForTimeout(250);await page.screenshot({path:info.outputPath(name)})}
 await dialog.getByRole('tab',{name:'Parameters & options',exact:true}).click()
 await input().fill('12000')
 await expect(dialog.locator('.wizard-dna-concentration')).toContainText('6.52 nm')
 await capture('relax.png')
 await dialog.locator('.wizard-mode',{hasText:'Production'}).click()
 await input().fill('12000')
 await expect(dialog.locator('.wizard-dna-concentration')).toContainText('6.52 nm')
 await dialog.locator('[data-thermal-field="enabled"]').check()
 await expect(input()).toHaveValue('12000')
 await capture('thermal.png')
 await page.setViewportSize({width:720,height:900})
 await capture('thermal-narrow.png')
 expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true)
 await page.setViewportSize({width:1280,height:900})
 await dialog.getByRole('tab',{name:'Summary',exact:true}).click()
 await dialog.getByRole('button',{name:'Create job',exact:true}).click()
 await expect.poll(()=>page.evaluate(()=>window.concentrationSubmitted?.dna_concentration_uM)).toBe(12000)
 await page.evaluate(()=>{
  window.concentrationJob={job_id:'queued',parent_job_id:'parent',status:'queued',salt_concentration:.3,
   run_config:{kind:'run',dna_concentration_uM:12000,box_conditions:{dna_strands:2,concentration_uM:12000,box_nm:[6.51677,6.51677,6.51677]}},
   stages:[{name:'1_production',kind:'production',steps:1000}],stage_specs:[{name:'1_production',temperature:'298.15K',salt_concentration:.3,thermostat:'brownian',diff_coeff:2.5}]}
  window.concentrationWizard.openEditable(window.concentrationJob)
 })
 await expect(input()).toHaveValue('12000')
 await input().fill('6000')
 await capture('edit.png')
 await dialog.getByRole('button',{name:'Save changes',exact:true}).click()
 await expect.poll(()=>page.evaluate(()=>window.concentrationEdited?.dna_concentration_uM)).toBe(6000)
 await page.evaluate(()=>window.concentrationWizard.openReadOnly({...window.concentrationJob,status:'completed'}))
 await dialog.getByRole('tab',{name:'Parameters & options',exact:true}).click()
 await expect(dialog.locator('.oxdna-recorded-fields:visible')).toContainText('µM total strands')
 await capture('view.png')
 expect(errors).toEqual([])
 if(process.env.NADOC_CONCENTRATION_REVIEW){console.log('CONCENTRATION_REVIEW',info.outputPath(''));await page.waitForTimeout(45000)}
})
