import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// An empty editor host is created through File > New; its __e2e__ file and
// project history are removed by global teardown, along with Vite credentials.
// Browser preferences die with the isolated context; session cache is disabled.
test('visualization cards collapse, persist, mirror, and align action buttons', async ({ page }) => {
  test.setTimeout(120000)
  page.setDefaultTimeout(15000)
  const errors = trackConsoleErrors(page)
  await page.setViewportSize({ width: 1800, height: 1100 })
  await page.goto('/?debug=1&doc=__e2e__visualization-cards')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__visualization-cards')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).toBeHidden()
  const rail = page.locator('#right-tab-strip [data-tab="visualization"]')
  await rail.click()
  for (const name of ['Representations', 'Coloring', 'View Actions']) {
    const toggle = page.getByRole('button', { name, exact: true })
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await toggle.focus(); await page.keyboard.press('Enter')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    const bodyId = await toggle.getAttribute('aria-controls')
    await expect(page.locator(`#${bodyId}`)).toBeHidden()
  }
  const actions = page.locator('.view-actions-card')
  await actions.getByRole('button', { name: 'View Actions', exact: true }).press('Space')
  await expect(actions.locator('.ox-card__body')).toBeVisible()
  await actions.getByRole('button', { name: 'Section view', exact: true }).click()
  await expect(actions.locator('#section-view-controls')).toBeVisible()
  const metrics = await actions.locator('.ox-card__body button:visible').evaluateAll(buttons => buttons.map(b => {
    const r = b.getBoundingClientRect(), s = getComputedStyle(b)
    return { id: b.id, x: r.x, y: r.y, width: r.width, height: r.height, font: s.fontSize,
      border: s.borderWidth, radius: s.borderRadius, background: s.backgroundColor, whiteSpace: s.whiteSpace, overflows: b.scrollWidth > b.clientWidth }
  }))
  expect(new Set(metrics.map(m => m.height)).size).toBe(1)
  expect(new Set(metrics.map(m => m.font)).size).toBe(1)
  expect(new Set(metrics.map(m => m.border)).size).toBe(1)
  expect(new Set(metrics.map(m => m.radius)).size).toBe(1)
  const reset = metrics.find(m => m.id === 'reset-btn'), unhide = metrics.find(m => m.id === 'unhide-all-btn')
  expect(metrics.every(m => m.whiteSpace === 'nowrap' && !m.overflows)).toBe(true)
  expect(reset.y).toBe(unhide.y); expect(reset.width).toBe(unhide.width)
  expect(reset.background).toBe(unhide.background)
  expect(metrics.find(m => m.id === 'section-view-btn').x).toBe(reset.x)
  if (process.env.NADOC_CARDS_SCREENSHOT) await actions.screenshot({ path: process.env.NADOC_CARDS_SCREENSHOT })
  await rail.click()
  const copies = page.locator('.sidebar-column[data-panel-type="visualization"]')
  await expect(copies).toHaveCount(2)
  await copies.nth(1).getByRole('button', { name: 'View Actions', exact: true }).click()
  for (const column of await copies.all()) {
    await expect(column.getByRole('button', { name: 'View Actions', exact: true })).toHaveAttribute('aria-expanded', 'false')
    await expect(column.locator('.view-actions-card .ox-card__body')).toBeHidden()
  }
  await page.reload()
  for (const name of ['Representations', 'Coloring', 'View Actions']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(2)
    for (const toggle of await page.getByRole('button', { name, exact: true }).all())
      await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  }
  expect(errors).toEqual([])
})
