/**
 * ONE-OFF browser test: toggling Display MD off must release the trajectory.
 *
 * Keeping a display WebSocket warm also keeps its DCD reader alive. For very large
 * trajectories that prevents disk space from being reclaimed after deletion. The
 * backend now caches only the expensive parsed PSF topology; toggle-off closes the
 * trajectory socket and a later toggle reconnects without pinning the old DCD.
 *
 * This drives the real app for the running 3x6x200 job: toggle on → off → on, and
 * asserts that after toggling OFF the indicator is off, no background re-warm is
 * started, and re-toggling explicitly loads and streams a frame again.
 *
 * Environment-dependent: SKIPS unless a NAMD job is running.  Run explicitly:
 *   npx playwright test e2e/md_display_toggle_rewarm.spec.js --reporter=list
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

test('toggling Display MD off releases its trajectory socket', async ({ page }) => {
  test.setTimeout(300_000)

  const jobsRes = await page.request.get(`${API}/md/jobs`)
  const body = await jobsRes.json()
  const jobs = Array.isArray(body) ? body : body.jobs || []
  test.skip(!jobs.some((j) => j.status === 'running'), 'no running MD job in this workspace')

  await page.goto('/')
  await page.waitForTimeout(1200)

  await page.evaluate(() => {
    window.__mdStates = []
    window.addEventListener('nadoc:md-display-state', (e) => window.__mdStates.push(e.detail?.state))
  })

  // Load the design + unlock the sidebar (client.loadDesign bypasses _hideWelcome).
  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
    document.getElementById('left-panel')?.classList.remove('locked-hidden', 'hidden')
    document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach((b) => { b.disabled = false })
    window.__leftSidebar?.refresh?.()
  }, DESIGN)

  await page.locator('#left-tab-strip [data-tab="dynamics"]').click()
  await expect(page.locator('#tab-content-dynamics')).toBeVisible()

  const toggle = page.locator('#md-jobs-display-toggle')
  if (!(await toggle.isVisible())) await page.locator('#md-jobs-panel-heading').click()
  await expect(toggle).toBeVisible()
  await page.locator('#md-jobs-show-all').check()

  const label = page.locator('#md-jobs-display-indicator-label')

  // ── 1) Toggle ON → first frame streams, indicator becomes ready. ──────────────
  await toggle.check()
  await expect
    .poll(() => page.evaluate(() => (window.__mdStates || []).includes('frame')), {
      timeout: 180_000,
      message: 'first frame should stream',
    })
    .toBe(true)
  await expect(label).toHaveText(/ready/i, { timeout: 15_000 })

  // ── 2) Toggle OFF → must NOT re-warm. ─────────────────────────────────────────
  const nAtOff = await page.evaluate(() => window.__mdStates.length)
  await toggle.uncheck()

  // Watch the indicator for ~10 s: it must never flip to "warming".
  const labels = []
  for (let k = 0; k < 10; k++) {
    labels.push((await label.textContent())?.trim())
    await page.waitForTimeout(1000)
  }
  console.log(`[rewarm] indicator after OFF over 10s: ${[...new Set(labels)].join(', ')}`)

  // No fresh load fired after toggling off (a re-warm would emit a "loading" state).
  const loadingAfterOff = await page.evaluate(
    (n) => (window.__mdStates || []).slice(n).filter((s) => s === 'loading').length,
    nAtOff,
  )
  expect(loadingAfterOff, 'toggle-off should not trigger a fresh load (re-warm)').toBe(0)
  expect(labels.join('|'), 'indicator should never show warming after toggle-off').not.toMatch(
    /warming/i,
  )
  await expect(label).toHaveText(/off/i)

  // ── 3) Re-toggle ON → a new socket loads using the cached PSF topology. ─────────
  const nAtReOn = await page.evaluate(() => window.__mdStates.length)
  const tRe = Date.now()
  await toggle.check()
  await expect
    .poll(
      () =>
        page.evaluate((n) => (window.__mdStates || []).slice(n).includes('frame'), nAtReOn),
      { timeout: 180_000, message: 're-toggle should load and stream a frame' },
    )
    .toBe(true)
  console.log(`[rewarm] re-toggle → frame in ${((Date.now() - tRe) / 1000).toFixed(1)}s`)
  const reSeq = await page.evaluate((n) => (window.__mdStates || []).slice(n), nAtReOn)
  console.log(`[rewarm] re-toggle state sequence: ${reSeq.join(' → ')}`)
  await expect(label).toHaveText(/ready/i)
})
