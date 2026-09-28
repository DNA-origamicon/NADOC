import { test, expect } from '@playwright/test'

// Only __e2e__ autosaved part/history; global teardown removes both. Native
// endpoints are intercepted: this test never starts or stops a user's viewer.
test('each desktop representation reaches the native launch request unchanged', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/vr/status', route => route.fulfill({ json: { available: true, running: false } }))
  await page.route('**/api/vr/launch', route => route.fulfill({ json: { available: true, running: false } }))
  await page.goto('/?doc=__e2e__vr-representations')
  await page.waitForFunction(() => !!window._nadocDebug?.refetch)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    await api.createBundle({ cells: [[0, 0], [0, 1]], lengthBp: 14, name: '__e2e__VR representations', plane: 'XY' })
  })
  const representations = {
    cylinders: 'menu-view-detail-cylinders', beads: 'menu-view-detail-beads',
    full: 'menu-view-detail-full', 'hull-prism': 'menu-view-hull-prism', surface: 'menu-view-surface',
    vdw: 'menu-view-atomistic-vdw', ballstick: 'menu-view-atomistic-ballstick', stick: 'menu-view-atomistic-stick',
    'mrdna-coarse': 'menu-view-mrdna-coarse', 'mrdna-fine': 'menu-view-mrdna-fine', oxdna: 'menu-view-oxdna',
  }
  for (const [representation, id] of Object.entries(representations)) {
    await page.locator('#'+id).evaluate(button => button.click())
    await expect(page.locator('#'+id)).toHaveClass(/is-checked/)
    const launch = page.waitForRequest(request => request.url().endsWith('/api/vr/launch'))
    await page.locator('#menu-help-view-vr').evaluate(button => button.click())
    expect((await launch).postDataJSON().representation).toBe(representation)
    await expect(page.locator('#menu-help-view-vr')).not.toBeDisabled()
  }
  expect(errors).toEqual([])
})
