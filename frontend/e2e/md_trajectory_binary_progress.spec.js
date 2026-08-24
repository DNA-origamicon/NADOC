/** Read-only live proof for the NAMD compact trajectory and phase-progress path. */
import { expect, test } from '@playwright/test'

const JOB = 'c8bcf4c1406f'
const DESIGN = '2hb_1xT'

async function openDesign(page) {
  await page.goto('/?doc=md-trajectory-binary-progress')
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click()
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
}

test('NAMD View trajectory uses NTRJ and reports named subprocesses', async ({ page }) => {
  test.setTimeout(120_000)
  const requests = []
  page.on('request', request => {
    if (request.url().includes(`/api/md/jobs/${JOB}/trajectory`)) requests.push(request.url())
  })
  await openDesign(page)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  const row = page.locator(`#md-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({ state: 'attached', timeout: 30_000 })
  await row.evaluate(el => el.click())
  const toggle = page.locator('#md-jobs-traj-toggle')
  await expect(toggle).toBeEnabled({ timeout: 30_000 })

  await page.evaluate(() => {
    const root = document.getElementById('md-jobs-traj-load-progress')
    window.__mdTrajProgress = []
    const sample = () => {
      const text = root?.textContent?.replace(/\s+/g, ' ').trim()
      if (text && !window.__mdTrajProgress.includes(text)) window.__mdTrajProgress.push(text)
    }
    new MutationObserver(sample).observe(root, { childList: true, subtree: true, characterData: true })
    sample()
  })
  await toggle.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change')) })
  await expect(page.locator('#md-jobs-traj-status')).toContainText(/frames/, { timeout: 60_000 })

  expect(requests.some(url => url.includes('/trajectory-bin?stride=20'))).toBe(true)
  expect(requests.some(url => /\/trajectory\?stride=20(?:$|&)/.test(url))).toBe(false)
  const progress = (await page.evaluate(() => window.__mdTrajProgress)).join('\n')
  expect(progress).toContain('Download trajectory')
  expect(progress).toContain('Decode trajectory')
  expect(progress).toContain('Apply first frame')
  expect(progress).toMatch(/Open topology and trajectory files|Read and align NAMD frames/)
})
