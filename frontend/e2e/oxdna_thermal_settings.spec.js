// Existing design read only; mocked runtime settings, no job or molecular authoring.
// __e2e__ session caching disabled; screenshots removed by the cleanup reporter.
import { test, expect } from '@playwright/test'

test('thermal settings are readable and queued copies have formatted controls', async ({page}, info) => {
  test.setTimeout(150000)
  await page.goto('/?doc=__e2e__thermal-settings')
  await page.waitForFunction(()=>!!window.__nadocTest)
  await page.evaluate(async () => {
    const {initOxdnaJobWizard} = await import('/src/ui/oxdna_job_wizard.js')
    const job = {job_id:'__e2e__settings',parent_job_id:'parent',status:'running',backend:'CUDA',
      salt_concentration:.3,random_seed:42,current_stage_idx:0,
      run_config:{kind:'run',salt_concentration:.3,thermal_ramp:{start_c:25,end_c:85,step_c:5,block_steps:2000000000}},
      stages:Array.from({length:13},(_,i)=>({name:`${i+1}_thermal`,steps:2000000000,status:i?'pending':'running'})),
      stage_specs:Array.from({length:13},(_,i)=>({name:`${i+1}_thermal`,dt:.005,thermostat:'brownian',newtonian_steps:100,diff_coeff:2.5,salt_concentration:.3,sequence_dependent:true,backend:'CUDA'}))}
    window.__settingsJob=job
    window.__settingsWizard=initOxdnaJobWizard()
    window.__settingsWizard.openReadOnly(job)
  })
  const dialog=page.locator('.modal--oxdna-wizard')
  await expect(dialog.locator('.oxdna-thermal-recorded')).toBeVisible()
  await expect(dialog.locator('.oxdna-thermal-recorded tbody tr')).toHaveCount(13)
  await expect(dialog.locator('.oxdna-thermal-recorded')).toContainText('2,000,000,000')
  await expect(dialog.locator('pre:visible,textarea:visible')).toHaveCount(0)
  await page.setViewportSize({width:1280,height:900})
  if(process.env.NADOC_SETTINGS_VISUAL) {
    await page.screenshot({path:info.outputPath('thermal-settings.png')})
    console.log('SETTINGS_SCREENSHOT', info.outputPath('thermal-settings.png'))
    await page.waitForTimeout(20000)
  }
  await page.evaluate(()=>{window.__settingsWizard.close();window.__settingsWizard.openEditable({...window.__settingsJob,status:'queued'})})
  await expect(dialog.getByLabel('Thermal ramp salt concentration (M)',{exact:true})).toHaveValue('0.3')
  await expect(dialog.getByLabel('Time step',{exact:true})).toHaveValue('0.005')
  await expect(dialog.getByLabel('Sequence-dependent base strengths')).toHaveValue('true')
  await expect(dialog.locator('textarea:visible')).toHaveCount(0)
  await page.setViewportSize({width:720,height:900})
  expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true)
  if(process.env.NADOC_SETTINGS_VISUAL) {
    await page.screenshot({path:info.outputPath('thermal-edit.png')})
    console.log('EDIT_SCREENSHOT', info.outputPath('thermal-edit.png'))
    await page.waitForTimeout(20000)
  }
})

test('new thermal ramp can select a stopped production parent', async ({page}) => {
  await page.goto('/?doc=__e2e__stopped-continuation')
  await page.waitForFunction(()=>!!window.__nadocTest)
  await page.evaluate(async()=>{
    const {initOxdnaJobWizard}=await import('/src/ui/oxdna_job_wizard.js')
    const jobs=[{job_id:'relax',status:'completed',can_seed_production:true,created_at:1,salt_concentration:.1},
      {job_id:'run',parent_job_id:'relax',status:'stopped',can_seed_production:true,created_at:2,salt_concentration:.3},
      {job_id:'empty',status:'stopped',can_seed_production:false,created_at:3}]
    const wizard=initOxdnaJobWizard({getJobs:()=>jobs,getParentLabels:()=>new Map([['relax','Relax 1'],['run','Run 1']])})
    wizard.open()
  })
  const dialog=page.locator('.modal--oxdna-wizard')
  await dialog.locator('.wizard-mode',{hasText:'Production'}).click()
  const select=dialog.getByLabel('Continue from')
  await expect(select.locator('option')).toHaveCount(2)
  await expect(select).toContainText('Run 1 — stopped (last saved frame)')
  await select.selectOption('run')
  await dialog.locator('[data-thermal-field="enabled"]').check()
  await expect(select).toHaveValue('run')
  await expect(dialog.locator('[data-thermal-field="block_steps"]')).toHaveValue('2000000000')
  const salt=dialog.getByLabel('Thermal ramp salt concentration (M)',{exact:true})
  await expect(salt).toHaveValue('0.3')
  await select.selectOption('relax')
  await expect(salt).toHaveValue('0.1')
  await salt.fill('0.25')
  await select.selectOption('run')
  await expect(salt).toHaveValue('0.25')
  await salt.fill('')
  await select.selectOption('relax')
  await expect(salt).toHaveValue('0.1')

})
