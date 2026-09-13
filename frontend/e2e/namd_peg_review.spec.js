import { test, expect } from '@playwright/test'
import { readFileSync, existsSync } from 'node:fs'
import path from 'node:path'

// Read-only user-requested persistent document/results. No test files are created.
// Dedicated backend disables session-cache writes; configured reporter clears images.
const file = path.resolve('..', 'workspace', 'NAMD_PEG8_wall_review.nadoc')
test('persistent PEG document and both successful native job trajectories are viewable', async ({ page }, info) => {
  test.skip(!existsSync(file), 'Run the native PEG qualification and publish its review first')
  test.setTimeout(60000)
  const design = JSON.parse(readFileSync(file, 'utf8'))
  const jobs = design.metadata.namd_peg_review.jobs
  expect(jobs).toHaveLength(2)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/?doc=__e2e__peg-qualification-readonly')
  await page.waitForSelector('#canvas')
  await page.locator('[data-library-path$="NAMD_PEG8_wall_review.nadoc"]').click()
  const card = page.getByRole('region', { name: 'Atomistic PEG qualification review' })
  await expect(card).toBeVisible()
  await expect(card).toHaveAttribute('data-atoms', '9092')
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('#engine-selector-mount').getByText('NAMD', { exact: true }).click()
  await expect(page.locator(`#simulate-jobs-list [data-job-id="${jobs[0].job_id}"]`)).toBeVisible()
  await card.getByRole('button', { name: 'Fit surface' }).click()
  await card.getByLabel('Show water oxygens').check()
  for (const job of jobs) {
    const response = await page.request.get(`/api/md/jobs/${job.job_id}`)
    expect(response.ok()).toBe(true)
    expect((await response.json()).status).toBe('completed')
    await card.getByLabel('PEG qualification job').selectOption(job.job_id)
    await expect(card).toHaveAttribute('data-frames', '10')
    await expect(card).toContainText(job.stage === 'resident' ? 'GPU-resident' : 'minimization')
    await card.getByRole('slider').fill('9')
    await expect(card).toContainText('Frame 10/10')
  }
  await card.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Pause' })).toBeVisible()
  await card.getByRole('button', { name: 'Pause' }).click()
  for (const job of jobs) {
    const row = page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`)
    await expect(row).toBeVisible()
    await row.click()
    await expect(card).toContainText(job.stage === 'resident' ? 'GPU-resident' : 'minimization')
  }
  await card.getByLabel('Show water oxygens').uncheck()
  if (process.env.NADOC_PEG_VISUAL_REVIEW === '1') {
    await page.screenshot({ path: info.outputPath('PEG_review.png') })
    await page.waitForTimeout(15000)
  }
  expect(errors).toEqual([])
})

test('standard NAMD visualization controls render PEG atoms and fixed-wall RMSF', async ({ page }, info) => {
  test.skip(!existsSync(file), 'Persistent qualification required')
  test.setTimeout(90000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  const dnaRequests = []
  page.on('request', request => {
    if (/\/md\/jobs\/654049290521\/(rmsf|trajectory|display|solvent)/.test(request.url())) dnaRequests.push(request.url())
  })
  await page.goto('/?doc=__e2e__peg-viz-readonly')
  await page.locator('[data-library-path$="NAMD_PEG8_wall_review.nadoc"]').click()
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('#engine-selector-mount').getByText('NAMD', { exact: true }).click()
  const card = page.getByRole('region', { name: 'Atomistic PEG qualification review' })
  await page.locator('#simulate-jobs-list [data-job-id="654049290521"]').click()
  await expect(card).toHaveAttribute('data-frames', '10')
  if (!await page.locator('#md-jobs-display-toggle').isVisible()) await page.locator('#md-jobs-viz-toggle').click()
  await page.locator('#md-jobs-display-toggle').check()
  await expect(card).toHaveAttribute('data-mode', 'display')
  await expect(card).toContainText('step 1000')
  await page.locator('#md-jobs-flex-toggle').check()
  await expect(card).toHaveAttribute('data-mode', 'flex')
  await expect(card.locator('.peg-rmsf-scale')).toContainText('Å · fixed surface frame')
  await page.locator('#canvas').click({ position: { x: 450, y: 100 } })
  await page.keyboard.press('F7')
  await expect(card).toHaveAttribute('data-representation', 'ballstick')
  await page.keyboard.press('F6')
  await expect(card).toHaveAttribute('data-representation', 'vdw')
  await page.keyboard.press('F4')
  await expect(card).toHaveAttribute('data-representation', 'full')
  await expect(page.locator('#md-jobs-water-toggle')).toBeDisabled()
  await expect(page.locator('#md-jobs-photoproduct-toggle')).toBeDisabled()
  await expect(page.locator('#md-jobs-photoproduct-status')).toContainText('no thymine')
  await expect(page.locator('#md-jobs-occupancy-toggle')).toBeDisabled()
  if (process.env.NADOC_PEG_VISUAL_REVIEW === '1') {
    await card.getByRole('button', { name: 'Fit surface' }).click()
    await page.screenshot({ path: info.outputPath('PEG_RMSF.png') })
    await page.waitForTimeout(15000)
  }
  await page.locator('#md-jobs-traj-toggle').check()
  await expect(card).toHaveAttribute('data-mode', 'traj')
  await page.locator('#md-jobs-traj-slider').fill('9')
  await expect(card).toContainText('Frame 10/10')
  await page.locator('#md-jobs-traj-prev').click()
  await expect(card).toContainText('Frame 9/10')
  await page.locator('#md-jobs-water-toggle').check()
  await page.locator('#md-jobs-water-scope-box').check()
  await expect(card).toHaveAttribute('data-water-atoms', '2944')
  await page.locator('#md-jobs-box-toggle').check()
  await page.locator('#md-jobs-viz-off').check()
  await expect(card).toHaveAttribute('data-mode', 'off')
  await expect(card).toContainText('Initial configuration')
  expect(dnaRequests).toEqual([])
  expect(errors).toEqual([])
})
