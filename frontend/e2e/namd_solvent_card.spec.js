import { test, expect } from '@playwright/test'
import fs from 'node:fs'
const trials = process.env.NADOC_SOLVENT_REVIEW ? JSON.parse(fs.readFileSync(process.env.NADOC_SOLVENT_REVIEW, 'utf8')) : []
for (const trial of trials) test(`Box and Solvent controls: ${trial.name}`, async ({ page }, info) => {
  test.setTimeout(150000)
  await page.setViewportSize({ width:1600,height:1000 })
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data:{path:trial.source},headers:route.request().headers() })
    await route.fulfill({response})
  })
  await page.goto(`/?debug=1&doc=__e2e__solvent-${trial.name}&open=${encodeURIComponent(trial.filename)}`)
  await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/,{timeout:30000})
  for(const name of ['Close Feature log sidebar','Close Properties sidebar']) {
    const close=page.getByRole('button',{name,exact:true});if(await close.count())await close.first().click()
  }
  await page.evaluate(()=>window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id=>{await window.__nadocMdPanel.refresh();await window.__nadocMdPanel.selectJob(id)},trial.job_id)
  await page.locator('#md-box-solvent-toggle').click()
  const card=page.locator('#md-box-solvent-body')
  for(const kind of ['water','ions','box'])await expect(card.locator(`#md-jobs-${kind}-toggle`)).toBeVisible()
  await page.locator('#md-jobs-display-toggle').check({force:true})
  await expect(page.locator('#md-jobs-display-status')).toContainText(/Displaying frame/i,{timeout:45000})
  await page.evaluate(()=>window.__nadocTest.setRepresentation('full'))
  const count=()=>page.evaluate(()=>{
    let n=0;window.__nadocTest.scene.traverseVisible(o=>{if(o.name==='mdSolvent' && o.isInstancedMesh)n+=o.count});return n
  })
  await card.locator('#md-jobs-water-toggle').check()
  await expect(card.locator('#md-jobs-water-count')).toContainText(/molecules/,{timeout:45000})
  await expect.poll(count).toBeGreaterThan(0)
  await card.locator('#md-jobs-water-toggle').uncheck()
  await expect.poll(count).toBe(0)
  await card.locator('#md-jobs-ions-toggle').check()
  await expect(card.locator('#md-jobs-ions-legend')).toContainText(/Na|Cl|Mg/,{timeout:45000})
  await expect.poll(count).toBeGreaterThan(0)
  const ionCount = await count()
  await card.locator('#md-jobs-box-toggle').check()
  await expect.poll(()=>page.evaluate(()=>!!window.__nadocTest.scene.getObjectByName('mdPeriodicBox')?.visible)).toBe(true)
  await card.locator('#md-jobs-water-toggle').check()
  await expect.poll(count,{timeout:45000}).toBeGreaterThan(ionCount)
  if(trial.name==='submodel')await card.locator('#md-box-view-details').check()
  await expect(card.locator('#md-box-source')).toContainText('Saved job:')
  await expect(card.locator('#md-box-padding')).toBeDisabled()
  // Include the entire actual periodic cell, not just the auto-fitted DNA.
  await page.evaluate(() => {
    const box=window.__nadocTest.scene.getObjectByName('mdPeriodicBox')
    box.geometry.computeBoundingBox()
    const {min,max}=box.geometry.boundingBox
    const target=['x','y','z'].map(k=>(min[k]+max[k])/2)
    const span=Math.max(...['x','y','z'].map(k=>max[k]-min[k]))
    window.__nadocTest.applyCameraPoseForTest({target,position:target.map((x,i)=>x+span*[1.4,.7,1.7][i])})
  })
  await page.screenshot({path:info.outputPath(`${trial.name}-solvent.png`)})
  console.log('REVIEW_IMAGE',info.outputPath(`${trial.name}-solvent.png`))
  await page.waitForTimeout(20000)
  for(const kind of ['water','ions','box'])await card.locator(`#md-jobs-${kind}-toggle`).uncheck()
  await expect.poll(count).toBe(0)
  await expect.poll(()=>page.evaluate(()=>!!window.__nadocTest.scene.getObjectByName('mdPeriodicBox')?.visible)).toBe(false)
  if(trial.name==='submodel')await expect.poll(()=>page.evaluate(()=>!!window.__nadocTest.scene.getObjectByName('simulation-submodel-shell')?.visible)).toBe(true)
})
