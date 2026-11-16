import { test, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { createGuide } from './capture.js'
import { designState, fitOblique } from './workflow.js'
import { createCadnanoSource } from './cadnano-source.js'

// Real local jobs only. All saved documents/jobs belong to the generator's owned
// scratch root. afterEach stops jobs even on failure; the generator finally
// stops remaining owned processes and removes the entire scratch workspace.
const jobs = new Set()
test.afterEach(async ({ request }) => {
  for (const id of jobs) {
    await request.post(`http://127.0.0.1:8019/api/oxdna/jobs/${id}/stop`)
    await expect.poll(async () => {
      const r = await request.get(`http://127.0.0.1:8019/api/oxdna/jobs/${id}`)
      return r.status() === 404 || ['completed', 'failed', 'stopped', 'queued'].includes((await r.json()).status)
    }, { timeout: 30000 }).toBe(true)
  }
  jobs.clear()
})

// Frame the actual rendered beads through ordinary camera input. All runtime
// geometry queries below are read-only; no camera or molecular state is set.
async function frameModel(page) {
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650); await page.mouse.wheel(0, 400)
  for (let attempt = 0; attempt < 16; attempt++) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const bounds = await page.evaluate(() => {
      const points = window.__nadocTest.getBackboneBeadScreenPositions(20000)
      if (!points.length) return null
      const canvas = document.querySelector('#canvas').getBoundingClientRect()
      const xs = points.map(p => p.x), ys = points.map(p => p.y)
      const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys)
      return { x: (left + right)/2, y: (top + bottom)/2,
        tx: canvas.left + canvas.width/2, ty: canvas.top + canvas.height/2,
        size: Math.max(right-left, bottom-top) }
    })
    expect(bounds).toBeTruthy()
    if (Math.hypot(bounds.x-bounds.tx, bounds.y-bounds.ty) > 20) {
      await page.mouse.move(bounds.tx, bounds.ty)
      await page.mouse.down({ button: 'middle' })
      await page.mouse.move(bounds.tx + bounds.tx-bounds.x, bounds.ty + bounds.ty-bounds.y, { steps: 10 })
      await page.mouse.up({ button: 'middle' })
    }
    if (bounds.size >= 460 && bounds.size <= 680) return
    await page.mouse.move(bounds.tx, bounds.ty)
    await page.mouse.wheel(0, bounds.size < 460 ? -50 : 50)
  }
  throw new Error('Could not frame the rendered molecule at a readable scale')
}

