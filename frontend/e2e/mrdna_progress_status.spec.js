import { test, expect } from '@playwright/test'

test('running mrDNA Fine job shows phase and actual progress', async ({ page }) => {
  const job = {
    job_id: 'fine-progress-e2e', design_name: 'fine-demo', status: 'running',
    created_at: Date.now() / 1000, coarse_steps: 100000, fine_steps: 200000,
    stages: [
      { name: 'coarse', steps: 100000, status: 'running' },
      { name: 'fine', steps: 200000, status: 'pending' },
    ],
  }
  await page.route('**/api/mrdna/available', r => r.fulfill({ json: { available: true, mrdna: true, arbd: true } }))
  await page.route('**/api/mrdna/jobs', r => r.fulfill({ json: [job] }))
  await page.route('**/api/mrdna/jobs/fine-progress-e2e/progress', r => r.fulfill({ json: {
    overall: 0.7, status: 'running', stage_status: 'running',
    stage_name: 'fine (twist)', stage_fraction: 0.75,
  } }))

  await page.goto('/')
  await page.evaluate(() => {
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden')
    document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
    window.__leftSidebar?.refresh?.()
  })
  await page.evaluate(() => {
    document.querySelector('#left-tab-strip [data-tab="dynamics"]')?.click()
    document.querySelector('.engine-selector-btn[data-engine="mrdna"]')?.click()
    document.getElementById('mrdna-jobs-list-toggle')?.click()
    const all = document.getElementById('mrdna-jobs-show-all')
    all.checked = true
    all.dispatchEvent(new Event('change'))
  })
  await expect(page.locator('#mrdna-jobs-list')).toContainText('fine-demo')
  await page.locator('#mrdna-jobs-list [data-job-id="fine-progress-e2e"]').evaluate(el => el.click())

  await expect(page.locator('#mrdna-jobs-detail-status')).toContainText('fine (twist) 70%')
  await expect(page.locator('#mrdna-jobs-timeline')).toHaveText('● coarse  ◐ fine')
  expect(await page.locator('#mrdna-jobs-progress .bar').evaluate(el => el.style.width)).toBe('70%')
})
