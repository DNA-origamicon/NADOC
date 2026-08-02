/**
 * Occupancy clouds — the top-N configurations of an oxDNA ensemble, superposed.
 *
 * Asserts the whole chain in the REAL app: DOM radio → oxdna_jobs_panel handler →
 * occupancy_controls → GET /oxdna/jobs/{id}/occupancy → oxdnaDisplay.displayOccupancy
 * (real model → most likely configuration) + occupancy_overlay (ghost copies of the
 * rest), and that turning it off tears both halves down.
 *
 * The vitest suites cover the pure logic under mocks; what only the app can prove is
 * that `buildHelixObjects` really produces a second visible structure in the scene —
 * a cylinder-LOD ghost, for instance, is built with every mesh `visible = false` and
 * draws nothing unless setDetailLevel is called.
 *
 * REQUIRES A JOB WITH A SAMPLING RUN. playwright.config.js starts a THROWAWAY backend on a
 * dedicated port (reuseExistingServer:false, so an e2e run never touches the user's :8000
 * process) — but that backend resolves the SAME on-disk workspace, so it does see the real
 * oxDNA jobs and this test runs rather than skipping. It skips only when the job id is
 * genuinely absent. Override with NADOC_E2E_OCC_JOB=<job_id>.
 *
 * The design load below hits the throwaway backend's own in-memory session, not the user's,
 * so it does not clobber a live session (memory/feedback_no_live_server_mutation_for_verify.md).
 */

import { expect, test } from '@playwright/test'

// Defaults to the suite's own throwaway backend, NOT the user's dev server.
const API = `${process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8002'}/api`
// VoltronCore field run — the design the user expects to hold distinct configurations.
const JOB_ID = process.env.NADOC_E2E_OCC_JOB || '5ce768ef2acf'

