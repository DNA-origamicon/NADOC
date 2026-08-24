/** Read-only live proof for CanDo's representative-only, live-scene display path. */
import { expect, test } from '@playwright/test'

const JOB = '080f75d47c3d'
const DESIGN = '6hb_validated'

async function openDesign(page) {
  await page.goto('/?doc=cando-representative-progress')
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

test('CanDo predicted shape reuses the matching scene and reports named subprocesses', async ({ page }) => {
  test.setTimeout(120_000)
  const requests = []
  page.on('request', request => {
    if (request.url().includes(`/api/cando/jobs/${JOB}/`)) requests.push(request.url())
  })

  await openDesign(page)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="cando"]').click()
  const row = page.locator(`#cando-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({ state: 'attached', timeout: 30_000 })
  await row.evaluate(el => el.click())

  const deform = page.locator('.cando-display-mode[value="deform"]')
  await expect(deform).toBeEnabled({ timeout: 30_000 })
  await page.evaluate(() => {
    const root = document.getElementById('cando-jobs-display-status')
    window.__candoDisplayProgress = []
    window.__candoDisplayTimeline = []
    const started = performance.now()
    const sample = () => {
      const text = root?.textContent?.replace(/\s+/g, ' ').trim()
      if (text && !window.__candoDisplayProgress.includes(text)) {
        window.__candoDisplayProgress.push(text)
        window.__candoDisplayTimeline.push([Math.round(performance.now() - started), text])
      }
    }
    new MutationObserver(sample).observe(root, { childList: true, subtree: true, characterData: true })
    sample()
  })

  const started = Date.now()
  await deform.evaluate(el => { el.checked = true; el.dispatchEvent(new Event('change')) })
  await expect(page.locator('#cando-jobs-display-status')).toContainText(
    'representative 298 K thermal conformation', { timeout: 60_000 },
  )
  test.info().annotations.push({ type: 'elapsed-ms', description: String(Date.now() - started) })
  test.info().annotations.push({
    type: 'phase-timeline-ms',
    description: JSON.stringify(await page.evaluate(() => window.__candoDisplayTimeline)),
  })

  expect(requests.some(url => url.includes('/thermal-representative-bin'))).toBe(true)
  expect(requests.some(url => /\/thermal-representative(?:\?|$)/.test(url))).toBe(false)
  expect(requests.some(url => url.includes('/thermal-trajectory'))).toBe(false)
  expect(requests.some(url => url.endsWith('/display'))).toBe(false)
  expect(requests.some(url => url.includes('/snapshot-geometry'))).toBe(false)
  const progress = (await page.evaluate(() => window.__candoDisplayProgress)).join('\n')
  expect(progress).toContain('Download representative conformation')
  expect(progress).toContain('Decode representative conformation')
  expect(progress).toContain('Transform display data')
  expect(progress).toContain('Reuse matching live scene')
  expect(progress).toContain('Apply visualization')
})
