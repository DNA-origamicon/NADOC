import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

test('numeric defaults across NAMD presets and oxDNA settings', async ({ page }) => {
  test.setTimeout(180000)
  await page.setViewportSize({ width:1600, height:1100 })
  const errors=[];page.on('pageerror', e=>errors.push(String(e)))
  await page.route('**/api/library/open-part', async route => {
    const response=await page.request.post('/api/design/load',{data:{path:process.env.NADOC_TEMPERATURE_SOURCE},headers:route.request().headers()});await route.fulfill({response})
  })
  await page.goto('/?debug=1&doc=__e2e__numeric-fields&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(()=>window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  if (!(await page.locator('#simulate-body').isVisible())) await page.click('#simulate-heading')
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.locator('#md-jobs-new-btn').click()
  let modal=page.locator('.modal--wizard:visible')
  await modal.locator('.wiz-target-card[data-target="local"] > div').first().click()
  await modal.locator('.wizard-tab',{hasText:'Protocol & settings'}).click()
  await expect(modal.locator('[data-job-temperature]')).toBeEnabled({timeout:60000})
  const snapshot=()=>modal.locator('input[type=number]').evaluateAll(inputs=>inputs.filter(i=>i.getClientRects().length).map(i=>({label:i.closest('.wizard-field')?.querySelector('.wizard-field__label')?.textContent,value:i.value,disabled:i.disabled,className:i.className,valid:i.checkValidity(),color:getComputedStyle(i).color,background:getComputedStyle(i).backgroundColor})))
  const presets=await modal.locator('.wizard-preset:not(:disabled) .wizard-preset__label').allTextContents()
  const results=[];let lastPlan=null
  for(const label of presets){
    const card=modal.locator('.wizard-preset').filter({has:page.locator('.wizard-preset__label',{hasText:label})})
    if(!(await card.isVisible()))await modal.locator('.wizard-more-presets summary').click()
    if(!(await card.getAttribute('class')).includes('is-selected')){
      const response=page.waitForResponse(r=>r.url().includes('/md/protocol-plan')&&r.request().method()==='POST');await card.click();lastPlan=await(await response).json()
      await expect(modal.locator('.wizard-field__control .nadoc-spinner')).toHaveCount(0)
    }
    const fields=await snapshot();
    for(const field of fields){expect(field.value, `${label}: ${field.label} default`).not.toBe('');expect(field.className).toContain('input--sm');expect(field.valid, `${label}: ${field.label} validity`).toBe(true)}
    const selects=await modal.locator('select:visible').evaluateAll(inputs=>inputs.map(i=>({label:i.closest('.wizard-field')?.querySelector('.wizard-field__label')?.textContent,value:i.value})))
    results.push({label,fields,selects});console.log('NUMERIC_AUDIT',JSON.stringify({label,fields}))
    if(label.toLowerCase().includes('literature')){
      expect(selects.find(s=>s.label?.includes('Ladder timestep'))?.value).toBe('2')
      expect(lastPlan.request.relax_timestep_fs.value).toBe(2);expect(lastPlan.request.relax_hmr.value).toBe(false)
      expect(lastPlan.stages.filter(s=>s.role!=='minimization'&&s.params.timestep).every(s=>Number(s.params.timestep)<=2)).toBe(true)
      const hmr=modal.locator('.wizard-field').filter({has:page.locator('.wizard-field__label',{hasText:'Ladder H-mass'})}).locator('input');await expect(hmr).not.toBeChecked()
      await modal.locator('[data-job-temperature]').scrollIntoViewIfNeeded()
      const screenshot=path.join(process.env.NADOC_WORKSPACE,'literature-numbers.png');await page.screenshot({path:screenshot});console.log('REVIEW_IMAGE',screenshot);await page.waitForTimeout(20000)
      await modal.locator('.wizard-tab',{hasText:'What each stage runs'}).click()
      const temperatureRow=modal.locator('.wizard-stages tr').filter({has:page.locator('.param',{hasText:'Temperature (K)'})})
      const cell=temperatureRow.locator('td').filter({hasText:/^300$/}).first();await cell.click()
      await expect(temperatureRow.locator('input')).toHaveValue('300');await temperatureRow.locator('input').press('Escape')
      await modal.locator('.wizard-tab',{hasText:'Protocol & settings'}).click()
    }
  }
  await modal.locator('.modal__actions button',{hasText:/Cancel|Close/}).click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click();await page.locator('#oxdna-jobs-new-btn').click()
  modal=page.locator('.modal--oxdna-wizard:visible');await modal.locator('.wiz-target-card[data-target="local"] > div').first().click();await modal.locator('.wizard-tab',{hasText:'Parameters & options'}).click()
  const oxFields=await snapshot();for(const field of oxFields){expect(field.value, field.label).not.toBe('');expect(field.className).toContain('input--sm');expect(field.valid, field.label).toBe(true)}
  results.push({label:'oxDNA',fields:oxFields});console.log('NUMERIC_AUDIT',JSON.stringify(results.at(-1)))
  const oxScreenshot=path.join(process.env.NADOC_WORKSPACE,'oxdna-numbers.png');await page.screenshot({path:oxScreenshot});console.log('REVIEW_IMAGE',oxScreenshot);await page.waitForTimeout(20000)
  await modal.locator('.modal__actions button',{hasText:/Cancel|Close/}).click()
  expect(errors).toEqual([])
  await fs.writeFile(path.join(process.env.NADOC_WORKSPACE,'ui-verification.json'),JSON.stringify({errors,results}))
})
