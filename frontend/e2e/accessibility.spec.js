import { test, expect } from '@playwright/test'

test('keyboard command surface and accessibility metadata are available in the running app', async ({ page }) => {
  await page.goto('/')

  const file = page.getByRole('button', { name: 'File', exact: true })
  await file.focus()
  await page.keyboard.press('ArrowDown')
  await expect(file).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#menu-file-new')).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(file).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.locator('#menu-file-new')).toBeFocused()

  const canvas = page.locator('#canvas')
  await expect(canvas).toHaveAttribute('aria-label', /interactive 3D molecular design workspace/i)

  await page.locator('#menu-help-hotkeys').evaluate(el => el.click())
  await expect(page.locator('#help-modal .hk-desc', { hasText: 'Undo' })).toBeVisible()
  await expect(page.locator('#help-modal .hk-key', { hasText: 'Ctrl Z' })).toBeVisible()

  const cameraHeading = page.locator('#camera-panel-heading')
  await expect(cameraHeading).toHaveAttribute('role', 'button')
  await expect(cameraHeading).toHaveAttribute('tabindex', '0')
})
