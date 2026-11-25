import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Browser-only fixtures: intercept all API/WebSocket traffic. No designs, jobs,
// sessions, or simulation files are created. Config reporter cleans test output.
test('remote skip controls explain resubmission; local toggle remains live', async ({ page }) => {
  const jobs = ['alpine', 'runpod', 'local'].map(execution_target => ({
    job_id: `__e2e__skip_${execution_target}`, design_name: `__e2e__skip_${execution_target}`,
    execution_target, status: 'running', early_stop_relax: false,
    early_stop_pending: execution_target === 'local' ? null : true,
    created_at: 1795450000, segments: [], health_samples: [],
  }))
  const toggles = []
  await page.routeWebSocket('**/*', () => {})
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    if (!pathname.startsWith('/api/')) return route.continue()
    const path = pathname.replace(/^\/api/, '')
    let body = {}
    if (path === '/md/jobs') body = jobs
    else if (path.endsWith('/early-stop')) {
      toggles.push(path)
      body = { ok: true, early_stop_relax: true, running: true }
    } else if (jobs.some(j => path === `/md/jobs/${j.job_id}`)) {
      body = jobs.find(j => path === `/md/jobs/${j.job_id}`)
    } else if (path === '/md/namd-available') body = { available: true, namd_available: true, gmx_available: true }
    else if (path === '/md/queue') body = { jobs: [] }
    await route.fulfill({ json: body })
  })
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
  const card = html.match(/<div class="ox-card" id="md-jobs-live-controls"[\s\S]*?<\/label>[\s\S]*?<\/div>\s*<\/div>\s*<\/div>/)[0]
  await page.route('**/__e2e__skip_controls', route => route.fulfill({ contentType: 'text/html', body: `
    <div id="md-jobs-panel"><div id="md-jobs-panel-body">
      <div id="md-jobs-list"></div><div id="md-jobs-detail"></div>
      <span id="md-jobs-namd-status"></span><button id="md-jobs-run-btn"></button>
    </div></div>${card}<script type="module">
      import { initMdJobsPanel } from '/src/ui/md_jobs_panel.js';
      window.panel = initMdJobsPanel();
    </script>` }))
  await page.goto('/__e2e__skip_controls')
  await page.waitForFunction(() => !!window.panel)
  const toggle = page.locator('#md-jobs-early-stop')
  for (const target of ['alpine', 'runpod']) {
    await page.evaluate(target => window.panel.selectJob(`__e2e__skip_${target}`), target)
    await expect(toggle).toBeVisible()
    await expect(toggle).toBeDisabled()
    await expect(toggle).not.toBeChecked()
    await expect(page.locator('#md-jobs-early-stop-note')).toContainText('set at submission')
    await expect(page.locator('#md-jobs-early-stop-note')).toContainText(target === 'alpine' ? 'Alpine' : 'RunPod')
    await expect(page.locator('#md-jobs-early-stop-pending')).toBeHidden()
    await toggle.dispatchEvent('change')
  }
  expect(toggles).toEqual([])
  await page.evaluate(() => window.panel.selectJob('__e2e__skip_local'))
  await expect(toggle).toBeEnabled()
  await expect(page.locator('#md-jobs-early-stop-note')).toContainText('next checkpoint')
  await toggle.check()
  await expect.poll(() => toggles).toEqual(['/md/jobs/__e2e__skip_local/early-stop'])
  await expect(toggle).toBeDisabled()
})
