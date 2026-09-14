import { expect, test } from '@playwright/test'
let jobId
let createdJob
const API = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'
test.afterEach(async ({ request }) => {
  if (!jobId && createdJob) jobId = (await createdJob.catch(() => null))?.job_id
  if (jobId) {
    expect((await request.delete(`${API}/api/md/jobs/${jobId}`)).ok()).toBeTruthy()
    expect((await request.get(`${API}/api/md/jobs/${jobId}`)).status()).toBe(404)
    jobId = null
  }
  createdJob = null
})
test('blank document creates a charged-wall draft with editable salt and charge', async ({ page }) => {
  await page.goto('/')
  await page.waitForSelector('#canvas')
  await page.locator('#menu-file-new').evaluate(el => el.click())
  await page.fill('#new-design-name', '__e2e__charged-surface')
  await page.getByRole('button', { name:'Create', exact:true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await expect(page.locator('#tab-content-dynamics')).toBeVisible()
  if (await page.locator('#simulate-body').evaluate(el => getComputedStyle(el).display === 'none')) await page.click('#simulate-heading')
  await expect(page.locator('#simulate-body')).toBeVisible()
  await page.click('.engine-selector-btn[data-engine="namd"]')
  await page.click('#md-surface-toggle')
  await page.check('#md-screening-enable')
  await page.locator('#md-screening-settings > summary').click()
  await expect(page.locator('#md-screening-charge')).toHaveValue('-0.0413')
  await page.fill('#md-screening-charge', '-0.02')
  await expect(page.locator('#md-screening-salt')).toHaveCount(0)
  await expect(page.locator('#md-screening-temperature')).toHaveCount(0)
  await page.click('#md-box-solvent-toggle')
  await page.selectOption('#md-box-salt','custom')
  await page.fill('#md-box-na','175')
  await page.fill('#md-box-mg','0')
  await page.fill('#md-box-temperature','298.15')
  await page.click('#md-jobs-new-btn')
  await expect(page.locator('#md-screening-enable')).toBeChecked()
  const modal=page.locator('.modal__overlay').filter({has:page.locator('.wizard-tab')})
  await modal.getByRole('tab', {name:/Protocol & settings/}).click()
  await expect(modal.locator('.wizard-field__label').filter({hasText:'Ionic conditions'})).toHaveCount(0)
  await expect(modal.locator('.wizard-help').filter({hasText:'Box and solvent'})).toContainText('175 mM')
  await modal.getByRole('tab', {name:/What each stage runs/}).click()
  await expect(page.locator('#md-screening-enable')).toBeChecked()
  const response=page.waitForResponse(r => r.url().endsWith('/api/md/jobs') && r.request().method()==='POST')
  createdJob = response.then(r => r.json())
  await modal.getByRole('button',{name:'Create job',exact:true}).click()
  const r=await response
  const job=await createdJob; jobId=job.job_id
  expect(r.ok(), JSON.stringify(job)).toBeTruthy()
  expect(jobId).toBeTruthy()
  expect(job.prep_params).toMatchObject({graphene_only:true,graphene_pore_diameter_nm:0,graphene_charge_density_C_m2:-.02,salt_mode:'custom',ion_conc_mM:175,mg_conc_mM:0,field:null})
  await expect(page.locator('#md-screening-charge')).toHaveValue('-0.02')
  const surfaceVisible=()=>page.evaluate(()=>!!window.__nadocScene.getObjectByName('Graphene nanopore preview')?.visible)
  await expect.poll(surfaceVisible).toBe(false)
  const row=page.locator(`#simulate-jobs-list [data-job-id="${jobId}"]`).first()
  await row.click()
  await expect.poll(surfaceVisible).toBe(true)
  // Changing setup cannot replace the selected job's immutable surface.
  await page.fill('#md-screening-charge','-0.03')
  await expect.poll(surfaceVisible).toBe(true)
  await row.click()
  await expect.poll(surfaceVisible).toBe(false)
  await row.click()
  await expect.poll(surfaceVisible).toBe(true)

  await page.route(`**/md/jobs/${jobId}/surface-profiles`, async route => {
    if(route.request().method()==='GET') return route.fulfill({status:404,body:'{}'})
    await route.fulfill({json:{frames:32,bulk_Na_mM:100,bulk_Cl_mM:100,reference_debye_nm:.96,
      screening_fit:{available:false,reason:'Insufficient resolved signal'},
      distance_nm:[.1,.2],edge_distance_nm:[.2,.3],
      concentration_mM:{positive:{'Na+':[200,100],'Cl-':[50,100]},negative:{'Na+':[200,100],'Cl-':[50,100]}},
      ionic_charge_e_nm3:{positive:[.1,0],negative:[.1,0]},residual_sheet_fraction:[.8,.5]}})
  })
  await page.click('#md-metrics-toggle')
  const profiles=page.locator('#md-metrics-surface-profiles')
  await expect(profiles).toBeVisible()
  await expect(profiles.locator('input')).toHaveCount(0)
  await profiles.getByRole('button',{name:'Surface ions and screening…',exact:true}).click()
  const popup=page.getByRole('dialog',{name:'Surface ions and screening'})
  await expect(popup).toBeVisible()
  await popup.locator('[name=bins]').fill('60')
  const calculation=page.waitForRequest(r=>r.url().endsWith(`/md/jobs/${jobId}/surface-profiles`) && r.method()==='POST')
  await popup.getByRole('button',{name:'Calculate',exact:true}).click()
  expect((await calculation).postDataJSON().bins).toBe(60)
  await expect(popup.locator('[data-summary]')).toContainText('32 sampled frames')
  await expect(popup.locator('canvas')).toHaveCount(3)
  await popup.locator('[name=dielectric]').fill('80')
  await popup.getByRole('button',{name:'Calculate',exact:true}).click()
  await expect(popup.locator('[data-status]')).toContainText('Calculation complete')
  await expect(popup.locator('canvas')).toHaveCount(3)
  await page.keyboard.press('Escape')
  await expect(popup).toHaveCount(0)
  const transport=page.locator('#md-metrics-ion-transport-row')
  for(const name of ['Generate','Display','Export'])await expect(transport.getByRole('button',{name,exact:true})).toBeVisible()
  await expect(transport.getByRole('button',{name:'Display',exact:true})).toBeDisabled()
})
