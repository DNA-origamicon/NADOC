import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Only an empty __e2e__ editor host is saved; global teardown removes its
// part and project history. Preferences are confined to the browser context.
test('representation options reset visible and hidden controls', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await page.goto('/?debug=1&doc=__e2e__repr-options-reset')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__repr-options-reset')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).toBeHidden()
  await page.locator('#right-tab-strip [data-tab="visualization"]').click()
  if (!await page.locator('#repr-options-reset').isVisible()) await page.locator('#slab-heading').click()
  await expect(page.locator('#repr-options-reset')).toBeVisible()
  await page.locator('#repr-options-section input[type="range"]').evaluateAll(sliders => {
    for (const slider of sliders) {
      slider.value = slider.max
      slider.dispatchEvent(new Event('input', { bubbles: true }))
      slider.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })
  await page.locator('#surface-color-uniform').evaluate(button => button.click())
  await page.locator('#show-base-interactions').evaluate(input => input.click())
  await page.getByRole('button', { name: 'Reset to defaults', exact: true }).click()
  await expect(page.locator('#sl-bead-radius')).toHaveValue('0.1')
  await expect(page.locator('#sv-bead-radius')).toHaveText('0.10')
  await expect(page.locator('#sl-slab-thickness')).toHaveValue('0.06')
  await expect(page.locator('#sl-atom-vdw-scale')).toHaveValue('1')
  await expect(page.locator('#sl-surface-probe')).toHaveValue('0.06')
  await expect(page.locator('#sl-surface-opacity')).toHaveValue('1')
  await expect(page.locator('#show-base-interactions')).not.toBeChecked()
  await expect(page.locator('#surface-color-strand')).toHaveClass(/active/)
  expect(errors).toEqual([])
})
