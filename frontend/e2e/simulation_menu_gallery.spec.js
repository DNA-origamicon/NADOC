import { test, expect } from '@playwright/test'

// Read-only app menu exercise. Launch request is intercepted; no native process,
// saved design, job, or tour evidence is created. Session cache is disabled by config.
test('simulation menu A/B study is discoverable and desktop-only', async ({ page }) => {
  await page.goto('/?doc=__e2e__simulation-menu-gallery')
  await page.locator('#menu-item-debug > button').click()
  await page.locator('#menu-debug-vr-gallery').hover()
  const gallery = page.locator('#menu-debug-vr-gallery')
  await gallery.locator('[data-category="components"]').hover()
  const launch = gallery.locator('[data-start="simulation-menu-gallery"]')
  await expect(launch).toHaveCount(1)
  await expect(launch).toBeVisible()
  await expect(launch).toHaveText('Simulation menus A/B desktop demo')
  await expect(launch).toHaveAttribute('data-mode', 'desktop')
  await page.route('**/api/vr/tours/start', route => route.fulfill({ status: 409, json: { detail: 'Desktop launch captured' } }))
  const requested = page.waitForRequest(request => request.url().endsWith('/api/vr/tours/start'))
  await launch.click()
  expect((await requested).postDataJSON()).toEqual({ tour: 'simulation-menu-gallery', mode: 'desktop' })
  await expect(page.getByText('Desktop launch captured').first()).toBeVisible()
})
