import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

// Existing design is read-only. The runner owns an isolated temporary workspace;
// no design authoring, native preparation, or simulation is performed here.
test('defines editable submodel bounds from bases through clusters with standard buttons', async ({ page }) => {
  const source = process.env.NADOC_SUBMODEL_SELECTION_SOURCE
  test.skip(!source, 'Requires the isolated selection-review runner and an existing design')
  test.setTimeout(120000)
  const design = JSON.parse(fs.readFileSync(source, 'utf8'))
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let createdJobs = 0
  await page.route('**/api/md/jobs', route => {
    if (route.request().method() === 'POST') { createdJobs++; return route.abort() }
    return route.continue()
  })
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: source }, headers: route.request().headers() })
    await route.fulfill({ response })
  })
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto(`/?debug=1&doc=__e2e__submodel-selection&open=${encodeURIComponent(path.basename(source))}`)
  await page.waitForFunction(() => window.__nadocTest && window.__NADOC_SUBMODEL__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30000 })
  for (const name of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name, exact: true }); if (await close.count()) await close.first().click()
  }
  await page.evaluate(() => { window.__nadocTest.setRepresentation('full'); window.__leftSidebar.selectTab('dynamics') })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.locator('#md-box-solvent-toggle').click()
  const fromSelection = page.locator('#md-submodel-from-selection')
  await expect(fromSelection).toBeDisabled()
  const base = await page.evaluate(() => {
    const { nuc, pos } = window.__nadocTest.getDesignRenderer().getBackboneEntries()[0]
    return { ref: { kind: 'base', key: `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}` }, pos: pos.toArray(), strand: nuc.strand_id, domain: nuc.domain_index }
  })
  const select = async refs => page.evaluate(refs => window.__nadocTest.selectRefsForTest(refs), refs)
  await select([base.ref]); await expect(fromSelection).toBeEnabled(); await fromSelection.click()
  const volume = await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0])
  expect(volume.min_corner).toEqual(base.pos.map(v => v - 1))
  expect(volume.max_corner).toEqual(base.pos.map(v => v + 1))
  await expect(page.locator('#md-submodel-controls')).toBeVisible()
  await expect(page.locator('#md-box-view-details')).toBeChecked()
  const style = await page.evaluate(() => {
    const a = document.getElementById('md-define-submodel'), b = document.getElementById('md-submodel-from-selection')
    const sa = getComputedStyle(a), sb = getComputedStyle(b)
    return { first: a.className, second: b.className, stacked: b.getBoundingClientRect().top >= a.getBoundingClientRect().bottom,
      heights: [sa.height, sb.height], fonts: [sa.fontSize, sb.fontSize], radii: [sa.borderRadius, sb.borderRadius], width: [sa.width, sb.width] }
  })
  expect(style.first).toBe('btn btn--sm'); expect(style.second).toBe('btn btn--sm'); expect(style.stacked).toBe(true)
  for (const key of ['heights', 'fonts', 'radii', 'width']) expect(style[key][0]).toBe(style[key][1])
  console.log('SELECTION_BUTTON_STYLE', JSON.stringify(style))
  for (const refs of [[{ kind: 'domain', strandId: base.strand, domainIndex: base.domain }], [{ kind: 'strand', id: base.strand }], [{ kind: 'cluster', id: design.cluster_transforms[0].id }]]) {
    await select(refs); await fromSelection.click()
    await expect(page.locator('#md-submodel > [role=status]')).toContainText('Submodel ready')
  }
  const crossover = design.crossovers.find(x => x.extra_bases?.length)
  expect(crossover).toBeTruthy()
  for (const ref of [{ kind: 'crossover', id: crossover.id, subtype: 'crossover' }, { kind: 'base', key: `__xb__:${crossover.id}:0` }]) {
    await select([ref]); await fromSelection.click()
    await expect(page.locator('#md-submodel > [role=status]')).toContainText('Submodel ready')
  }
  if (process.env.NADOC_SELECTION_CAPTURE) {
    await page.screenshot({ path: process.env.NADOC_SELECTION_CAPTURE })
    console.log('SELECTION_REVIEW_IMAGE', process.env.NADOC_SELECTION_CAPTURE)
    await page.waitForTimeout(20000) // runner removes the image in finally, including failures
  }
  await select([]); await expect(fromSelection).toBeDisabled()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  await select([base.ref])
  const ox = page.locator('#oxdna-submodel-from-selection')
  await ox.scrollIntoViewIfNeeded(); await ox.click()
  await expect(page.locator('#oxdna-submodel > [role=status]')).toContainText('Submodel ready')
  expect(createdJobs).toBe(0)
  expect(errors).toEqual([])
})
