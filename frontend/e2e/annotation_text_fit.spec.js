import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// No saved artifacts: autosave and save routes are disabled, the existing part
// is read-only, and session caching is disabled by the isolated backend config.
// Global teardown removes bridge credentials; the reporter removes traces/images.
test('auto-sized Anchors stays on one rendered line at 13px', async ({ page }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  await page.addInitScript(() => localStorage.setItem('nadoc:preferences:v1', JSON.stringify({ autosave: false })))
  await page.route('**/api/design/save**', route => route.fulfill({ status: 409, json: { detail: 'Read-only test' } }))
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/?doc=__e2e__annotation-text-fit')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(file)
    document.getElementById('welcome-screen').classList.add('hidden')
    for (const id of ['right-panel', 'right-tab-strip']) document.getElementById(id).classList.remove('locked-inactive')
  }, path.resolve(process.cwd(), '..', 'Examples/2hb_xover_atoms_test.nadoc'))
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const panel = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await panel.locator('.anno-add').click()
  await panel.locator('.anno-text').fill('Anchors')
  const font = panel.getByLabel('Font size', { exact: true })
  await font.fill('13'); await font.press('Tab')
  const box = page.locator('.nadoc-anno__box'), text = box.locator('.nadoc-anno__text')
  await expect(text).toBeVisible()
  await expect(box).toHaveCSS('font-size', '13px')
  const lines = () => text.evaluate(node => {
    const range = document.createRange(); range.selectNodeContents(node)
    return [...range.getClientRects()].map(r => ({ top: r.top, width: r.width, height: r.height }))
  })
  console.log('Anchors rendered lines:', await lines())
  await expect.poll(async () => (await lines()).length).toBe(1)
  // Edits and viewport changes must not reintroduce shrink-to-fit wrapping.
  for (const size of ['13.5', '20', '13']) {
    await font.fill(size); await font.press('Tab')
    await expect.poll(async () => (await lines()).length).toBe(1)
  }
  await page.setViewportSize({ width: 1200, height: 800 })
  await expect.poll(async () => (await lines()).length).toBe(1)
  // Explicit newlines and deliberately narrow manual boxes still wrap.
  await panel.locator('.anno-text').fill('Anchors\nSecond line')
  await expect.poll(async () => (await lines()).filter(r => r.width > 0).length).toBe(2)
  await panel.locator('.anno-text').fill('Anchors and a longer caption that should wrap inside a narrow box')
  for (const [label, value] of [['Box width (px)', '110'], ['Box height (px)', '150']]) {
    const input = panel.getByLabel(label, { exact: true }); await input.fill(value); await input.press('Tab')
  }
  await expect.poll(async () => (await lines()).length).toBeGreaterThan(1)
  expect(errors).toEqual([])
})
