/**
 * md_runpod_live_frame.spec.js — can NADOC actually show a frame from a RunPod run that
 * is happening RIGHT NOW?
 *
 * Everything else about this feature is unit-tested against fakes. The one question fakes
 * cannot answer is whether the whole chain holds against a live pod: RunPod session →
 * `get_pod` → SSH → SFTP `restart.coor` → one-frame DCD → display socket → a frame on the
 * scene. This drives that chain through the real UI and records what the display said the
 * whole time (`helpers/md_display_log.js`).
 *
 * REQUIRES A RUNNING RUNPOD JOB. It finds one through the API and SKIPS if there is none —
 * a skip means "not proven", never "passed".
 *
 * READ-ONLY as to the user's data (memory/feedback_no_live_server_mutation_for_verify):
 * it opens an existing design, selects an existing job row, and toggles a visualisation
 * radio. It creates/starts/stops nothing. It DOES cause snapshot fetches — that is the
 * feature under test, and they only write `output/<seg>.dcd` inside the job's own package.
 * The design file is checked for modification at the end.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_runpod_live_frame.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import { attachMdDisplayLog } from './helpers/md_display_log.js'

const LOG_DIR = 'e2e/logs'
const API = 'http://localhost:8000'

/** The running RunPod job, or null. Read straight from the API — hardcoding a job id
 *  would rot the moment this run ends. */
async function findRunningPodJob(request) {
  const res = await request.get(`${API}/api/md/jobs`)
  if (!res.ok()) return null
  const body = await res.json()
  const jobs = Array.isArray(body) ? body : (body.jobs ?? [])
  return jobs.find(j =>
    j.execution_target === 'runpod' && j.status === 'running' && j.runpod_pod_id) ?? null
}

test('a live RunPod run shows a frame, and says what it is doing throughout', async ({ page, request }) => {
  test.setTimeout(420_000)

  const job = await findRunningPodJob(request)
  test.skip(!job, 'no RunPod job is running — nothing to prove against a live pod')
  console.log(`[spec] job ${job.job_id} · ${job.design_name} · pod ${job.runpod_pod_id}`)

  // The design must not come back modified. `workspace/` is gitignored, so there is no
  // diff to fall back on if it does (feedback_playwright_fixtures_location).
  const designPath = `../workspace/${job.design_name}.nadoc`
  const mtimeBefore = fs.existsSync(designPath) ? fs.statSync(designPath).mtimeMs : null

  const log = await attachMdDisplayLog(page, { intervalMs: 500 })

  await page.goto(`/?doc=runpod-live-frame-${Date.now()}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  if (await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${job.design_name}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 90_000 })
  log.note(`design ${job.design_name} loaded`)

  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 15_000 })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click({ timeout: 15_000 })
  await page.waitForTimeout(1500)

  const row = page.locator(`#simulate-jobs-list [data-job-id="${job.job_id}"]`).first()
  await row.waitFor({ state: 'visible', timeout: 30_000 })
  await row.click({ timeout: 15_000 })
  log.note('job selected')
  await page.waitForTimeout(1500)

  await page.locator('#md-jobs-display-toggle').check({ timeout: 15_000 })
  log.note('Display MD on')

  // The frame is the whole point. A snapshot fetch is ~5 s of SFTP plus a PSF parse, and
  // the display socket then has to load the one-frame DCD, so allow generously.
  await page.waitForFunction(
    () => (window.__mdDisplayEvents || []).some(e => e.state === 'frame'),
    null, { timeout: 240_000 },
  ).catch(() => {})
  await log.sample()

  // ── The ⟳ button: RunPod only, and it must actually re-fetch ────────────────
  const refresh = page.locator('#md-jobs-live-frame-refresh')
  await expect(refresh).toBeVisible({ timeout: 30_000 })
  log.note('clicking ⟳')
  await refresh.click({ timeout: 15_000 })
  await page.waitForTimeout(1000)
  await log.sample()
  // "Retrieving…" has to appear, or the button is silent and the user cannot tell it worked.
  await page.waitForTimeout(12_000)
  await log.sample()

  // The frame is meant to be LOOKED at — a green assertion on an event does not prove
  // anything reached the canvas.
  await page.screenshot({ path: `${LOG_DIR}/md_runpod_live_frame.png`, fullPage: false })

  await log.stop()
  const files = log.write(`${LOG_DIR}/md_runpod_live_frame`)
  console.log(`[spec] log → ${files.txt}`)

  const statuses = log.statusTexts()
  console.log('[spec] status lines seen:')
  for (const s of [...new Set(statuses)]) console.log('   ·', s)

  // ── Assertions ──────────────────────────────────────────────────────────────
  expect(log.sawFrame(), 'no MD frame ever reached the scene').toBe(true)

  const joined = statuses.join(' | ')
  // The wording this whole change removed must not come back.
  expect(joined).not.toContain('not on this computer')
  expect(joined.toLowerCase()).not.toContain('fetch a live frame')
  // The user must be told a fetch is happening, and when the next one is.
  expect(joined).toMatch(/Retrieving the latest frame from the pod|Snapshot at step/)
  expect(joined).toMatch(/next update in/)

  expect(log.consoleErrors(), 'console errors during the run').toEqual([])

  const mtimeAfter = fs.existsSync(designPath) ? fs.statSync(designPath).mtimeMs : null
  expect(mtimeAfter, 'the spec must not modify the design').toBe(mtimeBefore)
})
