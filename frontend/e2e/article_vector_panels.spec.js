import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'

// The source and library part are read-only. The ZIP is in Playwright's temp
// storage. Global teardown removes the isolated bridge credential and caches.
const source = fileURLToPath(new URL(
  '../../workspace/Shared%20Designs/.provenance/D012/shapes-supp.pdf', import.meta.url,
))

test('article dialog offers the panel pairs and downloads verified D012', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  const libraryPart = page.locator('.lib-file-row[data-library-path="Shared Designs/D012.nadoc"]')
  const shared = page.locator('.lib-folder-row[data-library-path="Shared Designs"]')
  await expect(shared).toBeVisible()
  if (!await libraryPart.isVisible()) await shared.click()
  await expect(libraryPart).toBeVisible()

  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-experimental').hover()
  await page.locator('#menu-help-image-evaluation').click()
  await page.locator('[data-paper]').setInputFiles(source)
  await page.locator('[data-analyze]').click()

  for (const [figurePage, tablePage, staples] of [[7, 15, 186], [8, 16, 241], [9, 17, 121]]) {
    const card = page.locator('.article-design-card').filter({
      hasText: new RegExp(`Page ${figurePage} · publication routing diagram`, 'i'),
    })
    await expect(card).toHaveCount(1, { timeout: 60_000 })
    const select = card.getByRole('combobox').first()
    const option = select.getByRole('option', { name: new RegExp(`page ${tablePage} ·`, 'i') })
    await expect(option).toHaveCount(1)
    await select.selectOption(await option.getAttribute('value'))
    await expect(card).toContainText(`${staples}/${staples} published staple endpoint pairs recovered`)
    if (figurePage === 9) await card.getByRole('checkbox').check()
    else await expect(card).toContainText('Native reconstruction still needs verified lattice placement.')
  }
  const downloadPromise = page.waitForEvent('download', { timeout: 130_000 })
  await page.locator('[data-reconstruct]').click()
  const download = await downloadPromise
  try {
    const index = JSON.parse(execFileSync('python3', ['-c',
      'import sys, zipfile\nwith zipfile.ZipFile(sys.argv[1]) as z:\n print(z.read("reconstruction-index.json").decode())',
      await download.path(),
    ], { encoding: 'utf8' }))
    expect(index.counts).toEqual({ complete: 1, partial: 0, report_only: 0 })
    expect(index.results[0]).toMatchObject({ diagram_page: 9, table_page: 17, output: 'complete',
      native_file: 'Reconstructed-1-p9.nadoc' })
  } finally {
    await download.delete()
  }
  expect(errors).toEqual([])
})