test('cadnano to local oxDNA production guide', async ({ page, request }) => {
  const output = process.env.NADOC_GUIDE_OUTPUT
  const guide = await createGuide(page, output, 'From cadnano to a local oxDNA production simulation')
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  const cadnanoFile = await createCadnanoSource(page, output)
  await page.goto('/?doc=__e2e__cadnano-local-oxdna')
  await expect(page.locator('#canvas')).toBeVisible()
  // Count trusted clicks independently of screenshot numbers. Camera gestures
  // and keyboard input are separately scoped, not disguised as button clicks.
  await page.evaluate(() => {
    window.__guideClicks = null
    document.addEventListener('pointerdown', e => {
      if (!e.isTrusted || e.button !== 0 || !window.__guideClicks) return
      const control = e.target.closest('button, input, select, [role="button"], .ox-card__header')
      if (control) window.__guideClicks.push({ id: control.id || null, detail: e.detail, tag: control.tagName,
        label: (control.getAttribute('aria-label') || control.innerText || control.name || '').trim().replace(/\s+/g, ' ') })
    }, true)
  })
  guide.section('Import the cadnano design', 'Start with NADOC and a working local oxDNA installation. This example uses 6hb84-cadnano.json, exported from a NADOC honeycomb 6HB routed to 84 bp from a 63 bp extrusion using Seamed Autoscaffold and Standard Full Autostaple. Keep source.nadoc with the example family to retain the upstream construction history. The captured machine has a CUDA-capable NVIDIA GPU. Local CPU MD is available through the MD backend setting when needed.')
  await guide.click(page.locator('#menu-item-import > button'), 'Open the Import menu.')
  const chooser = page.waitForEvent('filechooser')
  await guide.click(page.locator('#menu-file-import-cadnano'), 'Choose caDNAno and select the supplied 6hb84-cadnano.json file.')
  await (await chooser).setFiles(cadnanoFile)
  const imported = page.waitForResponse(r => new URL(r.url()).pathname === '/api/design/import/cadnano' && r.request().method() === 'POST')
  await guide.click(page.locator('.origami-import-options').getByRole('button', { name: 'Import design', exact: true }), 'Leave Relax after import (experimental) unchecked and click Import design. The oxDNA relaxation is configured later.')
  expect((await imported).ok()).toBe(true)
  await page.evaluate(() => { window.__guideClicks = [] })
  await page.getByPlaceholder('filename', { exact: true }).fill('__e2e__cadnano-local-oxdna')
  await guide.click(page.getByRole('button', { name: 'Save', exact: true }), 'Save the imported part with a descriptive name. The capture uses a temporary example name.')
  await expect(page.getByRole('button', { name: 'Save', exact: true })).not.toBeVisible()
  await expect.poll(async () => (await designState(page))?.helices?.length).toBe(6)
  await fitOblique(page)
  await frameModel(page)
  await expect(page.locator('.toast-message')).toHaveCount(0, { timeout: 15000 })
  await guide.capture('Press F to fit and right-drag to orbit. Inspect the imported scaffold, staples, crossovers and both ends in Full representation.')
  await page.mouse.move(1100, 650)
  await page.mouse.down({ button: 'right' }); await page.mouse.move(1400, 750, { steps: 20 }); await page.mouse.up({ button: 'right' })
  await frameModel(page)
  await guide.capture('Orbit to the reverse side to inspect the back helices and terminal connections. Import preserves the cadnano routing; resolve any routing problems before simulation.')

  guide.section('Assign sequences', 'cadnano supplies the routing. Assign the intended scaffold sequence and complementary staples before creating the simulation. For this short demonstration, assign the beginning of M13mp18 to the short routed scaffold; the remaining reference bases are unused. For an experimental design, use its actual scaffold sequence and register.')
  const sequenceMenu = async () => {
    await page.locator('#menu-item-tools').hover()
    await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Sequencing/ }).hover()
  }
  await sequenceMenu()
  await guide.click(page.locator('#menu-seq-assign-scaffold'), 'Choose Tools → Sequencing → Assign Scaffold Sequence.')
  await expect(page.locator('input[name="asc-scaffold"][value="M13mp18"]')).toBeChecked()
  await guide.click(page.getByRole('dialog').filter({ hasText: 'Assign Scaffold Sequence' }).getByRole('button', { name: 'Apply', exact: true }), 'Review the scaffold length and M13mp18 selection, then click Apply.')
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(2)
  await sequenceMenu()
  await guide.click(page.locator('#menu-seq-assign-staples'), 'Choose Tools → Sequencing → Assign Staple Sequences to complement the routed staples.')
  await expect.poll(async () => (await designState(page)).strands.every(s => s.is_reference || (s.sequence && !/[^ACGT]/.test(s.sequence)))).toBe(true)
  await expect.poll(async () => {
    const d = JSON.parse(await readFile(path.join(process.env.NADOC_WORKSPACE, '__e2e__cadnano-local-oxdna.nadoc'), 'utf8'))
    return d.feature_log.length
  }).toBe(3)

  guide.section('Configure a local relaxation', 'Open Simulations and select oxDNA. A relaxation job contains CPU Monte Carlo minimization, molecular-dynamics relaxation, then equilibration. The example retains the default stage lengths and health gates.')
  await guide.click(page.locator('.left-tab-btn[data-tab="dynamics"]'), 'Open the Simulations sidebar.')
  await guide.click(page.locator('.engine-selector-btn[data-engine="oxdna"]'), 'Select oxDNA as the simulation engine.')
  await frameModel(page)
  await guide.click(page.locator('#oxdna-jobs-new-btn'), 'Click + New job to configure the relaxation.')
  const modal = page.locator('.modal--oxdna-wizard')
  await expect(modal).toBeVisible()
  await guide.capture('In Where it runs, keep Local selected. This uses the oxDNA installation on this computer.')
  await guide.click(modal.getByRole('button', { name: 'Next →', exact: true }), 'Click Next to review Parameters & options.')
  await expect(modal.locator('[data-oxdna-field="backend"]')).toHaveValue('CUDA')
  await expect(modal.locator('[data-oxdna-field="md_relax_steps"]')).toHaveValue('1000000')
  await guide.capture('Review oxDNA2, Automatic engine selection, CUDA device 0 and 0.5 M salt. Defaults are 1,000 MC steps, 1,000,000 MD relaxation steps and 100,000 equilibration steps, with a 0.5 base-pair retention gate and up to three escalating MD retries. Set conditions to match your experiment.')
  await guide.pointAt(modal.locator('[data-oxdna-field="min_bp_retained"]'), 'Scroll down to review equilibration, the base-pair retention gate and retry allowance. Keep the health gates enabled.')
  await guide.click(modal.getByRole('button', { name: 'Next →', exact: true }), 'Click Next to inspect Full configuration, including the stage temperatures, thermostats, force caps and output intervals.')
  await guide.capture('Review the generated inputs before creating the job. The default temperature is 296 K. The recorded sequence parameter file uses average interaction strengths; assigning sequences alone does not select sequence-dependent thermodynamics.')
  const created = page.waitForResponse(r => new URL(r.url()).pathname === '/api/oxdna/jobs' && r.request().method() === 'POST')
  await guide.click(modal.getByRole('button', { name: 'Create job', exact: true }), 'Click Create job to prepare the local relaxation inputs.')
  const createResponse = await created
  expect(createResponse.ok(), await createResponse.text()).toBe(true)
  const relax = await createResponse.json(); jobs.add(relax.job_id)
  expect(relax.execution_target).toBe('local')
  await expect(modal).toBeHidden()
  await guide.click(page.locator('#oxdna-jobs-run-btn'), 'Click Run to start the local relaxation. NADOC runs the stages in order and checks their health.')
  const getJob = async id => (await request.get(`http://127.0.0.1:8019/api/oxdna/jobs/${id}`)).json()
  let relaxed
  await expect.poll(async () => {
    relaxed = await getJob(relax.job_id)
    if (relaxed.status === 'failed') {
      const failed = relaxed.stages.find(s => s.status === 'failed')
      const log = await readFile(path.join(process.env.NADOC_WORKSPACE, 'oxdna_jobs', relax.job_id, failed.name, 'oxdna.log'), 'utf8')
      throw new Error(JSON.stringify(relaxed) + '\nNATIVE ERROR:\n' + log.slice(-6000))
    }
    return relaxed.status
  }, { timeout: 600000, intervals: [2000] }).toBe('completed')
  await expect(page.locator('#oxdna-jobs-new-btn')).toBeEnabled()
  guide.section('Start production from the relaxed structure', 'Continue after the relaxation completes successfully. Review stage health and the relaxed structure before committing to longer sampling. A completed relaxation makes a production starting configuration available; sampling adequacy still depends on the scientific question.')
  await guide.capture('Wait for production ready. If relaxation fails, inspect its reported health or engine error and resolve the cause before continuing.')
  if (!await page.locator('#oxdna-jobs-viz-body').isVisible()) {
    await guide.click(page.locator('#oxdna-jobs-viz-toggle'), 'Expand Visualizations in the oxDNA panel.')
  }
  await guide.click(page.locator('#oxdna-jobs-display-toggle'), 'Select OxDNA display to inspect the relaxed physical configuration.')
  await expect(page.locator('#oxdna-jobs-display-status')).toContainText('Showing relaxed positions', { timeout: 30000 })
  await frameModel(page)
  await guide.capture('Inspect the relaxed bundle and its terminal connections. Right-drag to orbit; physical display leaves the authored topology intact.')
  await page.mouse.move(1100, 650)
  await page.mouse.down({ button: 'right' }); await page.mouse.move(1340, 710, { steps: 20 }); await page.mouse.up({ button: 'right' })
  await frameModel(page)
  await guide.capture('Inspect the reverse side for displaced ends, separated strands or discontinuities before starting production.')
  await guide.click(page.locator('#oxdna-jobs-new-btn'), 'With the completed relaxation selected, click + New job. The wizard opens in Production mode.')
  await expect(modal.getByRole('combobox', { name: 'Continue from' })).toHaveValue(relax.job_id)
  await guide.capture('Check Continue from identifies the completed relaxation. Review the default 5,000,000 production steps and 10,000 steps per saved frame. Production inherits the local backend and salt from its parent; review the temperature, time step and thermostat for the intended sampling.')
  await guide.click(modal.getByRole('button', { name: 'Next →', exact: true }), 'Click Next to review the production Summary.')
  const productionCreated = page.waitForResponse(r => new URL(r.url()).pathname === `/api/oxdna/jobs/${relax.job_id}/run` && r.request().method() === 'POST')
  await guide.click(modal.getByRole('button', { name: 'Create job', exact: true }), 'Click Create job. NADOC creates and selects a separate production job using the parent’s final configuration.')
  const productionResponse = await productionCreated
  expect(productionResponse.ok(), await productionResponse.text()).toBe(true)
  const prod = await productionResponse.json(); jobs.add(prod.job_id)
  await expect(modal).toBeHidden()
  await guide.click(page.locator('#oxdna-jobs-run-btn'), 'Click Run to start production locally.')
  const clicks = await page.evaluate(() => { const result = window.__guideClicks; window.__guideClicks = null; return result })
  console.log('POST_IMPORT_BUTTON_CLICKS', JSON.stringify(clicks))
  let production
  await expect.poll(async () => {
    production = await getJob(prod.job_id)
    if (production.status === 'failed') throw new Error(JSON.stringify(production))
    const stage = production.stages.find(s => s.kind === 'production')
    return stage && ['running', 'done'].includes(stage.status)
  }, { timeout: 60000, intervals: [1000] }).toBe(true)
  // Require native trajectory output, not merely a running UI label.
  const jobRoot = path.join(process.env.NADOC_WORKSPACE, 'oxdna_jobs', prod.job_id)
  const stage = production.stages.find(s => s.kind === 'production')
  let nativeFrameTimes = []
  await expect.poll(async () => {
    try {
      const text = await readFile(path.join(jobRoot, stage.name, 'trajectory.dat'), 'utf8')
      nativeFrameTimes = [...text.matchAll(/^t = ([^\n]+)/gm)].map(m => Number(m[1]))
      return nativeFrameTimes.some(t => Number.isFinite(t) && t > 0)
    } catch { return false }
  }, { timeout: 60000 }).toBe(true)
  production = await getJob(prod.job_id)
  expect(['running', 'completed']).toContain(production.status)
  await expect(page.locator('.toast-message')).toHaveCount(0, { timeout: 15000 })
  await guide.capture('Production is running on this computer. Follow stage progress and saved trajectory frames in the oxDNA panel. Extend sampling and assess equilibration and convergence for your observable before interpreting results.')
  await writeFile(path.join(output, 'simulation-verification.json'), JSON.stringify({
    mode: 'real local native oxDNA; no mocked jobs or status',
    relaxation: { job_id: relax.job_id, status: relaxed.status, stages: relaxed.stages, health_samples: relaxed.health_samples, run_config: relaxed.run_config, n_nucleotides: relaxed.n_nucleotides, retries: relaxed.relax_retries },
    production: { job_id: prod.job_id, status: production.status, stages: production.stages, native_trajectory_observed: true, native_frame_times: nativeFrameTimes, execution_target: production.execution_target, run_config: production.run_config },
    scope: 'Default production launched and native output observed; capture cleanup stops the job. No convergence claim or completed production dataset.',
  }, null, 2))
  expect(errors).toEqual([])
  await guide.finish()
})
