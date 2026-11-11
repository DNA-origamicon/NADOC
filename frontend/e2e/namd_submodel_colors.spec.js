import { test, expect } from '@playwright/test'
import fs from 'node:fs'

// The same isolated workspace and failure-safe caller cleanup as namd_submodel.spec.js.
test('NAMD submodel scalar maps color unscored atoms as zero', async ({ page }, info) => {
  test.skip(!process.env.NADOC_NAMD_SUBMODEL_MANIFEST, 'Requires isolated native trials')
  test.setTimeout(180000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const trial = JSON.parse(fs.readFileSync(process.env.NADOC_NAMD_SUBMODEL_MANIFEST, 'utf8'))[0]
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: trial.source }, headers: route.request().headers() })
    await route.fulfill({ response })
  })
  await page.goto(`/?doc=__e2e__namd-uniform-colors&open=${encodeURIComponent(trial.filename)}`)
  await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30000 })
  for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
    const close = page.getByRole('button', { name: label, exact: true })
    if (await close.count()) await close.first().click()
  }
  await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(async id => {
    await window.__nadocMdPanel.refresh(); await window.__nadocMdPanel.selectJob(id)
  }, trial.job_id)
  await page.locator('#md-jobs-display-toggle').check({ force: true })
  await expect(page.locator('#md-jobs-display-status')).toContainText(/Displaying frame/i, { timeout: 45000 })
  await page.evaluate(() => window.__nadocTest.setRepresentation('vdw'))
  const scoreResponse = page.waitForResponse(r => r.url().includes('/photoproduct-likelihood') && r.status() === 200)
  await page.locator('#md-jobs-photoproduct-toggle').check({ force: true })
  const scores = await (await scoreResponse).json()
  await expect(page.locator('#md-jobs-photoproduct-status')).toContainText('Ready', { timeout: 60000 })
  const colorAudit = await page.evaluate(async scores => {
    const { photoproductColorMap } = await import('/src/ui/oxdna_display.js')
    const map = photoproductColorMap(scores).colorByKey
    const bad = [], missing = []; let count = 0
    const linear = c => c <= 0.04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4
    window.__nadocTest.getAtomisticRenderer().visitAtoms((atom, position, { instMesh, id }) => {
      count++
      const hex = map.get(atom.scalar_key) ?? map.get(`${atom.helix_id}:${atom.bp_index}:${atom.direction}:${atom.copy_k ?? 0}`)
      if (hex == null) { if (missing.length < 3) missing.push(atom); return }
      const expected = [16, 8, 0].map(shift => linear(((hex >> shift) & 255) / 255))
      const actual = Array.from(instMesh.instanceColor.array.slice(id * 3, id * 3 + 3))
      if (expected.some((x, i) => Math.abs(x - actual[i]) > 1e-4) && bad.length < 3) bad.push({ atom, expected, actual })
    })
    return { count, bad, missing }
  }, scores)
  console.log('COLOR_AUDIT', JSON.stringify(colorAudit))
  expect(colorAudit.missing).toEqual([])
  expect(colorAudit.bad).toEqual([])
  // Inspect the actual rendered instance colors, not just the map/legend state.
  await expect.poll(() => page.evaluate(() => {
    const colors = new Set()
    window.__nadocTest.getAtomisticRenderer().visitAtoms((atom, position, { instMesh, id }) => {
      const a = instMesh.instanceColor.array
      colors.add(Array.from(a.slice(id * 3, id * 3 + 3)).map(x => x.toFixed(5)).join(','))
    })
    return colors.has('0.00000,0.00000,0.00121') // magma zero #000004 in linear RGB
  }), { timeout: 30000 }).toBe(true)
  await page.evaluate(box => {
    const target = box.min_corner.map((x, i) => (x + box.max_corner[i]) / 2)
    window.__nadocTest.applyCameraPoseForTest({ target, position: [target[0] + 38, target[1] + 8, target[2] + 8] })
  }, trial.box)
  await page.screenshot({ path: info.outputPath('propensity-corrected.png') })
  console.log('REVIEW_IMAGE', info.outputPath('propensity-corrected.png'))
  if (process.env.NADOC_NAMD_SUBMODEL_REVIEW) await page.waitForTimeout(30000)
})
