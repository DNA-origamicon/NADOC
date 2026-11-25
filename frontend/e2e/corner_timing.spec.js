import { test, expect } from '@playwright/test'
import { beadCandidates, trackConsoleErrors } from './helpers/scene_harness.js'

// Focused timing diagnostic, not the <=30 s lifecycle acceptance test.
// Native __e2e__ authoring; global teardown removes workspace/revision stores.
// Captures remain in Playwright output only and the cleanup reporter removes them.
test.use({ trace: 'off' })
test('Corner cold Full timing diagnostic', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const crossSection = { lattice: 'HONEYCOMB', cells: [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]] }
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.goto('/?doc=__e2e__corner-tool')
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__corner-tool')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.metadata?.name === '__e2e__corner-tool')
  await page.evaluate(async crossSection => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: crossSection.cells,
      lengthBp: 168, name: '__e2e__corner-tool', latticeType: crossSection.lattice })
    if (crossSection.nick) {
      await api.addNick({ helixId: window.__nadocTest.store.getState().currentDesign.helices[0].id,
        bpIndex: 83, direction: 'FORWARD' })
    }
    if (crossSection.routed) {
      await api.autoScaffoldSeamless()
      await api.assignScaffoldSequence('M13mp18')
      await api.assignStapleSequences()
    }
    window.__nadocTest.applyCameraPoseForTest({ target: [3, 3, 28], position: [70, 18, 28] })
  }, crossSection)
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  const response = page.waitForResponse(r => r.url().includes('/corner/preview'))
  const started = Date.now()
  await page.locator('#menu-tools-corner').click()
  const popup = page.locator('.tool-popup[data-tool-panel="corner-panel"]')
  await expect(popup).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().selection.level)).toBe('cluster')
  await page.mouse.move(800, 700)
  const candidates = await beadCandidates(page)
  expect(candidates.length).toBeGreaterThan(0)
  for (const point of candidates.slice(0, 25)) {
    await page.mouse.click(point.x, point.y)
    if (await page.locator('#corner-positionBp').isEnabled()) break
  }
  await expect(page.locator('#corner-positionBp')).toBeEnabled()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().selection.level)).toBe('default')

  await expect(popup.locator('.def-btn.primary')).toBeEnabled({ timeout: 120000 })
  console.log('Corner diagnostic input-to-ready ms:', Date.now()-started)
  const events = (await (await response).text()).trim().split('\n').map(line => JSON.parse(line))
  console.log('Corner diagnostic phases:', JSON.stringify(events.filter(row => row.type === 'progress')))
  const ready = events.find(row => row.type === 'ready')
  console.log('Corner diagnostic source:', JSON.stringify({ count: ready.candidate.nucleotides.length,
    inserts: ready.candidate.seam_inserts.map(row => row.sequence.length) }))
  await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({
    target: [12, 4, 18], position: [65, 65, 95],
  }))
  const screenshot = testInfo.outputPath('approved-corner.png')
  await page.screenshot({ path: screenshot })
  console.log('Corner diagnostic capture:', screenshot)
  if (process.env.NADOC_REVIEW_INSPECTION_MS) await page.waitForTimeout(Math.min(60000, Number(process.env.NADOC_REVIEW_INSPECTION_MS)))
  expect(errors).toEqual([])
})
