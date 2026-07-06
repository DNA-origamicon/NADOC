/**
 * ONE-OFF browser validation of the Display-MD toggle for the live 3x6x200 job.
 *
 * Environment-dependent: SKIPS unless a running NAMD job is present in the
 * workspace (needs the real PSF/DCD + charge_audit on disk).  It loads the
 * 3x6x200_test.nadoc design, opens the Dynamics tab, flips "Display MD (live)",
 * and asserts a correctly-mapped MD frame actually streams into the scene:
 *   - a `nadoc:md-display-state` "frame" event lands with the full DNA-P count
 *     (~7229) — proving the psfgen-segid p_order mapping fix works in-app (a
 *     broken map errors at load and never streams a frame);
 *   - no "error" state occurs;
 *   - the toggle's readiness indicator shows "ready".
 *
 * Not part of the routine e2e suite — run explicitly:
 *   npx playwright test e2e/md_display_toggle.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '..', '..')
const DESIGN = path.join(REPO_ROOT, '3x6x200_test.nadoc')
const API = 'http://127.0.0.1:8000/api'

// The 3x6x200_test fixture is gitignored + regenerable — rebuild it headlessly
// (deterministic replay of its feature-log recipe) if it isn't on disk.
if (!fs.existsSync(DESIGN)) {
  execSync('uv run python -m scripts.build_3x6x200_test', { cwd: REPO_ROOT, stdio: 'inherit' })
}

test('Display MD toggle streams a correctly-mapped frame for the running job', async ({ page }) => {
  test.setTimeout(300_000) // 5 min: large design load + 143 MB PSF parse + frame

  // Guard: only meaningful when a real MD job is running in this workspace.
  const jobsRes = await page.request.get(`${API}/md/jobs`)
  const body = await jobsRes.json()
  const jobs = Array.isArray(body) ? body : body.jobs || []
  const running = jobs.find((j) => j.status === 'running')
  test.skip(!running, 'no running MD job in this workspace')

  page.on('console', (m) => {
    const t = m.text()
    if (/md|MD|display|ws|job/i.test(t)) console.log('[browser]', t)
  })

  const t0 = Date.now()
  await page.goto('/')
  await page.waitForTimeout(1200)

  // Collect display-state events before we touch anything.
  await page.evaluate(() => {
    window.__mdStates = []
    window.addEventListener('nadoc:md-display-state', (e) => window.__mdStates.push(e.detail))
  })

  // Load the design into this tab's document (store + geometry).  Loading via the
  // client bypasses the UI's _hideWelcome (which is what enables the left-tab
  // buttons), so we replicate that unlock here.
  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.getElementById('filter-view-strip')?.classList.remove('locked-disabled')
    document
      .querySelectorAll('#left-tab-strip .left-tab-btn')
      .forEach((b) => { b.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, DESIGN)
  console.log(`[md-toggle] design loaded in ${((Date.now() - t0) / 1000).toFixed(1)}s`)

  // Open the Dynamics tab (button now enabled).
  await page.locator('#left-tab-strip [data-tab="dynamics"]').click()
  await expect(page.locator('#tab-content-dynamics')).toBeVisible()

  // Make sure the MD Jobs section is expanded so its toggle is interactable
  // (only click the heading if the toggle isn't already visible — clicking an
  // already-open section would collapse it).
  const toggle = page.locator('#md-jobs-display-toggle')
  if (!(await toggle.isVisible())) {
    await page.locator('#md-jobs-panel-heading').click()
  }
  await expect(toggle).toBeVisible()

  // Show all jobs — the running job is filed under its own workspace path, which the
  // per-part filter would hide when the design is loaded directly (not via workspace).
  await page.locator('#md-jobs-show-all').check()

  // Flip Display MD on.  _startMdDisplay fetches jobs, auto-selects the running one,
  // and retries every 15 s until the trajectory resolves — so the first frame lands
  // shortly after (the WS load parses the 143 MB PSF ~9 s), within the poll below.
  await toggle.check()

  // A correctly-mapped frame must stream and apply: the "frame" event carries the
  // number of P positions sent to the renderer (~7229 for this bundle).  A broken
  // mapping would instead surface an "error" state and never reach "frame".
  await expect
    .poll(
      async () =>
        page.evaluate(
          () => (window.__mdStates || []).find((s) => s.state === 'frame')?.nPositions ?? 0,
        ),
      { timeout: 180_000, message: 'waiting for a streamed MD frame' },
    )
    .toBeGreaterThan(6000)

  const states = await page.evaluate(() => window.__mdStates.map((s) => s.state))
  console.log(`[md-toggle] display-state sequence: ${states.join(' → ')}`)
  expect(states, 'no error state should occur').not.toContain('error')

  // Readiness indicator reports ready.
  await expect(page.locator('#md-jobs-display-indicator-label')).toHaveText(/ready/i, {
    timeout: 15_000,
  })

  console.log(`[md-toggle] PASS in ${((Date.now() - t0) / 1000).toFixed(1)}s`)
})
