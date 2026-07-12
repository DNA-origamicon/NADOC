/**
 * "Use as NAMD seed" → deferred-prep DRAFT flow (running-app smoke).
 *
 * The oxDNA "Use as NAMD seed" button now creates an UNSTARTED draft NAMD job
 * (solvation deferred) so the user can set advanced options first, then press
 * "Relax from oxDNA".  This exercises, against the live servers, that:
 *   1. creating a seed job yields a `draft` with NO package (no solvation ran), and
 *   2. the unified sim-jobs listing surfaces it as a NAMD draft for its design, and
 *   3. the app boots with the NAMD launcher present ("Relax").
 *
 * The button RELABEL on draft-selection is covered by the pure unit tests
 * (mdJobIsDraft / mdDraftRunLabel / statusKeyFor('draft') in md_jobs_panel.test.js +
 * job_status_symbol.test.js) — it drives the same _paintRunControl path as the
 * e2e-covered Relax→Resume relabel.  A full click-through isn't asserted here: the
 * overhauled master job list scopes to the browser's workspace path, which this
 * harness can't set without driving the library-open UI.
 *
 * Run:
 *   cd /home/joshua/NADOC/frontend
 *   npx playwright test e2e/md_draft_seed.spec.js --reporter=list
 */

import { test, expect } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api'
const OXDNA_JOB = 'a20899d1b4ab'   // completed GT_corner_v2 oxDNA relax
const DESIGN_PATH = '/home/joshua/NADOC/workspace/GT_corner_v2.nadoc'

test('oxDNA "Use as NAMD seed" creates an unsolvated draft, surfaced in the sim list', async ({ page, request }) => {
  // 1. Create the draft exactly as the oxDNA "Use as NAMD seed" button does.
  const cr = await request.post(`${API}/md/jobs`, {
    data: { oxdna_job_id: OXDNA_JOB, draft: true, design_source_path: 'GT_corner_v2.nadoc' },
    headers: { 'Content-Type': 'application/json' },
  })
  test.skip(!cr.ok(), 'could not create draft (oxDNA seed job a20899d1b4ab missing?)')
  const draft = await cr.json()
  const draftId = draft.job_id

  try {
    // Draft, seeded, NOT solvated (no package, no segments).
    expect(draft.status).toBe('draft')
    expect(draft.seed_oxdna_job_id).toBe(OXDNA_JOB)
    expect(draft.package_subdir).toBe('')
    expect(draft.design_name).toBe('GT_corner_v2')   // nice label pulled from the seed

    // 2. The unified sim-jobs listing surfaces it as a NAMD draft for its design.
    const lr = await request.get(`${API}/simulate/jobs?design_source_path=GT_corner_v2.nadoc`)
    expect(lr.ok()).toBeTruthy()
    const nodes = await lr.json()
    const node = (Array.isArray(nodes) ? nodes : []).find(n => n.job_id === draftId)
    expect(node, 'draft must appear in the scoped sim-jobs list').toBeTruthy()
    expect(node.engine).toBe('namd')
    expect(node.status).toBe('draft')

    // (Deliberately do NOT call …/prepare here — it would kick off the heavy
    // solvation.  Its accept/guard behaviour is covered by test_md_draft.py.)

    // 3. The app boots with the NAMD launcher present.
    const load = await request.post(`${API}/design/load`, {
      data: { path: DESIGN_PATH }, headers: { 'Content-Type': 'application/json' },
    })
    expect(load.ok()).toBeTruthy()
    await page.goto('/')
    await page.waitForSelector('#canvas')
    await page.evaluate(() => {
      for (const id of ['splash-screen', 'welcome-screen']) {
        document.getElementById(id)?.style.setProperty('display', 'none')
      }
      document.querySelectorAll('.left-tab-btn').forEach(b => { b.disabled = false })
      document.getElementById('left-panel')?.classList.remove('hidden', 'locked-hidden')
      document.querySelectorAll('.tab-content').forEach(el => { el.hidden = el.id !== 'tab-content-dynamics' })
    })
    await page.click('.engine-selector-btn[data-engine="namd"]')
    const runBtn = page.locator('#md-jobs-run-btn')
    await expect(runBtn).toBeVisible()
    await expect(runBtn).toHaveText(/Relax/)
  } finally {
    await request.delete(`${API}/md/jobs/${draftId}`).catch(() => {})
  }
})
