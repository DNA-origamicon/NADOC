import { test, expect } from '@playwright/test'

const DOC = '__e2e__vr-feature-history'
const API = process.env.NADOC_E2E_API_BASE
// Persistence inventory: the named in-memory document can autosave a prefixed
// part/project; global teardown removes those artifacts and bridge credentials.
// Session cache is disabled by the isolated smoke config. No native process,
// simulation, or external fixture is created; PNGs use Playwright outputPath.
test.afterEach(async ({ page, request }) => {
  await page.close()
  await request.delete(`${API}/api/documents/${DOC}`)
})
test('VR history commands seek, edit, revert and delete through desktop handlers', async ({ page }, info) => {
  test.setTimeout(120000)
  const errors = [];page.on('pageerror', e => errors.push(e.message))
  let snapshot
  await page.route('**/api/vr/feature-log', async route => { snapshot = route.request().postDataJSON();await route.fulfill({ json: { published: true } }) })
  await page.route('**/api/vr/scene-refresh', route => route.fulfill({ json: { published: true } }))
  await page.goto(`/?test=1&doc=${DOC}&scrywrite=transactions`)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new');await page.fill('#new-design-name', DOC)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.addBundleSegment({ cells: [[0, 0]], lengthBp: 21 })
    await api.addBundleSegment({ cells: [[1, 0]], lengthBp: 21 })
  })
  await expect(page.locator('#fl-list')).toBeVisible()
  await expect(page.locator('#fl-list [data-fl-row]')).toHaveCount(3)
  let sequence=0
  async function command(id) {
    await page.evaluate(() => window.__nadocTest.scrywrite.publishFeatureHistory())
    expect(snapshot.rows.length).toBeGreaterThan(0)
    await page.evaluate(event => window.__nadocTest.scrywrite.dispatch(event), { type: 'feature_log', sequence: ++sequence, version: snapshot.version, id })
  }
  const cursor = () => page.evaluate(() => window.__nadocTest.store.getState().currentDesign.feature_log_cursor)
  await command('r:0');await expect.poll(cursor).toBe(-2)
  await expect.poll(() => page.evaluate(() => !!window.__nadocTest.store.getState().featureSeekPending)).toBe(false)
  await command('r:2');await expect.poll(cursor).toBe(-1) // Desktop normalizes the latest state to -1.
  await expect.poll(() => page.evaluate(() => !!window.__nadocTest.store.getState().featureSeekPending)).toBe(false)
  // Allow the acknowledged scene refresh to finish before requesting row actions.
  await expect.poll(async () => { await page.evaluate(() => window.__nadocTest.scrywrite.publishFeatureHistory());return snapshot.busy }).toBe(false)
  expect(snapshot.rows[2]).toMatchObject({ edit: true, revert: true, delete: true })
  await command('a:2:edit')
  await expect(page.locator('.modal__overlay').last()).toBeVisible()
  await page.locator('.modal__overlay').last().getByRole('button', { name: 'Cancel', exact: true }).click()
  await command('a:2:revert')
  await expect(page.locator('.modal__overlay').last()).toBeVisible()
  await page.locator('.modal__overlay').last().getByRole('button', { name: 'Revert', exact: true }).click()
  await expect(page.locator('#fl-list [data-fl-row]')).toHaveCount(2)
  await expect.poll(async () => { await page.evaluate(() => window.__nadocTest.scrywrite.publishFeatureHistory());return snapshot.busy }).toBe(false)
  await command('a:1:delete')
  await expect(page.locator('#fl-list [data-fl-row]')).toHaveCount(1)
  await page.screenshot({ path: info.outputPath('history-after-actions.png') })
  expect(errors).toEqual([])
})
