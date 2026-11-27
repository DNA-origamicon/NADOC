import { test, expect } from '@playwright/test'
import { beadCandidates, trackConsoleErrors } from './helpers/scene_harness.js'

// Isolated launcher owns workspace, revisions, browser profiles and caches;
// its finally removes the whole temporary root on success or failure.
for (const curved of [true, false]) test(`Bevel ${curved ? 'curved' : 'straight'} bundle preview, edit, undo and replay`, async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const doc = `__e2e__bevel-${curved}`
  const errors = trackConsoleErrors(page)
  page.on('response', async response => {
    if (response.status() >= 400) console.log('Bevel HTTP error', response.url(), response.status(), await response.text().catch(() => 'unavailable'))
  })
  await page.goto(`/?doc=${doc}`)
  await page.waitForFunction(() => !!window.__nadocTest?.store)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill(doc)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(doc => window.__nadocTest.store.getState().currentDesign?.metadata?.name === doc, doc)
  await page.evaluate(async ({ doc, curved }) => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: [[0, 0], [0, 1]], lengthBp: 84, name: doc, latticeType: 'HONEYCOMB' })
    if (curved) {
      const design = window.__nadocTest.store.getState().currentDesign
      const result = await api._request('POST', '/design/deformation', {
        type: 'bend', plane_a_bp: 7, plane_b_bp: 70,
        cluster_ids: [design.cluster_transforms[0].id],
        params: { kind: 'bend', curvature_deg_per_bp: .3, direction_deg: 30 },
      })
      if (!result) throw new Error('Bend failed')
      await api._syncFromDesignResponse(result)
    }
    window.__nadocTest.applyCameraPoseForTest({ target: [1, 1, 14], position: [55, 18, 14] })
  }, { doc, curved })
  const before = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))
  await page.getByRole('button', { name: 'Tools', exact: true }).hover()
  await page.locator('#menu-tools-bevel').click()
  const popup = page.locator('.tool-popup[data-tool-panel="bevel-panel"]')
  await expect(popup).toBeVisible()
  await expect(popup.locator('[role=status]')).toHaveText('Select a cluster in the viewer.', { timeout: 15000 })
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().selection.level)).toBe('cluster')
  const header = await popup.locator('.tool-popup__header').boundingBox()
  await page.mouse.move(header.x + 50, header.y + 12)
  await page.mouse.down()
  await page.mouse.move(350, 110)
  await page.mouse.up()
  await page.screenshot({ path: testInfo.outputPath('selection.png') })
  await page.mouse.move(800, 700)
  const points = await beadCandidates(page)
  for (const point of points) {
    const visible = await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id === 'canvas', point)
    if (!visible) continue
    await page.mouse.click(point.x, point.y)
    if (await page.locator('#bevel-positionBp').isEnabled()) break
  }
  if (!(await page.locator('#bevel-positionBp').isEnabled())) console.log('Bevel pick diagnostics', await page.evaluate(() => ({ selection: window.__nadocTest.store.getState().selection, clusters: window.__nadocTest.store.getState().currentDesign.cluster_transforms, status: document.querySelector('#bevel-panel [role=status]').textContent })), errors)
  await expect(page.locator('#bevel-positionBp')).toBeEnabled()
  await page.locator('#bevel-angleDeg').fill('30')
  await expect(popup.locator('.def-btn.primary')).toBeEnabled({ timeout: 30_000 })
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(before)
  await popup.locator('.def-btn.primary').click()
  await expect(popup).not.toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1).op_kind)).toBe('bevel')
  await page.screenshot({ path: testInfo.outputPath('applied.png') })
  const after = await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))
  expect(after).not.toBe(before)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(before)
  await page.evaluate(async () => (await import('/src/api/client.js')).redo())
  expect(await page.evaluate(() => JSON.stringify(window.__nadocTest.store.getState().currentDesign.strands))).toBe(after)
  await page.locator('#fl-list button[title^="Edit"]').last().click()
  await expect(popup).toBeVisible()
  await page.locator('#bevel-trimEnd').selectOption('start')
  await page.locator('#bevel-angleDeg').fill('15')
  await expect(popup.locator('.def-btn.primary')).toBeEnabled({ timeout: 30_000 })
  await popup.locator('.def-btn.primary').click()
  await expect(popup).not.toBeVisible()
  const row = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log.at(-1))
  expect(row.params).toMatchObject({ angle_deg: 15, trim_end: 'start' })
  const headers = { 'X-NADOC-Doc': doc }
  const start = await page.request.post('/api/design/features/verification/jobs', { headers })
  expect(start.status()).toBe(202)
  const { job_id: job } = await start.json()
  let result
  await expect.poll(async () => {
    result = await (await page.request.get(`/api/design/features/verification/jobs/${job}`, { headers })).json()
    return result.status
  }, { timeout: 15_000 }).toBe('complete')
  expect(result.result).toMatchObject({ status: 'verified', native_editable: true })
  expect(errors).toEqual([])
})