test('occupancy clouds superpose the likely configurations and tear down cleanly', async ({ page, request }) => {
  // VoltronCore is ~15 k nucleotides: the design load, the first render and a COLD
  // occupancy build (the frame cache is per-process) each take tens of seconds.
  test.setTimeout(600_000)

  const jr = await request.get(`${API}/oxdna/jobs/${JOB_ID}`).catch(() => null)
  test.skip(!jr?.ok(), `oxDNA job ${JOB_ID} not present on ${API} — see the header note`)
  const job = await jr.json()

  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push(String(e)))

  await page.goto('/', { timeout: 120_000 })
  await page.waitForSelector('#canvas', { timeout: 120_000 })
  await page.evaluate(() => {
    for (const id of ['splash-screen', 'welcome-screen']) {
      document.getElementById(id)?.style.setProperty('display', 'none')
    }
    document.querySelectorAll('.left-tab-btn').forEach((b) => { b.disabled = false })
    document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
    document.querySelectorAll('.tab-content').forEach((el) => {
      el.hidden = el.id !== 'tab-content-dynamics'
    })
  })

  // Load the design THROUGH THE PAGE's own client, not via a bare backend POST: the
  // backend call sets session state the already-booted page never syncs, leaving
  // currentDesign/currentGeometry null — the ghosts then have nothing to build from.
  await page.evaluate(async (fp) => {
    const client = await import('/src/api/client.js')
    await client.loadDesign(fp)
  }, job.design_source_path)
  await expect
    .poll(async () => page.evaluate(() => !!window.__nadocOccupancy?.stats?.().hasGeometry),
      { timeout: 120_000 })
    .toBe(true)

  // The oxDNA panel lives behind the Dynamics tab (click it AFTER the app has booted).
  await page.click('#left-tab-strip [data-tab="dynamics"]').catch(() => {})

  // No #oxdna-jobs-heading any more — the engine panels are tab-fronted and oxDNA is the
  // selector's default tab, so the panel is already up once Dynamics is open.
  const body = page.locator('#oxdna-jobs-body')
  await expect(body).toBeVisible({ timeout: 60_000 })

  // Job rows are scoped to the ACTIVE DESIGN, and a job's design_source_path may not
  // resolve to the same path the design was loaded from — so widen to all designs via the
  // oxDNA panel's own filter. That checkbox lives in the hidden legacy Jobs card
  // (index.html: "the oxDNA panel still renders into #oxdna-jobs-list ... and selectJob()
  // still works"), so it is set programmatically rather than clicked.
  await page.evaluate(() => {
    const all = document.getElementById('oxdna-jobs-show-all')
    if (all && !all.checked) {
      all.checked = true
      all.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })

  // Click the row inside that hidden list — it is the same handler the visible unified
  // list delegates to, and it is not subject to the visible list's design scoping.
  await expect.poll(async () => page.evaluate(
    (id) => !!document.querySelector(`#oxdna-jobs-list [data-job-id="${id}"]`),
    JOB_ID), { timeout: 60_000 }).toBe(true)
  await page.evaluate(
    (id) => document.querySelector(`#oxdna-jobs-list [data-job-id="${id}"]`).click(), JOB_ID)

  const toggle = page.locator('#oxdna-jobs-occupancy-toggle')
  await expect(toggle, 'occupancy unlocks once a sampling run exists').toBeEnabled({ timeout: 20_000 })

  const req = page.waitForRequest(
    (r) => r.url().includes(`/oxdna/jobs/${JOB_ID}/occupancy`)
      && !r.url().includes('occupancy-progress'),
    { timeout: 30_000 })
  await toggle.check()
  await req

  // Wait for a TERMINAL verdict. The in-progress line is "Clustering configurations…",
  // so a naive /configuration/ match races the fetch and passes before any result exists.
  const status = page.locator('#oxdna-jobs-occupancy-status')
  await expect
    .poll(async () => (await status.textContent()) ?? '', { timeout: 300_000 })
    .toMatch(/configurations, revisited|Drift, not switching|Single configuration/)
  const statusText = await status.textContent()

  // The legend only renders from a ready response, so its content is the real signal.
  const legend = page.locator('#oxdna-jobs-occupancy-legend')
  await expect(legend).toBeVisible({ timeout: 30_000 })
  await expect(legend.locator('.occ-state-row').first()).toBeVisible()
  const nRows = await legend.locator('.occ-state-row').count()
  expect(nRows, 'one row per state').toBeGreaterThan(1)
  // The box is scrollable, so a long state list cannot push the rest of the panel away.
  expect(await legend.evaluate((el) => getComputedStyle(el).overflowY)).toBe('auto')

  // The display controller owns the model, and ghosts exist for a switching ensemble.
  const state = await page.evaluate(() => ({
    mode: window.__nadocOxdnaDisplay?.mode?.() ?? null,
    overlayPresent: !!window.__nadocOccupancy,
    stats: window.__nadocOccupancy?.stats?.() ?? null,
    scenePresent: !!window.__nadocScene,
    ghostNodes: (() => {
      let n = 0
      window.__nadocScene?.traverse?.((o) => { if (o.name?.startsWith('occupancyGhost')) n++ })
      return n
    })(),
  }))
  expect(state.mode).toBe('occupancy')

  // Ghosts only exist when the ensemble genuinely switches; a drift/unimodal verdict
  // deliberately draws none, so gate the scene assertion on the verdict.
  if (/configurations, revisited/i.test(statusText ?? '')) {
    expect(state.ghostNodes,
      `a switching ensemble draws superposed structures; state=${JSON.stringify(state)}`)
      .toBe(nRows)

    // Unchecking a row must remove that structure from view without touching the others.
    await legend.locator('[data-occ-vis="1"]').uncheck()
    await expect
      .poll(async () => page.evaluate(() => window.__nadocOccupancy?.stats?.().hidden ?? -1),
        { timeout: 15_000 })
      .toBe(1)

    // Recolouring one state repaints only it.
    await legend.locator('[data-occ-color="0"]').evaluate((el) => {
      el.value = '#00ff80'
      el.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await expect
      .poll(async () => page.evaluate(() => window.__nadocOccupancy?.colors?.()[0] ?? null),
        { timeout: 30_000 })
      .toBe(0x00ff80)

    await legend.locator('[data-occ-vis="1"]').check()
  }

  await page.screenshot({ path: 'e2e/screenshots/occupancy-clouds.png', fullPage: false })

  // Switching to the flexibility map must drop the ghosts with the model.
  await page.locator('#oxdna-jobs-flex-toggle').check()
  await expect
    .poll(async () => page.evaluate(() => {
      let n = 0
      window.__nadocScene?.traverse?.((o) => { if (o.name?.startsWith('occupancyGhost')) n++ })
      return n
    }), { timeout: 60_000 })
    .toBe(0)

  expect(errors, `console errors: ${errors.join('\n')}`).toEqual([])
})
