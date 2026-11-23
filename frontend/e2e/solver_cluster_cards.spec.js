import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

import { execFileSync } from 'node:child_process'
import path from 'node:path'

// Persistence inventory: authoring helpers save only __e2e__solver_cluster_* parts,
// assembly autosaves and their project revisions; global-teardown removes those
// on failure too. Session cache is disabled by the smoke config. All remote/job
// creation calls are intercepted, so there are no native jobs, pods or credentials.
// Browser localStorage dies with its isolated context. Traces use configured output.
for (const host of ['part', 'assembly']) {
  test(`${host}: SNUPI and mrDNA submit the selected cluster with current solver options`, async ({ page }) => {
    test.setTimeout(120000)
    const requests = []
    page.on('response', async response => { if (response.status() >= 400 && response.url().includes('/api/')) console.log('API ERROR', response.url(), await response.text()) })
    page.on('pageerror', error => console.log('APP ERROR:', error.message))
    await page.route('**/api/simulate/jobs**', route => route.fulfill({ json: [] }))
    await page.route(/\/api\/(oxdna|md|cando|blade|lammps)\/jobs(?:\?.*)?$/, route => route.fulfill({ json: [] }))
    await page.route('**/api/cluster/availability**', route => route.fulfill({ json: { partitions: [{ partition: 'aa100', gpus_free: 2, gpus_total: 4, wait_min: 15, wait_basis: 'recent queue history' }] } }))
    await page.route('**/api/cluster/status', route => route.fulfill({ json: { state: 'connected', who: 'test@alpine', host: 'test' } }))
    await page.route('**/api/runpod/status', route => route.fulfill({ json: { connected: false } }))
    await page.route('**/api/solver-cluster/runpod-check', route => route.fulfill({ json: { ok: false, checks: [] } }))
    await page.route('**/api/solver-cluster/runpod-options**', route => route.fulfill({ json: { gpus: [{ id: 'test-gpu', display: 'Test GPU', vram_gb: 24, on_demand: .5, stock: 'High' }] } }))
    for (const engine of ['snupi', 'mrdna']) {
      await page.route(`**/api/${engine}/jobs`, async route => {
        if (route.request().method() !== 'POST') return route.fulfill({ json: [] })
        requests.push({ engine, body: route.request().postDataJSON() })
        await route.fulfill({ json: { job_id: `__e2e__${engine}`, status: 'failed', error: 'UI contract only; no remote launch', stages: [] } })
      })
      await page.route(`**/api/${engine}/jobs/__e2e__${engine}/progress`, route => route.fulfill({ json: { overall: 0, status: 'failed' } }))
    }
    const errors = trackConsoleErrors(page)
    const options = { doc: `__e2e__solver_cluster_${host}`, name: `solver_cluster_${host}` }
    const partPath = path.resolve(process.env.NADOC_WORKSPACE || '../workspace', `__e2e__${options.name}_part.nadoc`)
    // Native user-facing bundle command, independently replayed before publication.
    execFileSync('.venv/bin/python', ['-c', `
import sys
from uuid import uuid4
from experiments.recorded_review_process import Process
from scripts.agent_structure_guard import publish
p = Process('__e2e__solver_cluster_${host}')
p.append('bundle-create', {'_proof_version': 1, 'history_seed': str(uuid4()),
    'cells': [[0, 0]], 'length_bp': 32, 'name': '__e2e__solver_cluster_${host}',
    'lattice_type': 'HONEYCOMB', 'ligate_adjacent': False}, 'Create helix')
publish(p.design, sys.argv[1])
`, partPath], { cwd: '..', env: { ...process.env, PYTHONPATH: '.' } })
    await page.goto(`/?doc=${options.doc}&open=${encodeURIComponent(partPath)}`)
    await page.waitForFunction(() => !!window.__nadocTest)
    await expect(page.locator('.left-tab-btn[data-tab="dynamics"]')).toBeEnabled({ timeout: 30000 })
    await page.evaluate(async ({ partPath, host }) => {
      const api = await import('/src/api/client.js')
      if (host === 'assembly') {
        await api.createAssembly('__e2e__solver_cluster_assembly')
        for (let i = 0; i < 2; i++) {
          if (!await api.addInstance({ source: { type: 'file', path: partPath }, name: `Part ${i + 1}`,
            transform: { values: [1, 0, 0, 25 * i, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] } })) throw new Error(api.lastErrorMessage())
        }
        await window.__nadocTest.enterAssemblyMode()
      }
    }, { partPath, host })
    await expect(page.locator('#welcome-screen')).not.toBeVisible()
    while (await page.locator('.sidebar-close:visible').count()) await page.locator('.sidebar-close:visible').first().click()
    await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
    if (!(await page.locator('#simulate-body').isVisible())) await page.locator('#simulate-heading').click()
    for (const engine of ['snupi', 'mrdna']) {
      await page.locator(`.engine-selector-btn[data-engine="${engine}"]`).click()
      const card = page.locator(`#${engine}-cluster-card`)
      await expect(card).toBeVisible()
      const titles = await page.locator(`#${engine}-jobs-body > .ox-card > .ox-card__header .ox-card__title`).allTextContents()
      expect(titles.slice(0, 3)).toEqual(['Jobs', 'Clusters', 'Advanced'])
      await expect(card.locator('.ox-card__chevron')).toBeVisible()
      await expect(card.locator('input[type=radio]')).toHaveCount(3)
      const position = await card.evaluate(node => {
        const jobs = document.getElementById('simulate-jobs')
        return jobs.getBoundingClientRect().bottom <= node.getBoundingClientRect().top
      })
      expect(position).toBe(true)
      await page.locator(`#${engine}-run-target-alpine`).check()
      await card.locator(`#${engine}-jobs-alpine-pane summary`).click()
      await page.locator(`#${engine}-cluster-python`).fill('/remote/venv/bin/python')
      if (engine === 'mrdna') await page.locator(`#${engine}-cluster-arbd`).fill('/remote/bin/arbd')
      await expect(card.getByRole('button', { name: /Connected|test@alpine/ })).toBeVisible()
      await page.locator(`#${engine}-jobs-coarse-btn`).click()
      await expect(page.getByRole('dialog').getByText('Est. completion', { exact: true })).toBeVisible()
      await page.getByRole('dialog').getByRole('button', { name: 'Review resources' }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Submit job', exact: true }).click()
      await expect.poll(() => requests.filter(r => r.engine === engine).length).toBe(1)
      const alpine = requests.at(-1).body
      expect(alpine.execution_target).toBe('alpine')
      expect(alpine.cluster_settings.mem_gb).toBe(engine === 'snupi' ? 64 : 32)
      expect(engine === 'snupi' ? alpine.nonlinear : alpine.fine_steps).toBe(engine === 'snupi' ? false : 0)
      await page.locator(`#${engine}-run-target-runpod`).check()
      await card.getByRole('button', { name: 'Check RunPod GPUs' }).click()
      await card.locator('.runpod-gpu-row[data-key="test-gpu"]').click()
      await page.locator(`#${engine}-jobs-coarse-btn`).click()
      await expect(page.getByRole('dialog').getByText('Est. completion', { exact: true })).toBeVisible()
      await page.getByRole('dialog').getByRole('button', { name: 'Review resources' }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Rent pod and start' }).click()
      await expect.poll(() => requests.filter(r => r.engine === engine).length).toBe(2)
      expect(requests.at(-1).body).toMatchObject({ execution_target: 'runpod', runpod_settings: { gpu_id: 'test-gpu', budget_usd: 5, quoted_rate: .5 } })
    }
    // Reopen the saved input and independently replay the actual assembly log.
    execFileSync('.venv/bin/python', ['-m', 'scripts.agent_structure_guard', partPath], { cwd: '..' })
    if (host === 'assembly') {
      const content = await page.evaluate(async () => (await import('/src/api/client.js')).getAssemblyContent())
      execFileSync('.venv/bin/python', ['-c', `
import sys
from backend.core.models import Assembly
from backend.api.assembly import _replay_assembly_op
saved = Assembly.from_json(sys.stdin.read())
replayed = Assembly()
assert len(saved.feature_log) == 2
for row in saved.feature_log:
    replayed = _replay_assembly_op(replayed, row.op_kind, row.params)
assert len(replayed.instances) == len(saved.instances)
for actual, expected in zip(replayed.instances, saved.instances):
    # Adaptive renderer representation is presentation, not construction.
    a = actual.model_dump(exclude={'representation'})
    e = expected.model_dump(exclude={'representation'})
    differences = {key: [a[key], e[key]] for key in a if a[key] != e[key]}
    assert not differences, differences
assert replayed.joints == saved.joints
`], { cwd: '..', input: content })
    }
    expect(errors, errors.join('\n')).toEqual([])
  })
}
