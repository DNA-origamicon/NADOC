/**
 * md_run_queue.spec.js — VERIFICATION spec for "Chain Simulations is gone; ▶ Run becomes
 * ＋ Queue while a NAMD job is running".
 *
 * Not part of the routine dev cycle. It exists because the flip is only observable in the
 * real app AND because proving it honestly must not start a real NAMD run: "a job is
 * running" is faked by intercepting GET /api/md/queue, which is exactly the signal the
 * panel reads. Everything else — the button wiring, the 5 s queue poll, the queue list —
 * is the real code path.
 *
 * Read-only w.r.t. the workspace: it never enqueues, starts, stops or deletes anything
 * (POST/PUT/DELETE to /api/md/queue are refused by the route handler).
 *
 * ONE design load for all phases — opening a design here costs minutes, so the phases
 * change the faked queue and let the panel's own poll pick it up.
 *
 * Runs against the USER'S dev servers (playwright.livedev.config.js), on a PINNED ?doc.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/md_run_queue.spec.js --reporter=line
 */
import { test, expect } from '@playwright/test'

const DOC = 'e2e-md-queue'
const DESIGN = '3x6Sq_oxDNA'   // a design that HAS NAMD jobs on this machine

test('the run queue replaces Chain Simulations', async ({ page }) => {
  test.setTimeout(300_000)

  // The faked queue state, swapped between phases. GET only — a real mutation is refused.
  let fake = { queue: [], busy: false, running_job_id: null }
  await page.route('**/api/md/queue**', (route) => {
    if (route.request().method() !== 'GET') return route.abort()
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fake) })
  })

  // ── open the design through the app's own library, then the NAMD tab ────────
  await page.goto(`/?doc=${DOC}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  if (await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${DESIGN}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 90_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 120_000 })
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 30_000 })
  await page.locator('.engine-selector-btn[data-engine="namd"]').click({ timeout: 30_000 })
  await page.waitForTimeout(1200)

  // ── 1. the Chain Simulations section is gone ───────────────────────────────
  await expect(page.locator('#chain-sim-panel')).toHaveCount(0)
  await expect(page.locator('#chain-sim-enable')).toHaveCount(0)
  await expect(page.locator('#chain-sim-launch-btn')).toHaveCount(0)

  // ── 2. machine idle → nothing changes, no queue shown ──────────────────────
  const runBtn = page.locator('#md-jobs-run-btn')
  const rows = page.locator('#simulate-jobs-list [data-job-id]')
  await rows.first().waitFor({ timeout: 60_000 })
  await rows.first().click()
  await page.waitForTimeout(800)
  await expect(page.locator('#md-queue-wrap')).toBeHidden()
  await expect(runBtn).not.toHaveText(/Queue/)
  const idleLabel = await runBtn.textContent()

  // ── 3. a NAMD job running → the same job's ▶ Run becomes ＋ Queue ──────────
  // Re-selecting the row repaints the control off the freshly-fetched queue state.
  fake = { queue: [], busy: true, running_job_id: 'fake-running' }
  const n = await rows.count()
  let queued = false
  for (let i = 0; i < n && !queued; i++) {
    await rows.nth(i).click()
    await page.waitForTimeout(700)
    queued = /Queue/.test(await runBtn.textContent())
  }
  expect(queued, `no NAMD job flipped ▶ Run (was "${idleLabel}") to ＋ Queue`).toBe(true)
  await expect(runBtn).toBeEnabled()
  await page.screenshot({ path: 'e2e/screenshots/md_queue_button.png',
                          clip: { x: 0, y: 0, width: 430, height: 950 } })

  // ── 4. jobs waiting → the queue lists them in order, each droppable ────────
  // The 5 s poll is armed now (busy), so this lands without any further clicking —
  // which is the property that matters: the panel notices the server on its own.
  const ids = await rows.evaluateAll(els => els.slice(0, 2).map(e => e.dataset.jobId))
  fake = {
    busy: true, running_job_id: 'fake-running',
    queue: ids.map((job_id, i) => ({ job_id, position: i + 1, design_name: DESIGN, status: 'queued' })),
  }
  await expect(page.locator('#md-queue-wrap')).toBeVisible({ timeout: 20_000 })
  const qrows = page.locator('#md-queue-list > div')
  await expect(qrows).toHaveCount(2)
  await expect(qrows.first()).toContainText('1.')
  await expect(qrows.first()).toContainText(DESIGN)
  await expect(qrows.first().locator('button')).toHaveText('✕')
  // The selected job is now IN the queue → the control offers to take it back out.
  await page.locator(`#simulate-jobs-list [data-job-id="${ids[0]}"]`).click()
  await page.waitForTimeout(700)
  await expect(runBtn).toHaveText(/Queued #1/)
  await page.screenshot({ path: 'e2e/screenshots/md_queue_list.png',
                          clip: { x: 0, y: 0, width: 430, height: 950 } })

  // ── 5. the queue empties on its own → the poll disarms, the list hides ─────
  fake = { queue: [], busy: false, running_job_id: null }
  await expect(page.locator('#md-queue-wrap')).toBeHidden({ timeout: 20_000 })
})
