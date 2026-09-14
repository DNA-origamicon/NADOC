import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import path from 'node:path'

// Inventory: reads the persistent PEG review; creates ONE prepared MD child through
// the UI. afterEach deletes that exact child's job directory through the API, even
// after failure. No engine is launched. Dedicated backend disables session cache.
let child
let creation

test.afterEach(async ({ request }) => {
  if (!child && creation) { try { child = (await creation).job_id } catch {} }
  if (child) {
    const response = await request.delete(`/api/md/jobs/${child}`)
    expect(response.ok()).toBe(true)
    expect((await request.get(`/api/md/jobs/${child}`)).status()).toBe(404)
  }
  child = null; creation = null
})

test('PEG review prepares a managed fast relax child and exposes normal Run controls', async ({ page }) => {
  test.skip(!existsSync(path.resolve('..', 'workspace/NAMD_PEG8_wall_review.nadoc')), 'Persistent qualification required')
  test.setTimeout(60000)
  await page.goto('/?doc=__e2e__peg-fast-readonly')
  await page.locator('[data-library-path$="NAMD_PEG8_wall_review.nadoc"]').click()
  const card = page.getByRole('region', { name: 'Atomistic PEG qualification review' })
  await expect(card).toBeVisible()
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('#engine-selector-mount').getByText('NAMD', { exact: true }).click()
  creation = page.waitForResponse(r => r.url().endsWith('/fast-relax') && r.request().method() === 'POST').then(r => r.json())
  await card.getByRole('button', { name: 'Create fast relax job' }).click()
  const job = await creation; child = job.job_id
  expect(job.protocol).toBe('peg_fast_relax')
  expect(job.early_stop_relax).toBe(true)
  expect(job.status).toBe('queued')
  await expect(card).toContainText('Use Run in Simulations')
  await expect(page.locator(`#simulate-jobs-list [data-job-id="${child}"]`)).toBeVisible()
  // A prepared package uses the ordinary managed Run button, not the DNA builder.
  await expect(page.locator('#simulate-jobs-run-btn')).toBeEnabled()
  const validation = page.locator('#simulate-jobs-list [data-job-id="ab217dbdf612"]')
  await expect(validation).toBeVisible()
  await validation.click()
  const stages = card.getByLabel('PEG relaxation stage')
  await expect(stages).toBeVisible()
  await stages.selectOption('peg_warm_p100')
  await expect(card).toContainText('peg_warm_p100')
  await expect(card).toHaveAttribute('data-frames', '31')
  await stages.selectOption('peg_relax_p100')
  await expect(card).toContainText('peg_relax_p100')
  if (!await page.locator('#md-jobs-traj-toggle').isVisible()) await page.locator('#md-jobs-viz-toggle').click()
  await page.locator('#md-jobs-traj-toggle').check()
  await expect(card).toHaveAttribute('data-mode', 'traj')
  await card.getByRole('slider').fill('5')
  await expect(card).toContainText('Frame 6/')
})
