import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'

const fixture = path.resolve('../workspace/2x2_OH_test.nadoc')
test.skip(!existsSync(fixture), 'Requires the local overhang diagnostic fixture')
// Read-only legacy input. Block saving; edits remain in the isolated backend's
// memory, session caching is disabled. No new molecular files are published.
// Report artifacts and isolated bridge credentials are removed by global teardown.
let original
test.beforeEach(async ({ page }) => {
  original = await readFile(fixture, 'utf8')
  await page.route('**/api/design/save**', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: '{"identity_disposition":"confirmed"}' }))
})
test.afterEach(async () => { expect(await readFile(fixture, 'utf8')).toBe(original) })

test('overhang context menu confirms replacement and uses the recorded generator', async ({ page }) => {
  test.setTimeout(120000)
  page.setDefaultTimeout(15000)
  await page.goto('/?doc=__e2e__overhang-context-sequence')
  await page.waitForSelector('#canvas')
  const id = await page.evaluate(async fixture => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixture)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    const { store } = await import('/src/state/store.js')
    return store.getState().currentDesign.overhangs.find(o => o.sequence)?.id
  }, fixture)
  expect(id).toBeTruthy()
  await page.locator('#overhang-panel-heading').evaluate(el => el.click())
  const openMenu = async () => {
    await page.locator(`#overhang-list [data-overhang-id="${id}"]`).evaluate(el => el.click())
    const box = await page.locator('#canvas').boundingBox()
    await page.mouse.click(box.x + 20, box.y + 20, { button: 'right' })
    await page.getByText('Generate sequence…', { exact: true }).click()
  }
  let requests = 0
  page.on('request', request => { if (request.url().includes(`/overhang/${id}/generate-random`)) requests++ })
  await openMenu()
  await expect(page.getByText('Replace overhang sequence?', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(requests).toBe(0)
  await openMenu()
  const generated = page.waitForResponse(r => r.url().includes(`/overhang/${id}/generate-random`))
  await page.getByRole('button', { name: 'Generate new sequence', exact: true }).click()
  const response = await generated
  expect(response.ok()).toBe(true)
  expect(requests).toBe(1)
  await expect(page.getByText('Replace overhang sequence?', { exact: true })).toHaveCount(0)
})
