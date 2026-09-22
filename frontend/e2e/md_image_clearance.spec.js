/** Read-only UI exercise: all cluster calls are stubbed; no jobs/files are created. */
import { test, expect } from '@playwright/test'

test('Alpine review blocks the P2-sized gap and sends an explicit independent override', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.evaluate(async () => {
    const { initMdSubmitReview } = await import('/src/ui/md_submit_review.js')
    window.__clearanceSubmissions = []
    window.__clearanceCard = initMdSubmitReview({ api: {
      getMdRemoteRecommendation: async () => ({ prepared: true, design_name: 'Clearance UI fixture',
        resources: { partition: 'ah200', qos: 'gpu-normal' },
        image_clearance: { status: 'insufficient', requires_override: true,
          axis_gaps_nm: [.571, .469, .637], recommended_gap_nm: 2.4,
          coordinate_source: 'equilibrated.coor', cell_source: 'equilibrated.xsc',
          detail: 'Fixed-pose envelope clearance; overall rotational diffusion is excluded.' } }),
      submitMdJobRemote: async (id, body) => {
        window.__clearanceSubmissions.push({ id, body }); return { slurm_job_id: 'test-only' }
      },
    }, toast: () => {} })
    await window.__clearanceCard.open('__e2e__clearance')
  })
  await expect(page.locator('#mr-image-clearance')).toContainText('0.57 / 0.47 / 0.64 nm')
  await expect(page.locator('#mr-go')).toBeDisabled()
  await page.locator('#mr-allow-small-image-gap').check()
  await expect(page.locator('#mr-go')).toBeEnabled()
  await page.locator('#mr-allow-small-image-gap').uncheck()
  await expect(page.locator('#mr-go')).toBeDisabled()
  await page.locator('#mr-allow-small-image-gap').check()
  await page.locator('#mr-go').click()
  await expect.poll(() => page.evaluate(() => window.__clearanceSubmissions.length)).toBe(1)
  expect(await page.evaluate(() => window.__clearanceSubmissions[0].body.allow_small_image_gap)).toBe(true)
  await page.evaluate(() => window.__clearanceCard.open('__e2e__clearance'))
  await expect(page.locator('#mr-go')).toBeDisabled()
  await page.locator('#mr-cancel').click()
  await expect(page.locator('#mr-image-clearance')).toHaveCount(0)
})
