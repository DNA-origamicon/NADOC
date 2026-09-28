import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Only __e2e__ workspace files and their project histories are persisted;
// global-teardown.js removes both, plus isolated bridge credentials. No sessions
// are written by the dedicated backend (NADOC_DISABLE_SESSION_CACHE=1).
test('saved VR-format measurements appear on desktop, survive file reload, and retain icon edits', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-dimension-persistence'
  await loadScaffoldedPart(page, { doc, name: 'dimension-persistence' })
  const headers = { 'X-NADOC-Doc': doc }
  const api = (process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002') + '/api'
  const { design } = await (await page.request.get(api+'/design', { headers })).json()
  const entry = { id: 'vr_saved_measurement', name: 'VR measurement', a: [1,2,3], b: [4,6,3], visible: true }
  const response = await page.request.patch(api+'/design/dimensions', { headers, data: { document_id: design.id, upsert: [entry] } })
  expect(response.ok()).toBeTruthy()
  await page.keyboard.press('d')
  await expect(page.locator('.dimensions-row__name')).toHaveText('VR measurement')
  await expect(page.locator('.dimensions-row__value')).toHaveText('5.000 nm')
  expect(await page.evaluate(() => {
    let count=0;window.__nadocTest.scene.traverse(o => { if(o.isLine && o.parent?.userData?.isDimension) count++ });return count
  })).toBe(1)
  const path = design.metadata.identity_last_known_path || '__e2e__dimension-persistence-saved.nadoc'
  expect((await page.request.post(api+'/design/save-workspace', { headers, data: { path, overwrite:true } })).ok()).toBeTruthy()
  const content = await (await page.request.get(api+'/library/content?path='+encodeURIComponent(path))).json()
  // Reload from the saved file into the same document, rather than trusting the live cache.
  expect((await page.request.post(api+'/design/import', { headers, data: { content: content.content } })).ok()).toBeTruthy()
  await page.goto('/?doc='+doc+'&open='+encodeURIComponent(path)+'&open-type=part')
  await page.waitForFunction(() => window.__nadocTest?.dimensions)
  await expect(page.locator('#welcome-screen')).toBeHidden()
  await expect(page.locator('#file-load-progress')).toBeHidden()
  await page.evaluate(() => window.__nadocTest.dimensions.open())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.dimensions.measurements().length)).toBe(1)
  await expect(page.locator('.dimensions-row__name')).toHaveText('VR measurement')
  await page.locator('.dimensions-row [aria-label="Hide dimension"]').click()
  await expect.poll(async () => (await (await page.request.get(api+`/design/dimensions?document_id=${design.id}`,{headers})).json()).dimensions[0]?.visible).toBe(false)
  await page.locator('.dimensions-row [aria-label="Delete dimension"]').click()
  await expect.poll(async () => (await (await page.request.get(api+`/design/dimensions?document_id=${design.id}`,{headers})).json()).dimensions.length).toBe(0)
  expect(errors,errors.join('\n')).toEqual([])
})
