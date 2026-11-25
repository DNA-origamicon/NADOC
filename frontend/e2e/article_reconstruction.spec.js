/** No workspace structures, downloads or captures. Session cache is disabled by
 * the smoke config; its bridge credential is removed by global teardown. */
import { test, expect } from '@playwright/test'

test('article dialog screens a real upload, reports blockers, and resets on edits', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-experimental').hover()
  await expect(page.locator('#menu-help-image-evaluation')).toHaveText('Reconstruct from Article…')
  await page.locator('#menu-help-image-evaluation').click()
  await expect(page.getByText('Reconstruct from Article', { exact: true })).toBeVisible()
  await page.locator('[data-check]').click()
  await expect(page.locator('.article-reconstruction [data-status]')).toContainText('Enter a DOI')
  await page.locator('[data-paper]').setInputFiles({ name: 'large-invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(26 * 1024 * 1024, 'x') })
  await page.locator('[data-check]').click()
  await expect(page.locator('.article-reconstruction [data-status]')).toContainText('Checks complete')
  await expect(page.locator('[data-checks] [data-state="failed"]')).toHaveCount(3)
  await expect(page.locator('[data-checks]')).toContainText('Upload a valid PDF.')
  await expect(page.locator('[data-checks] [data-state="deferred"]')).toHaveCount(2)
  await expect(page.locator('[data-checks]')).not.toContainText('AGENT_PROCESS_REQUIRED')
  await expect(page.locator('[data-reconstruct]')).toBeDisabled()
  await page.locator('[data-doi]').fill('10.1234/example')
  await expect(page.locator('[data-checks] [data-state="pending"]')).toHaveCount(3)
  await page.locator('[data-evidence]').click()
  await expect(page.locator('.ie-modal')).toBeVisible()
  await page.locator('.ie-modal .modal__close').click()
  await page.locator('.modal').filter({ has: page.locator('.article-reconstruction') }).locator('.modal__close').click()
  expect(errors).toEqual([])
})

test('DOI screening presents caption confirmation and defers confidence assessment', async ({ page }) => {
  const events = [
    { id: 'paper', status: 'passed', detail: 'Paper found by DOI.' },
    { id: 'origami', status: 'passed', detail: 'DNA origami identified.' },
    { id: 'supplement', status: 'passed', detail: 'Figure S1. caDNAno diagram. Staple list not confirmed; this does not block image analysis.' },
    { id: 'detail', status: 'deferred', detail: 'Later stage: image analysis.' },
    { id: 'reconstruction', status: 'deferred', detail: 'Later stage: reconstruction confidence. caDNAno files are not required.' },
    { type: 'complete', can_reconstruct: false, ready_for_analysis: true, confidence: null },
  ]
  await page.route('**/api/article-reconstruction/check', async route => {
    expect(route.request().postDataJSON()).toEqual({ doi: '10.1234/test', paper: null, supplements: [] })
    await route.fulfill({ contentType: 'application/x-ndjson', body: events.map(item => JSON.stringify(item) + '\n').join('') })
  })
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-experimental').hover()
  await page.locator('#menu-help-image-evaluation').click()
  await page.locator('[data-doi]').fill('10.1234/test')
  await page.locator('[data-check]').click()
  await expect(page.locator('.article-reconstruction [data-status]')).toContainText('sufficient to proceed to image analysis')
  await expect(page.locator('[data-checks] [data-state="passed"]')).toHaveCount(3)
  await expect(page.locator('[data-checks] [data-state="deferred"]')).toHaveCount(2)
  await expect(page.locator('[data-reconstruct]')).toBeDisabled()
  await page.locator('.modal').filter({ has: page.locator('.article-reconstruction') }).locator('.modal__close').click()
})
