import { test, expect } from '@playwright/test'

// No files/design mutations or native processes; cleanup reporter removes traces.
test('Debug flyouts launch visualization directly and retain descriptions as tooltips', async ({ page }) => {
  await page.goto('/?doc=e2e-vr-tour-menu')
  await page.locator('#menu-item-debug > button').click()
  await page.locator('#menu-debug-vr-tours').hover()
  const right = page.locator('[data-category=right]')
  await right.hover()
  const demo = right.locator('[data-start=representations][data-mode=demo]')
  await expect(demo).toBeVisible()
  await expect(demo).toHaveText('Visualization demo')
  await expect(demo).toHaveAttribute('title', /open design/)
  await expect(page.getByRole('dialog', {name:'VR Tours & Tests'})).toHaveCount(0)
  await page.route('**/api/vr/tours/start', route => route.fulfill({json:{detail:'Open a design before starting the visualization demo.'},status:400}))
  const requested = page.waitForRequest(request => request.url().endsWith('/api/vr/tours/start'))
  await demo.click()
  expect((await requested).postDataJSON()).toEqual({tour:'representations',mode:'demo',assembly_active:false})
  await expect(page.getByText('Open a design before starting the visualization demo.').first()).toBeVisible()
})
