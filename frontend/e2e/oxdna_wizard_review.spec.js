// Temporary __e2e__ session only; no structures/jobs saved. Global teardown and
// cleanup reporter remove session artifacts, credentials and screenshots.
import {test,expect} from '@playwright/test'
test('review oxDNA wizard conditions across run types',async({page},info)=>{
 test.setTimeout(120000)
 await page.goto('/?doc=__e2e__wizard-review')
 await page.waitForFunction(()=>!!window.__nadocTest)
 await page.evaluate(async()=>{
  const {initOxdnaJobWizard}=await import('/src/ui/oxdna_job_wizard.js')
  const parent={job_id:'parent',status:'completed',salt_concentration:.3,can_seed_production:true,
   continuation_parameters:{temperature:'310K',salt_concentration:.3},run_config:{kind:'relax'}}
  window.reviewWizard=initOxdnaJobWizard({getJobs:()=>[parent],getParentLabels:()=>new Map([['parent','Relax 1']])})
  window.reviewWizard.open()
 })
 const dialog=page.locator('.modal--oxdna-wizard')
 const capture=async name=>{await expect(dialog).toBeVisible();await page.waitForTimeout(250);await page.screenshot({path:info.outputPath(name)})}
 await expect(dialog.locator('.wiz-target-card[data-target="local"]')).not.toContainText('NAMD')
 await capture('target.png')
 await dialog.getByRole('tab',{name:'Parameters & options',exact:true}).click()
 await capture('relax.png')
 await dialog.locator('.wizard-mode',{hasText:'Production'}).click()
 await capture('production.png')
 await dialog.locator('[data-thermal-field="enabled"]').check()
 await capture('thermal.png')
 await page.setViewportSize({width:720,height:900})
 await capture('thermal-narrow.png')
 expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true)
 await page.setViewportSize({width:1280,height:900})
 for (const kind of ['run','surface_deposition']) {
  await page.evaluate(kind=>{
   window.reviewWizard.close()
   window.reviewJob={job_id:'review',parent_job_id:'parent',status:'queued',salt_concentration:.3,
    run_config:{kind},stages:[{name:'1_production',kind:'production',steps:1000}],
    stage_specs:[{name:'1_production',temperature:'310K',salt_concentration:.3,steps:1000,thermostat:'bussi'}]}
   window.reviewWizard.openEditable(window.reviewJob)
  },kind)
  const conditions=dialog.locator('.oxdna-job-settings-view .oxdna-conditions')
  await expect(conditions.getByLabel('Temperature (K)',{exact:true})).toHaveValue('310')
  await expect(conditions.getByLabel('Salt concentration (M)',{exact:true})).toHaveValue('0.3')
  await capture(`edit-${kind}.png`)
 }
 await page.evaluate(()=>{window.reviewWizard.close();window.reviewWizard.openReadOnly({...window.reviewJob,status:'completed'})})
 await dialog.getByRole('tab',{name:'Parameters & options',exact:true}).click()
 await expect(dialog.locator('tbody:visible')).toContainText('310K')
 await expect(dialog.locator('tbody:visible')).toContainText('0.3')
 await capture('view.png')
 if(process.env.NADOC_WIZARD_REVIEW){console.log('WIZARD_REVIEW',info.outputPath(''));await page.waitForTimeout(45000)}
})
