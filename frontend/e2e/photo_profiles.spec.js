import { test, expect } from '@playwright/test'
import { loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

test('Photomode profiles retain their settings across reloads', async ({ page }) => {
  test.setTimeout(60_000)
  const errors = trackConsoleErrors(page)
  const doc = `__e2e__photo-profile-${Date.now()}`
  await loadScaffoldedPart(page, { doc, name: 'photo-profile' })

  await page.locator('.left-tab-btn[data-tab="photo"]').click()
  await expect(page.locator('#photo-profile-select')).toHaveValue('Default')

  page.once('dialog', dialog => dialog.accept('Studio Green'))
  await page.locator('#photo-profile-new').click()
  await expect(page.locator('#photo-profile-select')).toHaveValue('Studio Green')

  await page.locator('#photo-key-intensity').fill('3.25')
  await page.locator('#photo-key-intensity').dispatchEvent('input')
  await expect(page.locator('#photo-key-intensity-label')).toHaveText('3.25')
  await page.waitForTimeout(350)

  await page.reload()
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__photo-profile-reload')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('.left-tab-btn[data-tab="photo"]').click()
  await expect(page.locator('#photo-profile-select')).toHaveValue('Studio Green')
  await expect(page.locator('#photo-key-intensity')).toHaveValue('3.25')
  await expect(page.locator('#photo-key-intensity-label')).toHaveText('3.25')
  expect(errors, errors.join('\n')).toEqual([])
})
