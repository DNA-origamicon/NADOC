import { test, expect } from '@playwright/test'

test('mrDNA Visualizations card exposes unified maps and confidence warning', async ({ page }) => {
  await page.goto('/')
  const card = page.locator('#mrdna-jobs-display-toggle')
  await expect(card).toContainText('Visualizations')

  const modes = page.locator('input[name="mrdna-display-mode"]')
  await expect(modes).toHaveCount(6)
  await expect(page.locator('input[name="mrdna-display-mode"][value="flex"]')).toBeDisabled()
  await expect(page.locator('input[name="mrdna-display-mode"][value="deviation"]')).toBeDisabled()

  const strain = page.locator('input[name="mrdna-display-mode"][value="strain"]')
  await expect(strain).toBeDisabled()
  await expect(strain.locator('..')).toContainText('Backbone strain map')
  const confidence = page.locator('#mrdna-jobs-display-confidence')
  await expect(confidence).toBeHidden()
  await expect(confidence).toHaveAttribute('aria-label', /Lower-confidence interpolated/)

  await card.evaluate(el => el.click())
  await expect(page.locator('#mrdna-jobs-display-body')).toHaveCSS('display', 'none')
  await card.evaluate(el => el.click())
  await expect(page.locator('#mrdna-jobs-display-body')).not.toHaveCSS('display', 'none')
})
