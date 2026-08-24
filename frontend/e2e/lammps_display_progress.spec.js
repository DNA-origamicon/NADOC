/** Read-only live proof for the LAMMPS fallback final-structure display. */
import { expect, test } from '@playwright/test'

const JOB = '3bb1b170da66'
const DESIGN = '6hbx100_noT'

test('LAMMPS final display reports its processing phases', async ({ page }) => {
  test.setTimeout(150_000)
  const requests = []
  const trajectoryRequests = []
  page.on('request', request => {
    if (request.url().includes(`/api/lammps/jobs/${JOB}/display`)) requests.push(request.url())
    if (request.url().includes(`/api/lammps/jobs/${JOB}/trajectory`)) trajectoryRequests.push(request.url())
  })
  await page.goto('/?doc=lammps-display-progress')
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  if (await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click()
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 90_000 })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  const row = page.locator(`#simulate-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({ state: 'visible', timeout: 30_000 })
  await row.click()
  const display = page.locator('#oxdna-jobs-display-toggle')
  await expect(display).toBeEnabled({ timeout: 30_000 })
  await page.evaluate(() => {
    window.__lammpsDisplayPhases = []
    const target = document.getElementById('oxdna-jobs-display-status')
    new MutationObserver(() => {
      for (const row of target?.querySelectorAll('[data-lammps-display-phase]') ?? []) {
        window.__lammpsDisplayPhases.push(row.dataset.lammpsDisplayPhase)
      }
    }).observe(target, { childList: true, subtree: true, characterData: true })
  })
  const started = Date.now()
  await display.check()
  await expect(page.locator('#oxdna-jobs-display-status')).toContainText('Showing the final structure', { timeout: 90_000 })
  test.info().annotations.push({ type: 'elapsed-ms', description: String(Date.now() - started) })
  const phases = await page.evaluate(() => [...new Set(window.__lammpsDisplayPhases)])
  expect(phases).toEqual(expect.arrayContaining(['final-frame', 'transform', 'apply']))
  expect(requests).toHaveLength(1)

  const rmsfStarted = Date.now()
  await page.evaluate(() => {
    window.__lammpsRmsfPhases = []
    const target = document.getElementById('oxdna-jobs-flex-status')
    new MutationObserver(() => {
      for (const row of target?.querySelectorAll('[data-lammps-display-phase]') ?? []) {
        window.__lammpsRmsfPhases.push(row.dataset.lammpsDisplayPhase)
      }
    }).observe(target, { childList: true, subtree: true, characterData: true })
  })
  await page.locator('#oxdna-jobs-flex-toggle').check()
  await expect(page.locator('#oxdna-jobs-flex-status')).toContainText('Avg structure', { timeout: 90_000 })
  test.info().annotations.push({ type: 'rmsf-elapsed-ms', description: String(Date.now() - rmsfStarted) })
  const rmsfPhases = await page.evaluate(() => [...new Set(window.__lammpsRmsfPhases)])
  expect(rmsfPhases).toEqual(expect.arrayContaining(['rmsf-analysis', 'transform', 'apply']))

  await page.evaluate(() => {
    window.__lammpsDeviationPhases = []
    const target = document.getElementById('oxdna-jobs-deviation-status')
    new MutationObserver(() => {
      for (const row of target?.querySelectorAll('[data-lammps-display-phase]') ?? []) {
        window.__lammpsDeviationPhases.push(row.dataset.lammpsDisplayPhase)
      }
    }).observe(target, { childList: true, subtree: true, characterData: true })
  })
  await page.locator('#oxdna-jobs-deviation-toggle').check()
  await expect(page.locator('#oxdna-jobs-deviation-status')).toContainText('Mean vs design', { timeout: 90_000 })
  const deviationPhases = await page.evaluate(() => [...new Set(window.__lammpsDeviationPhases)])
  expect(deviationPhases).toEqual(expect.arrayContaining(['deviation-analysis', 'transform', 'apply']))

  const trajectoryStarted = Date.now()
  await page.evaluate(() => {
    window.__lammpsTrajectoryPhases = []
    const target = document.getElementById('oxdna-jobs-traj-status')
    new MutationObserver(() => {
      for (const row of target?.querySelectorAll('[data-lammps-display-phase]') ?? []) {
        window.__lammpsTrajectoryPhases.push(row.dataset.lammpsDisplayPhase)
      }
    }).observe(target, { childList: true, subtree: true, characterData: true })
  })
  await page.locator('#oxdna-jobs-traj-toggle').check()
  await expect(page.locator('#oxdna-jobs-traj-status')).toContainText('frames — play or scrub', { timeout: 90_000 })
  test.info().annotations.push({ type: 'trajectory-elapsed-ms', description: String(Date.now() - trajectoryStarted) })
  const trajectoryPhases = await page.evaluate(() => [...new Set(window.__lammpsTrajectoryPhases)])
  expect(trajectoryPhases).toEqual(expect.arrayContaining([
    'trajectory-download', 'trajectory-decode', 'transform', 'apply',
  ]))
  expect(trajectoryRequests).toHaveLength(1)
  expect(trajectoryRequests[0]).toContain('/trajectory-bin')
})
