import { test, expect } from '@playwright/test'

// Only isolated browser preferences change. No documents, jobs, downloads or
// server folders are created. Context disposal removes all browser storage.
test('File Settings tabs, text preview, apply, reload and cancel', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  const open = async () => {
    await page.locator('#menu-bar > .menu-item > button').filter({ hasText: /^File$/ }).hover()
    await page.locator('#menu-file-settings').click()
    await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible()
  }
  await open()
  await expect(page.getByRole('dialog', { name: 'Settings' }).getByRole('tab')).toHaveCount(10)
  await expect(page.getByRole('tab', { name: 'Simulation workflow' })).toHaveCount(0)
  await page.getByLabel('Application text size multiplier').fill('1.25')
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--text-base'))).toBe('18.75px')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.locator('.settings-status')).toHaveText('Settings applied.')
  await page.getByRole('tab', { name: 'Files & storage' }).click()
  await page.getByLabel('MD / NAMD storage folder').fill('/__nadoc_settings_unavailable__')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.locator('.settings-status')).toContainText('Folder does not exist')
  expect(await page.evaluate(() => localStorage.getItem('nadoc.runDir.namd'))).toBeNull()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.reload(); await page.waitForFunction(() => !!window.__nadocTest)
  await open()
  await expect(page.getByLabel('Application text size multiplier')).toHaveValue('1.25')
  await page.getByLabel('Application text size multiplier').fill('2')
  await expect(page.getByRole('button', { name: 'Apply', exact: true })).toBeInViewport()
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeInViewport()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Settings' })).toHaveCount(0)
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--text-base'))).toBe('18.75px')
  expect(errors).toEqual([])
})
