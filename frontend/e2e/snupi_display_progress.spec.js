/** Read-only live proof for SNUPI's current-job predicted-shape display path. */
import { expect, test } from '@playwright/test'

const JOB = '6f32b88f5a06'
const DESIGN = '3x6x400_test'

async function openDesign(page) {
  await page.goto('/?doc=snupi-display-progress')
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click()
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 90_000 })
}

test('SNUPI predicted shape reports named subprocesses on the matching live scene', async ({ page }) => {
  test.setTimeout(150_000)
  const requests = []
  page.on('request', request => {
    if (request.url().includes(`/api/snupi/jobs/${JOB}/`)) requests.push(request.url())
  })
  await openDesign(page)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="snupi"]').click()
  const row = page.locator(`#snupi-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({ state: 'attached', timeout: 30_000 })
  await row.evaluate(el => el.click())
  const deform = page.locator('.snupi-display-mode[value="deform"]')
  await expect(deform).toBeEnabled({ timeout: 30_000 })
  await page.evaluate(() => {
    const root = document.getElementById('snupi-jobs-display-status')
    window.__snupiDisplayProgress = []
    window.__snupiDisplayTimeline = []
    const started = performance.now()
    const sample = () => {
      const text = root?.textContent?.replace(/\s+/g, ' ').trim()
      if (text && !window.__snupiDisplayProgress.includes(text)) {
        window.__snupiDisplayProgress.push(text)
        window.__snupiDisplayTimeline.push([Math.round(performance.now() - started), text])
      }
    }
    new MutationObserver(sample).observe(root, { childList: true, subtree: true, characterData: true })
  })
  const started = Date.now()
  await deform.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change')) })
  await expect(page.locator('#snupi-jobs-display-status')).toContainText('Showing predicted shape', { timeout: 90_000 })
  test.info().annotations.push({ type: 'elapsed-ms', description: String(Date.now() - started) })
  test.info().annotations.push({ type: 'phase-timeline-ms', description: JSON.stringify(await page.evaluate(() => window.__snupiDisplayTimeline)) })
  expect(requests.some(url => url.endsWith('/display-bin'))).toBe(true)
  expect(requests.some(url => url.endsWith('/display'))).toBe(false)
  expect(requests.some(url => url.includes('/snapshot-geometry'))).toBe(false)
  const progress = (await page.evaluate(() => window.__snupiDisplayProgress)).join('\n')
  expect(progress).toContain('Download predicted positions')
  expect(progress).toContain('Decode predicted positions')
  expect(progress).toContain('Transform display data')
  expect(progress).toContain('Reuse matching live scene')
  expect(progress).toContain('Apply visualization')
})
