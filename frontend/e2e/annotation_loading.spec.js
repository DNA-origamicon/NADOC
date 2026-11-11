import { test, expect } from '@playwright/test'
import path from 'node:path'

// Read existing molecular fixture; only response annotation metadata is changed.
// No files are saved. Standard isolated-server teardown handles test artifacts.
test('annotations wait for model geometry before appearing', async ({ page }) => {
  test.setTimeout(60000)
  await page.goto('/?doc=__e2e__annotation-loading')
  await page.waitForFunction(() => !!window.__nadocTest)
  let release
  const gate = new Promise(resolve => { release = resolve })
  let geometryRequested = false
  await page.route('**/api/design/geometry*', async route => {
    geometryRequested = true
    await gate
    await route.continue()
  })
  await page.route('**/api/design/load', async route => {
    const response = await route.fetch()
    const json = await response.json()
    json.design.annotations = [{ id: 'loading-caption', text: 'Loaded model caption', size: 1, enabled: true }]
    delete json.nucleotides
    delete json.nucleotides_compact
    await route.fulfill({ response, json })
  })
  try {
    await page.evaluate(async example => {
      const api = await import('/src/api/client.js')
      document.getElementById('welcome-screen').classList.add('hidden')
      window.__annotationLoad = api.loadDesign(example)
    }, path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
    await expect.poll(() => geometryRequested).toBe(true)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.annotations?.[0]?.text)).toBe('Loaded model caption')
    await expect(page.locator('.nadoc-anno-layer')).toBeHidden()
    release()
    await page.evaluate(() => window.__annotationLoad)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length ?? 0)).toBeGreaterThan(0)
    await expect(page.locator('.nadoc-anno-layer')).toBeVisible()
    await expect(page.locator('.nadoc-anno-layer')).toContainText('Loaded model caption')
  } finally {
    release()
  }
})
