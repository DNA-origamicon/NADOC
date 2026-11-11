import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

test('transfer controls and compact submission review', async ({ page }) => {
  test.setTimeout(120000)
  await page.setViewportSize({ width: 1440, height: 1000 })
  const errors = [];page.on('pageerror', e => errors.push(String(e)))
  await page.route('**/api/library/open-part', async route => {
    const response = await page.request.post('/api/design/load', { data: { path: process.env.NADOC_TEMPERATURE_SOURCE }, headers: route.request().headers() });await route.fulfill({ response })
  })
  await page.goto('/?debug=1&doc=__e2e__submit-review&open=2hb_1xT.nadoc&open-type=design')
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  if (!(await page.locator('#simulate-body').isVisible())) await page.click('#simulate-heading')
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.locator('#md-jobs-new-btn').click()
  const modal = page.locator('.modal--wizard:visible')
  for (const name of ['Upload Mbps', 'Download Mbps']) {
    const input = modal.getByRole('spinbutton', { name, exact: true })
    await expect(input).toBeVisible({ timeout: 60000 })
    expect(await input.evaluate(e => ({ background: getComputedStyle(e).backgroundColor, valid: e.checkValidity() }))).toEqual({ background: 'rgb(13, 17, 23)', valid: true })
  }
  await modal.getByRole('spinbutton', { name: 'Upload Mbps', exact: true }).scrollIntoViewIfNeeded()
  const ratesImage = path.join(process.env.NADOC_WORKSPACE, 'transfer-fields.png');await page.screenshot({ path: ratesImage });console.log('REVIEW_IMAGE', ratesImage);await page.waitForTimeout(15000)
  await modal.locator('.modal__actions button', { hasText: /Cancel|Close/ }).click()
  // Exercise the real review component with representative estimates; never submit a job.
  await page.evaluate(async () => {
    const { initMdSubmitReview } = await import('/src/ui/md_submit_review.js')
    window.__submitReview = initMdSubmitReview({ api: { getMdRemoteRecommendation: async () => ({
      prepared: true, design_name: '2hb_1xT · 200 ns production', n_atoms: 240000, total_ns: 200,
      image_clearance: { status: 'pass', requires_override: false, detail: 'Sufficient starting clearance.' },
      available_partitions: [{ name: 'ah200', kind: 'gpu', gpu_model: 'H200' }], available_qos: [{ name: 'gpu-normal', max_walltime_h: 24 }],
      resources: { partition: 'ah200', kind: 'gpu', cores: 8, gpus: 1, mem_gb: 32, walltime: '24:00:00', qos: 'gpu-normal', expected_ns_per_day: 240,
        completion: { available: true, known_hours: 22, low_hours: 20, high_hours: 28, cost: 176, low_cost: 160, high_cost: 224 } },
    }) } })
    await window.__submitReview.open('__e2e__review')
  })
  const review = page.getByRole('dialog', { name: 'Submit job review' })
  await expect(review.locator('[data-submit-metrics] > div')).toHaveCount(3)
  await expect(review.locator('#mr-edit')).toBeHidden()
  await expect(review.locator('#mr-image-clearance')).toBeHidden()
  await expect(review.getByRole('button', { name: 'Estimate details' })).toHaveAttribute('title', /System:/)
  const reviewImage = path.join(process.env.NADOC_WORKSPACE, 'submit-review.png');await page.screenshot({ path: reviewImage });console.log('REVIEW_IMAGE', reviewImage);await page.waitForTimeout(15000)
  await review.locator('#mr-edit-toggle').click()
  await expect(review.locator('#mr-cores')).toHaveValue('8')
  await review.locator('#mr-cores').fill('12')
  await review.locator('#mr-cancel').click()
  expect(errors).toEqual([])
  await fs.writeFile(path.join(process.env.NADOC_WORKSPACE, 'ui-verification.json'), JSON.stringify({ errors, transferFields: 'live wizard', review: 'real component with representative estimates; cancel only' }))
})
