/**
 * AF-26 — out-of-date job → feature-log sync, END TO END in the real app.
 *
 * The regression guard for the reported bug "the ⚠ doesn't clear after rolling /
 * manually seeking the Feature Log back to a job's run state, and the model doesn't
 * visibly roll". Every backend slice + every isolated client function already passed
 * green while the live flow stayed broken — so this drives the GENUINE path: the real
 * oxDNA panel, a real overhang edit, a real feature-log seek, asserting the real DOM.
 *
 * The bug's root cause was backend: `_topology_substitute` didn't roll back the
 * `overhangs` list on a seek, so the seeked design's fingerprint stayed wrong and the
 * job never re-matched. Reverting that one line makes THIS test go red (the ⚠ stays).
 *
 * GPU-free: a completed job + a matching .nadoc are pre-seeded into the workspace by
 * tests/e2e_seed_af26.py (no relaxation is run).
 */

import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

const PROJECT_ROOT = path.resolve(import.meta.dirname ?? __dirname, '../..')
const WORKSPACE = path.join(PROJECT_ROOT, 'workspace')

let seed   // { job_id, nadoc_path, run_position, overhang }

test.beforeAll(() => {
  // Seed a completed oxDNA job + its .nadoc into the workspace the running backend reads.
  const out = execFileSync(
    'uv', ['run', 'python', 'tests/e2e_seed_af26.py', WORKSPACE],
    { cwd: PROJECT_ROOT, env: { ...process.env, PYTHONPATH: '.', PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}` } },
  ).toString()
  seed = JSON.parse(out.trim().split('\n').pop())
})

async function newDesign(page, name) {
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
}

test('AF-26: an overhang edit marks the job stale; a feature-log seek back clears the ⚠ and rolls the model', async ({ page }) => {
  await newDesign(page, 'af26-job-log-sync')

  // Load the seeded .nadoc INTO THIS TAB (in-tab client stamps the doc header).
  await page.evaluate(async (p) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(p)
  }, seed.nadoc_path)

  // Open the Dynamics tab so the real oxDNA jobs panel renders + fetches.
  await page.click('#left-tab-strip [data-tab="dynamics"]')

  // Show ALL jobs (our seeded job's source path won't match the loaded design's),
  // so the real panel renders its row. The out-of-date flag is still computed by
  // the backend against the live design, so this doesn't affect what we assert.
  await page.evaluate(() => {
    const t = document.getElementById('oxdna-jobs-show-all')
    if (t && !t.checked) { t.checked = true; t.dispatchEvent(new Event('change')) }
  })

  // Expand the oxDNA jobs panel section if it's collapsed (best-effort, faithful).
  await page.evaluate(() => {
    const body = document.getElementById('oxdna-jobs-body')
    const heading = document.getElementById('oxdna-jobs-heading')
    if (body && heading && (body.hidden || getComputedStyle(body).display === 'none')) heading.click()
  })

  // The real panel rendered our job's row (assert on the rendered DOM, not its
  // CSS visibility — the marker logic runs in _renderList regardless of collapse).
  const row = page.locator(`#oxdna-jobs-body [data-job-id="${seed.job_id}"]`)
  await expect(row).toHaveCount(1, { timeout: 15_000 })
  const staleWarn = row.locator('.oxdna-job-stale-warn')

  // 1. Initially the loaded design MATCHES the job → no ⚠.
  await expect(staleWarn).toHaveCount(0)

  // 2. Edit: add an overhang (the membership case). The job goes out of date → ⚠.
  await page.evaluate(async (o) => {
    const ovh = await import('/src/api/overhang_endpoints.js')
    await ovh.extrudeOverhang(o)
  }, seed.overhang)
  await expect(staleWarn).toHaveCount(1, { timeout: 15_000 })
  expect(await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    return store.getState().currentDesign.overhangs.length
  })).toBe(1)

  // 3. Manually seek the Feature Log back to the job's run position. The ⚠ must
  //    CLEAR (fingerprint re-matches) and the model must roll (overhang gone,
  //    cursor at the run position) — the exact hand-check that was failing.
  await page.evaluate(async (pos) => {
    const api = await import('/src/api/client.js')
    await api.seekFeatures(pos)
  }, seed.run_position)

  await expect(staleWarn).toHaveCount(0, { timeout: 15_000 })
  const after = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    return { overhangs: d.overhangs.length, cursor: d.feature_log_cursor }
  })
  expect(after.overhangs).toBe(0)              // model rolled: the overhang is gone
  expect(after.cursor).toBe(seed.run_position) // cursor seeked to the run position
})
