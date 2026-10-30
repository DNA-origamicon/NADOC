/** Read-only inventory/menu exercise. No workspace writes or simulations.
 * Downloads are deleted in finally; Playwright context also cleans unsaved downloads.
 * Screenshots stay under configured outputDir and are removed by cleanup reporter.
 * Isolated server disables session cache; global teardown removes its bridge key.
 */
import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

test('Experimental groups tools and opens a searchable evidence inventory', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  const errors = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/'); await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('#menu-bar > .menu-item').filter({ has: page.locator('#menu-help-experimental') }).hover()
  await page.locator('#menu-help-experimental').hover()
  for (const id of ['image-evaluation', 'generate-design', 'peg-testing', 'fjc-sim', 't-junctions', 'connectivity', 'cpd-progress']) {
    await expect(page.locator(`#menu-help-experimental #menu-help-${id}`)).toBeVisible()
  }
  await page.locator('#menu-help-nanobase-inventory').click()
  await expect(page.locator('.ni-modal')).toBeVisible()
  await expect(page.locator('.ni-modal [data-count]')).toContainText('109 of 109')
  await page.locator('.ni-modal [data-search]').fill('MagicDNA')
  await expect(page.locator('.ni-modal tbody')).toContainText('Gripper')
  await expect(page.locator('.ni-modal tbody')).toContainText('Other design figures verified')
  await page.locator('.ni-modal [data-search]').fill('N_nanobase.json')
  await expect(page.locator('.ni-modal tbody tr')).toHaveCount(1)
  await expect(page.locator('.ni-modal tbody')).toContainText('PDF page 3')
  await expect(page.locator('.ni-modal tbody')).toContainText('Not compared')
  const pending = page.waitForEvent('download'); await page.locator('.ni-modal [data-csv]').click(); const download = await pending
  try {
    expect(await readFile(await download.path(), 'utf8')).toContain('Narcissus')
  } finally { await download.delete() }
  await page.locator('.ni-modal [data-search]').fill('')
  await page.locator('.ni-modal [data-figures]').selectOption('verified')
  await expect(page.locator('.ni-modal tbody')).toContainText('Verified caDNAno routing figure')
  if (process.env.NADOC_INVENTORY_CAPTURE === '1') {
    await page.screenshot({ path: testInfo.outputPath('inventory.png') })
    console.log(`INVENTORY_REVIEW=${testInfo.outputPath('inventory.png')}`)
    await page.waitForTimeout(15000)
  }
  await page.locator('.ni-modal .modal__close').click()
  await expect(page.locator('.ni-modal')).toHaveCount(0)
  expect(errors).toEqual([])
})
