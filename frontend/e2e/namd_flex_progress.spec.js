/** Read-only flex regression using the reported completed job when available. */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const JOB = '9b1151dfca21'
test('flex progress remains visible through an atomistic representation switch', async ({ page }) => {
  test.skip(!existsSync(fileURLToPath(new URL(`../../workspace/md_jobs/${JOB}/job.json`, import.meta.url))))
  test.setTimeout(300_000)
  const requests = []
  page.on('request', r => { if (r.url().includes(`/md/jobs/${JOB}/`)) requests.push(r.url()) })
  await page.goto('/?doc=__e2e__namd_flex_progress&open=3x6SQ_norm_skips.nadoc&impostors=1')
  await page.waitForFunction(() => !!window.__nadocTest && !!window.__nadocMdPanel)
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 60_000 })
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  await page.evaluate(id => window.__nadocMdPanel.selectJob(id), JOB)
  const toggle = page.locator('#md-jobs-flex-toggle')
  await expect(toggle).toBeEnabled()
  await toggle.check({ force: true })
  const bar = page.locator('#md-jobs-flex-bar')
  await expect(bar.locator('[role="progressbar"]')).toBeAttached()
  await expect(bar).toContainText('%')
  await expect(bar).toContainText('ready', { timeout: 150_000 })
  console.log('FLEX_BEADS_READY')
  const before = requests.length
  const started = Date.now()
  await page.evaluate(() => { void window.__nadocTest.setRepresentation('vdw') })
  await expect(bar.locator('[role="progressbar"]')).toBeAttached({ timeout: 30_000 })
  await expect(bar).toContainText('%')
  await expect(bar).toContainText('ready', { timeout: 60_000 })
  console.log('FLEX_ATOMISTIC_SWITCH_MS', Date.now() - started)
  const drawn = await page.evaluate(() => {
    const renderer = window.__nadocTest.getAtomisticRenderer()
    let count = 0
    renderer.visitAtoms(() => count++)
    return { count, mode: renderer.getMode() }
  })
  expect(drawn).toEqual({ count: 149666, mode: 'vdw' })
  const atomisticRequests = requests.slice(before)
  expect(atomisticRequests.some(u => u.endsWith('/rmsf-atomistic'))).toBe(true)
  expect(atomisticRequests.some(u => /\/atomistic-model(?:-bin)?$/.test(u))).toBe(false)
})
