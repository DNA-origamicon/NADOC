import { test, expect } from '@playwright/test'
import path from 'node:path'

// No molecular documents or engine jobs are authored. Job region endpoints use an
// in-memory transport fixture; backend disk round trips have focused pytest coverage.
// Only Playwright-managed screenshots/traces and browser-local storage can persist.
test('shared box gestures and per-job region restore in the running app', async ({ page }) => {
  test.setTimeout(90_000) // Two full app boots and read-only example loads.
  const saved = new Map(), errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/*/jobs/*/submodel', async route => {
    const key = new URL(route.request().url()).pathname
    if (route.request().method() === 'PUT') saved.set(key, route.request().postDataJSON())
    await route.fulfill({ json: saved.get(key) ?? { box: null } })
  })
  async function open() {
    await page.goto('/?doc=e2e-submodel-ui')
    await page.waitForFunction(() => window.__NADOC_SUBMODEL__ && window.__nadocTest)
    // Read an existing fixture; region edits never modify the molecular document.
    await page.evaluate(async designPath => {
      const api = await import('/src/api/client.js')
      if (!(await api.loadDesign(designPath))) throw new Error('Fixture load failed')
      document.getElementById('welcome-screen')?.classList.add('hidden')
      document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
      document.querySelectorAll('#left-tab-strip button').forEach(button => { button.disabled = false })
      window.__leftSidebar?.refresh?.()
    }, path.resolve('..', 'Examples', '2hb_xover_atoms_test.nadoc'))
    await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  }
  await open()
  await page.locator('#engine-selector-mount').getByRole('tab', { name: 'oxDNA', exact: true }).click()
  await page.locator('#oxdna-define-submodel').click()
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.gizmoVisible())).toBe(true)
  await page.keyboard.press('Escape')
  const point = await page.evaluate(() => window.__NADOC_SUBMODEL__.outlinePoint('submodel'))
  await page.mouse.click(point.x, point.y)
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.selected())).toBe('submodel')
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.mode())).toBe('scale')
  // Drive the same TransformControls events for reproducible numerical transforms.
  let expected = await page.evaluate(async () => {
    const box = window.__NADOC_SUBMODEL__
    box.begin(); box.scalePreview([0.6, 0.8, 0.5]); box.commit()
    box.setMode('rotate'); box.begin(); box.rotatePreview([0, 0, 1], Math.PI / 6); box.commit()
    box.setMode('translate'); box.begin(); box.translatePreview([1, 2, 3]); box.commit()
    await box.saveToJob('oxdna', 'ui-a')
    return box.volumes()[0]
  })
  await page.locator('#oxdna-define-submodel').click()
  expected = await page.evaluate(() => {
    const box = window.__NADOC_SUBMODEL__
    box.moveSelected([2, 0, 0])
    return box.volumes()[0]
  })
  await expect.poll(() => saved.get('/api/oxdna/jobs/ui-a/submodel')?.box.min_corner).toEqual(expected.min_corner)
  await page.evaluate(() => window.__NADOC_SUBMODEL__.selectJob('oxdna', 'ui-b'))
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes())).toEqual([])
  await page.evaluate(() => window.__NADOC_SUBMODEL__.selectJob('oxdna', 'ui-a'))
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0])).toEqual(expected)
  await open()
  await page.evaluate(() => window.__NADOC_SUBMODEL__.selectJob('oxdna', 'ui-a'))
  expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0])).toEqual(expected)
  await page.locator('#engine-selector-mount').getByRole('tab', { name: 'NAMD', exact: true }).click()
  await page.locator('#md-box-solvent-toggle').click()
  await page.locator('#md-define-submodel').click()
  await page.evaluate(() => window.__NADOC_SUBMODEL__.saveToJob('md', 'ui-namd'))
  await expect(page.locator('#md-submodel')).toContainText('Submodel saved to job.')
  expect(errors).toEqual([])
})
