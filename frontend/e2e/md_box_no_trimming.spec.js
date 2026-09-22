import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Only __e2e__no-trim .nadoc/project-history artifacts; global teardown removes them.
// No job creation, solvation, cluster connection, or native simulation.
test('View details preserves rotation sizing and padding without a trim warning', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__no-trim', name: 'no-trim' })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  if (await page.locator('#simulate-body').evaluate(el => getComputedStyle(el).display === 'none')) await page.click('#simulate-heading')
  await page.click('.engine-selector-btn[data-engine="namd"]')
  await page.locator('#md-box-solvent-toggle').evaluate(el => {
    if (document.getElementById('md-box-solvent-body').style.display === 'none') el.click()
  })
  const preview = page.waitForResponse(response => response.url().includes('/md/protocol-box-preview') &&
    response.request().postDataJSON()?.box_mode === 'rotation' &&
    response.request().postDataJSON()?.padding_nm === 2)
  await page.selectOption('#md-box-sizing', 'rotation')
  await page.fill('#md-box-padding', '2')
  await page.check('#md-box-view-details')
  const result = (await (await preview).json()).box_preview
  expect(result.padding_nm).toBe(2)
  expect(result.box_mode).toBe('rotation')
  expect(result.sizing_notes).toEqual([])
  expect(Math.min(...result.calculated_nm)).toBeGreaterThan(60)
  await expect(page.locator('#md-box-loading')).not.toBeVisible()
  await expect(page.locator('#md-box-warning')).not.toBeVisible()
  await expect(page.locator('#md-box-warnings')).not.toContainText('trimmed padding')
  await expect(page.locator('#md-box-padding')).toHaveValue('2')
  await expect.poll(() => page.evaluate(() => window.__nadocScene.getObjectByName('NAMD box and solvent details')?.visible)).toBe(true)
  const recommended = page.waitForResponse(response => response.url().includes('/md/protocol-box-preview') &&
    response.request().postDataJSON()?.box_mode === 'bbox' &&
    response.request().postDataJSON()?.padding_nm === 2)
  await page.fill('#md-box-padding', '3')
  await page.selectOption('#md-box-sizing', 'auto')
  const fitted = (await (await recommended).json()).box_preview
  const spans = fitted.solute_bounds_nm.max.map((v,i)=>v-fitted.solute_bounds_nm.min[i])
  fitted.calculated_nm.forEach((v,i)=>expect(v-spans[i]).toBeCloseTo(4,2))
  await expect(page.locator('#md-box-clearance')).toContainText('X− 2.00 / X+ 2.00')
  await expect(page.locator('#md-box-clearance')).toContainText('Z− 2.00 / Z+ 2.00')
  await expect(page.locator('#md-box-padding')).toHaveValue('2')
  await page.uncheck('#md-box-view-details')
  await page.check('#md-box-view-periodic')
  const ghosts = await page.evaluate(() => {
    const group=window.__nadocScene.getObjectByName('NAMD periodic images')
    return {visible:group.visible,offsets:group.children.map(c=>c.position.toArray()),
      points:group.children.map(c=>c.geometry.attributes.position.count),
      shared:new Set(group.children.map(c=>c.geometry)).size,
      details:window.__nadocScene.getObjectByName('NAMD box and solvent details').visible}
  })
  expect(ghosts.visible).toBe(true)
  expect(ghosts.details).toBe(false)
  expect(ghosts.offsets).toHaveLength(6)
  expect(ghosts.shared).toBe(1)
  expect(ghosts.points.every(n=>n>0 && n<=12000)).toBe(true)
  expect(ghosts.offsets[1]).toEqual([fitted.calculated_nm[0],0,0])
  const rows=await page.evaluate(()=>['md-box-view-details','md-box-view-periodic'].map(id=>{
    const r=document.getElementById(id).parentElement.getBoundingClientRect();return {top:r.top,bottom:r.bottom}
  }))
  expect(rows[1].top).toBeGreaterThanOrEqual(rows[0].bottom)
  await page.locator('#menu-view-detail-beads').evaluate(el=>el.click())
  await expect(page.locator('#md-box-view-periodic')).not.toBeChecked()
  await expect(page.locator('#md-box-view-periodic')).toBeDisabled()
  await page.locator('#menu-view-detail-full').evaluate(el=>el.click())
  await expect(page.locator('#md-box-view-periodic')).toBeEnabled()
  await expect(page.locator('#md-box-view-periodic')).not.toBeChecked()
  await page.check('#md-box-view-periodic')
  await page.uncheck('#md-box-view-periodic')
  await expect.poll(()=>page.evaluate(()=>window.__nadocScene.getObjectByName('NAMD periodic images').children.length)).toBe(0)
  expect(errors).toEqual([])
})
