import { test, expect } from '@playwright/test'
import path from 'node:path'

// Read-only legacy fixture. All job data and DELETE responses are intercepted;
// no design, simulation job, or output file is authored. Only browser-local state
// and Playwright-managed output can persist; config disables session autosave.
test('confirmed deletion disappears before the server responds and returns on failure', async ({ page }) => {
  const job = { engine: 'oxdna', job_id: 'delete-ui', design_name: 'Delete UI',
    status: 'completed', created_at: 1, stages: [], kind: 'relax',
    design_source_path: null, current_stage_idx: 0 }
  let release, requested = false
  const response = new Promise(resolve => { release = resolve })
  await page.route('**/api/simulate/jobs*', route => route.fulfill({ json: [job] }))
  await page.route('**/api/oxdna/jobs**', async route => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'DELETE') {
      requested = true
      await response
      await route.fulfill({ status: 409, json: { detail: 'Test delete failed' } })
    } else if (url.pathname === '/api/oxdna/jobs') await route.fulfill({ json: [job] })
    else await route.fulfill({ json: url.pathname.endsWith('/submodel') ? { box: null } : job })
  })
  await page.goto('/?doc=__e2e__delete-ui')
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async designPath => {
    const api = await import('/src/api/client.js')
    if (!(await api.loadDesign(designPath))) throw new Error('Fixture load failed')
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip button').forEach(button => { button.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, path.resolve('..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('#engine-selector-mount').getByRole('tab', { name: 'oxDNA', exact: true }).click()
  const row = page.locator('#simulate-jobs-list [data-job-id="delete-ui"]')
  await row.click()
  await page.locator('#simulate-jobs-delete-btn').click()
  await expect(row).toBeVisible() // Still visible before confirmation.
  await page.locator('.modal__overlay').getByRole('button', { name: /^Delete/ }).click()
  await expect.poll(() => requested).toBe(true)
  await expect(row).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed')))
  await expect(row).toHaveCount(0)
  page.on('dialog', dialog => dialog.accept())
  release()
  await expect(row).toBeVisible()
})
