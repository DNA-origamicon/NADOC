import { test, expect } from '@playwright/test'
import fs from 'node:fs'

// Opt-in native evidence, copied into an isolated workspace by the caller.
// No molecular files are authored. The caller removes that workspace in finally;
// Playwright's cleanup reporter removes screenshots and traces even on failure.
test('NAMD submodel jobs restore their region and display native trajectories', async ({ page }, info) => {
  test.skip(!process.env.NADOC_NAMD_SUBMODEL_MANIFEST, 'Requires isolated native trials')
  test.setTimeout(480_000)
  page.setDefaultTimeout(30_000)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const trials = JSON.parse(fs.readFileSync(process.env.NADOC_NAMD_SUBMODEL_MANIFEST, 'utf8'))
  // Keep existing source documents read-only: use the diagnostic load route for
  // the file-open transport, while retaining the real workspace/sidebar lifecycle.
  // All job, region, trajectory and analysis routes remain unmocked.
  await page.route('**/api/library/open-part', async route => {
    const trial = trials.find(item => item.filename === route.request().postDataJSON().path)
    const response = await page.request.post('/api/design/load', {
      data: { path: trial.source }, headers: route.request().headers(),
    })
    await route.fulfill({ response })
  })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const trial of trials) {
    await page.goto(`/?doc=__e2e__namd-submodel-${trial.name}&open=${encodeURIComponent(trial.filename)}`)
    await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
    await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30_000 })
    for (const label of ['Close Feature log sidebar', 'Close Properties sidebar']) {
      const close = page.getByRole('button', { name: label, exact: true })
      if (await close.count()) await close.first().click()
    }
    await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
    await page.locator('.engine-selector-btn[data-engine="namd"]').click()
    if (trial.parent_job_id) await expect(page.locator(`[data-job-id="${trial.parent_job_id}"]:visible`).first()).toBeVisible({ timeout: 30_000 })
    await page.evaluate(async id => {
      await window.__nadocMdPanel.refresh()
      await window.__nadocMdPanel.selectJob(id)
    }, trial.job_id)
    await expect.poll(() => page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0]?.min_corner)).toEqual(trial.box.min_corner)
    const heading = page.locator('#md-box-solvent-toggle')
    if (!(await page.locator('#md-define-submodel').isVisible())) await heading.click()
    await expect(page.locator('#md-submodel-shell')).toHaveValue(String(trial.box.shell_nm))
    await expect(page.locator('#md-define-submodel')).toHaveAttribute('title', /surrounding shell/)
    await expect(page.locator('#md-submodel-controls')).toBeHidden()
    await page.locator('#md-box-view-details').check({ force: true })
    await page.locator('#md-define-submodel').click()
    await expect(page.locator('#md-submodel-controls')).toBeVisible()
    expect(await page.evaluate(() => window.__NADOC_SUBMODEL__.gizmoVisible())).toBe(true)
    await page.keyboard.press('Escape')
    // Escape also closes the sidebar; reopen it before using live-display controls.
    if (await page.locator('#tab-content-dynamics').evaluate(el => el.hidden)) {
      await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
    }
    await expect(page.locator('#tab-content-dynamics')).toBeVisible()
    await page.locator('#md-jobs-display-toggle').check({ force: true })
    await expect(page.locator('#md-jobs-display-status')).toContainText(/Displaying frame/i, { timeout: 45_000 })
    await page.evaluate(() => window.__nadocTest.setRepresentation('vdw'))
    await page.locator('#md-jobs-traj-interval').fill('1')
    await page.locator('#md-jobs-traj-interval').dispatchEvent('change')
    await page.locator('#md-jobs-traj-toggle').check({ force: true })
    await expect(page.locator('#md-jobs-traj-status')).toContainText(/frame|ready/i, { timeout: 45_000 })
    await expect.poll(() => page.evaluate(() => {
      let count = 0
      window.__nadocTest.getAtomisticRenderer().visitAtoms(() => count++)
      return count
    }), { timeout: 30_000 }).toBeGreaterThan(0)
    await expect(page.locator('#md-jobs-traj-play')).toBeEnabled({ timeout: 45_000 })
    const initialFrame = await page.locator('#md-jobs-traj-label').innerText()
    await page.locator('#md-jobs-traj-play').click()
    await expect(page.locator('#md-jobs-traj-label')).not.toHaveText(initialFrame, { timeout: 30000 })
    await page.locator('#md-jobs-traj-play').click()
    await page.evaluate(box => {
      const target = box.min_corner.map((x, i) => (x + box.max_corner[i]) / 2)
      const direction = [1, 0.2, 0.3] // Side view exposes helix length, rather than looking down its axis.
      const norm = Math.hypot(...direction)
      const distance = 3 * Math.max(...box.max_corner.map((x, i) => x - box.min_corner[i] + 2 * box.shell_nm))
      window.__nadocTest.applyCameraPoseForTest({ target, position: target.map((x, i) => x + distance * direction[i] / norm) })
    }, trial.box)
    await page.screenshot({ path: info.outputPath(`${trial.name}.png`) })
    if (process.env.NADOC_NAMD_SUBMODEL_REVIEW === '1') {
      console.log('REVIEW_IMAGE', info.outputPath(`${trial.name}.png`))
      await page.waitForTimeout(20_000)
    }
    if (trial.all_visualizations) {
      for (const representation of ['full', 'ballstick', 'vdw']) {
        await page.evaluate(rep => window.__nadocTest.setRepresentation(rep), representation)
        await page.waitForTimeout(500)
        await page.screenshot({ path: info.outputPath(`representation-${representation}.png`) })
      }
      await expect(page.locator('#md-jobs-water-toggle')).toBeDisabled()
      await page.locator('#md-jobs-display-toggle').check({ force: true })
      await expect(page.locator('#md-jobs-display-status')).toContainText(/Displaying frame/i, { timeout: 45000 })
      await expect(page.locator('#md-jobs-water-toggle')).toBeEnabled()
      await page.locator('#md-jobs-water-toggle').check()
      await expect(page.locator('#md-jobs-water-count')).toContainText(/molecules/i, { timeout: 45000 })
      await page.locator('#md-jobs-ions-toggle').check({ force: true })
      await expect(page.locator('#md-jobs-ions-legend')).toContainText(/Na|Cl/, { timeout: 45000 })
      await page.locator('#md-jobs-box-toggle').check({ force: true })
      await page.screenshot({ path: info.outputPath('solvent.png') })
      console.log('REVIEW_IMAGE', info.outputPath('solvent.png'))
      if (process.env.NADOC_NAMD_SUBMODEL_REVIEW) await page.waitForTimeout(20000)
      await page.locator('#md-jobs-water-toggle').uncheck({ force: true })
      await page.locator('#md-jobs-ions-toggle').uncheck({ force: true })
      await page.locator('#md-jobs-box-toggle').uncheck({ force: true })
      await page.locator('#md-jobs-flex-toggle').check({ force: true })
      await expect(page.locator('#md-jobs-flex-status')).toContainText('Avg structure', { timeout: 60000 })
      await expect(page.locator('#md-jobs-flex-legend')).toBeVisible()
      await page.screenshot({ path: info.outputPath('flexibility.png') })
      console.log('REVIEW_IMAGE', info.outputPath('flexibility.png'))
      if (process.env.NADOC_NAMD_SUBMODEL_REVIEW) await page.waitForTimeout(20000)
      await page.locator('#md-jobs-occupancy-toggle').check({ force: true })
      await expect(page.locator('#md-jobs-occupancy-status')).toContainText(/frames/, { timeout: 60000 })
      await page.locator('#md-jobs-occupancy-density').check({ force: true })
      await page.locator('#md-jobs-occupancy-rerun').click()
      await expect(page.locator('#md-jobs-occupancy-status')).toContainText(/frames/, { timeout: 60000 })
      await page.screenshot({ path: info.outputPath('occupancy.png') })
      console.log('REVIEW_IMAGE', info.outputPath('occupancy.png'))
      if (process.env.NADOC_NAMD_SUBMODEL_REVIEW) await page.waitForTimeout(20000)
      await page.locator('#md-jobs-photoproduct-toggle').check({ force: true })
      await expect(page.locator('#md-jobs-photoproduct-status')).toContainText('Ready', { timeout: 60000 })
      await expect(page.locator('#md-jobs-photoproduct-legend')).toBeVisible()
      await page.screenshot({ path: info.outputPath('propensity.png') })
      console.log('REVIEW_IMAGE', info.outputPath('propensity.png'))
      if (process.env.NADOC_NAMD_SUBMODEL_REVIEW) await page.waitForTimeout(20000)
      await expect(page.locator('#md-ion-paths-toggle')).toBeDisabled()
      await expect(page.locator('#md-ion-vector-field-toggle')).toBeDisabled()
    }
    await page.locator('#md-jobs-viz-off').check({ force: true })
  }
  // A completed job's inputs are immutable. Editing its region must become a
  // fresh setup that can actually be created, without a failed historical PUT.
  const trial = trials.at(-1)
  const frozenId = trial.parent_job_id
  const oldRow = page.locator(`#simulate-jobs-list [data-job-id="${frozenId}"]`)
  await oldRow.click()
  await expect(oldRow).toHaveCSS('background-color', 'rgb(42, 58, 74)')
  const original = await (await page.request.get(`/api/md/jobs/${frozenId}/submodel`)).json()
  const failedSaves = []
  page.on('response', response => {
    if (response.request().method() === 'PUT' && response.url().endsWith('/submodel') && !response.ok()) failedSaves.push(response.status())
  })
  await page.locator('#md-define-submodel').click()
  await page.locator('#md-submodel-shell').fill('2.4')
  await expect(page.locator('#md-submodel-shell')).toHaveValue('2.4')
  await page.locator('#md-submodel-shell').dispatchEvent('change')
  console.log('REGION_EDIT', await page.locator('#md-submodel').innerText())
  await expect(page.locator('#md-submodel')).toContainText('Submodel ready for new job.')
  await expect(oldRow).not.toHaveCSS('background-color', 'rgb(42, 58, 74)')
  await page.locator('#md-jobs-new-btn').click()
  console.log('NEW_JOB_OPENED')
  const wizard = page.locator('.modal--wizard')
  await expect(wizard).toBeVisible()
  await wizard.getByRole('button', { name: 'Next →', exact: true }).click()
  await wizard.getByRole('button', { name: 'Next →', exact: true }).click()
  const created = page.waitForResponse(response => response.request().method() === 'POST' && /\/api\/md\/jobs$/.test(response.url()))
  await wizard.getByRole('button', { name: 'Create job', exact: true }).click()
  console.log('CREATE_JOB_CLICKED')
  const response = await created
  expect(response.ok()).toBe(true)
  const job = await response.json()
  await expect(wizard).toBeHidden()
  await expect(page.locator('#md-submodel')).toContainText('Submodel saved to job.')
  const saved = await (await page.request.get(`/api/md/jobs/${job.job_id}/submodel`)).json()
  expect(saved.box.shell_nm).toBe(2.4)
  expect(saved.box.min_corner).toEqual(trial.box.min_corner)
  await page.evaluate(async ({ oldId, newId }) => {
    await window.__nadocMdPanel.selectJob(oldId)
    await window.__nadocMdPanel.selectJob(newId)
  }, { oldId: frozenId, newId: job.job_id })
  await expect(page.locator('#md-submodel-shell')).toHaveValue('2.4')
  expect(await (await page.request.get(`/api/md/jobs/${frozenId}/submodel`)).json()).toEqual(original)
  expect(failedSaves).toEqual([])
  if (trial.central_box) {
    const update = await page.request.put(`/api/md/jobs/${job.job_id}/submodel`, { data: { box: trial.central_box } })
    expect(update.ok()).toBe(true)
    // This isolated server disables session caching, and opening consumes the
    // URL's open parameter. Reopen the read-only source in the new page load.
    await page.goto(`/?doc=__e2e__namd-submodel-${trial.name}&open=${encodeURIComponent(trial.filename)}`)
    await page.waitForFunction(() => window.__nadocMdPanel && window.__NADOC_SUBMODEL__)
    await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 30_000 })
    await page.evaluate(() => window.__leftSidebar.selectTab('dynamics'))
    await page.locator('.engine-selector-btn[data-engine="namd"]').click()
    await page.evaluate(async id => {
      await window.__nadocMdPanel.refresh()
      await window.__nadocMdPanel.selectJob(id)
    }, job.job_id)
    await expect.poll(() => page.evaluate(() => window.__NADOC_SUBMODEL__.volumes()[0]?.min_corner)).toEqual(trial.central_box.min_corner)
    if (!(await page.locator('#md-define-submodel').isVisible())) await page.locator('#md-box-solvent-toggle').click()
    await page.locator('#md-box-view-details').check({ force: true })
    await page.locator('#md-define-submodel').click()
    await page.evaluate(box => {
      const target = box.min_corner.map((x, i) => (x + box.max_corner[i]) / 2)
      window.__nadocTest.applyCameraPoseForTest({ target, position: [target[0] + 55, target[1] + 12, target[2] + 10] })
    }, trial.central_box)
    await page.screenshot({ path: info.outputPath('central-box.png') })
    if (['1', 'central'].includes(process.env.NADOC_NAMD_SUBMODEL_REVIEW)) {
      console.log('REVIEW_IMAGE', info.outputPath('central-box.png'))
      await page.waitForTimeout(30_000)
    }
  }
  expect(errors).toEqual([])
})
