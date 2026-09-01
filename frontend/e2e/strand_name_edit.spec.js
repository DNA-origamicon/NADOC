import { test, expect } from '@playwright/test'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

const SAVED = '__e2e__strand-name-edit.nadoc'

test('strand name supports normal typing and survives a file reload', async ({ page }) => {
  test.setTimeout(60_000)
  await loadScaffoldedPart(page, { doc: 'e2e-strand-name', name: 'strand-name' })
  if (await page.locator('#spreadsheet-panel').evaluate(el => el.getBoundingClientRect().height < 50)) {
    await page.locator('#sheet-toggle').click()
  }
  const input = page.locator('#spreadsheet-tbody tr[data-strand-id] td[data-col="name"] input').first()
  await expect(input).toBeVisible()
  const strandId = await input.locator('xpath=ancestor::tr').getAttribute('data-strand-id')

  await input.click()
  await input.pressSequentially('Voltron Core Arm', { delay: 15 })
  await expect(input).toBeFocused()
  await expect(input).toHaveValue('Voltron Core Arm')

  const patched = page.waitForResponse(r =>
    r.request().method() === 'PATCH' && r.url().includes(`/api/design/strand/${encodeURIComponent(strandId)}`),
  )
  await input.press('Enter')
  expect((await patched).ok()).toBe(true)

  const audit = await page.evaluate(() => window.__nadocNameAudit.snapshot())
  expect(audit.filter(e => e.event === 'input')).toHaveLength('Voltron Core Arm'.length)
  expect(audit.some(e => e.event === 'commit-success' && e.value === 'Voltron Core Arm')).toBe(true)

  await page.evaluate(async path => {
    const api = await import('/src/api/client.js')
    await api.saveDesignAs(path, true)
  }, SAVED)
  await page.goto(`/?open=${encodeURIComponent(SAVED)}&open-type=part&open-name=strand-name`)
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 30_000 })
  if (await page.locator('#spreadsheet-panel').evaluate(el => el.getBoundingClientRect().height < 50)) {
    await page.locator('#sheet-toggle').click()
  }
  await expect(page.locator(`tr[data-strand-id="${strandId}"] td[data-col="name"] input`))
    .toHaveValue('Voltron Core Arm')
})
