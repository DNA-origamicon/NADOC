import { test, expect } from '@playwright/test'

// All API traffic is intercepted; jobs and edits exist only in browser-test memory.
test('saving a copied local draft as Alpine updates its launch control and target pane', async ({ page }) => {
  page.on('pageerror', error => console.error(error.message))
  let job = {
    job_id: '__e2e__draft_target', design_name: '__e2e__draft_target', status: 'draft',
    execution_target: 'local', created_at: 1785000000,
    prep_params: { execution_target: 'local', relax_preset: 'literature', threads: 8, fast: false, autostart: false, salt_mode: 'screening' },
  }
  const plan = {
    param_groups: [], stages: [], request: {}, totals: { n_stages: 0, total_steps: 0, total_ns: 0 },
    preset: { id: 'literature', label: 'Literature protocol' },
    conditions: [], deferred: [], retries: [], warnings: [],
  }
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname
    if (!pathname.startsWith('/api/')) return route.continue()
    const path = pathname.replace(/^\/api/, '')
    let body = {}
    if (path === '/md/jobs') body = [job]
    else if (path.endsWith('/settings') && route.request().method() === 'PUT') {
      const saved = route.request().postDataJSON()
      job = { ...job, execution_target: saved.execution_target, partition: saved.partition, prep_params: saved }
      body = job
    } else if (path === `/md/jobs/${job.job_id}`) body = job
    else if (path === '/md/namd-available') body = { available: true, namd_available: true, gmx_available: true }
    else if (path === '/md/queue') body = { jobs: [] }
    else if (path === '/cluster/status') body = { state: 'connected', connected: true }
    else if (path === '/cluster/availability') body = { partitions: [{ partition: 'ah200', gpu_model: 'NVIDIA H200', gpus_free: 6, gpus_total: 16, wait_label: '~0 min', speed_factor: 2.5 }] }
    else if (path === '/md/protocol-plan') body = plan
    else if (path === '/md/relax-presets') body = { presets: [{ id: 'literature', label: 'Literature protocol' }] }
    else if (path.includes('/hardware')) body = { gpu_name: 'RTX 3090', summary: 'RTX 3090' }
    else if (path.includes('slurm')) body = { resources: {} }
    await route.fulfill({ json: body })
  })
  await page.route('**/__e2e__draft_target', route => route.fulfill({ contentType: 'text/html', body: `
    <div id="md-jobs-panel"><div id="md-jobs-panel-body">
      <div id="md-jobs-list"></div><div id="md-jobs-detail"></div>
      <span id="md-jobs-namd-status"></span><button id="md-jobs-run-btn"></button>
      ${['local', 'alpine', 'runpod'].map(t => `<input type="radio" name="md-run-target" id="md-run-target-${t}"><div id="md-jobs-${t}-pane"></div>`).join('')}
    </div></div><script type="module">
      import { initMdJobsPanel } from '/src/ui/md_jobs_panel.js';
      window.panel = initMdJobsPanel({ getClusterState: () => 'connected' });
    </script>` }))
  await page.goto('/__e2e__draft_target')
  await page.waitForFunction(() => !!window.panel)
  await page.evaluate(() => window.panel.selectJob('__e2e__draft_target'))
  const run = page.locator('#md-jobs-run-btn')
  await expect(run).toHaveText('▶ Run')
  for (const target of ['alpine', 'local']) {
    await page.evaluate(() => window.panel.openJobSettings('__e2e__draft_target'))
    await page.locator(`.wiz-target-card[data-target="${target}"] > div`).first().click()
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:cluster-state-change', { detail: { state: 'connected' } })))
    await page.locator('.wizard-tab').last().click()
    await page.getByRole('button', { name: 'Save changes', exact: false }).click()
    await expect(run).toHaveText(target === 'alpine' ? '☁ Submit to Alpine' : '▶ Run')
    await expect(run).toBeEnabled()
    await expect(page.locator(`#md-run-target-${target}`)).toBeChecked()
    await expect(page.locator(`#md-jobs-${target}-pane`)).not.toHaveAttribute('hidden')
    expect(job.execution_target).toBe(target)
  }
})
